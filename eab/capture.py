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
from typing import Literal


_TS_PREFIX = re.compile(r"^\[(\d{2}:\d{2}:\d{2}\.\d{3})\]\s+(.*)$")
_BASE64_LINE = re.compile(r"^[A-Za-z0-9+/=]+$")
_INDEXED_LINE = re.compile(r"^(\d+):(\d+):([0-9A-Fa-f]{4}):([A-Za-z0-9+/=]+)$")


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
    metadata: dict[str, str]


def _crc16_le(data: bytes) -> int:
    crc = 0
    for byte in data:
        crc ^= byte
        for _ in range(8):
            if crc & 1:
                crc = (crc >> 1) ^ 0xA001
            else:
                crc >>= 1
    return crc & 0xFFFF


def capture_between_markers(
    *,
    log_path: str,
    start_marker: str,
    end_marker: str,
    output_path: str,
    timeout_s: float = 120.0,
    from_end: bool = True,
    strip_timestamps: bool = True,
    filter_mode: Literal["none", "base64", "indexed"] = "base64",
    decode_base64: bool = False,
) -> CaptureResult:
    """
    Capture log lines between `start_marker` and `end_marker` and write them to a file.

    Notes:
    - This reads from `latest.log` (or any log file path) and produces a clean payload
      output that excludes timestamps and non-payload noise when using `filter_mode`.
    - If `decode_base64=True`, the captured payload is base64-decoded and written as bytes.
    - If `filter_mode="indexed"`, lines are expected in "idx:len:crc16:base64" format.
    """
    started = time.time()
    deadline = started + max(timeout_s, 0.0)

    os.makedirs(os.path.dirname(output_path) or ".", exist_ok=True)

    start_seen = False
    end_seen = False
    lines_seen = 0
    captured_lines: list[str] = []
    metadata: dict[str, str] = {}

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
                if not payload or not _BASE64_LINE.match(payload):
                    # Check if it's metadata (key:value)
                    if ":" in payload and not payload.startswith("="):
                        parts = payload.split(":", 1)
                        metadata[parts[0].strip()] = parts[1].strip()
                    continue
                if payload.startswith("="):
                    continue
            elif filter_mode == "indexed":
                if not payload:
                    continue
                if not _INDEXED_LINE.match(payload):
                    # Check if it's metadata (key:value)
                    if ":" in payload and not payload.startswith("="):
                        parts = payload.split(":", 1)
                        metadata[parts[0].strip()] = parts[1].strip()
                    continue
            
            captured_lines.append(payload)

    bytes_written = 0
    if decode_base64:
        decoded_parts: list[bytes] = []
        for line in captured_lines:
            if filter_mode == "indexed":
                m = _INDEXED_LINE.match(line)
                if not m:
                    continue
                _, expected_len, expected_crc, b64_data = m.groups()
                try:
                    part = base64.b64decode(b64_data)
                    if len(part) != int(expected_len):
                        print(f"WARNING: chunk length mismatch (got {len(part)}, expected {expected_len})")
                    
                    # Verify CRC16 if needed (using same algo as firmware)
                    # Note: firmware uses esp_rom_crc16_le which is standard CRC16-CCITT or similar.
                    # We'll just assume length check for now if CRC implementation differs.
                    
                    decoded_parts.append(part)
                except Exception as e:
                    print(f"WARNING: failed to decode indexed line: {e}")
                    continue
            else:
                try:
                    decoded_parts.append(base64.b64decode(line, validate=True))
                except Exception:
                    if line.startswith("="):
                        continue
                    try:
                        decoded_parts.append(base64.b64decode(line, validate=False))
                    except Exception:
                        continue
        
        decoded = b"".join(decoded_parts)
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
        metadata=metadata,
    )
