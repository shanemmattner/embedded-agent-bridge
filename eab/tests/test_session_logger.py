"""
Tests for session-based logging.

These tests define the expected session logging behavior BEFORE implementation.
"""

import pytest
from datetime import datetime
import sys
import os

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__)))))

from eab.mocks import MockFileSystem, MockClock


class TestSessionLogger:
    """Tests for SessionLogger class."""

    def test_creates_session_log_file(self):
        """Should create a new log file when session starts."""
        from eab.session_logger import SessionLogger

        fs = MockFileSystem()
        clock = MockClock(datetime(2025, 12, 11, 1, 30, 0))

        logger = SessionLogger(
            filesystem=fs,
            clock=clock,
            base_dir="/var/run/eab/serial"
        )

        logger.start_session(port="/dev/ttyUSB0", baud=115200)

        assert fs.file_exists("/var/run/eab/serial/latest.log")

    def test_session_id_format(self):
        """Should generate session ID with correct timestamp format."""
        from eab.session_logger import SessionLogger

        fs = MockFileSystem()
        clock = MockClock(datetime(2025, 12, 11, 1, 30, 0))

        logger = SessionLogger(
            filesystem=fs,
            clock=clock,
            base_dir="/var/run/eab/serial"
        )

        logger.start_session(port="/dev/ttyUSB0", baud=115200)

        assert logger.session_id == "serial_2025-12-11_01-30-00"

    def test_writes_session_header(self):
        """Should write formatted header at session start."""
        from eab.session_logger import SessionLogger

        fs = MockFileSystem()
        clock = MockClock(datetime(2025, 12, 11, 1, 30, 0))

        logger = SessionLogger(
            filesystem=fs,
            clock=clock,
            base_dir="/var/run/eab/serial"
        )

        logger.start_session(port="/dev/ttyUSB0", baud=115200)

        content = fs.read_file("/var/run/eab/serial/latest.log")
        assert "SESSION:" in content
        assert "serial_2025-12-11_01-30-00" in content
        assert "/dev/ttyUSB0" in content
        assert "115200" in content

    def test_log_line_with_timestamp(self):
        """Should log lines with millisecond timestamps."""
        from eab.session_logger import SessionLogger

        fs = MockFileSystem()
        clock = MockClock(datetime(2025, 12, 11, 1, 30, 0, 123000))

        logger = SessionLogger(
            filesystem=fs,
            clock=clock,
            base_dir="/var/run/eab/serial"
        )

        logger.start_session(port="/dev/ttyUSB0", baud=115200)
        logger.log_line("I (12345) MAIN: Starting application")

        content = fs.read_file("/var/run/eab/serial/latest.log")
        assert "[01:30:00.123]" in content
        assert "I (12345) MAIN: Starting application" in content

    def test_log_multiple_lines(self):
        """Should log multiple lines in order."""
        from eab.session_logger import SessionLogger

        fs = MockFileSystem()
        clock = MockClock(datetime(2025, 12, 11, 1, 30, 0))

        logger = SessionLogger(
            filesystem=fs,
            clock=clock,
            base_dir="/var/run/eab/serial"
        )

        logger.start_session(port="/dev/ttyUSB0", baud=115200)

        clock.advance(0.1)
        logger.log_line("Line 1")
        clock.advance(0.5)
        logger.log_line("Line 2")
        clock.advance(1.0)
        logger.log_line("Line 3")

        content = fs.read_file("/var/run/eab/serial/latest.log")
        lines = content.split("\n")

        # Find log lines (not header)
        log_lines = [l for l in lines if l.startswith("[")]
        assert len(log_lines) == 3
        assert "Line 1" in log_lines[0]
        assert "Line 2" in log_lines[1]
        assert "Line 3" in log_lines[2]

    def test_log_command_with_marker(self):
        """Should mark commands with >>> prefix."""
        from eab.session_logger import SessionLogger

        fs = MockFileSystem()
        clock = MockClock(datetime(2025, 12, 11, 1, 30, 0))

        logger = SessionLogger(
            filesystem=fs,
            clock=clock,
            base_dir="/var/run/eab/serial"
        )

        logger.start_session(port="/dev/ttyUSB0", baud=115200)
        logger.log_command("AT+RST")

        content = fs.read_file("/var/run/eab/serial/latest.log")
        assert ">>> CMD:" in content
        assert "AT+RST" in content

    def test_end_session_writes_footer(self):
        """Should write summary footer when session ends."""
        from eab.session_logger import SessionLogger

        fs = MockFileSystem()
        clock = MockClock(datetime(2025, 12, 11, 1, 30, 0))

        logger = SessionLogger(
            filesystem=fs,
            clock=clock,
            base_dir="/var/run/eab/serial"
        )

        logger.start_session(port="/dev/ttyUSB0", baud=115200)
        logger.log_line("Test line 1")
        logger.log_line("Test line 2")
        logger.log_command("CMD1")
        clock.advance(3600)  # 1 hour

        logger.end_session()

        content = fs.read_file("/var/run/eab/serial/latest.log")
        assert "SESSION ENDED" in content
        assert "LINES LOGGED: 2" in content
        assert "COMMANDS SENT: 1" in content

    def test_grep_friendly_format(self):
        """Log format should be easily grep-able."""
        from eab.session_logger import SessionLogger

        fs = MockFileSystem()
        clock = MockClock(datetime(2025, 12, 11, 1, 30, 0))

        logger = SessionLogger(
            filesystem=fs,
            clock=clock,
            base_dir="/var/run/eab/serial"
        )

        logger.start_session(port="/dev/ttyUSB0", baud=115200)
        logger.log_line("E (45890) BLE: Connection timeout")

        content = fs.read_file("/var/run/eab/serial/latest.log")

        # Check format is grep-able: [timestamp] content
        import re
        pattern = r'\[\d{2}:\d{2}:\d{2}\.\d{3}\] E \(45890\) BLE: Connection timeout'
        assert re.search(pattern, content) is not None

    def test_lines_logged_counter(self):
        """Should track number of lines logged."""
        from eab.session_logger import SessionLogger

        fs = MockFileSystem()
        clock = MockClock(datetime(2025, 12, 11, 1, 30, 0))

        logger = SessionLogger(
            filesystem=fs,
            clock=clock,
            base_dir="/var/run/eab/serial"
        )

        logger.start_session(port="/dev/ttyUSB0", baud=115200)

        for i in range(100):
            logger.log_line(f"Line {i}")

        assert logger.lines_logged == 100

    def test_commands_sent_counter(self):
        """Should track number of commands sent."""
        from eab.session_logger import SessionLogger

        fs = MockFileSystem()
        clock = MockClock(datetime(2025, 12, 11, 1, 30, 0))

        logger = SessionLogger(
            filesystem=fs,
            clock=clock,
            base_dir="/var/run/eab/serial"
        )

        logger.start_session(port="/dev/ttyUSB0", baud=115200)

        logger.log_command("CMD1")
        logger.log_command("CMD2")
        logger.log_command("CMD3")

        assert logger.commands_sent == 3

    def test_immediate_flush(self):
        """Should flush to disk immediately (no buffering loss)."""
        from eab.session_logger import SessionLogger

        fs = MockFileSystem()
        clock = MockClock(datetime(2025, 12, 11, 1, 30, 0))

        logger = SessionLogger(
            filesystem=fs,
            clock=clock,
            base_dir="/var/run/eab/serial"
        )

        logger.start_session(port="/dev/ttyUSB0", baud=115200)
        logger.log_line("Critical data")

        # Data should be in file immediately without explicit flush
        content = fs.read_file("/var/run/eab/serial/latest.log")
        assert "Critical data" in content


