"""Shared utilities for eabctl CLI commands."""

from __future__ import annotations

import json
import os
import re
import time
from typing import Any, Optional

from eab.singleton import check_singleton
from eab.device_registry import list_devices, _get_devices_dir

DEFAULT_BASE_DIR = "/tmp/eab-session"


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
    2. --device name → /tmp/eab-devices/<name>/
    3. Single running device in /tmp/eab-devices/ → use it
    4. Legacy global singleton → its base_dir
    5. Default /tmp/eab-session/
    """
    if override:
        return override
    if device:
        return os.path.join(_get_devices_dir(), device)

    # Fall back to legacy global singleton first (cheap — single PID file check)
    existing = check_singleton()
    if existing and existing.is_alive and existing.base_dir and existing.base_dir != "unknown":
        return existing.base_dir

    # Auto-detect: scan devices dir only when no legacy singleton is running
    devices_dir = _get_devices_dir()
    if os.path.isdir(devices_dir):
        devices = list_devices()
        running = [d for d in devices if d.is_alive]
        if len(running) == 1:
            return running[0].base_dir

    return DEFAULT_BASE_DIR


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
