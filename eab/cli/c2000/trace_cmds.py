"""C2000 trace export command (Perfetto JSON)."""

from __future__ import annotations

import json
from typing import Optional

from eab.cli.helpers import _print


def cmd_c2000_trace_export(
    *,
    output_file: str,
    erad_data: Optional[str] = None,
    dlog_data: Optional[str] = None,
    log_file: Optional[str] = None,
    process_name: str = "C2000 Debug",
    json_mode: bool = False,
) -> int:
    """Export C2000 debug data to Perfetto JSON trace.

    Args:
        output_file: Path to write Perfetto JSON file.
        erad_data: Optional path to ERAD profiling JSON.
        dlog_data: Optional path to DLOG buffer JSON.
        log_file: Optional path to log file (one line per event).
        process_name: Process name for Perfetto trace.
        json_mode: If True, output JSON summary instead of human-readable text.

    Returns:
        Exit code (0 = success, 2 = error).
    """
    from eab.analyzers.perfetto_export import (
        DLOGTrack,
        ERADSpan,
        LogEvent,
        PerfettoExporter,
    )

    exporter = PerfettoExporter(process_name=process_name)

    if erad_data:
        try:
            with open(erad_data) as f:
                data = json.load(f)
            for span in data.get("spans", []):
                exporter.add_erad_span(ERADSpan(
                    name=span["name"],
                    start_us=span.get("start_us", 0),
                    duration_us=span["duration_us"],
                    cpu_cycles=span.get("cpu_cycles", 0),
                ))
        except (FileNotFoundError, json.JSONDecodeError, KeyError) as e:
            _print({"error": f"Failed to load ERAD data: {e}"}, json_mode=json_mode)
            return 2

    if dlog_data:
        try:
            with open(dlog_data) as f:
                data = json.load(f)
            for name, values in data.get("buffers", {}).items():
                exporter.add_dlog_track(DLOGTrack(name=name, values=values))
        except (FileNotFoundError, json.JSONDecodeError) as e:
            _print({"error": f"Failed to load DLOG data: {e}"}, json_mode=json_mode)
            return 2

    if log_file:
        try:
            with open(log_file) as f:
                for i, line in enumerate(f):
                    line = line.strip()
                    if line:
                        exporter.add_log_event(LogEvent(
                            timestamp_us=float(i) * 1000,
                            message=line,
                        ))
        except FileNotFoundError as e:
            _print({"error": f"Log file not found: {e}"}, json_mode=json_mode)
            return 2

    summary = exporter.write(output_file)
    _print(summary, json_mode=json_mode)
    return 0
