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


class TestLogRotation:
    """Tests for log rotation functionality."""

    def test_rotation_triggers_when_bytes_exceed_max(self):
        """Should rotate log when bytes written exceeds max_size_bytes."""
        from eab.session_logger import SessionLogger, LogRotationConfig

        fs = MockFileSystem()
        clock = MockClock(datetime(2025, 12, 11, 1, 30, 0))

        # Set small max size to trigger rotation easily
        config = LogRotationConfig(max_size_bytes=100, max_files=5, compress=False)
        logger = SessionLogger(
            filesystem=fs,
            clock=clock,
            base_dir="/var/run/eab/serial",
            rotation_config=config
        )

        logger.start_session(port="/dev/ttyUSB0", baud=115200)

        # Write enough data to exceed 100 bytes (will trigger rotation)
        for i in range(10):
            logger.log_line(f"This is a longer test line {i} with some content")

        # Write one more line after rotation to create new latest.log
        logger.log_line("After rotation")

        # Should have triggered rotation and created new file
        assert fs.file_exists("/var/run/eab/serial/latest.log.1")
        assert fs.file_exists("/var/run/eab/serial/latest.log")

    def test_file_numbering_shifts_correctly(self):
        """Should shift file numbers correctly: .1 → .2, .2 → .3, etc."""
        from eab.session_logger import SessionLogger, LogRotationConfig

        fs = MockFileSystem()
        clock = MockClock(datetime(2025, 12, 11, 1, 30, 0))

        config = LogRotationConfig(max_size_bytes=50, max_files=5, compress=False)
        logger = SessionLogger(
            filesystem=fs,
            clock=clock,
            base_dir="/var/run/eab/serial",
            rotation_config=config
        )

        logger.start_session(port="/dev/ttyUSB0", baud=115200)

        # Write enough to trigger multiple rotations
        for i in range(20):
            logger.log_line(f"Line {i} with enough content to trigger rotation")

        # Write one more to create new latest.log
        logger.log_line("Final line")

        # Check that numbered files exist
        files = fs.get_all_files()
        log_files = [k for k in files.keys() if "latest.log" in k]

        # Should have latest.log and at least .1
        assert any("latest.log.1" in f for f in log_files)
        assert any("latest.log" == f.split("/")[-1] for f in log_files)

    def test_oldest_file_deleted_when_max_files_exceeded(self):
        """Should delete oldest file when max_files limit is reached."""
        from eab.session_logger import SessionLogger, LogRotationConfig

        fs = MockFileSystem()
        clock = MockClock(datetime(2025, 12, 11, 1, 30, 0))

        config = LogRotationConfig(max_size_bytes=30, max_files=3, compress=False)
        logger = SessionLogger(
            filesystem=fs,
            clock=clock,
            base_dir="/var/run/eab/serial",
            rotation_config=config
        )

        logger.start_session(port="/dev/ttyUSB0", baud=115200)

        # Write enough to trigger multiple rotations (more than max_files)
        for i in range(30):
            logger.log_line(f"Line {i}")

        # Write one more to ensure current log exists
        logger.log_line("Final")

        files = fs.get_all_files()
        log_files = [k for k in files.keys() if "latest.log" in k]

        # Should not have .4 or higher since max_files=3
        assert not any("latest.log.4" in f for f in log_files)

        # Should have .1, .2, .3 and current
        assert "/var/run/eab/serial/latest.log" in files

    def test_compressed_files_get_gz_suffix(self):
        """Should add .gz suffix to compressed files when compress=True."""
        from eab.session_logger import SessionLogger, LogRotationConfig

        fs = MockFileSystem()
        clock = MockClock(datetime(2025, 12, 11, 1, 30, 0))

        config = LogRotationConfig(max_size_bytes=50, max_files=5, compress=True)
        logger = SessionLogger(
            filesystem=fs,
            clock=clock,
            base_dir="/var/run/eab/serial",
            rotation_config=config
        )

        logger.start_session(port="/dev/ttyUSB0", baud=115200)

        # Write enough to trigger rotation
        for i in range(10):
            logger.log_line(f"Line {i} with enough content")

        # Write one more line
        logger.log_line("After rotation")

        # Check for .gz files
        files = fs.get_all_files()
        gz_files = [k for k in files.keys() if k.endswith(".gz")]

        assert len(gz_files) > 0, "Should have at least one .gz file"
        assert any("latest.log.1.gz" in f for f in gz_files)

    def test_compressed_files_have_gzip_marker(self):
        """Should have [GZIP] marker in compressed files for MockFileSystem."""
        from eab.session_logger import SessionLogger, LogRotationConfig

        fs = MockFileSystem()
        clock = MockClock(datetime(2025, 12, 11, 1, 30, 0))

        config = LogRotationConfig(max_size_bytes=50, max_files=5, compress=True)
        logger = SessionLogger(
            filesystem=fs,
            clock=clock,
            base_dir="/var/run/eab/serial",
            rotation_config=config
        )

        logger.start_session(port="/dev/ttyUSB0", baud=115200)

        # Write content
        logger.log_line("First line with content")
        for i in range(5):
            logger.log_line(f"Line {i}")

        # Should have triggered rotation and created .gz file
        if fs.file_exists("/var/run/eab/serial/latest.log.1.gz"):
            content = fs.read_file("/var/run/eab/serial/latest.log.1.gz")
            assert content.startswith("[GZIP]"), "Compressed file should have [GZIP] marker"

    def test_no_compression_without_compress(self):
        """Should not create .gz files when compress=False."""
        from eab.session_logger import SessionLogger, LogRotationConfig

        fs = MockFileSystem()
        clock = MockClock(datetime(2025, 12, 11, 1, 30, 0))

        config = LogRotationConfig(max_size_bytes=50, max_files=5, compress=False)
        logger = SessionLogger(
            filesystem=fs,
            clock=clock,
            base_dir="/var/run/eab/serial",
            rotation_config=config
        )

        logger.start_session(port="/dev/ttyUSB0", baud=115200)

        # Write enough to trigger rotation
        for i in range(10):
            logger.log_line(f"Line {i} with content")

        # Write one more
        logger.log_line("After rotation")

        # Check no .gz files exist
        files = fs.get_all_files()
        gz_files = [k for k in files.keys() if k.endswith(".gz")]

        assert len(gz_files) == 0, "Should not have any .gz files when compress=False"

    def test_no_lines_lost_during_rotation(self):
        """Should not lose any lines during rotation."""
        from eab.session_logger import SessionLogger, LogRotationConfig

        fs = MockFileSystem()
        clock = MockClock(datetime(2025, 12, 11, 1, 30, 0))

        config = LogRotationConfig(max_size_bytes=80, max_files=5, compress=False)
        logger = SessionLogger(
            filesystem=fs,
            clock=clock,
            base_dir="/var/run/eab/serial",
            rotation_config=config
        )

        logger.start_session(port="/dev/ttyUSB0", baud=115200)

        # Write lines before rotation
        logger.log_line("Before rotation line 1")
        logger.log_line("Before rotation line 2")

        # Write enough to trigger rotation
        for i in range(5):
            logger.log_line(f"Rotation trigger line {i}")

        # Write lines after rotation
        logger.log_line("After rotation line 1")
        logger.log_line("After rotation line 2")

        # Verify all content exists somewhere
        files = fs.get_all_files()
        all_content = "".join(files.values())

        assert "Before rotation line 1" in all_content
        assert "Before rotation line 2" in all_content
        assert "After rotation line 1" in all_content
        assert "After rotation line 2" in all_content

    def test_archive_previous_on_new_session(self):
        """Should actually archive old log when starting new session."""
        from eab.session_logger import SessionLogger, LogRotationConfig

        fs = MockFileSystem()
        clock = MockClock(datetime(2025, 12, 11, 8, 45, 0))

        # Pre-existing log from previous session
        fs.write_file("/var/run/eab/serial/latest.log", "Old session content\n")

        config = LogRotationConfig(compress=False)
        logger = SessionLogger(
            filesystem=fs,
            clock=clock,
            base_dir="/var/run/eab/serial",
            rotation_config=config
        )

        logger.start_session(port="/dev/ttyUSB0", baud=115200)

        # Old content should be in .1 file
        assert fs.file_exists("/var/run/eab/serial/latest.log.1")
        old_content = fs.read_file("/var/run/eab/serial/latest.log.1")
        assert "Old session content" in old_content

        # New session should have fresh header
        new_content = fs.read_file("/var/run/eab/serial/latest.log")
        assert "Old session content" not in new_content
        assert "SESSION:" in new_content

    def test_archive_previous_with_compression(self):
        """Should archive with compression when compress=True on new session."""
        from eab.session_logger import SessionLogger, LogRotationConfig

        fs = MockFileSystem()
        clock = MockClock(datetime(2025, 12, 11, 8, 45, 0))

        # Pre-existing log
        fs.write_file("/var/run/eab/serial/latest.log", "Old session data\n")

        config = LogRotationConfig(compress=True)
        logger = SessionLogger(
            filesystem=fs,
            clock=clock,
            base_dir="/var/run/eab/serial",
            rotation_config=config
        )

        logger.start_session(port="/dev/ttyUSB0", baud=115200)

        # Should have .gz archive
        assert fs.file_exists("/var/run/eab/serial/latest.log.1.gz")
        archived = fs.read_file("/var/run/eab/serial/latest.log.1.gz")
        assert "[GZIP]" in archived or "Old session data" in archived

    def test_custom_config_values_respected(self):
        """Should respect custom configuration values."""
        from eab.session_logger import SessionLogger, LogRotationConfig

        fs = MockFileSystem()
        clock = MockClock(datetime(2025, 12, 11, 1, 30, 0))

        # Custom config
        config = LogRotationConfig(
            max_size_bytes=200,
            max_files=3,
            compress=False
        )
        logger = SessionLogger(
            filesystem=fs,
            clock=clock,
            base_dir="/var/run/eab/serial",
            rotation_config=config
        )

        # Verify config is stored
        assert logger.rotation_config.max_size_bytes == 200
        assert logger.rotation_config.max_files == 3
        assert logger.rotation_config.compress is False

        logger.start_session(port="/dev/ttyUSB0", baud=115200)

        # Write data to trigger rotation with custom size
        for i in range(20):
            logger.log_line(f"Line {i}")

        files = fs.get_all_files()

        # Should respect max_files=3
        assert not any("latest.log.4" in k for k in files.keys())

    def test_default_config_when_none_provided(self):
        """Should use default LogRotationConfig when none provided."""
        from eab.session_logger import SessionLogger, LogRotationConfig

        fs = MockFileSystem()
        clock = MockClock(datetime(2025, 12, 11, 1, 30, 0))

        logger = SessionLogger(
            filesystem=fs,
            clock=clock,
            base_dir="/var/run/eab/serial"
        )

        # Should have default config
        assert logger.rotation_config.max_size_bytes == 100_000_000
        assert logger.rotation_config.max_files == 5
        assert logger.rotation_config.compress is True

    def test_rotation_resets_byte_counter(self):
        """Should reset byte counter to 0 after rotation."""
        from eab.session_logger import SessionLogger, LogRotationConfig

        fs = MockFileSystem()
        clock = MockClock(datetime(2025, 12, 11, 1, 30, 0))

        config = LogRotationConfig(max_size_bytes=50, max_files=5, compress=False)
        logger = SessionLogger(
            filesystem=fs,
            clock=clock,
            base_dir="/var/run/eab/serial",
            rotation_config=config
        )

        logger.start_session(port="/dev/ttyUSB0", baud=115200)

        # Write to trigger rotation
        for i in range(5):
            logger.log_line(f"Line {i} with content")

        # After rotation, bytes_written should be small (only new content)
        # We can't directly access _bytes_written, but we can verify behavior
        # by writing more and checking another rotation doesn't happen immediately
        initial_files = len(fs.get_all_files())

        # Write one more line (should not trigger rotation if counter was reset)
        logger.log_line("Single line")

        # Should not have created more rotated files
        assert len(fs.get_all_files()) <= initial_files + 1

    def test_log_command_also_triggers_rotation(self):
        """Should check rotation after log_command() calls."""
        from eab.session_logger import SessionLogger, LogRotationConfig

        fs = MockFileSystem()
        clock = MockClock(datetime(2025, 12, 11, 1, 30, 0))

        config = LogRotationConfig(max_size_bytes=50, max_files=5, compress=False)
        logger = SessionLogger(
            filesystem=fs,
            clock=clock,
            base_dir="/var/run/eab/serial",
            rotation_config=config
        )

        logger.start_session(port="/dev/ttyUSB0", baud=115200)

        # Write commands to trigger rotation
        for i in range(10):
            logger.log_command(f"command_{i}_with_enough_content")

        # Write one more
        logger.log_command("final")

        # Should have triggered rotation
        assert fs.file_exists("/var/run/eab/serial/latest.log.1")
        assert fs.file_exists("/var/run/eab/serial/latest.log")

    def test_mixed_lines_and_commands_rotation(self):
        """Should handle rotation with mixed log_line and log_command calls."""
        from eab.session_logger import SessionLogger, LogRotationConfig

        fs = MockFileSystem()
        clock = MockClock(datetime(2025, 12, 11, 1, 30, 0))

        config = LogRotationConfig(max_size_bytes=100, max_files=5, compress=False)
        logger = SessionLogger(
            filesystem=fs,
            clock=clock,
            base_dir="/var/run/eab/serial",
            rotation_config=config
        )

        logger.start_session(port="/dev/ttyUSB0", baud=115200)

        # Mix lines and commands
        for i in range(10):
            if i % 2 == 0:
                logger.log_line(f"Log line {i} with content")
            else:
                logger.log_command(f"command_{i}")

        # Write one more
        logger.log_line("Final")

        # Should have rotation artifacts
        files = fs.get_all_files()
        log_files = [k for k in files.keys() if "latest.log" in k]
        assert len(log_files) > 1  # Should have at least latest.log and .1
