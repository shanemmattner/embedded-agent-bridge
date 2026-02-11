"""
RTT stream processor for Embedded Agent Bridge.

Sits between raw RTT bytes (from pylink rtt_read()) and clean outputs:
- rtt.log: sanitized text, rotated
- rtt.jsonl: structured records
- rtt.csv: DATA records as CSV (timestamp, key=value columns)
- asyncio.Queue: for real-time plotter

Handles ANSI stripping, line framing, log format auto-detection,
log rotation, and boot-reset detection.

Does NOT strip arbitrary byte values — filters structurally, not by content.
"""

from __future__ import annotations

import asyncio
import json
import os
import re
import time
from enum import Enum, auto
from pathlib import Path
from typing import IO, Optional

from .device_control import strip_ansi

# ---------------------------------------------------------------------------
# Log format detection and parsing
# ---------------------------------------------------------------------------

_TIMESTAMP_RE = re.compile(r"\[(\d+:\d+:\d+[.,]\d+)")
_DATA_RE = re.compile(r"DATA:\s*(.*)")
_STATE_RE = re.compile(r"STATE:\s*(\S+)")
_KV_RE = re.compile(r"(\w+)=(-?[\d.]+)")
_BANNER_RE = re.compile(r"^(###RTT Client:|SEGGER J-Link)")

# Boot patterns that indicate target reset
_BOOT_PATTERNS = [
    "*** Booting Zephyr",
    "*** Booting nRF Connect SDK",
    "Booting Zephyr OS",
    "I: Starting bootloader",
    "rst:0x",           # ESP32 reset reason
    "I (0) boot:",      # ESP-IDF early boot
]


class LogFormat(Enum):
    UNKNOWN = auto()
    ZEPHYR = auto()
    ESP_IDF = auto()
    NRF_SDK = auto()
    GENERIC = auto()


_FORMAT_DETECTORS: dict[LogFormat, re.Pattern] = {
    LogFormat.ZEPHYR: re.compile(r"^\[[\d:.,]+\]\s+<\w+>"),
    LogFormat.ESP_IDF: re.compile(r"^[EWIDV]\s+\(\d+\)\s+\w+:"),
    LogFormat.NRF_SDK: re.compile(r"^<\w+>\s+\w+:"),
}

# Zephyr level extraction: <inf>, <wrn>, <err>, <dbg>
_ZEPHYR_LEVEL_RE = re.compile(r"<(\w+)>")
_ZEPHYR_MODULE_RE = re.compile(r"<\w+>\s+(\w+):")

# ESP-IDF level: single char at start
_ESPIDF_LEVEL_MAP = {"E": "err", "W": "wrn", "I": "inf", "D": "dbg", "V": "dbg"}
_ESPIDF_PARSE_RE = re.compile(r"^([EWIDV])\s+\((\d+)\)\s+(\w+):\s*(.*)")

# nRF SDK: <info>, <warning>, <error>, <debug>
_NRFSDK_PARSE_RE = re.compile(r"^<(\w+)>\s+(\w+):\s*(.*)")
_NRFSDK_LEVEL_MAP = {"info": "inf", "warning": "wrn", "error": "err", "debug": "dbg"}


def _detect_format(line: str) -> LogFormat:
    """Detect log format from a single cleaned line."""
    for fmt, pattern in _FORMAT_DETECTORS.items():
        if pattern.match(line):
            return fmt
    return LogFormat.GENERIC


def _parse_line(line: str, fmt: LogFormat) -> Optional[dict]:
    """Parse a cleaned log line into a structured record."""
    if not line.strip():
        return None

    # Extract key=value data and state from any format
    data_match = _DATA_RE.search(line)
    state_match = _STATE_RE.search(line)

    if state_match:
        ts_m = _TIMESTAMP_RE.search(line)
        return {
            "type": "state",
            "ts": ts_m.group(1) if ts_m else None,
            "state": state_match.group(1),
        }

    if data_match:
        kvs = dict(_KV_RE.findall(data_match.group(1)))
        if kvs:
            ts_m = _TIMESTAMP_RE.search(line)
            return {
                "type": "data",
                "ts": ts_m.group(1) if ts_m else None,
                "values": {k: float(v) for k, v in kvs.items()},
            }

    # Format-specific parsing for log lines
    if fmt == LogFormat.ZEPHYR:
        ts_m = _TIMESTAMP_RE.search(line)
        level_m = _ZEPHYR_LEVEL_RE.search(line)
        mod_m = _ZEPHYR_MODULE_RE.search(line)
        # Extract message after "module: "
        msg = line
        if mod_m:
            idx = line.find(mod_m.group(0)) + len(mod_m.group(0))
            msg = line[idx:].strip()
        return {
            "type": "log",
            "ts": ts_m.group(1) if ts_m else None,
            "level": level_m.group(1) if level_m else None,
            "module": mod_m.group(1) if mod_m else None,
            "message": msg,
        }

    if fmt == LogFormat.ESP_IDF:
        m = _ESPIDF_PARSE_RE.match(line)
        if m:
            return {
                "type": "log",
                "ts": m.group(2),
                "level": _ESPIDF_LEVEL_MAP.get(m.group(1)),
                "module": m.group(3),
                "message": m.group(4),
            }

    if fmt == LogFormat.NRF_SDK:
        m = _NRFSDK_PARSE_RE.match(line)
        if m:
            return {
                "type": "log",
                "ts": None,
                "level": _NRFSDK_LEVEL_MAP.get(m.group(1), m.group(1)),
                "module": m.group(2),
                "message": m.group(3),
            }

    # Generic: just return the line as a log message
    ts_m = _TIMESTAMP_RE.search(line)
    return {
        "type": "log",
        "ts": ts_m.group(1) if ts_m else None,
        "level": None,
        "module": None,
        "message": line,
    }


