"""
Status Manager for Serial Daemon.

Writes connection state and statistics to status.json for agent consumption.
Uses atomic file writes to prevent race conditions with agent reads.
"""

from typing import Dict, Optional
from datetime import datetime
import json
import os
import tempfile

from .interfaces import FileSystemInterface, ClockInterface, ConnectionState


class StatusManager:
    """
    Manages status.json file with daemon state.

    Provides a single JSON file that agents can read to understand:
    - Current session info
    - Connection state
    - Performance counters
    - Pattern match statistics
    - Health indicators for agent monitoring

    Uses atomic file writes (temp file + rename) to prevent partial reads.
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
        self._stream = {
            "enabled": False,
            "active": False,
            "mode": "raw",
            "chunk_size": 0,
            "marker": None,
            "pattern_matching": True,
        }

        # Health tracking
        self._last_activity_time: Optional[datetime] = None
        self._bytes_last_minute: int = 0
        self._bytes_minute_start: Optional[datetime] = None
        self._read_errors: int = 0
        self._usb_disconnects: int = 0
        self._reset_statistics: dict = {}

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

    def record_activity(self, byte_count: int = 0) -> None:
        """Record serial activity for health monitoring."""
        now = self._clock.now()
        self._last_activity_time = now

        # Track bytes per minute for throughput monitoring
        if self._bytes_minute_start is None:
            self._bytes_minute_start = now
            self._bytes_last_minute = byte_count
        elif (now - self._bytes_minute_start).total_seconds() >= 60:
            # Reset minute counter
            self._bytes_minute_start = now
            self._bytes_last_minute = byte_count
        else:
            self._bytes_last_minute += byte_count

    def set_stream_state(
        self,
        *,
        enabled: bool,
        active: bool,
        mode: str,
        chunk_size: int,
        marker: Optional[str],
        pattern_matching: bool,
    ) -> None:
        """Update stream state for agents."""
        self._stream = {
            "enabled": enabled,
            "active": active,
            "mode": mode,
            "chunk_size": chunk_size,
            "marker": marker,
            "pattern_matching": pattern_matching,
        }
        self.update()

    def record_read_error(self) -> None:
        """Record a serial read error."""
        self._read_errors += 1
        self.update()

    def record_usb_disconnect(self) -> None:
        """Record a USB disconnect event."""
        self._usb_disconnects += 1
        self.update()

    def set_reset_statistics(self, stats: dict) -> None:
        """Store reset statistics from ResetTracker for inclusion in status.json."""
        self._reset_statistics = stats

    def update(self) -> None:
        """Write current status to file using atomic write."""
        now = self._clock.now()
        uptime = (now - self._started).total_seconds() if self._started else 0

        # Calculate seconds since last activity
        if self._last_activity_time:
            idle_seconds = (now - self._last_activity_time).total_seconds()
        else:
            idle_seconds = uptime  # No activity yet means idle since start

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
            "health": {
                "last_activity": self._last_activity_time.isoformat() if self._last_activity_time else None,
                "idle_seconds": int(idle_seconds),
                "bytes_last_minute": self._bytes_last_minute,
                "read_errors": self._read_errors,
                "usb_disconnects": self._usb_disconnects,
                "status": self._compute_health_status(idle_seconds),
            },
            "patterns": self._pattern_counts,
            "resets": self._reset_statistics,
            "stream": self._stream,
            "last_updated": now.isoformat(),
        }

        self._atomic_write(json.dumps(status, indent=2))

    def _compute_health_status(self, idle_seconds: float) -> str:
        """Compute overall health status for agents."""
        if self._state == ConnectionState.DISCONNECTED:
            return "disconnected"
        if idle_seconds > 30:
            return "stuck"  # No activity for 30+ seconds
        if idle_seconds > 10:
            return "idle"   # No activity for 10+ seconds
        if self._read_errors > 10:
            return "degraded"  # Many read errors
        return "healthy"

    def _atomic_write(self, content: str) -> None:
        """Write content atomically using temp file + rename."""
        # Get the directory of the status file
        status_dir = os.path.dirname(self._status_path)
        if not status_dir:
            status_dir = "."

        # Write to temp file in same directory (ensures same filesystem)
        try:
            fd, temp_path = tempfile.mkstemp(
                suffix=".tmp",
                prefix="status_",
                dir=status_dir
            )
            try:
                os.write(fd, content.encode("utf-8"))
            finally:
                os.close(fd)

            # Atomic rename
            os.replace(temp_path, self._status_path)
        except Exception:
            # Fallback to non-atomic write if atomic fails
            self._fs.write_file(self._status_path, content)
