"""Shared utilities for eabctl CLI commands."""

from __future__ import annotations

import json
import os
import re
import time
from typing import Any, Optional

from eab.device_registry import _get_devices_dir


def _now_iso() -> str:
    # Keep it simple; agents mostly need consistent ordering.
    return time.strftime("%Y-%m-%dT%H:%M:%S", time.localtime())


def _print(obj: Any, *, json_mode: bool) -> None:
    if json_mode:
        print(json.dumps(obj, indent=2, sort_keys=True))
    else:
        if isinstance(obj, str):
            print(obj)
        else:
            print(json.dumps(obj, indent=2, sort_keys=True))


def _resolve_base_dir(override: Optional[str], device: Optional[str] = None) -> str:
    """Resolve session base directory.

    Priority:
    1. Explicit --base-dir override
    2. /tmp/eab-devices/{device or "default"}/
    """
    if override:
        return override
    return os.path.join(_get_devices_dir(), device or "default")


def _read_text(path: str) -> str:
    with open(path, "r", encoding="utf-8", errors="replace") as f:
        return f.read()


def _tail_lines(path: str, lines: int) -> list[str]:
    try:
        text = _read_text(path)
    except FileNotFoundError:
        return []
    raw_lines = text.splitlines()
    if lines <= 0:
        return []
    return raw_lines[-lines:]


def _read_bytes(path: str, offset: int, length: int) -> bytes:
    if length <= 0:
        return b""
    with open(path, "rb") as f:
        f.seek(offset)
        return f.read(length)


def _parse_event_line(line: str) -> dict[str, Any]:
    try:
        return json.loads(line)
    except json.JSONDecodeError:
        return {"raw": line, "error": "invalid_json"}


def _tail_events(path: str, lines: int) -> list[dict[str, Any]]:
    raw = _tail_lines(path, lines)
    return [_parse_event_line(line) for line in raw]


_TS_PREFIX = re.compile(r"^\[(\d{2}:\d{2}:\d{2}\.\d{3})\]\s+(.*)$")


def _parse_log_line(line: str) -> dict[str, Any]:
    m = _TS_PREFIX.match(line)
    if not m:
        return {"timestamp": None, "content": line, "raw": line}
    return {"timestamp": m.group(1), "content": m.group(2), "raw": line}


def _event_matches(
    event: dict[str, Any],
    *,
    event_type: Optional[str],
    contains: Optional[str],
    command: Optional[str],
) -> bool:
    if event_type and event.get("type") != event_type:
        return False
    if command and event.get("data", {}).get("command") != command:
        return False
    if contains:
        try:
            blob = json.dumps(event, sort_keys=True)
        except Exception:
            blob = str(event)
        if contains not in blob:
            return False
    return True
