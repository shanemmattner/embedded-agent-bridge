"""Tests for JLinkRTTManager.

Tests the RTT streaming manager that wraps JLinkRTTLogger subprocess.
Focuses on binary detection, process management, and status parsing.
"""

from __future__ import annotations

from unittest.mock import MagicMock, patch


from eab.jlink_rtt import JLinkRTTManager, _find_rtt_logger


class TestFindRTTLogger:
    """Tests for _find_rtt_logger() binary detection."""

    @patch("eab.jlink_rtt.shutil.which")
    def test_find_rtt_logger_on_path(self, mock_which):
        """Should find JLinkRTTLogger via shutil.which when on PATH."""
        mock_which.return_value = "/usr/bin/JLinkRTTLogger"
        
        result = _find_rtt_logger()
        
        assert result == "/usr/bin/JLinkRTTLogger"
        mock_which.assert_called_once_with("JLinkRTTLogger")

    @patch("eab.jlink_rtt.os.access")
    @patch("eab.jlink_rtt.os.path.isfile")
    @patch("eab.jlink_rtt.shutil.which")
    def test_find_rtt_logger_fallback(self, mock_which, mock_isfile, mock_access):
        """Should find JLinkRTTLogger in fallback locations when not on PATH."""
        mock_which.return_value = None
        # First candidate succeeds
        mock_isfile.side_effect = lambda p: p == "/Applications/SEGGER/JLink/JLinkRTTLoggerExe"
        mock_access.side_effect = lambda p, mode: p == "/Applications/SEGGER/JLink/JLinkRTTLoggerExe"
        
        result = _find_rtt_logger()
        
        assert result == "/Applications/SEGGER/JLink/JLinkRTTLoggerExe"
        mock_which.assert_called_once_with("JLinkRTTLogger")

    @patch("eab.jlink_rtt.os.access")
    @patch("eab.jlink_rtt.os.path.isfile")
    @patch("eab.jlink_rtt.shutil.which")
    def test_find_rtt_logger_not_found(self, mock_which, mock_isfile, mock_access):
        """Should return None when JLinkRTTLogger is not found anywhere."""
        mock_which.return_value = None
        mock_isfile.return_value = False
        mock_access.return_value = False
        
        result = _find_rtt_logger()
        
        assert result is None
        mock_which.assert_called_once_with("JLinkRTTLogger")


