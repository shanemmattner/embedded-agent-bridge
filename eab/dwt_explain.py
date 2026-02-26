"""DWT stream explain feature for ARM Cortex-M targets.

Arms DWT watchpoints on requested symbols, captures JSONL hit events for a
given duration, resolves each event's address to source-file/line/function via
addr2line, and formats the enriched data into an LLM-ready prompt.

Architecture:
    resolve_source_line()   → addr2line wrapper, returns SourceLocation dict
    capture_events()        → arms daemons, sleeps, returns raw JSONL events
    enrich_events()         → adds source location fields to each raw event
    format_explain_prompt() → builds structured prompt + suggested watchpoints
    run_dwt_explain()       → orchestrator that ties all steps together
"""

from __future__ import annotations

import json
import logging
import os
import subprocess
import tempfile
import time
from collections import Counter
from typing import Any, Optional, TypedDict

logger = logging.getLogger(__name__)

# ---------------------------------------------------------------------------
# pyelftools — optional (same pattern as eab/cli/dwt/_helpers.py)
# ---------------------------------------------------------------------------
try:
    from elftools.elf.elffile import ELFFile  # noqa: F401
    from elftools.elf.sections import SymbolTableSection  # noqa: F401
    _PYELFTOOLS_AVAILABLE = True
except ImportError:
    _PYELFTOOLS_AVAILABLE = False

# ---------------------------------------------------------------------------
# pylink — optional (same pattern as eab/dwt_watchpoint.py)
# ---------------------------------------------------------------------------
try:
    import pylink as _pylink
except ImportError:
    _pylink = None  # type: ignore

# noqa: E402 — internal imports follow conditional optional-dep blocks above
from eab.cli.dwt._helpers import _open_jlink, _resolve_symbol  # noqa: E402
from eab.dwt_watchpoint import (  # noqa: E402
    Comparator,
    ComparatorAllocator,
    DwtWatchpointDaemon,
    SymbolNotFoundError,
    _requires_write_to_clear_matched,
)
from eab.toolchain import which_or_sdk  # noqa: E402


class SourceLocation(TypedDict):
    """Resolved source location for one address."""

    source_file: str
    line_number: int
    function_name: str


class RawEvent(TypedDict):
    """One JSONL watchpoint-hit event as emitted by DwtWatchpointDaemon."""

    ts: int
    label: str
    addr: str
    value: str


class EnrichedEvent(TypedDict):
    """Raw watchpoint event augmented with source location fields."""

    ts: int
    label: str
    addr: str
    value: str
    source_file: str
    line_number: int
    function_name: str


class ExplainResult(TypedDict):
    """Full result returned by run_dwt_explain."""

    events: list[EnrichedEvent]
    source_context: str
    ai_prompt: str
    suggested_watchpoints: list[str]


# =============================================================================
# ELF source-line enrichment
# =============================================================================

def resolve_source_line(address: int, elf_path: str) -> SourceLocation:
    """Resolve an address to source file, line number, and function name.

    Tries arm-none-eabi-addr2line / arm-zephyr-eabi-addr2line first, then
    the generic addr2line as a last resort.  Returns ``??`` / ``0`` fallbacks
    when the binary cannot resolve the address.

    Args:
        address:  Target virtual address (integer).
        elf_path: Path to ELF binary that contains DWARF debug info.

    Returns:
        SourceLocation dict with ``source_file``, ``line_number``, and
        ``function_name`` keys.

    Raises:
        ValueError: If ``elf_path`` does not exist.
    """
    if not os.path.isfile(elf_path):
        raise ValueError(f"ELF file not found: {elf_path!r}")

    addr2line = (
        which_or_sdk("arm-none-eabi-addr2line")
        or which_or_sdk("arm-zephyr-eabi-addr2line")
        or which_or_sdk("addr2line")
    )

    fallback: SourceLocation = {
        "source_file": "??",
        "line_number": 0,
        "function_name": "??",
    }

    if addr2line is None:
        logger.warning("addr2line not found; cannot resolve 0x%08X", address)
        return fallback

    try:
        result = subprocess.run(
            [addr2line, "-e", elf_path, "-f", "-C", hex(address)],
            capture_output=True,
            text=True,
            timeout=10.0,
        )
    except subprocess.TimeoutExpired:
        logger.error("addr2line timed out resolving 0x%08X", address)
        return fallback
    except OSError as exc:
        logger.error("addr2line invocation failed: %s", exc)
        return fallback

    if result.returncode != 0:
        logger.warning("addr2line returned %d: %s", result.returncode, result.stderr)
        return fallback

    lines = result.stdout.strip().split("\n")
    # addr2line -f output: line 0 = function name, line 1 = file:lineno
    func_name = lines[0].strip() if len(lines) > 0 else "??"
    loc_line = lines[1].strip() if len(lines) > 1 else "??:0"

    if func_name == "??":
        func_name = "??"

    source_file = "??"
    line_number = 0
    if ":" in loc_line and not loc_line.startswith("??"):
        parts = loc_line.rsplit(":", 1)
        if len(parts) == 2:
            source_file = parts[0]
            try:
                line_number = int(parts[1])
            except ValueError:
                line_number = 0

    return SourceLocation(
        source_file=source_file,
        line_number=line_number,
        function_name=func_name,
    )


