"""Unit tests for BleCentral — no hardware required."""

from __future__ import annotations

from unittest.mock import MagicMock

import pytest

from eab.hil.hil_device import HilDevice, HilDeviceError
from eab.hil.ble_central import BleCentral, BleCentralError


@pytest.fixture
def mock_dev() -> MagicMock:
    dev = MagicMock(spec=HilDevice)
    dev.device = "nrf5340-central"
    dev.chip = "NRF5340_XXAA_APP"
    dev.default_timeout = 30
    return dev


@pytest.fixture
def central(mock_dev) -> BleCentral:
    return BleCentral(mock_dev)


class TestBleCentralInit:
    def test_device_property(self, central, mock_dev):
        assert central.device is mock_dev

    def test_wraps_hil_device(self, mock_dev):
        c = BleCentral(mock_dev)
        assert c._dev is mock_dev


class TestScan:
    def test_success_returns_address(self, central, mock_dev):
        mock_dev.wait.return_value = "SCAN_RESULT: EAB-Peripheral AA:BB:CC:DD:EE:FF"
        addr = central.scan("EAB-Peripheral", timeout=10)
        mock_dev.send.assert_called_once_with("ble scan EAB-Peripheral")
        mock_dev.wait.assert_called_once_with("SCAN_RESULT: ", timeout=10)
        assert addr == "AA:BB:CC:DD:EE:FF"

    def test_timeout_raises_ble_central_error(self, central, mock_dev):
        mock_dev.wait.side_effect = HilDeviceError("timeout")
        with pytest.raises(BleCentralError, match="not found"):
            central.scan("EAB-Peripheral", timeout=5)

    def test_missing_address_in_line_returns_empty(self, central, mock_dev):
        mock_dev.wait.return_value = "SCAN_RESULT: "
        addr = central.scan("EAB-Peripheral")
        assert addr == ""

    def test_default_timeout_is_15(self, central, mock_dev):
        mock_dev.wait.return_value = "SCAN_RESULT: X AA:BB:CC:DD:EE:FF"
        central.scan("X")
        mock_dev.wait.assert_called_once_with("SCAN_RESULT: ", timeout=15)

    def test_sends_correct_command(self, central, mock_dev):
        mock_dev.wait.return_value = "SCAN_RESULT: MyDevice 11:22:33:44:55:66"
        central.scan("MyDevice", timeout=5)
        mock_dev.send.assert_called_once_with("ble scan MyDevice")


class TestConnect:
    def test_success(self, central, mock_dev):
        mock_dev.wait.return_value = "CONNECTED: AA:BB:CC:DD:EE:FF"
        central.connect(timeout=10)
        mock_dev.send.assert_called_once_with("ble connect")
        mock_dev.wait.assert_called_once_with("CONNECTED: ", timeout=10)

    def test_explicit_address(self, central, mock_dev):
        mock_dev.wait.return_value = "CONNECTED: AA:BB:CC:DD:EE:FF"
        central.connect("AA:BB:CC:DD:EE:FF", timeout=10)
        mock_dev.send.assert_called_once_with("ble connect AA:BB:CC:DD:EE:FF")

    def test_failure_raises(self, central, mock_dev):
        mock_dev.wait.side_effect = HilDeviceError("timeout")
        with pytest.raises(BleCentralError, match="connect failed"):
            central.connect(timeout=5)

    def test_no_addr_sends_plain_connect(self, central, mock_dev):
        mock_dev.wait.return_value = "CONNECTED: 00:11:22:33:44:55"
        central.connect()
        mock_dev.send.assert_called_once_with("ble connect")


class TestDisconnect:
    def test_success(self, central, mock_dev):
        mock_dev.wait.return_value = "DISCONNECTED"
        central.disconnect(timeout=10)
        mock_dev.send.assert_called_once_with("ble disconnect")
        mock_dev.wait.assert_called_once_with("DISCONNECTED", timeout=10)

    def test_failure_raises(self, central, mock_dev):
        mock_dev.wait.side_effect = HilDeviceError("timeout")
        with pytest.raises(BleCentralError, match="disconnect failed"):
            central.disconnect()


class TestSubscribe:
    def test_success(self, central, mock_dev):
        mock_dev.wait.return_value = "SUBSCRIBED: EAB20002"
        central.subscribe("EAB20002", timeout=10)
        mock_dev.send.assert_called_once_with("ble subscribe EAB20002")
        mock_dev.wait.assert_called_once_with("SUBSCRIBED: ", timeout=10)

    def test_failure_raises(self, central, mock_dev):
        mock_dev.wait.side_effect = HilDeviceError("no confirmation")
        with pytest.raises(BleCentralError, match="no confirmation"):
            central.subscribe("EAB20002", timeout=5)