class TestJLinkRTTManager:
    """Tests for JLinkRTTManager lifecycle and status."""

    def test_status_initial(self, tmp_path):
        """Initial status should show not running with no device."""
        manager = JLinkRTTManager(tmp_path)
        
        status = manager.status()
        
        assert status.running is False
        assert status.device is None
        assert status.log_path == str(tmp_path / "rtt.log")
        assert status.num_up_channels == 0
        assert status.bytes_read == 0
        assert status.last_error is None

    @patch("eab.jlink_rtt._find_rtt_logger")
    def test_start_no_logger(self, mock_find_logger, tmp_path):
        """start() should fail gracefully when JLinkRTTLogger is not found."""
        mock_find_logger.return_value = None
        manager = JLinkRTTManager(tmp_path)
        
        status = manager.start(device="TEST_DEVICE")
        
        assert status.running is False
        assert "not found" in status.last_error
        mock_find_logger.assert_called_once()

    @patch("eab.jlink_rtt.subprocess.Popen")
    @patch("eab.jlink_rtt._find_rtt_logger")
    def test_start_process_fails(self, mock_find_logger, mock_popen, tmp_path):
        """start() should handle subprocess launch failures."""
        mock_find_logger.return_value = "/usr/bin/JLinkRTTLogger"
        mock_popen.side_effect = OSError("Permission denied")
        manager = JLinkRTTManager(tmp_path)
        
        status = manager.start(device="TEST_DEVICE")
        
        assert status.running is False
        assert "Failed to start JLinkRTTLogger" in status.last_error
        assert "Permission denied" in status.last_error

    def test_stdout_reader_parses_channels(self, tmp_path):
        """_stdout_reader() should parse channel count from JLinkRTTLogger output."""
        manager = JLinkRTTManager(tmp_path)

        # Write stdout content to file (stdout reader now tails a file)
        stdout_path = tmp_path / "rtt-stdout.log"
        stdout_path.write_text("3 up-channels found:\n")
        manager._stdout_path = stdout_path

        # Mock process as exited so reader stops after reading
        mock_proc = MagicMock()
        mock_proc.poll.return_value = 0
        manager._proc = mock_proc

        manager._stdout_reader()

        assert manager._num_up == 3

    def test_stdout_reader_detects_failure(self, tmp_path):
        """_stdout_reader() should detect RTT control block not found error."""
        manager = JLinkRTTManager(tmp_path)

        stdout_path = tmp_path / "rtt-stdout.log"
        stdout_path.write_text("RTT Control Block not found\n")
        manager._stdout_path = stdout_path

        mock_proc = MagicMock()
        mock_proc.poll.return_value = 0
        manager._proc = mock_proc

        manager._stdout_reader()

        assert manager._last_error == "RTT control block not found"

    def test_stdout_reader_handles_invalid_channel_count(self, tmp_path):
        """_stdout_reader() should handle malformed channel count lines gracefully."""
        manager = JLinkRTTManager(tmp_path)

        stdout_path = tmp_path / "rtt-stdout.log"
        stdout_path.write_text("invalid up-channels found:\n")
        manager._stdout_path = stdout_path

        mock_proc = MagicMock()
        mock_proc.poll.return_value = 0
        manager._proc = mock_proc

        manager._stdout_reader()

        assert manager._num_up == 0

    def test_stdout_reader_logs_transfer_rate(self, tmp_path):
        """_stdout_reader() should process transfer rate updates without error."""
        manager = JLinkRTTManager(tmp_path)

        stdout_path = tmp_path / "rtt-stdout.log"
        stdout_path.write_text("Transfer rate: 100 KB/s\n")
        manager._stdout_path = stdout_path

        mock_proc = MagicMock()
        mock_proc.poll.return_value = 0
        manager._proc = mock_proc

        manager._stdout_reader()

        assert manager._last_error is None

    def test_stop_cleans_up_resources(self, tmp_path):
        """stop() should clean up all resources and reset state."""
        manager = JLinkRTTManager(tmp_path)
        
        # Simulate running state
        manager._device = "TEST_DEVICE"
        manager._num_up = 3
        mock_proc = MagicMock()
        mock_proc.poll.return_value = None  # Still running
        mock_proc.returncode = 0
        manager._proc = mock_proc
        
        # Mock processor
        mock_processor = MagicMock()
        manager._processor = mock_processor
        
        status = manager.stop()
        
        # Should terminate process (check before stop() nulls it)
        mock_proc.terminate.assert_called_once()
        
        # Should clean up state
        assert manager._proc is None
        assert manager._device is None
        assert manager._processor is None
        
        # Status should reflect stopped state
        assert status.running is False
        assert status.device is None

    @patch("eab.jlink_rtt.subprocess.Popen")
    @patch("eab.jlink_rtt._find_rtt_logger")
    @patch("eab.jlink_rtt.threading.Thread")
    def test_start_creates_threads(self, mock_thread, mock_find_logger, mock_popen, tmp_path):
        """start() should create stdout reader and tailer threads."""
        mock_find_logger.return_value = "/usr/bin/JLinkRTTLogger"
        
        # Mock successful process launch
        mock_proc = MagicMock()
        mock_proc.poll.return_value = None  # Process running
        mock_proc.pid = 12345
        mock_popen.return_value = mock_proc
        
        # Mock thread instances
        mock_stderr_thread = MagicMock()
        mock_tailer_thread = MagicMock()
        mock_thread.side_effect = [mock_stderr_thread, mock_tailer_thread]
        
        manager = JLinkRTTManager(tmp_path)
        # Preset channel count to skip waiting loop
        manager._num_up = 1
        
        manager.start(device="TEST_DEVICE")
        
        # Should create two threads
        assert mock_thread.call_count == 2
        mock_stderr_thread.start.assert_called_once()
        mock_tailer_thread.start.assert_called_once()
