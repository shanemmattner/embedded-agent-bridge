"""
Interfaces for Embedded Agent Bridge Serial Daemon

Abstract base classes that define contracts for all pluggable components.
This enables dependency injection and mock-based testing without hardware.
"""

from abc import ABC, abstractmethod
from typing import Optional, List, Callable
from dataclasses import dataclass
from datetime import datetime
from enum import Enum


class ConnectionState(Enum):
    """Serial port connection states."""
    DISCONNECTED = "disconnected"
    CONNECTING = "connecting"
    CONNECTED = "connected"
    RECONNECTING = "reconnecting"
    ERROR = "error"


@dataclass
class PortInfo:
    """Information about a serial port."""
    device: str
    description: str
    hwid: str


@dataclass
class SerialConfig:
    """Serial port configuration."""
    port: str
    baud: int = 115200
    timeout: float = 1.0


class SerialPortInterface(ABC):
    """
    Abstract interface for serial port operations.

    Implementations:
    - RealSerialPort: Wraps pyserial for actual hardware
    - MockSerialPort: For unit testing without hardware
    """

    @abstractmethod
    def open(self, port: str, baud: int, timeout: float = 1.0) -> bool:
        """Open serial port. Returns True on success."""
        pass

    @abstractmethod
    def close(self) -> None:
        """Close serial port."""
        pass

    @abstractmethod
    def is_open(self) -> bool:
        """Check if port is currently open."""
        pass

    @abstractmethod
    def read_line(self) -> Optional[bytes]:
        """Read a line from eab. Returns None if no data available."""
        pass

    @abstractmethod
    def read_bytes(self, max_bytes: int) -> bytes:
        """Read up to max_bytes from serial. Returns b'' if no data."""
        pass

    @abstractmethod
    def write(self, data: bytes) -> int:
        """Write data to serial. Returns bytes written."""
        pass

    @abstractmethod
    def bytes_available(self) -> int:
        """Return number of bytes waiting in receive buffer."""
        pass

    @staticmethod
    @abstractmethod
    def list_ports() -> List[PortInfo]:
        """List available serial ports."""
        pass


class FileSystemInterface(ABC):
    """
    Abstract interface for file system operations.

    Implementations:
    - RealFileSystem: Actual file I/O
    - MockFileSystem: In-memory for testing
    """

    @abstractmethod
    def read_file(self, path: str) -> str:
        """Read entire file contents."""
        pass

    @abstractmethod
    def write_file(self, path: str, content: str, append: bool = False) -> None:
        """Write content to file. Creates parent dirs if needed."""
        pass

    @abstractmethod
    def file_exists(self, path: str) -> bool:
        """Check if file exists."""
        pass

    @abstractmethod
    def get_mtime(self, path: str) -> float:
        """Get file modification time as timestamp."""
        pass

    @abstractmethod
    def ensure_dir(self, path: str) -> None:
        """Create directory and parents if they don't exist."""
        pass

    @abstractmethod
    def delete_file(self, path: str) -> None:
        """Delete a file."""
        pass

    @abstractmethod
    def file_size(self, path: str) -> int:
        """Return file size in bytes. Raises FileNotFoundError if missing."""
        pass

    @abstractmethod
    def rename_file(self, old_path: str, new_path: str) -> None:
        """Rename a file."""
        pass

    @abstractmethod
    def list_dir(self, path: str) -> List[str]:
        """List filenames in a directory."""
        pass


class ClockInterface(ABC):
    """
    Abstract interface for time operations.

    Enables deterministic testing of time-dependent logic.
    """

    @abstractmethod
    def now(self) -> datetime:
        """Get current datetime."""
        pass

    @abstractmethod
    def timestamp(self) -> float:
        """Get current timestamp (seconds since epoch)."""
        pass

    @abstractmethod
    def sleep(self, seconds: float) -> None:
        """Sleep for specified duration."""
        pass


class LoggerInterface(ABC):
    """
    Abstract interface for logging.

    Separates daemon logic from log output formatting.
    """

    @abstractmethod
    def debug(self, msg: str) -> None:
        """Log debug message."""
        pass

    @abstractmethod
    def info(self, msg: str) -> None:
        """Log info message."""
        pass

    @abstractmethod
    def warning(self, msg: str) -> None:
        """Log warning message."""
        pass

    @abstractmethod
    def error(self, msg: str) -> None:
        """Log error message."""
        pass


@dataclass
class AlertMatch:
    """Represents a pattern match alert."""
    timestamp: datetime
    pattern: str
    line: str


class PatternMatcherInterface(ABC):
    """
    Abstract interface for pattern matching.

    Enables pluggable pattern detection strategies.
    """

    @abstractmethod
    def add_pattern(self, name: str, pattern: str) -> None:
        """Add a pattern to watch for. Pattern can be string or regex."""
        pass

    @abstractmethod
    def remove_pattern(self, name: str) -> None:
        """Remove a pattern."""
        pass

    @abstractmethod
    def check_line(self, line: str) -> List[AlertMatch]:
        """Check line against all patterns. Returns list of matches."""
        pass

    @abstractmethod
    def get_counts(self) -> dict:
        """Get count of matches per pattern."""
        pass


@dataclass
class SessionStats:
    """Statistics for a daemon session."""
    session_id: str
    started: datetime
    port: str
    baud: int
    connection_state: ConnectionState
    reconnect_count: int
    lines_logged: int
    bytes_received: int
    commands_sent: int
    alerts_triggered: int
    pattern_counts: dict
    last_updated: datetime


class StatsCollectorInterface(ABC):
    """
    Abstract interface for statistics collection.
    """

    @abstractmethod
    def start_session(self, session_id: str, port: str, baud: int) -> None:
        """Start a new session."""
        pass

    @abstractmethod
    def record_line(self, line: str) -> None:
        """Record a logged line."""
        pass

    @abstractmethod
    def record_bytes(self, count: int) -> None:
        """Record bytes received."""
        pass

    @abstractmethod
    def record_command(self) -> None:
        """Record a command sent."""
        pass

    @abstractmethod
    def record_alert(self, pattern: str) -> None:
        """Record an alert triggered."""
        pass

    @abstractmethod
    def record_reconnect(self) -> None:
        """Record a reconnection attempt."""
        pass

    @abstractmethod
    def set_connection_state(self, state: ConnectionState) -> None:
        """Update connection state."""
        pass

    @abstractmethod
    def get_stats(self) -> SessionStats:
        """Get current session statistics."""
        pass

    @abstractmethod
    def to_json(self) -> str:
        """Export stats as JSON string."""
        pass