class TestAssertNotify:
    def test_collects_values(self, central, mock_dev):
        mock_dev.wait.return_value = "NOTIFY_DONE: EAB20002 3 0A 0B 0C"
        vals = central.assert_notify("EAB20002", count=3, timeout=15)
        mock_dev.send.assert_called_once_with("ble expect_notify EAB20002 3")
        assert vals == ["0A", "0B", "0C"]

    def test_expect_value_match(self, central, mock_dev):
        mock_dev.wait.return_value = "NOTIFY_DONE: EAB20002 1 0A"
        vals = central.assert_notify("EAB20002", count=1, expect_value="0A")
        assert vals == ["0A"]

    def test_expect_value_mismatch_raises(self, central, mock_dev):
        mock_dev.wait.return_value = "NOTIFY_DONE: EAB20002 1 FF"
        with pytest.raises(BleCentralError, match="expected last value"):
            central.assert_notify("EAB20002", count=1, expect_value="0A")

    def test_timeout_raises(self, central, mock_dev):
        mock_dev.wait.side_effect = HilDeviceError("timeout")
        with pytest.raises(BleCentralError, match="did not receive"):
            central.assert_notify("EAB20002", count=5, timeout=5)

    def test_expect_value_case_insensitive(self, central, mock_dev):
        mock_dev.wait.return_value = "NOTIFY_DONE: EAB20002 1 0a"
        vals = central.assert_notify("EAB20002", count=1, expect_value="0A")
        assert vals == ["0a"]

    def test_no_values_in_line(self, central, mock_dev):
        mock_dev.wait.return_value = "NOTIFY_DONE: EAB20002 1"
        vals = central.assert_notify("EAB20002", count=1)
        assert vals == []


class TestWrite:
    def test_hex_string(self, central, mock_dev):
        mock_dev.wait.return_value = "WRITE_OK"
        central.write("EAB20003", "01", timeout=10)
        mock_dev.send.assert_called_once_with("ble write EAB20003 01 norsp")

    def test_bytes_value(self, central, mock_dev):
        mock_dev.wait.return_value = "WRITE_OK"
        central.write("EAB20003", b"\x01\x02", timeout=10)
        mock_dev.send.assert_called_once_with("ble write EAB20003 0102 norsp")

    def test_with_response_flag(self, central, mock_dev):
        mock_dev.wait.return_value = "WRITE_OK"
        central.write("EAB20003", "01", without_response=False)
        mock_dev.send.assert_called_once_with("ble write EAB20003 01 rsp")

    def test_failure_raises(self, central, mock_dev):
        mock_dev.wait.side_effect = HilDeviceError("timeout")
        with pytest.raises(BleCentralError, match="failed"):
            central.write("EAB20003", "01")

    def test_lowercase_hex_uppercased(self, central, mock_dev):
        mock_dev.wait.return_value = "WRITE_OK"
        central.write("EAB20003", "deadbeef")
        mock_dev.send.assert_called_once_with("ble write EAB20003 DEADBEEF norsp")

    def test_bytearray_value(self, central, mock_dev):
        mock_dev.wait.return_value = "WRITE_OK"
        central.write("EAB20003", bytearray(b"\xAA\xBB"))
        mock_dev.send.assert_called_once_with("ble write EAB20003 AABB norsp")


class TestRead:
    def test_success(self, central, mock_dev):
        mock_dev.wait.return_value = "READ_RESULT: EAB20004 AABBCC"
        val = central.read("EAB20004", timeout=10)
        mock_dev.send.assert_called_once_with("ble read EAB20004")
        assert val == "AABBCC"

    def test_failure_raises(self, central, mock_dev):
        mock_dev.wait.side_effect = HilDeviceError("timeout")
        with pytest.raises(BleCentralError, match="no result"):
            central.read("EAB20004")

    def test_returns_empty_on_short_line(self, central, mock_dev):
        mock_dev.wait.return_value = "READ_RESULT: EAB20004"
        val = central.read("EAB20004")
        assert val == ""


class TestDelegatedMethods:
    def test_flash_delegates_to_device(self, central, mock_dev):
        central.flash("firmware.bin")
        mock_dev.flash.assert_called_once_with("firmware.bin")

    def test_reset_delegates_to_device(self, central, mock_dev):
        central.reset()
        mock_dev.reset.assert_called_once_with()

    def test_assert_no_fault_delegates_to_device(self, central, mock_dev):
        central.assert_no_fault()
        mock_dev.assert_no_fault.assert_called_once_with()
