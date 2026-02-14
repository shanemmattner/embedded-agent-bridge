"""Tests for JLinkRTTManager.reset_target() and RTT CLI commands."""

from __future__ import annotations

from pathlib import Path
from unittest.mock import MagicMock, patch, call

import pytest

from eab.jlink_rtt import JLinkRTTManager


class TestResetTargetSavesConfig:
    """Verify that start() saves all params for reset_target() to restore."""

    @patch("eab.jlink_rtt.subprocess.Popen")
    @patch("eab.jlink_rtt._find_rtt_logger")
    @patch("eab.jlink_rtt.threading.Thread")
    def test_start_saves_all_params(self, mock_thread, mock_find, mock_popen, tmp_path):
        mock_find.return_value = "/usr/bin/JLinkRTTLogger"
        mock_proc = MagicMock()
        mock_proc.poll.return_value = None
        mock_proc.pid = 12345
        mock_popen.return_value = mock_proc

        mock_thread.return_value = MagicMock()

        mgr = JLinkRTTManager(tmp_path)
        mgr._num_up = 1  # skip wait loop

        mgr.start(
            device="NRF5340_XXAA_APP",
            interface="SWD",
            speed=8000,
            rtt_channel=2,
            block_address=0x20000410,
        )

        assert mgr._device == "NRF5340_XXAA_APP"
        assert mgr._interface == "SWD"
        assert mgr._speed == 8000
        assert mgr._channel == 2
        assert mgr._block_address == 0x20000410


class TestResetTargetNotRunning:
    """reset_target() should return error status when RTT is not running."""

    def test_reset_when_not_running(self, tmp_path):
        mgr = JLinkRTTManager(tmp_path)

        status = mgr.reset_target()

        assert status.running is False
        assert "not running" in status.last_error


class TestResetTargetSequence:
    """reset_target() should stop → pylink reset → restart in correct order."""

    @patch("eab.jlink_rtt.time.sleep")
    def test_reset_sequence(self, mock_sleep, tmp_path):
        mgr = JLinkRTTManager(tmp_path)

        # Simulate running state with saved config
        mgr._device = "NRF5340_XXAA_APP"
        mgr._interface = "SWD"
        mgr._speed = 4000
        mgr._channel = 0
        mgr._block_address = 0x20000410
        mgr._queue = None

        mock_proc = MagicMock()
        mock_proc.poll.return_value = None  # running
        mgr._proc = mock_proc
        mock_processor = MagicMock()
        mgr._processor = mock_processor

        # Mock pylink
        mock_jlink_inst = MagicMock()
        mock_jlink_cls = MagicMock(return_value=mock_jlink_inst)

        with patch.dict("sys.modules", {"pylink": MagicMock()}):
            import sys
            mock_pylink = sys.modules["pylink"]
            mock_pylink.JLink = mock_jlink_cls
            mock_pylink.enums.JLinkInterfaces.SWD = 1

            # Mock start() to return a status (after reset restarts RTT)
            with patch.object(mgr, "start") as mock_start:
                mock_start.return_value = MagicMock(running=True, last_error=None)

                result = mgr.reset_target(wait_after_reset_s=0.5)

        # Verify pylink sequence
        mock_jlink_cls.assert_called_once()
        mock_jlink_inst.open.assert_called_once()
        mock_jlink_inst.set_tif.assert_called_once()
        mock_jlink_inst.connect.assert_called_once_with("NRF5340_XXAA_APP", speed=4000)
        mock_jlink_inst.reset.assert_called_once_with(halt=False)
        mock_jlink_inst.close.assert_called_once()

        # Verify sleep after reset
        mock_sleep.assert_any_call(0.5)

        # Verify start() called with saved config
        mock_start.assert_called_once_with(
            device="NRF5340_XXAA_APP",
            interface="SWD",
            speed=4000,
            rtt_channel=0,
            block_address=0x20000410,
            queue=None,
        )

    @patch("eab.jlink_rtt.time.sleep")
    def test_reset_pylink_failure(self, mock_sleep, tmp_path):
        """If pylink reset fails, should return error status without restarting."""
        mgr = JLinkRTTManager(tmp_path)

        # Simulate running
        mgr._device = "NRF5340_XXAA_APP"
        mgr._interface = "SWD"
        mgr._speed = 4000
        mgr._channel = 0
        mgr._block_address = None
        mgr._queue = None

        mock_proc = MagicMock()
        mock_proc.poll.return_value = None
        mgr._proc = mock_proc
        mgr._processor = MagicMock()

        # Mock pylink to raise
        with patch.dict("sys.modules", {"pylink": MagicMock()}):
            import sys
            mock_pylink = sys.modules["pylink"]
            mock_pylink.JLink.return_value.open.side_effect = RuntimeError("No J-Link found")

            status = mgr.reset_target()

        assert status.running is False
        assert "pylink reset failed" in status.last_error


class TestRTTCLIParsing:
    """Verify CLI argument parsing for RTT subcommands."""

    def test_rtt_subparser_exists(self):
        from eab.cli import _build_parser
        parser = _build_parser()

        # Should parse rtt start
        args = parser.parse_args(["rtt", "start", "--device", "NRF5340_XXAA_APP"])
        assert args.cmd == "rtt"
        assert args.rtt_action == "start"
        assert args.device == "NRF5340_XXAA_APP"
        assert args.interface == "SWD"
        assert args.speed == 4000
        assert args.channel == 0
        assert args.block_address is None

    def test_rtt_start_with_all_options(self):
        from eab.cli import _build_parser
        parser = _build_parser()

        args = parser.parse_args([
            "rtt", "start",
            "--device", "NRF5340_XXAA_APP",
            "--interface", "JTAG",
            "--speed", "8000",
            "--channel", "2",
            "--block-address", "0x20000410",
        ])
        assert args.interface == "JTAG"
        assert args.speed == 8000
        assert args.channel == 2
        assert args.block_address == 0x20000410

    def test_rtt_stop_parsing(self):
        from eab.cli import _build_parser
        parser = _build_parser()

        args = parser.parse_args(["rtt", "stop"])
        assert args.cmd == "rtt"
        assert args.rtt_action == "stop"

    def test_rtt_status_parsing(self):
        from eab.cli import _build_parser
        parser = _build_parser()

        args = parser.parse_args(["rtt", "status"])
        assert args.cmd == "rtt"
        assert args.rtt_action == "status"

    def test_rtt_reset_parsing(self):
        from eab.cli import _build_parser
        parser = _build_parser()

        args = parser.parse_args(["rtt", "reset"])
        assert args.cmd == "rtt"
        assert args.rtt_action == "reset"
        assert args.wait == 1.0

    def test_rtt_reset_custom_wait(self):
        from eab.cli import _build_parser
        parser = _build_parser()

        args = parser.parse_args(["rtt", "reset", "--wait", "2.5"])
        assert args.wait == 2.5

    def test_rtt_tail_parsing(self):
        from eab.cli import _build_parser
        parser = _build_parser()

        args = parser.parse_args(["rtt", "tail", "20"])
        assert args.cmd == "rtt"
        assert args.rtt_action == "tail"
        assert args.lines == 20

    def test_rtt_tail_default_lines(self):
        from eab.cli import _build_parser
        parser = _build_parser()

        args = parser.parse_args(["rtt", "tail"])
        assert args.lines == 50
