"""
Mock implementations for testing.

These classes implement the abstract interfaces with in-memory behavior
suitable for unit testing without hardware.
"""

from typing import Optional, List, Dict
from datetime import datetime
from collections import deque
import json
import re

from .interfaces import (
    SerialPortInterface, FileSystemInterface, ClockInterface,
    LoggerInterface, PatternMatcherInterface, StatsCollectorInterface,
    PortInfo, ConnectionState, AlertMatch, SessionStats
)


class MockSerialPort(SerialPortInterface):
    """
    Mock serial port for testing.

    Provides a queue-based simulation of serial communication.
    Test code can inject data with inject_line() and read sent data with get_sent().
    """

    def __init__(self):
        self._is_open = False
        self._port = ""
        self._baud = 0
        self._rx_buffer: deque = deque()
        self._tx_buffer: List[bytes] = []
        self._disconnect_after: Optional[int] = None
        self._read_count = 0
        self._fail_on_open = False
        self._available_ports: List[PortInfo] = []

    def open(self, port: str, baud: int, timeout: float = 1.0) -> bool:
        if self._fail_on_open:
            return False
        self._port = port
        self._baud = baud
        self._is_open = True
        return True

    def close(self) -> None:
        self._is_open = False

    def is_open(self) -> bool:
        return self._is_open

    def read_line(self) -> Optional[bytes]:
        if not self._is_open:
            return None

        self._read_count += 1

        # Simulate disconnect after N reads
        if self._disconnect_after and self._read_count >= self._disconnect_after:
            self._is_open = False
            self._disconnect_after = None
            return None

        if self._rx_buffer:
            return self._rx_buffer.popleft()
        return None

    def write(self, data: bytes) -> int:
        if not self._is_open:
            return 0
        self._tx_buffer.append(data)
        return len(data)

    def bytes_available(self) -> int:
        return sum(len(b) for b in self._rx_buffer)

    @staticmethod
    def list_ports() -> List[PortInfo]:
        return []

    # Test helper methods

    def inject_line(self, line: str) -> None:
        """Inject a line into the receive buffer (for testing)."""
        self._rx_buffer.append((line + "\n").encode())

    def inject_bytes(self, data: bytes) -> None:
        """Inject raw bytes into the receive buffer."""
        self._rx_buffer.append(data)

    def get_sent(self) -> List[bytes]:
        """Get all data sent via write() (for testing)."""
        return self._tx_buffer.copy()

    def clear_sent(self) -> None:
        """Clear the sent buffer."""
        self._tx_buffer.clear()

    def set_disconnect_after(self, reads: int) -> None:
        """Simulate disconnect after N read operations."""
        self._disconnect_after = reads
        self._read_count = 0

    def set_fail_on_open(self, fail: bool) -> None:
        """Make open() fail (for testing error handling)."""
        self._fail_on_open = fail

    def set_available_ports(self, ports: List[PortInfo]) -> None:
        """Set the list returned by list_ports()."""
        self._available_ports = ports


class MockFileSystem(FileSystemInterface):
    """
    In-memory file system for testing.

    All file operations are performed in memory without touching disk.
    """

    def __init__(self):
        self._files: Dict[str, str] = {}
        self._mtimes: Dict[str, float] = {}
        self._dirs: set = set()

    def read_file(self, path: str) -> str:
        if path not in self._files:
            raise FileNotFoundError(f"No such file: {path}")
        return self._files[path]

    def write_file(self, path: str, content: str, append: bool = False) -> None:
        if append and path in self._files:
            self._files[path] += content
        else:
            self._files[path] = content
        self._mtimes[path] = datetime.now().timestamp()

    def file_exists(self, path: str) -> bool:
        return path in self._files

    def get_mtime(self, path: str) -> float:
        if path not in self._mtimes:
            raise FileNotFoundError(f"No such file: {path}")
        return self._mtimes[path]

    def ensure_dir(self, path: str) -> None:
        self._dirs.add(path)

    def delete_file(self, path: str) -> None:
        if path in self._files:
            del self._files[path]
        if path in self._mtimes:
            del self._mtimes[path]

    # Test helper methods

    def get_all_files(self) -> Dict[str, str]:
        """Get dictionary of all files and contents."""
        return self._files.copy()

    def clear(self) -> None:
        """Clear all files."""
        self._files.clear()
        self._mtimes.clear()
        self._dirs.clear()

    def set_mtime(self, path: str, mtime: float) -> None:
        """Manually set file modification time."""
        self._mtimes[path] = mtime


class MockClock(ClockInterface):
    """
    Controllable clock for testing.

    Time can be advanced manually for deterministic testing of
    time-dependent behavior.
    """

    def __init__(self, start_time: Optional[datetime] = None):
        self._current_time = start_time or datetime(2025, 1, 1, 0, 0, 0)
        self._sleep_calls: List[float] = []

    def now(self) -> datetime:
        return self._current_time

    def timestamp(self) -> float:
        return self._current_time.timestamp()

    def sleep(self, seconds: float) -> None:
        self._sleep_calls.append(seconds)
        # Don't actually sleep, just record the call

    # Test helper methods

    def advance(self, seconds: float) -> None:
        """Advance time by specified seconds."""
        from datetime import timedelta
        self._current_time += timedelta(seconds=seconds)

    def set_time(self, dt: datetime) -> None:
        """Set current time to specific datetime."""
        self._current_time = dt

    def get_sleep_calls(self) -> List[float]:
        """Get list of all sleep() calls made."""
        return self._sleep_calls.copy()

    def clear_sleep_calls(self) -> None:
        """Clear recorded sleep calls."""
        self._sleep_calls.clear()


