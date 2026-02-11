"""
Event emission for the Embedded Agent Bridge daemon.

Writes JSONL events to disk so agents and other processes can tail them
without blocking the daemon or requiring sockets.
"""

from __future__ import annotations

import json
import os
from typing import Any, Optional

import portalocker

from .interfaces import FileSystemInterface, ClockInterface


class EventEmitter:
    """Append-only JSONL event emitter with simple sequence tracking."""

    def __init__(self, filesystem: FileSystemInterface, clock: ClockInterface, events_path: str) -> None:
        self._fs = filesystem
        self._clock = clock
        self._events_path = events_path
        self._sequence = 0
        self._session_id: Optional[str] = None

        events_dir = os.path.dirname(events_path) or "."
        self._fs.ensure_dir(events_dir)
        self._sequence = self._load_last_sequence()

    def set_session_id(self, session_id: str) -> None:
        self._session_id = session_id

    def emit(self, event_type: str, data: Optional[dict[str, Any]] = None, level: str = "info") -> dict[str, Any]:
        self._sequence += 1
        payload = {
            "schema_version": 1,
            "sequence": self._sequence,
            "timestamp": self._clock.now().isoformat(),
            "type": event_type,
            "level": level,
            "session_id": self._session_id,
            "data": data or {},
        }
        self._append_line(json.dumps(payload, sort_keys=True))
        return payload

    def _append_line(self, content: str) -> None:
        with open(self._events_path, "a", encoding="utf-8") as f:
            portalocker.lock(f, portalocker.LOCK_EX)
            try:
                f.write(content)
                if not content.endswith("\n"):
                    f.write("\n")
                f.flush()
            finally:
                portalocker.unlock(f)

    def _load_last_sequence(self) -> int:
        if not os.path.exists(self._events_path):
            return 0

        try:
            with open(self._events_path, "rb") as f:
                f.seek(0, os.SEEK_END)
                size = f.tell()
                if size == 0:
                    return 0

                # Read the last line efficiently.
                offset = min(size, 4096)
                f.seek(-offset, os.SEEK_END)
                chunk = f.read().splitlines()
                if not chunk:
                    return 0
                last_line = chunk[-1].decode("utf-8", errors="replace")
        except Exception:
            return 0

        try:
            data = json.loads(last_line)
            return int(data.get("sequence", 0) or 0)
        except Exception:
            return 0