def _is_printable_line(line: str) -> bool:
    """Check if a line contains at least some printable content."""
    return any(ch.isprintable() or ch in ("\t", " ") for ch in line)


# ---------------------------------------------------------------------------
# Stream processor
# ---------------------------------------------------------------------------

class RTTStreamProcessor:
    """Process raw RTT bytes into clean log lines and structured records.

    Handles ANSI stripping, line framing, format auto-detection,
    log rotation, and target reset detection.
    """

    def __init__(
        self,
        log_path: Path | None = None,
        jsonl_path: Path | None = None,
        csv_path: Path | None = None,
        queue: Optional[asyncio.Queue] = None,
        max_log_bytes: int = 5_000_000,
        max_line_chars: int = 1024,
        max_backups: int = 3,
    ):
        self._log_path = log_path
        self._jsonl_path = jsonl_path
        self._csv_path = csv_path
        self._queue = queue
        self._max_log_bytes = max_log_bytes
        self._max_line_chars = max_line_chars
        self._max_backups = max_backups

        self._buf = ""
        self._format: LogFormat = LogFormat.UNKNOWN
        self._detect_count = 0  # Lines seen for format detection

        # Persistent file handles (opened lazily, flushed on write)
        self._log_f: Optional[IO] = None
        self._jsonl_f: Optional[IO] = None
        self._csv_f: Optional[IO] = None
        self._csv_columns: list[str] = []  # Learned from first DATA record
        self._log_bytes_written = 0

    def feed(self, raw: bytes) -> list[dict]:
        """Feed raw bytes from pylink rtt_read(). Returns parsed records."""
        text = raw.decode("utf-8", errors="replace")
        self._buf += text

        # Normalize line endings
        self._buf = self._buf.replace("\r\n", "\n").replace("\r", "\n")

        results: list[dict] = []

        # Process complete lines
        while "\n" in self._buf:
            line, self._buf = self._buf.split("\n", 1)
            self._process_line(line, results)

        # Force break if buffer exceeds max line length
        while len(self._buf) > self._max_line_chars:
            chunk = self._buf[: self._max_line_chars]
            self._buf = self._buf[self._max_line_chars :]
            self._process_line(chunk, results)

        return results

    def flush(self) -> list[dict]:
        """Force-emit whatever is in the line buffer. Flush file handles."""
        results: list[dict] = []
        if self._buf.strip():
            self._process_line(self._buf, results)
        self._buf = ""
        # Flush all open handles
        for f in (self._log_f, self._jsonl_f, self._csv_f):
            if f and not f.closed:
                try:
                    f.flush()
                except OSError:
                    pass
        return results

    def close(self) -> None:
        """Close all file handles."""
        for f in (self._log_f, self._jsonl_f, self._csv_f):
            if f and not f.closed:
                try:
                    f.close()
                except OSError:
                    pass
        self._log_f = self._jsonl_f = self._csv_f = None

    def drain_initial(self, raw: bytes) -> None:
        """Discard stale ring buffer content on connect."""
        pass

    def reset(self) -> None:
        """Clear state on target reset. Re-enables format detection."""
        self._buf = ""
        self._format = LogFormat.UNKNOWN
        self._detect_count = 0

    def _process_line(self, line: str, results: list[dict]) -> None:
        """Sanitize, parse, and emit a single line."""
        cleaned = strip_ansi(line).strip()

        # Skip empty lines and SEGGER banners
        if not cleaned or _BANNER_RE.match(cleaned):
            return

        # Structural validation: discard lines with no printable content
        if not _is_printable_line(cleaned):
            return

        # Check for target reset
        for pattern in _BOOT_PATTERNS:
            if pattern in cleaned:
                self.reset()
                break

        # Auto-detect format from first few valid lines
        if self._format == LogFormat.UNKNOWN and self._detect_count < 10:
            detected = _detect_format(cleaned)
            if detected != LogFormat.GENERIC:
                self._format = detected
            self._detect_count += 1
            # After 10 lines with no match, lock to GENERIC
            if self._detect_count >= 10 and self._format == LogFormat.UNKNOWN:
                self._format = LogFormat.GENERIC

        fmt = self._format if self._format != LogFormat.UNKNOWN else LogFormat.GENERIC

        # Parse
        record = _parse_line(cleaned, fmt)

        # Write clean line to log
        if self._log_path:
            self._write_log(cleaned)

        # Write structured record to jsonl
        if record and self._jsonl_path:
            self._write_jsonl(record)

        # Write DATA records to CSV
        if record and record.get("type") == "data" and self._csv_path:
            self._write_csv(record)

        # Enqueue for plotter
        if record and self._queue is not None:
            try:
                self._queue.put_nowait(record)
            except asyncio.QueueFull:
                try:
                    self._queue.get_nowait()
                except asyncio.QueueEmpty:
                    pass
                try:
                    self._queue.put_nowait(record)
                except asyncio.QueueFull:
                    pass

        if record:
            results.append(record)

    def _open_log(self) -> IO:
        """Open or reopen log file handle."""
        if self._log_f and not self._log_f.closed:
            return self._log_f
        self._log_f = open(self._log_path, "a", encoding="utf-8", buffering=1)
        try:
            self._log_bytes_written = os.path.getsize(self._log_path)
        except OSError:
            self._log_bytes_written = 0
        return self._log_f

    def _write_log(self, line: str) -> None:
        """Append a clean line to rtt.log, rotating if needed."""
        if self._log_path is None:
            return

        if self._log_bytes_written >= self._max_log_bytes:
            self._rotate_log()

        try:
            f = self._open_log()
            encoded = line + "\n"
            f.write(encoded)
            self._log_bytes_written += len(encoded.encode("utf-8"))
        except OSError:
            pass

    def _rotate_log(self) -> None:
        """Rotate rtt.log → rtt.log.1 → rtt.log.2 etc."""
        # Close current handle
        if self._log_f and not self._log_f.closed:
            self._log_f.close()
            self._log_f = None

        p = Path(self._log_path)
        oldest = p.parent / f"{p.name}.{self._max_backups}"
        if oldest.exists():
            oldest.unlink(missing_ok=True)
        for i in range(self._max_backups - 1, 0, -1):
            src = p.parent / f"{p.name}.{i}"
            dst = p.parent / f"{p.name}.{i + 1}"
            if src.exists():
                src.rename(dst)
        if p.exists():
            p.rename(p.parent / f"{p.name}.1")

        self._log_bytes_written = 0

    def _write_jsonl(self, record: dict) -> None:
        """Append a structured record to rtt.jsonl."""
        if self._jsonl_path is None:
            return
        try:
            if self._jsonl_f is None or self._jsonl_f.closed:
                self._jsonl_f = open(self._jsonl_path, "a", encoding="utf-8", buffering=1)
            self._jsonl_f.write(json.dumps(record, separators=(",", ":")) + "\n")
        except OSError:
            pass

    def _write_csv(self, record: dict) -> None:
        """Append a DATA record to rtt.csv. Auto-discovers columns."""
        if self._csv_path is None:
            return
        values = record.get("values", {})
        if not values:
            return

        try:
            need_header = False
            if self._csv_f is None or self._csv_f.closed:
                exists = os.path.exists(self._csv_path) and os.path.getsize(self._csv_path) > 0
                self._csv_f = open(self._csv_path, "a", encoding="utf-8", buffering=1)
                if not exists:
                    need_header = True

            # Learn columns from first record or expand if new keys appear
            new_keys = [k for k in values if k not in self._csv_columns]
            if new_keys:
                self._csv_columns.extend(new_keys)
                need_header = True
                # Rewrite header by reopening
                if self._csv_f and not self._csv_f.closed:
                    self._csv_f.close()
                self._csv_f = open(self._csv_path, "w", encoding="utf-8", buffering=1)
                self._csv_f.write("timestamp," + ",".join(self._csv_columns) + "\n")

            if need_header and not new_keys:
                self._csv_f.write("timestamp," + ",".join(self._csv_columns) + "\n")

            # Write row
            ts = record.get("ts") or f"{time.time():.3f}"
            row = [ts] + [str(values.get(c, "")) for c in self._csv_columns]
            self._csv_f.write(",".join(row) + "\n")
        except OSError:
            pass