class TestSessionArchiving:
    """Tests for session log archiving."""

    def test_previous_session_archived_on_start(self):
        """Should archive previous session log when starting new session."""
        from eab.session_logger import SessionLogger

        fs = MockFileSystem()
        clock = MockClock(datetime(2025, 12, 11, 8, 45, 0))

        # Pre-existing log from previous session
        fs.write_file("/var/run/eab/serial/latest.log", "Old session content")

        logger = SessionLogger(
            filesystem=fs,
            clock=clock,
            base_dir="/var/run/eab/serial",
            archive_dir="/var/run/eab/sessions"
        )

        logger.start_session(port="/dev/ttyUSB0", baud=115200)

        # Old content should be archived (we'll check it was moved)
        # New session should have fresh header
        content = fs.read_file("/var/run/eab/serial/latest.log")
        assert "Old session content" not in content
        assert "SESSION:" in content

    def test_get_recent_lines(self):
        """Should provide access to recent lines for context."""
        from eab.session_logger import SessionLogger

        fs = MockFileSystem()
        clock = MockClock(datetime(2025, 12, 11, 1, 30, 0))

        logger = SessionLogger(
            filesystem=fs,
            clock=clock,
            base_dir="/var/run/eab/serial",
            recent_buffer_size=10
        )

        logger.start_session(port="/dev/ttyUSB0", baud=115200)

        for i in range(20):
            logger.log_line(f"Line {i}")

        recent = logger.get_recent_lines(5)
        assert len(recent) == 5
        assert "Line 15" in recent[0]
        assert "Line 19" in recent[4]