class MockLogger(LoggerInterface):
    """
    Logger that captures all messages for testing.
    """

    def __init__(self):
        self._messages: List[tuple] = []

    def debug(self, msg: str) -> None:
        self._messages.append(("DEBUG", msg))

    def info(self, msg: str) -> None:
        self._messages.append(("INFO", msg))

    def warning(self, msg: str) -> None:
        self._messages.append(("WARNING", msg))

    def error(self, msg: str) -> None:
        self._messages.append(("ERROR", msg))

    # Test helper methods

    def get_messages(self, level: Optional[str] = None) -> List[tuple]:
        """Get logged messages, optionally filtered by level."""
        if level:
            return [(l, m) for l, m in self._messages if l == level]
        return self._messages.copy()

    def clear(self) -> None:
        """Clear all logged messages."""
        self._messages.clear()

    def contains(self, substring: str, level: Optional[str] = None) -> bool:
        """Check if any message contains substring."""
        messages = self.get_messages(level)
        return any(substring in m for _, m in messages)


class MockPatternMatcher(PatternMatcherInterface):
    """
    Pattern matcher for testing.
    """

    def __init__(self):
        self._patterns: Dict[str, re.Pattern] = {}
        self._counts: Dict[str, int] = {}

    def add_pattern(self, name: str, pattern: str) -> None:
        self._patterns[name] = re.compile(pattern, re.IGNORECASE)
        self._counts[name] = 0

    def remove_pattern(self, name: str) -> None:
        if name in self._patterns:
            del self._patterns[name]
            del self._counts[name]

    def check_line(self, line: str) -> List[AlertMatch]:
        matches = []
        for name, pattern in self._patterns.items():
            if pattern.search(line):
                self._counts[name] += 1
                matches.append(AlertMatch(
                    timestamp=datetime.now(),
                    pattern=name,
                    line=line
                ))
        return matches

    def get_counts(self) -> dict:
        return self._counts.copy()

    # Test helper methods

    def reset_counts(self) -> None:
        """Reset all pattern counts to zero."""
        for name in self._counts:
            self._counts[name] = 0


class MockStatsCollector(StatsCollectorInterface):
    """
    Statistics collector for testing.
    """

    def __init__(self, clock: ClockInterface):
        self._clock = clock
        self._session_id = ""
        self._started: Optional[datetime] = None
        self._port = ""
        self._baud = 0
        self._state = ConnectionState.DISCONNECTED
        self._reconnect_count = 0
        self._lines_logged = 0
        self._bytes_received = 0
        self._commands_sent = 0
        self._alerts_triggered = 0
        self._pattern_counts: Dict[str, int] = {}

    def start_session(self, session_id: str, port: str, baud: int) -> None:
        self._session_id = session_id
        self._port = port
        self._baud = baud
        self._started = self._clock.now()
        self._state = ConnectionState.CONNECTING

    def record_line(self, line: str) -> None:
        self._lines_logged += 1

    def record_bytes(self, count: int) -> None:
        self._bytes_received += count

    def record_command(self) -> None:
        self._commands_sent += 1

    def record_alert(self, pattern: str) -> None:
        self._alerts_triggered += 1
        self._pattern_counts[pattern] = self._pattern_counts.get(pattern, 0) + 1

    def record_reconnect(self) -> None:
        self._reconnect_count += 1

    def set_connection_state(self, state: ConnectionState) -> None:
        self._state = state

    def get_stats(self) -> SessionStats:
        return SessionStats(
            session_id=self._session_id,
            started=self._started or self._clock.now(),
            port=self._port,
            baud=self._baud,
            connection_state=self._state,
            reconnect_count=self._reconnect_count,
            lines_logged=self._lines_logged,
            bytes_received=self._bytes_received,
            commands_sent=self._commands_sent,
            alerts_triggered=self._alerts_triggered,
            pattern_counts=self._pattern_counts.copy(),
            last_updated=self._clock.now()
        )

    def to_json(self) -> str:
        stats = self.get_stats()
        return json.dumps({
            "session": {
                "id": stats.session_id,
                "started": stats.started.isoformat() if stats.started else None,
                "uptime_seconds": (self._clock.now() - stats.started).total_seconds() if stats.started else 0
            },
            "connection": {
                "port": stats.port,
                "baud": stats.baud,
                "status": stats.connection_state.value,
                "reconnects": stats.reconnect_count
            },
            "counters": {
                "lines_logged": stats.lines_logged,
                "bytes_received": stats.bytes_received,
                "commands_sent": stats.commands_sent,
                "alerts_triggered": stats.alerts_triggered
            },
            "patterns": stats.pattern_counts,
            "last_updated": stats.last_updated.isoformat()
        }, indent=2)