# =============================================================================
# Event capture
# =============================================================================

def capture_events(
    comparators: list[Comparator],
    jlink: Any,
    duration_s: float,
    write_to_clear: bool = False,
    poll_hz: int = 100,
) -> list[RawEvent]:
    """Run DWT watchpoint daemons for ``duration_s`` and collect JSONL events.

    One :class:`~eab.dwt_watchpoint.DwtWatchpointDaemon` is created per
    comparator.  All daemons share a single temp JSONL file; after the sleep
    the file is parsed and returned as a list of dicts.

    Args:
        comparators:    Already-allocated Comparator objects.
        jlink:          Connected pylink.JLink instance.
        duration_s:     How long (seconds) to capture.
        write_to_clear: Pass-through to DwtWatchpointDaemon (True for M4).
        poll_hz:        DWT poll rate in Hz (default 100).

    Returns:
        List of raw event dicts with keys ``ts``, ``label``, ``addr``,
        ``value``.
    """
    tf = tempfile.NamedTemporaryFile(suffix=".jsonl", delete=False)
    events_path = tf.name
    tf.close()

    daemons: list[DwtWatchpointDaemon] = [
        DwtWatchpointDaemon(
            jlink,
            comp,
            poll_hz=poll_hz,
            events_file=events_path,
            write_to_clear=write_to_clear,
        )
        for comp in comparators
    ]

    try:
        for d in daemons:
            d.start()

        time.sleep(duration_s)

    finally:
        for d in daemons:
            d.stop()

    events: list[RawEvent] = []
    try:
        with open(events_path) as fh:
            for raw_line in fh:
                raw_line = raw_line.strip()
                if not raw_line:
                    continue
                try:
                    events.append(json.loads(raw_line))
                except json.JSONDecodeError as exc:
                    logger.warning("Skipping malformed JSONL line: %s (%s)", raw_line, exc)
    finally:
        try:
            os.unlink(events_path)
        except OSError:
            pass

    return events


# =============================================================================
# Event enrichment
# =============================================================================

def enrich_events(events: list[RawEvent], elf_path: str) -> list[EnrichedEvent]:
    """Add source location fields to each raw watchpoint event.

    Calls :func:`resolve_source_line` for every event and merges the returned
    ``SourceLocation`` fields into a copy of the raw event dict.

    Args:
        events:   Raw JSONL event dicts as returned by :func:`capture_events`.
        elf_path: Path to the ELF binary with DWARF debug info.

    Returns:
        List of enriched event dicts that include all original fields plus
        ``source_file``, ``line_number``, and ``function_name``.

    Raises:
        ValueError: If ``elf_path`` does not exist (propagated from
            :func:`resolve_source_line`).
    """
    enriched: list[EnrichedEvent] = []
    for event in events:
        try:
            address = int(event["addr"], 16)
        except (KeyError, ValueError) as exc:
            logger.warning("Cannot parse addr from event %r: %s", event, exc)
            address = 0

        location = resolve_source_line(address, elf_path)

        enriched_event: EnrichedEvent = {
            "ts": event["ts"],
            "label": event["label"],
            "addr": event["addr"],
            "value": event["value"],
            "source_file": location["source_file"],
            "line_number": location["line_number"],
            "function_name": location["function_name"],
        }
        enriched.append(enriched_event)

    return enriched


# =============================================================================
# Prompt formatting
# =============================================================================

