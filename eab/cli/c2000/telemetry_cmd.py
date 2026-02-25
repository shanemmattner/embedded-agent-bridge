"""C2000 FOC telemetry decode command.

Reads the raw binary telemetry captured by the FTDI UART daemon (data.bin)
and renders it as a human-readable table, JSON, or CSV.
"""

from __future__ import annotations

import csv
import io
import json
import sys
from typing import Optional

from eab.cli.helpers import _print


# ---------------------------------------------------------------------------
# Output formatters
# ---------------------------------------------------------------------------


def _fmt_table(packets: list, first_isr: int) -> str:  # type: ignore[type-arg]
    """Render *packets* as an aligned text table."""
    hdr = (
        "  t(s)   | pos_ref    theta       iq     omega    duty  "
        "| state    fault"
    )
    sep = (
        "---------+--------------------------------------------------"
        "+------------------"
    )
    lines = [hdr, sep]
    for pkt in packets:
        t = (pkt.isr_count - first_isr) / 10_000.0
        lines.append(
            f"{t:8.3f} | "
            f"{pkt.pos_ref:8.4f}  "
            f"{pkt.theta:8.4f}  "
            f"{pkt.iq:7.4f}  "
            f"{pkt.omega:8.2f}  "
            f"{pkt.duty:6.3f}  "
            f"| {pkt.sys_state:<8s}  "
            f"0x{pkt.fault_code:04X}"
        )
    return "\n".join(lines)


def _fmt_csv(packets: list) -> str:  # type: ignore[type-arg]
    """Render *packets* as CSV text."""
    buf = io.StringIO()
    writer = csv.writer(buf)
    writer.writerow([
        "offset", "isr_count", "pos_ref", "theta", "iq",
        "omega", "duty", "sys_state", "fault_code", "hil_tick",
    ])
    for pkt in packets:
        writer.writerow([
            pkt.offset,
            pkt.isr_count,
            pkt.pos_ref,
            pkt.theta,
            pkt.iq,
            pkt.omega,
            pkt.duty,
            pkt.sys_state,
            pkt.fault_code,
            pkt.hil_tick,
        ])
    return buf.getvalue()


def _fmt_json(packets: list, summary: dict) -> str:  # type: ignore[type-arg]
    """Render *packets* + *summary* as a JSON string."""
    obj = {
        "summary": summary,
        "packets": [p.to_dict() for p in packets],
    }
    return json.dumps(obj, indent=2)


# ---------------------------------------------------------------------------
# CLI command
# ---------------------------------------------------------------------------


def cmd_c2000_telemetry_decode(
    *,
    input_path: str,
    output: Optional[str] = None,
    format: str = "table",
    max_packets: int = 0,
    summary_only: bool = False,
    json_mode: bool = False,
) -> int:
    """Decode C2000 FOC telemetry packets from a raw binary capture file.

    Args:
        input_path: Path to the binary data file (e.g. data.bin).
        output: Optional path to write the decoded output.  If *None* the
            output is written to stdout.
        format: ``"table"`` (default), ``"json"``, or ``"csv"``.
        max_packets: Maximum number of packets to include in the output.
            ``0`` means *all*.
        summary_only: When ``True`` only the summary statistics dict is
            printed (always as JSON regardless of *format*).
        json_mode: When ``True`` wrap non-table output in structured JSON
            (used by agent callers).

    Returns:
        Exit code: 0 on success, 2 on error.
    """
    from eab.analyzers.c2000_telemetry import (
        decode_packets_with_stats,
        decode_summary,
        split_at_reboots,
    )

    # --- Read input file ---------------------------------------------------
    try:
        with open(input_path, "rb") as fh:
            raw = fh.read()
    except FileNotFoundError:
        _print({"error": f"File not found: {input_path}"}, json_mode=json_mode)
        return 2
    except OSError as exc:
        _print({"error": f"Cannot read {input_path}: {exc}"}, json_mode=json_mode)
        return 2

    # --- Decode ------------------------------------------------------------
    packets, checksum_failures = decode_packets_with_stats(raw)

    # Handle reboot boundaries — use the last segment (most recent boot)
    segments = split_at_reboots(packets)
    if len(segments) > 1:
        packets = segments[-1]

    if max_packets > 0:
        packets = packets[:max_packets]

    summary = decode_summary(packets, checksum_failures)

    # --- Summary-only mode -------------------------------------------------
    if summary_only:
        text = json.dumps(summary, indent=2)
        _write_output(text, output)
        return 0

    # --- Full output -------------------------------------------------------
    fmt = format.lower()

    if fmt == "table":
        first_isr = packets[0].isr_count if packets else 0
        text = _fmt_table(packets, first_isr)
    elif fmt == "json":
        text = _fmt_json(packets, summary)
    elif fmt == "csv":
        text = _fmt_csv(packets)
    else:
        _print({"error": f"Unknown format: {format!r}"}, json_mode=json_mode)
        return 2

    _write_output(text, output)
    return 0


def _write_output(text: str, output: Optional[str]) -> None:
    """Write *text* to *output* file or stdout."""
    if output:
        with open(output, "w", encoding="utf-8") as fh:
            fh.write(text)
    else:
        print(text)
