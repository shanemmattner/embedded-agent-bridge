"""
High-signal capture helpers for extracting structured/binary payloads from logs.

Motivation:
EAB's main session log (`latest.log`) is intentionally "human + agent" friendly:
it includes timestamps and occasional daemon-injected status lines. That makes
bulk extraction of device-emitted payloads (e.g. base64 blobs) fragile if you
try to copy/paste from the log directly.

This module provides a focused helper to capture data between markers and write
it out cleanly.
"""

from __future__ import annotations

import base64
import os
import re
import time
from dataclasses import dataclass
from typing import Literal, Optional


_TS_PREFIX = re.compile(r"^\[(\d{2}:\d{2}:\d{2}\.\d{3})\]\s+(.*)$")
_BASE64_LINE = re.compile(r"^[A-Za-z0-9+/=]+$")


def strip_timestamp_prefix(line: str) -> str:
    m = _TS_PREFIX.match(line)
    if not m:
        return line
    return m.group(2)


@dataclass(frozen=True)
class CaptureResult:
    start_seen: bool
    end_seen: bool
    lines_seen: int
    lines_captured: int
    bytes_written: int
    duration_ms: int
    output_path: str
    decode_base64: bool


def capture_between_markers(
    *,
    log_path: str,
    start_marker: str,
    end_marker: str,
    output_path: str,
    timeout_s: float = 120.0,
    from_end: bool = True,
    strip_timestamps: bool = True,
    filter_mode: Literal["none", "base64"] = "base64",
    decode_base64: bool = False,
) -> CaptureResult:
    """
    Capture log lines between `start_marker` and `end_marker` and write them to a file.

    Notes:
    - This reads from `latest.log` (or any log file path) and produces a clean payload
      output that excludes timestamps and non-payload noise when using `filter_mode`.
    - If `decode_base64=True`, the captured payload is base64-decoded and written as bytes.
    """
    started = time.time()
    deadline = started + max(timeout_s, 0.0)

    os.makedirs(os.path.dirname(output_path) or ".", exist_ok=True)

    start_seen = False
    end_seen = False
    lines_seen = 0
    captured_lines: list[str] = []

    with open(log_path, "r", encoding="utf-8", errors="replace") as f:
        if from_end:
            f.seek(0, os.SEEK_END)

        while True:
            if time.time() > deadline and not (start_seen and end_seen):
                break

            raw = f.readline()
            if raw == "":
                time.sleep(0.05)
                continue

            line = raw.rstrip("\n")
            lines_seen += 1

            content = strip_timestamp_prefix(line) if strip_timestamps else line

            if not start_seen:
                if start_marker in content:
                    start_seen = True
                continue

            if end_marker in content:
                end_seen = True
                break

            payload = content.strip()

            if filter_mode == "base64":
                # Keep only base64-ish lines. This reliably excludes timestamps, EAB
                # injected messages, and normal ESP-IDF logs.
                if not payload or not _BASE64_LINE.match(payload):
                    continue

            captured_lines.append(payload)

    bytes_written = 0
    if decode_base64:
        joined = "".join(captured_lines)
        decoded = base64.b64decode(joined, validate=False)
        with open(output_path, "wb") as out:
            out.write(decoded)
            bytes_written = len(decoded)
    else:
        with open(output_path, "w", encoding="utf-8") as out:
            if captured_lines:
                out.write("\n".join(captured_lines))
                out.write("\n")
            bytes_written = out.tell()

    duration_ms = int((time.time() - started) * 1000)
    return CaptureResult(
        start_seen=start_seen,
        end_seen=end_seen,
        lines_seen=lines_seen,
        lines_captured=len(captured_lines),
        bytes_written=bytes_written,
        duration_ms=duration_ms,
        output_path=output_path,
        decode_base64=decode_base64,
    )