def format_explain_prompt(enriched_events: list[EnrichedEvent]) -> ExplainResult:
    """Build a structured prompt and context from enriched watchpoint events.

    Groups events by symbol label and source location, counts hit frequency,
    derives suggested follow-up watchpoints from the unique labels observed,
    and formats an LLM-ready prompt string.

    Args:
        enriched_events: Enriched event dicts from :func:`enrich_events`.

    Returns:
        ExplainResult dict with keys:

        - ``events``: the input list (passed through).
        - ``source_context``: human-readable summary of hit locations.
        - ``ai_prompt``: structured prompt string for an LLM.
        - ``suggested_watchpoints``: list of unique symbol names hit.
    """
    # --- source_context: group by (label, source_file, line_number, function_name) ---
    hit_counter: Counter = Counter()
    for ev in enriched_events:
        key = (ev["label"], ev["source_file"], ev["line_number"], ev["function_name"])
        hit_counter[key] += 1

    context_lines: list[str] = ["DWT Watchpoint Hit Summary", "=" * 40]
    for (label, src_file, line_no, func_name), count in sorted(
        hit_counter.items(), key=lambda x: -x[1]
    ):
        context_lines.append(
            f"  Symbol : {label}"
        )
        context_lines.append(
            f"  Function : {func_name}"
        )
        context_lines.append(
            f"  Location : {src_file}:{line_no}"
        )
        context_lines.append(
            f"  Hit count: {count}"
        )
        context_lines.append("")

    source_context = "\n".join(context_lines)

    # --- ai_prompt ---
    prompt_lines: list[str] = [
        "You are an expert embedded-systems engineer.",
        "The following DWT (Data Watchpoint and Trace) events were captured from",
        "an ARM Cortex-M target.  Each event represents a memory access to a",
        "watched symbol at the source location shown.",
        "",
        "Captured watchpoint events:",
        "",
    ]

    for (label, src_file, line_no, func_name), count in sorted(
        hit_counter.items(), key=lambda x: -x[1]
    ):
        prompt_lines.append(
            f"  - Symbol '{label}' was accessed {count} time(s) "
            f"in {func_name}() at {src_file}:{line_no}."
        )

    prompt_lines += [
        "",
        "Please analyse the access pattern above and:",
        "  1. Explain why each symbol is being accessed at its recorded location.",
        "  2. Identify any potential race conditions, unexpected access patterns,",
        "     or performance hotspots.",
        "  3. Suggest any additional symbols that would be worth watching to",
        "     understand this behaviour more fully.",
    ]

    ai_prompt = "\n".join(prompt_lines)

    # --- suggested_watchpoints: unique labels observed ---
    suggested_watchpoints: list[str] = sorted(
        {ev["label"] for ev in enriched_events}
    )

    return ExplainResult(
        events=enriched_events,
        source_context=source_context,
        ai_prompt=ai_prompt,
        suggested_watchpoints=suggested_watchpoints,
    )


# =============================================================================
# Orchestrator
# =============================================================================

def run_dwt_explain(
    symbols: list[str],
    duration_s: int,
    elf_path: str,
    device: Optional[str] = None,
) -> ExplainResult:
    """Arm DWT watchpoints, capture events, enrich, and format an LLM prompt.

    Arms one DWT watchpoint comparator per symbol (read/write mode), captures
    hit events for ``duration_s`` seconds, resolves addresses to source
    locations, and returns a fully formatted :class:`ExplainResult`.

    Args:
        symbols:    List of symbol names to watch (looked up in ``elf_path``).
        duration_s: Capture duration in seconds.
        elf_path:   Path to ELF binary with DWARF debug info.
        device:     J-Link device string (e.g. ``"NRF5340_XXAA_APP"``).
                    Required — raises ``ValueError`` when ``None``.

    Returns:
        ExplainResult containing enriched events, source context, AI prompt,
        and suggested watchpoints.

    Raises:
        ValueError: If ``elf_path`` does not exist, ``device`` is ``None``,
            or any symbol is not found in the ELF.
    """
    if not os.path.isfile(elf_path):
        raise ValueError(f"ELF file not found: {elf_path!r}")

    if device is None:
        raise ValueError(
            "A J-Link device string must be provided (e.g. 'NRF5340_XXAA_APP'). "
            "Pass it via the device= argument."
        )

    # Resolve all symbols before opening hardware
    resolved: list[tuple[str, int, int]] = []  # (label, address, size_bytes)
    for sym in symbols:
        try:
            addr, size = _resolve_symbol(sym, elf_path)
        except SymbolNotFoundError as exc:
            raise ValueError(str(exc)) from exc

        resolved.append((sym, addr, size))
        logger.debug("Resolved symbol '%s' → 0x%08X (size=%d)", sym, addr, size)

    write_to_clear = _requires_write_to_clear_matched(device)

    jlink = _open_jlink(device)

    allocator = ComparatorAllocator(jlink)
    comparators: list[Comparator] = []

    try:
        for label, addr, size in resolved:
            comp = allocator.allocate(
                watch_addr=addr,
                label=label,
                mode="rw",
                size_bytes=size,
            )
            comparators.append(comp)
            logger.debug("Armed DWT comparator slot %d for '%s'", comp.index, label)

        raw_events = capture_events(
            comparators,
            jlink,
            duration_s=float(duration_s),
            write_to_clear=write_to_clear,
        )
        logger.info("Captured %d raw events in %ds", len(raw_events), duration_s)

        enriched = enrich_events(raw_events, elf_path)
        result = format_explain_prompt(enriched)

    finally:
        allocator.release_all()

    return result
