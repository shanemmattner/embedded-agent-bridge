"""cmd_dwt_watch — non-halting DWT memory watchpoint that streams JSONL events."""

from __future__ import annotations

import json
import logging
import sys
import time
from typing import Optional

logger = logging.getLogger(__name__)

# Optional pylink import (may not be installed in all envs)
try:
    import pylink
except ImportError:
    pylink = None  # type: ignore

from eab.dwt_watchpoint import (
    ComparatorAllocator,
    DwtWatchpointDaemon,
    SymbolNotFoundError,
    _requires_write_to_clear_matched,
)
from eab.cli.dwt._helpers import _resolve_symbol, _open_jlink


def cmd_dwt_watch(
    *,
    symbol: Optional[str],
    addr: Optional[int],
    elf: Optional[str],
    device: str,
    mode: str = "write",
    size: Optional[int] = None,
    poll_hz: int = 100,
    output: Optional[str] = None,
    duration: Optional[float] = None,
    probe_selector: Optional[str] = None,
    json_mode: bool = False,
) -> int:
    """Non-halting DWT watchpoint — streams JSONL hit events to stdout.

    Args:
        symbol:         Symbol name to watch (requires --elf for lookup).
        addr:           Raw address override (skips ELF lookup).
        elf:            ELF file path for symbol resolution.
        device:         J-Link device string.
        mode:           "read", "write", or "rw".
        size:           Variable size in bytes (1/2/4). Auto-detected from ELF.
        poll_hz:        Poll rate in Hz (default 100).
        output:         Optional file to append JSONL events.
        duration:       Stop after N seconds (None = until Ctrl-C).
        probe_selector: J-Link serial number for multi-probe setups.
        json_mode:      Output JSON for non-event messages (errors etc.).

    Returns:
        0 on success, non-zero on error.
    """
    # ------------------------------------------------------------------
    # 1. Resolve address
    # ------------------------------------------------------------------
    watch_addr: int
    size_bytes: int
    label: str

    if addr is not None:
        watch_addr = addr
        size_bytes = size or 4
        label = symbol or f"0x{addr:08X}"
    elif symbol and elf:
        try:
            watch_addr, detected_size = _resolve_symbol(symbol, elf)
        except SymbolNotFoundError as exc:
            _emit_error(str(exc), json_mode)
            return 2
        except FileNotFoundError as exc:
            _emit_error(str(exc), json_mode)
            return 2
        size_bytes = size or detected_size
        label = symbol
    elif symbol and not elf:
        _emit_error(
            f"Symbol '{symbol}' requires --elf for address lookup, or pass --addr directly.",
            json_mode,
        )
        return 2
    else:
        _emit_error("Specify --symbol (with --elf) or --addr.", json_mode)
        return 2

    # ------------------------------------------------------------------
    # 2. Warn on high poll rate
    # ------------------------------------------------------------------
    if poll_hz > 500:
        logger.warning(
            "poll-hz=%d is high (>500). SWD overhead ~%.0f%%. "
            "Consider reducing if target behaviour changes.",
            poll_hz,
            poll_hz * 0.01,
        )

    # ------------------------------------------------------------------
    # 3. Connect J-Link
    # ------------------------------------------------------------------
    if pylink is None:
        _emit_error(
            "pylink-square is not installed. Run: pip install pylink-square",
            json_mode,
        )
        return 1

    try:
        jlink = _open_jlink(device, probe_selector=probe_selector)
    except Exception as exc:
        _emit_error(f"Failed to connect J-Link: {exc}", json_mode)
        return 1

    # ------------------------------------------------------------------
    # 4. Allocate DWT comparator
    # ------------------------------------------------------------------
    write_to_clear = _requires_write_to_clear_matched(device)
    allocator = ComparatorAllocator(jlink)

    try:
        comparator = allocator.allocate(
            watch_addr=watch_addr,
            label=label,
            mode=mode,
            size_bytes=size_bytes,
        )
    except Exception as exc:
        _emit_error(f"Failed to allocate DWT comparator: {exc}", json_mode)
        return 1

    # ------------------------------------------------------------------
    # 5. Start daemon and wait
    # ------------------------------------------------------------------
    daemon = DwtWatchpointDaemon(
        jlink,
        comparator,
        poll_hz=poll_hz,
        events_file=output,
        write_to_clear=write_to_clear,
    )

    try:
        daemon.start()
        if duration is not None and duration <= 0.0:
            # Immediate exit (used in tests with duration=0.0)
            pass
        elif duration is not None:
            time.sleep(duration)
        else:
            # Run until Ctrl-C
            try:
                while True:
                    time.sleep(0.1)
            except KeyboardInterrupt:
                pass
    finally:
        daemon.stop()
        allocator.release(comparator.index)

    return 0


def _emit_error(message: str, json_mode: bool) -> None:
    """Write an error to stderr."""
    if json_mode:
        print(
            json.dumps({"error": message}),
            file=sys.stderr,
            flush=True,
        )
    else:
        print(f"Error: {message}", file=sys.stderr, flush=True)
