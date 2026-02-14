"""Internal helpers for serial commands."""

from __future__ import annotations

import os
import time
from typing import Any, Optional

from eab.cli.helpers import _parse_event_line, _event_matches


def _await_log_ack(log_path: str, marker: str, timeout_s: float) -> bool:
    """Tail *log_path* until *marker* appears or *timeout_s* expires.

    Args:
        log_path: Path to the log file to tail.
        marker: Substring to search for in new log lines.
        timeout_s: Maximum seconds to wait.

    Returns:
        True if the marker was found, False on timeout or missing file.
    """
    start = time.time()
    try:
        with open(log_path, "r", encoding="utf-8", errors="replace") as f:
            f.seek(0, os.SEEK_END)
            pos = f.tell()
            while time.time() - start < timeout_s:
                f.seek(pos)
                chunk = f.read()
                if chunk:
                    for line in chunk.splitlines():
                        if marker in line:
                            return True
                    pos = f.tell()
                time.sleep(0.05)
    except FileNotFoundError:
        return False
    return False


def _await_event(
    events_path: str,
    *,
    event_type: Optional[str],
    contains: Optional[str],
    command: Optional[str],
    timeout_s: float,
) -> Optional[dict[str, Any]]:
    """Tail *events_path* (JSONL) for a matching event.

    Args:
        events_path: Path to the ``events.jsonl`` file.
        event_type: If set, only match events with this ``type`` field.
        contains: If set, only match events whose JSON contains this substring.
        command: If set, only match events whose ``data.command`` equals this.
        timeout_s: Maximum seconds to wait.

    Returns:
        The matched event dict, or None on timeout / missing file.
    """
    start = time.time()
    try:
        with open(events_path, "r", encoding="utf-8", errors="replace") as f:
            f.seek(0, os.SEEK_END)
            pos = f.tell()
            while time.time() - start < timeout_s:
                f.seek(pos)
                chunk = f.read()
                if chunk:
                    for line in chunk.splitlines():
                        event = _parse_event_line(line)
                        if _event_matches(
                            event,
                            event_type=event_type,
                            contains=contains,
                            command=command,
                        ):
                            return event
                    pos = f.tell()
                time.sleep(0.05)
    except FileNotFoundError:
        return None
    return None
