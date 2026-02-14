"""Tests for probe-rs CLI wiring (parser + dispatch).

Verifies that eabctl probe-rs subcommands parse correctly and
dispatch routes to the right cmd_probe_rs_* handlers.
"""

from __future__ import annotations

from unittest.mock import patch, MagicMock

import pytest

from eab.cli.parser import _build_parser
from eab.cli.dispatch import main


# =============================================================================
# Parser tests
# =============================================================================


class TestProbeRsParser:
    """Verify argparse accepts probe-rs subcommands."""

    @pytest.fixture(autouse=True)
    def parser(self):
        self.parser = _build_parser()

    def test_list(self):
        args = self.parser.parse_args(["probe-rs", "list"])
        assert args.cmd == "probe-rs"
        assert args.probe_rs_action == "list"

    def test_info(self):
        args = self.parser.parse_args(["probe-rs", "info", "--chip", "nrf52840"])
        assert args.cmd == "probe-rs"
        assert args.probe_rs_action == "info"
        assert args.chip == "nrf52840"

    def test_rtt_start(self):
        args = self.parser.parse_args([
            "probe-rs", "rtt", "--chip", "nrf52840", "--channel", "1",
            "--probe", "1234:5678:ABCD",
        ])
        assert args.probe_rs_action == "rtt"
        assert args.chip == "nrf52840"
        assert args.channel == 1
        assert args.probe == "1234:5678:ABCD"
        assert args.stop is False

    def test_rtt_stop(self):
        args = self.parser.parse_args(["probe-rs", "rtt", "--chip", "nrf52840", "--stop"])
        assert args.stop is True

    def test_flash(self):
        args = self.parser.parse_args([
            "probe-rs", "flash", "app.elf", "--chip", "stm32f407vg",
            "--verify", "--reset-halt", "--probe", "1234:5678",
        ])
        assert args.probe_rs_action == "flash"
        assert args.firmware == "app.elf"
        assert args.chip == "stm32f407vg"
        assert args.verify is True
        assert args.reset_halt is True
        assert args.probe == "1234:5678"

    def test_flash_defaults(self):
        args = self.parser.parse_args(["probe-rs", "flash", "fw.hex", "--chip", "nrf52840"])
        assert args.verify is False
        assert args.reset_halt is False
        assert args.probe is None

    def test_reset(self):
        args = self.parser.parse_args(["probe-rs", "reset", "--chip", "nrf52840", "--halt"])
        assert args.probe_rs_action == "reset"
        assert args.chip == "nrf52840"
        assert args.halt is True

    def test_reset_defaults(self):
        args = self.parser.parse_args(["probe-rs", "reset", "--chip", "nrf52840"])
        assert args.halt is False
        assert args.probe is None

    def test_json_flag_with_probe_rs(self):
        args = self.parser.parse_args(["--json", "probe-rs", "list"])
        assert args.json is True
        assert args.cmd == "probe-rs"

    def test_missing_action_fails(self):
        with pytest.raises(SystemExit):
            self.parser.parse_args(["probe-rs"])

    def test_info_missing_chip_fails(self):
        with pytest.raises(SystemExit):
            self.parser.parse_args(["probe-rs", "info"])


# =============================================================================
# Dispatch tests
# =============================================================================


class TestProbeRsDispatch:
    """Verify dispatch routes probe-rs actions to cmd_probe_rs_* handlers."""

    @patch("eab.cli.cmd_probe_rs_list", return_value=0)
    @patch("eab.cli._resolve_base_dir", return_value="/tmp/eab")
    def test_dispatch_list(self, mock_resolve, mock_cmd):
        rc = main(["probe-rs", "list"])
        assert rc == 0
        mock_cmd.assert_called_once_with(base_dir="/tmp/eab", json_mode=False)

    @patch("eab.cli.cmd_probe_rs_list", return_value=0)
    @patch("eab.cli._resolve_base_dir", return_value="/tmp/eab")
    def test_dispatch_list_json(self, mock_resolve, mock_cmd):
        rc = main(["--json", "probe-rs", "list"])
        assert rc == 0
        mock_cmd.assert_called_once_with(base_dir="/tmp/eab", json_mode=True)

    @patch("eab.cli.cmd_probe_rs_info", return_value=0)
    @patch("eab.cli._resolve_base_dir", return_value="/tmp/eab")
    def test_dispatch_info(self, mock_resolve, mock_cmd):
        rc = main(["probe-rs", "info", "--chip", "nrf52840"])
        assert rc == 0
        mock_cmd.assert_called_once_with(base_dir="/tmp/eab", chip="nrf52840", json_mode=False)

    @patch("eab.cli.cmd_probe_rs_rtt", return_value=0)
    @patch("eab.cli._resolve_base_dir", return_value="/tmp/eab")
    def test_dispatch_rtt(self, mock_resolve, mock_cmd):
        rc = main(["probe-rs", "rtt", "--chip", "nrf52840", "--channel", "1"])
        assert rc == 0
        mock_cmd.assert_called_once_with(
            base_dir="/tmp/eab",
            chip="nrf52840",
            channel=1,
            probe=None,
            stop=False,
            json_mode=False,
        )

    @patch("eab.cli.cmd_probe_rs_flash", return_value=0)
    @patch("eab.cli._resolve_base_dir", return_value="/tmp/eab")
    def test_dispatch_flash(self, mock_resolve, mock_cmd):
        rc = main(["probe-rs", "flash", "app.elf", "--chip", "nrf52840", "--verify"])
        assert rc == 0
        mock_cmd.assert_called_once_with(
            base_dir="/tmp/eab",
            firmware="app.elf",
            chip="nrf52840",
            verify=True,
            reset_halt=False,
            probe=None,
            json_mode=False,
        )

    @patch("eab.cli.cmd_probe_rs_reset", return_value=0)
    @patch("eab.cli._resolve_base_dir", return_value="/tmp/eab")
    def test_dispatch_reset(self, mock_resolve, mock_cmd):
        rc = main(["probe-rs", "reset", "--chip", "nrf52840", "--halt"])
        assert rc == 0
        mock_cmd.assert_called_once_with(
            base_dir="/tmp/eab",
            chip="nrf52840",
            halt=True,
            probe=None,
            json_mode=False,
        )
