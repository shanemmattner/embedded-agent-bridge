"""Tests for JLinkBridge.

Tests the unified J-Link services facade that manages RTT, SWO, and GDB
server subprocesses.
"""

from __future__ import annotations

import os
from pathlib import Path
from unittest.mock import MagicMock, Mock, patch

import pytest

from eab.jlink_bridge import JLinkBridge
from eab.process_utils import read_pid_file


class TestJLinkBridge:
    """Tests for JLinkBridge lifecycle and delegation."""

    def test_initialization_creates_paths(self, tmp_path):
        """__init__ should create base directory and set up path attributes."""
        bridge = JLinkBridge(str(tmp_path / "bridge"))
        
        assert bridge.base_dir.exists()
        assert bridge.base_dir == tmp_path / "bridge"
        assert bridge.swo_log_path == tmp_path / "bridge" / "swo.log"
        assert bridge.gdb_log_path == tmp_path / "bridge" / "jlink_gdb.log"

    @patch("eab.jlink_bridge.JLinkRTTManager")
    def test_rtt_delegation(self, mock_rtt_manager_class, tmp_path):
        """start_rtt() should delegate to JLinkRTTManager.start()."""
        # Mock the RTT manager instance
        mock_manager = MagicMock()
        mock_rtt_manager_class.return_value = mock_manager
        
        # Mock the status response
        mock_status = MagicMock()
        mock_status.running = True
        mock_status.device = "TEST_DEVICE"
        mock_manager.start.return_value = mock_status
        
        bridge = JLinkBridge(str(tmp_path))
        
        status = bridge.start_rtt(device="TEST_DEVICE", interface="SWD", speed=4000)
        
        # Should call manager's start with all arguments
        mock_manager.start.assert_called_once_with(
            device="TEST_DEVICE",
            interface="SWD",
            speed=4000,
            rtt_channel=0,
            block_address=None,
            queue=None,
        )
        assert status.running is True
        assert status.device == "TEST_DEVICE"

    @patch("eab.jlink_bridge.JLinkRTTManager")
    def test_rtt_stop_delegation(self, mock_rtt_manager_class, tmp_path):
        """stop_rtt() should delegate to JLinkRTTManager.stop()."""
        mock_manager = MagicMock()
        mock_rtt_manager_class.return_value = mock_manager
        
        mock_status = MagicMock()
        mock_status.running = False
        mock_manager.stop.return_value = mock_status
        
        bridge = JLinkBridge(str(tmp_path))
        
        status = bridge.stop_rtt(timeout_s=3.0)
        
        mock_manager.stop.assert_called_once_with(3.0)
        assert status.running is False

    @patch("eab.jlink_bridge.JLinkRTTManager")
    def test_rtt_status_delegation(self, mock_rtt_manager_class, tmp_path):
        """rtt_status() should delegate to JLinkRTTManager.status()."""
        mock_manager = MagicMock()
        mock_rtt_manager_class.return_value = mock_manager
        
        mock_status = MagicMock()
        mock_status.running = False
        mock_status.device = None
        mock_manager.status.return_value = mock_status
        
        bridge = JLinkBridge(str(tmp_path))
        
        status = bridge.rtt_status()
        
        mock_manager.status.assert_called_once()
        assert status.running is False
        assert status.device is None

    def test_swo_status_no_process(self, tmp_path):
        """swo_status() should return not running when no process exists."""
        bridge = JLinkBridge(str(tmp_path))
        
        status = bridge.swo_status()
        
        assert status.running is False
        assert status.pid is None
        assert status.device is None
        assert status.log_path == str(tmp_path / "swo.log")

    @patch("eab.jlink_bridge.pid_alive")
    def test_swo_status_with_dead_pid(self, mock_pid_alive, tmp_path):
        """swo_status() should clean up stale PID files."""
        bridge = JLinkBridge(str(tmp_path))
        
        # Write stale PID file
        bridge.swo_pid_path.write_text("12345")
        mock_pid_alive.return_value = False
        
        status = bridge.swo_status()
        
        assert status.running is False
        assert status.pid is None
        # PID file should be cleaned up
        assert not bridge.swo_pid_path.exists()

    def test_gdb_status_no_process(self, tmp_path):
        """gdb_status() should return not running when no process exists."""
        bridge = JLinkBridge(str(tmp_path))
        
        status = bridge.gdb_status()
        
        assert status.running is False
        assert status.pid is None
        assert status.device is None
        assert status.port == 2331

    @patch("eab.jlink_bridge.pid_alive")
    def test_gdb_status_with_dead_pid(self, mock_pid_alive, tmp_path):
        """gdb_status() should clean up stale PID files."""
        bridge = JLinkBridge(str(tmp_path))
        
        # Write stale PID file
        bridge.gdb_pid_path.write_text("67890")
        mock_pid_alive.return_value = False
        
        status = bridge.gdb_status()
        
        assert status.running is False
        assert status.pid is None
        # PID file should be cleaned up
        assert not bridge.gdb_pid_path.exists()

    @patch("eab.jlink_bridge.subprocess.Popen")
    @patch("eab.jlink_bridge.pid_alive")
    def test_start_swo_success(self, mock_pid_alive, mock_popen, tmp_path):
        """start_swo() should launch JLinkSWOViewerCLExe and track PID."""
        mock_proc = MagicMock()
        mock_proc.pid = 12345
        mock_proc.poll.return_value = None  # Still running
        mock_popen.return_value = mock_proc
        mock_pid_alive.return_value = True
        
        bridge = JLinkBridge(str(tmp_path))
        
        status = bridge.start_swo(device="TEST_DEVICE")
        
        # Should spawn process with correct args
        mock_popen.assert_called_once()
        args = mock_popen.call_args[0][0]
        assert "JLinkSWOViewerCLExe" in args[0]
        assert "-device" in args
        assert "TEST_DEVICE" in args
        
        # Should write PID file
        assert bridge.swo_pid_path.exists()
        assert bridge.swo_pid_path.read_text() == "12345"
        
        # Status should reflect running state
        assert status.running is True
        assert status.pid == 12345
        assert status.device == "TEST_DEVICE"

    @patch("eab.process_utils.os.kill")
    @patch("eab.jlink_bridge.pid_alive")
    @patch("eab.process_utils.pid_alive")
    def test_stop_swo(self, mock_pu_pid_alive, mock_jb_pid_alive, mock_kill, tmp_path):
        """stop_swo() should terminate process and clean up PID file."""
        bridge = JLinkBridge(str(tmp_path))
        
        # Simulate running process
        bridge.swo_pid_path.write_text("12345")
        # pid_alive is called multiple times: initial check says alive, then dead after SIGTERM
        mock_jb_pid_alive.side_effect = [True, False, False, False]
        mock_pu_pid_alive.side_effect = [True, False, False, False]
        
        status = bridge.stop_swo()
        
        # Should send SIGTERM (at least once)
        assert mock_kill.call_count >= 1
        # Verify SIGTERM signal was used
        import signal
        call_args = mock_kill.call_args_list[0]
        assert call_args[0][1] == signal.SIGTERM
        
        # Should clean up PID file
        assert not bridge.swo_pid_path.exists()
        
        # Status should reflect stopped state
        assert status.running is False
        assert status.pid is None

    @patch("eab.jlink_bridge.subprocess.Popen")
    @patch("eab.jlink_bridge.pid_alive")
    def test_start_gdb_server_success(self, mock_pid_alive, mock_popen, tmp_path):
        """start_gdb_server() should launch JLinkGDBServer with correct args."""
        mock_proc = MagicMock()
        mock_proc.pid = 67890
        mock_proc.poll.return_value = None
        mock_popen.return_value = mock_proc
        mock_pid_alive.return_value = True
        
        bridge = JLinkBridge(str(tmp_path))
        
        status = bridge.start_gdb_server(
            device="TEST_DEVICE",
            port=2331,
            swo_port=2332,
            telnet_port=2333,
        )
        
        # Should spawn process with correct args
        mock_popen.assert_called_once()
        args = mock_popen.call_args[0][0]
        assert "JLinkGDBServer" in args[0]
        assert "-device" in args
        assert "TEST_DEVICE" in args
        assert "-port" in args
        assert "2331" in args
        
        # Should write PID file
        assert bridge.gdb_pid_path.exists()
        
        # Status should reflect running state
        assert status.running is True
        assert status.pid == 67890
        assert status.device == "TEST_DEVICE"
        assert status.port == 2331

    @patch("eab.process_utils.os.kill")
    @patch("eab.jlink_bridge.pid_alive")
    @patch("eab.process_utils.pid_alive")
    def test_stop_gdb_server(self, mock_pu_pid_alive, mock_jb_pid_alive, mock_kill, tmp_path):
        """stop_gdb_server() should terminate process and clean up PID file."""
        bridge = JLinkBridge(str(tmp_path))
        
        # Simulate running process
        bridge.gdb_pid_path.write_text("67890")
        # pid_alive is called multiple times: initial check says alive, then dead after SIGTERM
        mock_jb_pid_alive.side_effect = [True, False, False, False]
        mock_pu_pid_alive.side_effect = [True, False, False, False]
        
        status = bridge.stop_gdb_server()
        
        # Should send SIGTERM (at least once)
        assert mock_kill.call_count >= 1
        # Verify SIGTERM signal was used
        import signal
        call_args = mock_kill.call_args_list[0]
        assert call_args[0][1] == signal.SIGTERM
        
        # Should clean up PID file
        assert not bridge.gdb_pid_path.exists()
        
        # Status should reflect stopped state
        assert status.running is False
        assert status.pid is None

    def test_read_pid_missing_file(self, tmp_path):
        """read_pid_file() should return None when PID file doesn't exist."""
        pid = read_pid_file(tmp_path / "nonexistent.pid")
        
        assert pid is None

    def test_read_pid_invalid_content(self, tmp_path):
        """read_pid_file() should return None when PID file contains invalid data."""
        pid_file = tmp_path / "invalid.pid"
        pid_file.write_text("not-a-number")
        
        pid = read_pid_file(pid_file)
        
        assert pid is None

    def test_read_pid_valid(self, tmp_path):
        """read_pid_file() should parse valid PID from file."""
        pid_file = tmp_path / "valid.pid"
        pid_file.write_text("12345")
        
        pid = read_pid_file(pid_file)
        
        assert pid == 12345
