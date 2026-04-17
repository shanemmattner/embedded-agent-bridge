"""Tests for chip-info VID/PID-aware auto port selection (Bug 1).

Regression: ``eabctl chip-info --chip esp32c6`` (no ``--port``) used to fall
through to esptool's own glob-sorted auto-detect, which picks the
alphabetically-first ``/dev/cu.usbmodem*`` node. When an NXP MCU-Link probe
is plugged in alongside an ESP32-C6, the NXP node
(``/dev/cu.usbmodemI2WZW2OTY3RUW3``) beats the ESP32 node
(``/dev/cu.usbmodem101``) because capital-I sorts before digit-1. Wasted
~14s per probe and caused spurious "chip not found" errors.

Fix: when port is None, call :func:`eab.auto_detect.resolve_port_for_chip`
which filters USB devices by VID/PID against ``KNOWN_BOARDS``.
"""
from __future__ import annotations

from unittest import mock

import pytest

from eab.auto_detect import _chip_matches, resolve_port_for_chip
from eab.cli.flash import chip_info_cmd


ESP32_BOARD = {
    "name": "ESP32 USB-JTAG",
    "chip": "esp32",
    "probe": "esp-usb-jtag",
    "port": "/dev/cu.usbmodem101",
    "vid": "303a",
    "pid": "1001",
    "serial": "F0:F5:BD:01:88:2C",
}

NXP_BOARD = {
    "name": "FRDM-MCXN947",
    "chip": "mcxn947",
    "probe": "cmsis-dap",
    "port": "/dev/cu.usbmodemI2WZW2OTY3RUW3",
    "vid": "1fc9",
    "pid": "0143",
    "serial": "I2WZW2OTY3RUW",
}


class TestChipMatches:
    def test_exact_match(self):
        assert _chip_matches("esp32", "esp32") is True

    def test_variant_matches_family(self):
        # User asks for "esp32c6", KNOWN_BOARDS records "esp32"
        assert _chip_matches("esp32c6", "esp32") is True

    def test_family_matches_variant(self):
        assert _chip_matches("esp32", "esp32c6") is True

    def test_case_insensitive(self):
        assert _chip_matches("ESP32C6", "esp32") is True

    def test_distinct_chips(self):
        assert _chip_matches("esp32c6", "mcxn947") is False
        assert _chip_matches("stm32", "esp32") is False

    def test_empty_inputs(self):
        assert _chip_matches("", "esp32") is False
        assert _chip_matches("esp32", "") is False


class TestResolvePortForChip:
    def test_picks_esp32_not_nxp_when_both_present(self):
        """The real-world failure: both an ESP32 and an NXP probe are plugged in.

        Alphabetical sort puts the NXP node first. VID/PID resolver must
        still return the ESP32 node when the user asks for esp32c6.
        """
        port, err = resolve_port_for_chip("esp32c6", boards=[NXP_BOARD, ESP32_BOARD])
        assert port == "/dev/cu.usbmodem101"
        assert err is None

    def test_picks_nxp_when_requested(self):
        port, err = resolve_port_for_chip("mcxn947", boards=[NXP_BOARD, ESP32_BOARD])
        assert port == "/dev/cu.usbmodemI2WZW2OTY3RUW3"
        assert err is None

    def test_returns_no_match_when_chip_absent(self):
        port, err = resolve_port_for_chip("stm32", boards=[NXP_BOARD, ESP32_BOARD])
        assert port is None
        assert err == "no_match"

    def test_returns_ambiguous_when_multiple_match(self):
        second_esp = dict(ESP32_BOARD, port="/dev/cu.usbmodem102", serial="AA:BB")
        port, err = resolve_port_for_chip("esp32c6", boards=[ESP32_BOARD, second_esp])
        assert port is None
        assert err is not None and err.startswith("ambiguous:")
        assert "/dev/cu.usbmodem101" in err
        assert "/dev/cu.usbmodem102" in err

    def test_boards_with_empty_port_are_skipped(self):
        """ioreg detection returns empty port string — must not false-match."""
        no_port = dict(NXP_BOARD, port="")
        port, err = resolve_port_for_chip("mcxn947", boards=[no_port])
        assert port is None
        assert err == "no_match"


class TestChipInfoCmdAutoPort:
    def test_auto_port_picks_esp32_over_nxp(self):
        """End-to-end: cmd_chip_info with port=None, two USB devices present,
        must invoke esptool against the ESP32 port — not the NXP port.
        """
        captured: dict = {}

        def fake_run(cmd_list, capture_output, text, timeout):
            captured["cmd"] = cmd_list
            result = mock.Mock()
            result.returncode = 0
            result.stdout = "Chip is ESP32-C6"
            result.stderr = ""
            return result

        with mock.patch(
            "eab.cli.flash.chip_info_cmd.resolve_port_for_chip",
            return_value=("/dev/cu.usbmodem101", None),
        ), mock.patch(
            "eab.cli.flash.chip_info_cmd.subprocess.run",
            side_effect=fake_run,
        ):
            rc = chip_info_cmd.cmd_chip_info(chip="esp32c6", port=None, json_mode=True)

        assert rc == 0
        # Critical: esptool was invoked with the ESP32 node, not the NXP node.
        assert "/dev/cu.usbmodem101" in captured["cmd"]
        assert "/dev/cu.usbmodemI2WZW2OTY3RUW3" not in captured["cmd"]

    def test_auto_port_no_match_returns_error(self, capsys):
        with mock.patch(
            "eab.cli.flash.chip_info_cmd.resolve_port_for_chip",
            return_value=(None, "no_match"),
        ):
            rc = chip_info_cmd.cmd_chip_info(chip="esp32c6", port=None, json_mode=True)
        assert rc == 1
        out = capsys.readouterr().out
        assert "No USB device matching chip" in out

    def test_auto_port_ambiguous_returns_error(self, capsys):
        err = "ambiguous:/dev/cu.usbmodem101,/dev/cu.usbmodem102"
        with mock.patch(
            "eab.cli.flash.chip_info_cmd.resolve_port_for_chip",
            return_value=(None, err),
        ):
            rc = chip_info_cmd.cmd_chip_info(chip="esp32c6", port=None, json_mode=True)
        assert rc == 1
        out = capsys.readouterr().out
        assert "Multiple USB devices" in out
        assert "--port" in out

    def test_explicit_port_skips_resolver(self):
        """If --port is passed, resolver must not be called; esptool gets the
        explicit port unchanged.
        """
        captured: dict = {}

        def fake_run(cmd_list, capture_output, text, timeout):
            captured["cmd"] = cmd_list
            result = mock.Mock()
            result.returncode = 0
            result.stdout = ""
            result.stderr = ""
            return result

        with mock.patch(
            "eab.cli.flash.chip_info_cmd.resolve_port_for_chip",
        ) as resolver, mock.patch(
            "eab.cli.flash.chip_info_cmd.subprocess.run",
            side_effect=fake_run,
        ):
            rc = chip_info_cmd.cmd_chip_info(
                chip="esp32c6",
                port="/dev/cu.usbmodem999",
                json_mode=True,
            )

        assert rc == 0
        resolver.assert_not_called()
        assert "/dev/cu.usbmodem999" in captured["cmd"]
