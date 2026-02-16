"""Perfetto trace export for C2000 debug data.

Converts ERAD profiling results, DLOG buffer captures, and serial logs
into Chrome JSON trace format viewable at ui.perfetto.dev.

Data sources mapped to Perfetto event types:
- ERAD profiling → duration events (function execution spans)
- DLOG buffers → counter tracks (variable values over sample index)
- Log lines → instant events (timestamped markers)

All sources combined into one Perfetto JSON file.
"""

from __future__ import annotations

import json
from dataclasses import dataclass, field
from pathlib import Path
from typing import IO, Optional


@dataclass
class ERADSpan:
    """A profiled function execution span from ERAD."""

    name: str
    start_us: float
    duration_us: float
    cpu_cycles: int = 0


@dataclass
class DLOGTrack:
    """A DLOG buffer as a counter track."""

    name: str
    values: list[float]
    sample_interval_us: float = 0.0  # 0 = sample index only


@dataclass
class LogEvent:
    """A log line as an instant event."""

    timestamp_us: float
    message: str
    channel: str = "serial"


class PerfettoExporter:
    """Build a Perfetto JSON trace from C2000 debug data.

    Usage:
        exporter = PerfettoExporter(process_name="C2000 Debug")
        exporter.add_erad_span(ERADSpan("motor_isr", 0, 25.5, 3060))
        exporter.add_dlog_track(DLOGTrack("dBuff1", [1.0, 2.0, 3.0]))
        exporter.add_log_event(LogEvent(100.0, "Boot complete"))
        exporter.write("trace.json")
    """

    def __init__(self, process_name: str = "C2000 Debug"):
        self._process_name = process_name
        self._erad_spans: list[ERADSpan] = []
        self._dlog_tracks: list[DLOGTrack] = []
        self._log_events: list[LogEvent] = []

    def add_erad_span(self, span: ERADSpan) -> None:
        """Add an ERAD profiling span (duration event)."""
        self._erad_spans.append(span)

    def add_erad_spans(self, spans: list[ERADSpan]) -> None:
        """Add multiple ERAD profiling spans."""
        self._erad_spans.extend(spans)

    def add_dlog_track(self, track: DLOGTrack) -> None:
        """Add a DLOG buffer as a counter track."""
        self._dlog_tracks.append(track)

    def add_dlog_tracks(self, tracks: list[DLOGTrack]) -> None:
        """Add multiple DLOG buffer tracks."""
        self._dlog_tracks.extend(tracks)

    def add_log_event(self, event: LogEvent) -> None:
        """Add a log line as an instant event."""
        self._log_events.append(event)

    def add_log_events(self, events: list[LogEvent]) -> None:
        """Add multiple log events."""
        self._log_events.extend(events)

    def build_trace(self) -> dict:
        """Build the complete Perfetto trace dict.

        Returns:
            Dict with "traceEvents" and "displayTimeUnit" keys.
        """
        events: list[dict] = []
        tid_map: dict[str, int] = {}  # track name → tid
        next_tid = 1

        def get_tid(name: str) -> int:
            nonlocal next_tid
            if name not in tid_map:
                tid_map[name] = next_tid
                next_tid += 1
            return tid_map[name]

        # ERAD spans → duration events (ph: "X" = complete event)
        for span in self._erad_spans:
            tid = get_tid(f"erad:{span.name}")
            events.append({
                "pid": 1,
                "tid": tid,
                "ts": span.start_us,
                "dur": span.duration_us,
                "ph": "X",
                "name": span.name,
                "cat": "erad",
                "args": {
                    "cpu_cycles": span.cpu_cycles,
                    "duration_us": span.duration_us,
                },
            })

        # DLOG tracks → counter events (ph: "C")
        for track in self._dlog_tracks:
            tid = get_tid(f"dlog:{track.name}")
            for i, value in enumerate(track.values):
                if track.sample_interval_us > 0:
                    ts = i * track.sample_interval_us
                else:
                    ts = float(i)  # Use sample index as timestamp
                events.append({
                    "pid": 1,
                    "tid": tid,
                    "ts": ts,
                    "ph": "C",
                    "name": track.name,
                    "cat": "dlog",
                    "args": {track.name: value},
                })

        # Log events → instant events (ph: "i")
        for event in self._log_events:
            tid = get_tid(f"log:{event.channel}")
            events.append({
                "pid": 1,
                "tid": tid,
                "ts": event.timestamp_us,
                "ph": "i",
                "name": event.message[:80],
                "cat": "log",
                "s": "g",  # global scope
                "args": {"channel": event.channel, "raw": event.message},
            })

        # Metadata events
        metadata: list[dict] = [
            {
                "pid": 1,
                "tid": 0,
                "name": "process_name",
                "ph": "M",
                "cat": "__metadata",
                "args": {"name": self._process_name},
            },
        ]
        for name, tid in sorted(tid_map.items(), key=lambda x: x[1]):
            metadata.append({
                "pid": 1,
                "tid": tid,
                "name": "thread_name",
                "ph": "M",
                "cat": "__metadata",
                "args": {"name": name},
            })

        return {
            "traceEvents": metadata + events,
            "displayTimeUnit": "ms",
        }

    def write(self, output_path: str | Path) -> dict:
        """Write Perfetto JSON trace to file.

        Args:
            output_path: Path to output .json file.

        Returns:
            Summary dict with event counts and file size.
        """
        output_path = Path(output_path)
        trace = self.build_trace()

        with open(output_path, "w") as f:
            json.dump(trace, f)

        return {
            "erad_spans": len(self._erad_spans),
            "dlog_tracks": len(self._dlog_tracks),
            "log_events": len(self._log_events),
            "total_events": len(trace["traceEvents"]),
            "output_path": str(output_path),
            "output_size_bytes": output_path.stat().st_size,
        }

    def write_to_stream(self, output: IO[str]) -> dict:
        """Write Perfetto JSON trace to a stream.

        Args:
            output: File-like object with write() method.

        Returns:
            Summary dict with event counts.
        """
        trace = self.build_trace()
        json.dump(trace, output)
        return {
            "erad_spans": len(self._erad_spans),
            "dlog_tracks": len(self._dlog_tracks),
            "log_events": len(self._log_events),
            "total_events": len(trace["traceEvents"]),
        }
