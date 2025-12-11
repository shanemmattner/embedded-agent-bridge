"""
Session Logger for Serial Daemon.

Handles session-based logging with timestamped entries, session headers/footers,
and log archiving.
"""

from typing import Optional, List
from collections import deque
from .interfaces import FileSystemInterface, ClockInterface


class SessionLogger:
    """
    Manages session-based logging for serial data.

    Features:
    - Timestamped log entries with millisecond precision
    - Session headers and footers with metadata
    - Grep-friendly log format
    - Recent lines buffer for crash context
    - Automatic archiving of previous sessions
    """

    def __init__(
        self,
        filesystem: FileSystemInterface,
        clock: ClockInterface,
        base_dir: str,
        archive_dir: Optional[str] = None,
        recent_buffer_size: int = 500,
    ):
        self._fs = filesystem
        self._clock = clock
        self._base_dir = base_dir
        self._archive_dir = archive_dir or f"{base_dir}/../sessions"
        self._recent_buffer_size = recent_buffer_size

        self._session_id: str = ""
        self._port: str = ""
        self._baud: int = 0
        self._started = None
        self._lines_logged: int = 0
        self._commands_sent: int = 0
        self._recent_lines: deque = deque(maxlen=recent_buffer_size)

        self._log_path = f"{base_dir}/latest.log"

    @property
    def session_id(self) -> str:
        """Current session ID."""
        return self._session_id

    @property
    def lines_logged(self) -> int:
        """Number of lines logged this session."""
        return self._lines_logged

    @property
    def commands_sent(self) -> int:
        """Number of commands sent this session."""
        return self._commands_sent

    def start_session(self, port: str, baud: int) -> None:
        """
        Start a new logging session.

        Archives previous session if exists, creates new log file with header.
        """
        self._port = port
        self._baud = baud
        self._started = self._clock.now()
        self._lines_logged = 0
        self._commands_sent = 0
        self._recent_lines.clear()

        # Generate session ID
        self._session_id = self._started.strftime("serial_%Y-%m-%d_%H-%M-%S")

        # Archive previous log if exists
        if self._fs.file_exists(self._log_path):
            self._archive_previous()

        # Ensure directory exists
        self._fs.ensure_dir(self._base_dir)

        # Write header
        header = self._format_header()
        self._fs.write_file(self._log_path, header)

    def _archive_previous(self) -> None:
        """Archive the previous session log."""
        # For now, just clear the file
        # Full archiving with compression would be added later
        pass

    def _format_header(self) -> str:
        """Format the session header."""
        sep = "=" * 80
        return (
            f"{sep}\n"
            f"SESSION: {self._session_id}\n"
            f"PORT: {self._port}\n"
            f"BAUD: {self._baud}\n"
            f"STARTED: {self._started.isoformat()}\n"
            f"{sep}\n\n"
        )

    def log_line(self, line: str) -> None:
        """
        Log a line with timestamp.

        Format: [HH:MM:SS.mmm] <line>
        """
        timestamp = self._clock.now().strftime("%H:%M:%S.%f")[:-3]
        formatted = f"[{timestamp}] {line}\n"

        self._fs.write_file(self._log_path, formatted, append=True)
        self._lines_logged += 1
        self._recent_lines.append(formatted.strip())

    def log_command(self, command: str) -> None:
        """
        Log a command with special marker.

        Format: [HH:MM:SS.mmm] >>> CMD: <command>
        """
        timestamp = self._clock.now().strftime("%H:%M:%S.%f")[:-3]
        formatted = f"[{timestamp}] >>> CMD: {command}\n"

        self._fs.write_file(self._log_path, formatted, append=True)
        self._commands_sent += 1
        self._recent_lines.append(formatted.strip())

    def end_session(self) -> None:
        """
        End the current session and write footer.
        """
        now = self._clock.now()
        duration = now - self._started if self._started else None

        # Format duration
        if duration:
            total_seconds = int(duration.total_seconds())
            hours = total_seconds // 3600
            minutes = (total_seconds % 3600) // 60
            seconds = total_seconds % 60
            duration_str = f"{hours}h {minutes}m {seconds:02d}s"
        else:
            duration_str = "unknown"

        sep = "=" * 80
        footer = (
            f"\n{sep}\n"
            f"SESSION ENDED: {now.strftime('%Y-%m-%d_%H-%M-%S')}\n"
            f"DURATION: {duration_str}\n"
            f"LINES LOGGED: {self._lines_logged}\n"
            f"COMMANDS SENT: {self._commands_sent}\n"
            f"{sep}\n"
        )

        self._fs.write_file(self._log_path, footer, append=True)

    def get_recent_lines(self, count: int) -> List[str]:
        """
        Get the most recent N logged lines.

        Useful for crash context analysis.
        """
        recent = list(self._recent_lines)
        return recent[-count:] if count < len(recent) else recent
