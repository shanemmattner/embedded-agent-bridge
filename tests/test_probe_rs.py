"""Tests for ProbeRsBackend.

Tests the probe-rs wrapper that provides unified debug interface across
multiple probe types (J-Link, ST-Link, CMSIS-DAP). Focuses on subprocess
command generation, process management, and status parsing.
"""

from __future__ import annotations

import subprocess
from pathlib import Path
from unittest.mock import MagicMock, Mock, patch, mock_open

import pytest

from eab.probe_rs import ProbeRsBackend, ProbeInfo, _find_probe_rs


class TestFindProbeRs:
    """Tests for _find_probe_rs() binary detection."""

    @patch("eab.probe_rs.shutil.which")
    def test_find_probe_rs_on_path(self, mock_which):
        """Should find probe-rs via shutil.which when on PATH."""
        mock_which.return_value = "/usr/local/bin/probe-rs"
        
        result = _find_probe_rs()
        
        assert result == "/usr/local/bin/probe-rs"
        mock_which.assert_called_once_with("probe-rs")

    @patch("eab.probe_rs.os.access")
    @patch("eab.probe_rs.shutil.which")
    def test_find_probe_rs_fallback(self, mock_which, mock_access):
        """Should find probe-rs in fallback locations when not on PATH."""
        mock_which.return_value = None
        
        # First candidate succeeds
        cargo_path = Path.home() / ".cargo" / "bin" / "probe-rs"
        
        def access_side_effect(path, mode):
            return str(path) == str(cargo_path)
        
        mock_access.side_effect = access_side_effect
        
        # Mock Path.exists() on the actual Path object
        with patch.object(Path, 'exists', return_value=True):
            result = _find_probe_rs()
        
        assert result == str(cargo_path)
        mock_which.assert_called_once_with("probe-rs")

    @patch("eab.probe_rs.shutil.which")
    def test_find_probe_rs_not_found(self, mock_which):
        """Should return None when probe-rs is not found anywhere."""
        mock_which.return_value = None
        
        # Use real Path objects but mock their existence checks
        with patch("eab.probe_rs.os.access", return_value=False):
            result = _find_probe_rs()
        
        # Should return None since shutil.which returned None and all fallbacks fail
        assert result is None
        mock_which.assert_called_once_with("probe-rs")


