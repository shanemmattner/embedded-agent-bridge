"""
Status Manager for Serial Daemon.

Writes connection state and statistics to status.json for agent consumption.
"""

from typing import Dict, Optional
from datetime import datetime
import json

from .interfaces import FileSystemInterface, ClockInterface, ConnectionState


class StatusManager:
    """
    Manages status.json file with daemon state.

    Provides a single JSON file that agents can read to understand:
    - Current session info
    - Connection state
    - Performance counters
    - Pattern match statistics
    """

    def __init__(
        self,
        filesystem: FileSystemInterface,
        clock: ClockInterface,
        status_path: str,
    ):
        self._fs = filesystem
        self._clock = clock
        self._status_path = status_path

        self._session_id: str = ""
        self._started: Optional[datetime] = None
        self._port: str = ""
        self._baud: int = 0
        self._state = ConnectionState.DISCONNECTED
        self._reconnect_count = 0
        self._lines_logged = 0
        self._bytes_received = 0
        self._commands_sent = 0
        self._alerts_triggered = 0
        self._pattern_counts: Dict[str, int] = {}

    def start_session(self, session_id: str, port: str, baud: int) -> None:
        """Start tracking a new session."""
        self._session_id = session_id
        self._port = port
        self._baud = baud
        self._started = self._clock.now()
        self._state = ConnectionState.CONNECTING
        self._reconnect_count = 0
        self._lines_logged = 0
        self._bytes_received = 0
        self._commands_sent = 0
        self._alerts_triggered = 0
        self._pattern_counts = {}
        self.update()

    def set_connection_state(self, state: ConnectionState) -> None:
        """Update connection state."""
        self._state = state
        self.update()

    def record_reconnect(self) -> None:
        """Record a reconnection."""
        self._reconnect_count += 1
        self.update()

    def record_line(self) -> None:
        """Record a logged line."""
        self._lines_logged += 1

    def record_bytes(self, count: int) -> None:
        """Record bytes received."""
        self._bytes_received += count

    def record_command(self) -> None:
        """Record a command sent."""
        self._commands_sent += 1

    def record_alert(self, pattern: str) -> None:
        """Record an alert triggered."""
        self._alerts_triggered += 1
        self._pattern_counts[pattern] = self._pattern_counts.get(pattern, 0) + 1

    def update(self) -> None:
        """Write current status to file."""
        now = self._clock.now()
        uptime = (now - self._started).total_seconds() if self._started else 0

        status = {
            "session": {
                "id": self._session_id,
                "started": self._started.isoformat() if self._started else None,
                "uptime_seconds": int(uptime),
            },
            "connection": {
                "port": self._port,
                "baud": self._baud,
                "status": self._state.value,
                "reconnects": self._reconnect_count,
            },
            "counters": {
                "lines_logged": self._lines_logged,
                "bytes_received": self._bytes_received,
                "commands_sent": self._commands_sent,
                "alerts_triggered": self._alerts_triggered,
            },
            "patterns": self._pattern_counts,
            "last_updated": now.isoformat(),
        }

        self._fs.write_file(self._status_path, json.dumps(status, indent=2))