class TestProbeRsBackend:
    """Tests for ProbeRsBackend lifecycle and operations."""

    def test_is_available_when_found(self, tmp_path):
        """Should return True when probe-rs binary is found."""
        with patch("eab.probe_rs._find_probe_rs", return_value="/usr/bin/probe-rs"):
            backend = ProbeRsBackend(tmp_path)
            assert backend.is_available() is True

    def test_is_available_when_not_found(self, tmp_path):
        """Should return False when probe-rs binary is not found."""
        with patch("eab.probe_rs._find_probe_rs", return_value=None):
            backend = ProbeRsBackend(tmp_path)
            assert backend.is_available() is False

    @patch("eab.probe_rs._find_probe_rs")
    def test_flash_not_available(self, mock_find, tmp_path):
        """Should raise FileNotFoundError when probe-rs is not installed."""
        mock_find.return_value = None
        backend = ProbeRsBackend(tmp_path)
        
        with pytest.raises(FileNotFoundError, match="probe-rs not found"):
            backend.flash("firmware.bin", "nrf52840")

    @patch("eab.probe_rs.subprocess.run")
    @patch("eab.probe_rs._find_probe_rs")
    def test_flash_success(self, mock_find, mock_run, tmp_path):
        """Should execute probe-rs download command successfully."""
        mock_find.return_value = "/usr/bin/probe-rs"
        mock_run.return_value = subprocess.CompletedProcess(
            args=["probe-rs", "download", "firmware.bin", "--chip", "nrf52840", "--verify"],
            returncode=0,
            stdout="Flashing done",
            stderr="",
        )
        
        backend = ProbeRsBackend(tmp_path)
        result = backend.flash("firmware.bin", "nrf52840")
        
        assert result.returncode == 0
        assert "Flashing done" in result.stdout
        mock_run.assert_called_once()
        args = mock_run.call_args[0][0]
        assert args[0] == "/usr/bin/probe-rs"
        assert args[1] == "download"
        assert "firmware.bin" in args
        assert "--chip" in args
        assert "nrf52840" in args
        assert "--verify" in args

    @patch("eab.probe_rs.subprocess.run")
    @patch("eab.probe_rs._find_probe_rs")
    def test_flash_with_options(self, mock_find, mock_run, tmp_path):
        """Should pass all flash options to probe-rs command."""
        mock_find.return_value = "/usr/bin/probe-rs"
        mock_run.return_value = subprocess.CompletedProcess(
            args=[], returncode=0, stdout="", stderr=""
        )
        
        backend = ProbeRsBackend(tmp_path)
        backend.flash(
            "firmware.bin",
            "stm32f407vg",
            verify=False,
            reset_halt=True,
            probe_selector="1234:5678:ABCD",
        )
        
        args = mock_run.call_args[0][0]
        assert "--chip" in args
        assert "stm32f407vg" in args
        assert "--verify" not in args  # verify=False
        assert "--reset-halt" in args
        assert "--probe" in args
        assert "1234:5678:ABCD" in args

    @patch("eab.probe_rs.subprocess.run")
    @patch("eab.probe_rs._find_probe_rs")
    def test_reset_success(self, mock_find, mock_run, tmp_path):
        """Should execute probe-rs reset command successfully."""
        mock_find.return_value = "/usr/bin/probe-rs"
        mock_run.return_value = subprocess.CompletedProcess(
            args=["probe-rs", "reset", "--chip", "nrf52840"],
            returncode=0,
            stdout="Reset successful",
            stderr="",
        )
        
        backend = ProbeRsBackend(tmp_path)
        result = backend.reset("nrf52840")
        
        assert result.returncode == 0
        args = mock_run.call_args[0][0]
        assert "reset" in args
        assert "--chip" in args
        assert "nrf52840" in args

    @patch("eab.probe_rs.subprocess.run")
    @patch("eab.probe_rs._find_probe_rs")
    def test_list_probes_success(self, mock_find, mock_run, tmp_path):
        """Should parse probe list output correctly."""
        mock_find.return_value = "/usr/bin/probe-rs"
        mock_run.return_value = subprocess.CompletedProcess(
            args=["probe-rs", "list"],
            returncode=0,
            stdout="""The following debug probes were found:
[0]: J-Link (J-Link) (VID: 1366, PID: 1015, Serial: 123456789)
[1]: ST-Link V3 (STLink) (VID: 0483, PID: 374E, Serial: ABC123)
""",
            stderr="",
        )
        
        backend = ProbeRsBackend(tmp_path)
        probes = backend.list_probes()
        
        assert len(probes) == 2
        assert probes[0].identifier == "[0]"
        assert probes[0].probe_type == "J-Link"
        assert probes[0].vendor_id == "1366"
        assert probes[0].product_id == "1015"
        assert probes[0].serial_number == "123456789"
        
        assert probes[1].identifier == "[1]"
        assert probes[1].probe_type == "STLink"
        assert probes[1].vendor_id == "0483"
        assert probes[1].product_id == "374E"

    @patch("eab.probe_rs.subprocess.run")
    @patch("eab.probe_rs._find_probe_rs")
    def test_list_probes_empty(self, mock_find, mock_run, tmp_path):
        """Should handle empty probe list gracefully."""
        mock_find.return_value = "/usr/bin/probe-rs"
        mock_run.return_value = subprocess.CompletedProcess(
            args=["probe-rs", "list"],
            returncode=0,
            stdout="The following debug probes were found:\n",
            stderr="",
        )
        
        backend = ProbeRsBackend(tmp_path)
        probes = backend.list_probes()
        
        assert len(probes) == 0

    @patch("eab.probe_rs._pid_alive")
    @patch("eab.probe_rs.subprocess.Popen")
    @patch("eab.probe_rs._find_probe_rs")
    def test_start_rtt_success(self, mock_find, mock_popen, mock_pid_alive, tmp_path):
        """Should start RTT streaming process successfully."""
        mock_find.return_value = "/usr/bin/probe-rs"
        mock_pid_alive.return_value = True  # Process is alive
        
        # Mock successful process launch
        mock_proc = MagicMock()
        mock_proc.pid = 12345
        mock_proc.poll.return_value = None  # Process running
        mock_popen.return_value = mock_proc
        
        # Mock file operations
        with patch("builtins.open", mock_open()):
            backend = ProbeRsBackend(tmp_path)
            status = backend.start_rtt("nrf52840", channel=0)
        
        assert status.running is True
        assert status.pid == 12345
        assert status.chip == "nrf52840"
        assert status.channel == 0
        mock_popen.assert_called_once()
        args = mock_popen.call_args[0][0]
        assert "rtt" in args
        assert "--chip" in args
        assert "nrf52840" in args
        assert "--up" in args
        assert "0" in args

    @patch("eab.probe_rs.subprocess.Popen")
    @patch("eab.probe_rs._find_probe_rs")
    def test_start_rtt_already_running(self, mock_find, mock_popen, tmp_path):
        """Should return current status if RTT is already running."""
        mock_find.return_value = "/usr/bin/probe-rs"
        
        backend = ProbeRsBackend(tmp_path)
        
        # Simulate already running by creating PID file
        backend.rtt_pid_path.write_text("12345")
        
        # Mock that PID is alive
        with patch("eab.probe_rs._pid_alive", return_value=True):
            status = backend.start_rtt("nrf52840")
        
        # Should not start new process
        mock_popen.assert_not_called()
        assert status.pid == 12345

    @patch("eab.probe_rs.time.time")
    @patch("eab.probe_rs.time.sleep")
    @patch("eab.probe_rs._pid_alive")
    @patch("eab.probe_rs.os.kill")
    @patch("eab.probe_rs._find_probe_rs")
    def test_stop_rtt(self, mock_find, mock_kill, mock_pid_alive, mock_sleep, mock_time, tmp_path):
        """Should stop RTT streaming process."""
        mock_find.return_value = "/usr/bin/probe-rs"
        
        # Mock time.time() to simulate timeout after first check
        mock_time.side_effect = [0.0, 0.0, 10.0]  # Start, first check (in while loop), timeout
        
        backend = ProbeRsBackend(tmp_path)
        
        # Simulate running process
        backend.rtt_pid_path.write_text("12345")
        
        # Process dies on first check in while loop
        # Calls: in _stop_process check, in while loop, final SIGKILL check
        mock_pid_alive.side_effect = [True, False, False]
        
        status = backend.stop_rtt()
        
        assert status.running is False
        assert status.pid is None
        # SIGTERM should be called
        assert mock_kill.called
        assert mock_kill.call_args_list[0][0] == (12345, 15)  # SIGTERM

    @patch("eab.probe_rs.subprocess.run")
    @patch("eab.probe_rs._find_probe_rs")
    def test_read_memory_success(self, mock_find, mock_run, tmp_path):
        """Should read memory from target successfully."""
        mock_find.return_value = "/usr/bin/probe-rs"
        mock_run.return_value = subprocess.CompletedProcess(
            args=["probe-rs", "read", "0x20000000", "256", "--chip", "nrf52840"],
            returncode=0,
            stdout=b"\x00\x01\x02\x03" * 64,  # 256 bytes
            stderr=b"",
        )
        
        backend = ProbeRsBackend(tmp_path)
        data = backend.read_memory(0x20000000, 256, "nrf52840")
        
        assert len(data) == 256
        assert data[:4] == b"\x00\x01\x02\x03"

    @patch("eab.probe_rs.subprocess.run")
    @patch("eab.probe_rs._find_probe_rs")
    def test_read_memory_failure(self, mock_find, mock_run, tmp_path):
        """Should raise RuntimeError on memory read failure."""
        mock_find.return_value = "/usr/bin/probe-rs"
        mock_run.return_value = subprocess.CompletedProcess(
            args=[], returncode=1, stdout=b"", stderr=b"Memory read failed"
        )
        
        backend = ProbeRsBackend(tmp_path)
        
        with pytest.raises(RuntimeError, match="Memory read failed"):
            backend.read_memory(0x20000000, 256, "nrf52840")

    @patch("eab.probe_rs.subprocess.run")
    @patch("eab.probe_rs._find_probe_rs")
    def test_chip_info_success(self, mock_find, mock_run, tmp_path):
        """Should retrieve chip information successfully."""
        mock_find.return_value = "/usr/bin/probe-rs"
        mock_run.return_value = subprocess.CompletedProcess(
            args=["probe-rs", "chip", "info", "nrf52840"],
            returncode=0,
            stdout="Chip: nRF52840\nArchitecture: ARM Cortex-M4\n",
            stderr="",
        )
        
        backend = ProbeRsBackend(tmp_path)
        info = backend.chip_info("nrf52840")
        
        assert info["chip"] == "nrf52840"
        assert "Chip: nRF52840" in info["info"]
        assert "error" not in info

    @patch("eab.probe_rs.subprocess.run")
    @patch("eab.probe_rs._find_probe_rs")
    def test_chip_info_failure(self, mock_find, mock_run, tmp_path):
        """Should handle chip info failure gracefully."""
        mock_find.return_value = "/usr/bin/probe-rs"
        mock_run.return_value = subprocess.CompletedProcess(
            args=[], returncode=1, stdout="", stderr="Unknown chip"
        )
        
        backend = ProbeRsBackend(tmp_path)
        info = backend.chip_info("unknown_chip")
        
        assert "error" in info
        assert "Unknown chip" in info["error"]

    def test_rtt_status_no_process(self, tmp_path):
        """Should return not-running status when no RTT process exists."""
        with patch("eab.probe_rs._find_probe_rs", return_value="/usr/bin/probe-rs"):
            backend = ProbeRsBackend(tmp_path)
            status = backend.rtt_status()
            
            assert status.running is False
            assert status.pid is None

    def test_rtt_status_stale_pid(self, tmp_path):
        """Should clean up stale PID file."""
        with patch("eab.probe_rs._find_probe_rs", return_value="/usr/bin/probe-rs"):
            backend = ProbeRsBackend(tmp_path)
            
            # Create stale PID file
            backend.rtt_pid_path.write_text("99999")
            
            # Mock that process is not alive
            with patch("eab.probe_rs._pid_alive", return_value=False):
                status = backend.rtt_status()
            
            assert status.running is False
            assert status.pid is None
            assert not backend.rtt_pid_path.exists()
