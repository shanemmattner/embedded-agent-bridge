"""Unit tests for HilDevice — no hardware required."""

from __future__ import annotations

from unittest.mock import MagicMock, patch

import pytest

from eab.hil.hil_device import HilDevice, HilDeviceError
from eab.cli.regression.models import StepResult


def _ok(step_type="flash", **kw):
    return StepResult(step_type=step_type, params={}, passed=True,
                      duration_ms=10, output=kw)


def _fail(step_type="flash", error="boom"):
    return StepResult(step_type=step_type, params={}, passed=False,
                      duration_ms=10, error=error)


@pytest.fixture()
def dev():
    with patch("eab.hil.hil_device.os.path.getsize", return_value=0):
        return HilDevice(device="nrf5340", chip="NRF5340_XXAA_APP")


class TestFlash:
    def test_flash_success(self, dev):
        with patch("eab.hil.hil_device._run_flash", return_value=_ok()) as m:
            dev.flash("firmware.bin")
            m.assert_called_once()

    def test_flash_failure_raises(self, dev):
        with patch("eab.hil.hil_device._run_flash", return_value=_fail(error="no probe")):
            with pytest.raises(HilDeviceError, match="no probe"):
                dev.flash("firmware.bin")

    def test_flash_passes_firmware_path(self, dev):
        with patch("eab.hil.hil_device._run_flash", return_value=_ok()) as m:
            dev.flash("path/to/zephyr.bin")
            call_args = m.call_args
            step = call_args[0][0]
            assert step.params["firmware"] == "path/to/zephyr.bin"

    def test_flash_uses_default_timeout(self, dev):
        with patch("eab.hil.hil_device._run_flash", return_value=_ok()) as m:
            dev.flash("firmware.bin")
            call_kwargs = m.call_args[1]
            assert call_kwargs["timeout"] == dev.default_timeout

    def test_flash_custom_timeout(self, dev):
        with patch("eab.hil.hil_device._run_flash", return_value=_ok()) as m:
            dev.flash("firmware.bin", timeout=60)
            call_kwargs = m.call_args[1]
            assert call_kwargs["timeout"] == 60


class TestReset:
    def test_reset_success(self, dev):
        with patch("eab.hil.hil_device._run_reset", return_value=_ok("reset")):
            dev.reset()  # should not raise

    def test_reset_re_anchors_log_offset(self, dev):
        with patch("eab.hil.hil_device._run_reset", return_value=_ok("reset")):
            with patch.object(dev, "_record_log_offset") as m:
                dev.reset()
                m.assert_called_once()

    def test_reset_failure_raises(self, dev):
        with patch("eab.hil.hil_device._run_reset", return_value=_fail("reset")):
            with pytest.raises(HilDeviceError):
                dev.reset()

    def test_reset_no_re_anchor_on_failure(self, dev):
        """_record_log_offset should NOT be called if reset fails."""
        with patch("eab.hil.hil_device._run_reset", return_value=_fail("reset")):
            with patch.object(dev, "_record_log_offset") as m:
                with pytest.raises(HilDeviceError):
                    dev.reset()
                m.assert_not_called()


class TestWait:
    def test_wait_returns_matched_line(self, dev):
        result = _ok("wait", line="BLE initialized [OK]")
        with patch("eab.hil.hil_device._run_wait", return_value=result):
            line = dev.wait("BLE initialized", timeout=5)
            assert "BLE initialized" in line

    def test_wait_timeout_raises(self, dev):
        with patch("eab.hil.hil_device._run_wait",
                   return_value=_fail("wait", error="timeout")):
            with pytest.raises(HilDeviceError, match="timed out"):
                dev.wait("never", timeout=1)

    def test_wait_passes_log_offset(self, dev):
        dev._log_offset = 1234
        result = _ok("wait", line="hello")
        with patch("eab.hil.hil_device._run_wait", return_value=result) as m:
            dev.wait("hello", timeout=5)
            call_kwargs = m.call_args[1]
            assert call_kwargs["log_offset"] == 1234

    def test_wait_returns_empty_string_when_no_line(self, dev):
        result = _ok("wait")  # no 'line' key in output
        with patch("eab.hil.hil_device._run_wait", return_value=result):
            line = dev.wait("pattern", timeout=5)
            assert line == ""


class TestSend:
    def test_send_success(self, dev):
        with patch("eab.hil.hil_device._run_send", return_value=_ok("send")):
            dev.send("hello")  # should not raise

    def test_send_failure_raises(self, dev):
        with patch("eab.hil.hil_device._run_send",
                   return_value=_fail("send", error="send timeout")):
            with pytest.raises(HilDeviceError, match="send timeout"):
                dev.send("hello")

    def test_send_passes_text(self, dev):
        with patch("eab.hil.hil_device._run_send", return_value=_ok("send")) as m:
            dev.send("reboot")
            step = m.call_args[0][0]
            assert step.params["text"] == "reboot"


class TestAssertNoFault:
    def test_no_fault_passes(self, dev):
        with patch("eab.hil.hil_device._run_fault_check", return_value=_ok("fault_check")):
            dev.assert_no_fault()  # should not raise

    def test_fault_raises(self, dev):
        with patch("eab.hil.hil_device._run_fault_check",
                   return_value=_fail("fault_check", error="UsageFault")):
            with pytest.raises(HilDeviceError, match="UsageFault"):
                dev.assert_no_fault()

    def test_fault_raises_with_assert_no_fault_message(self, dev):
        with patch("eab.hil.hil_device._run_fault_check",
                   return_value=_fail("fault_check", error="HardFault")):
            with pytest.raises(HilDeviceError, match="assert_no_fault"):
                dev.assert_no_fault()


class TestHilDeviceInit:
    def test_device_attributes(self):
        with patch("eab.hil.hil_device.os.path.getsize", return_value=100):
            dev = HilDevice(device="esp32c6", chip="ESP32-C6", probe="usb:0483:3748")
            assert dev.device == "esp32c6"
            assert dev.chip == "ESP32-C6"
            assert dev.probe == "usb:0483:3748"

    def test_default_timeout(self):
        with patch("eab.hil.hil_device.os.path.getsize", return_value=0):
            dev = HilDevice(device="test", chip="TEST_CHIP")
            assert dev.default_timeout == 30

    def test_custom_timeout(self):
        with patch("eab.hil.hil_device.os.path.getsize", return_value=0):
            dev = HilDevice(device="test", chip="TEST_CHIP", default_timeout=60)
            assert dev.default_timeout == 60

    def test_log_offset_recorded_at_init(self):
        with patch("eab.hil.hil_device.os.path.getsize", return_value=42) as m:
            dev = HilDevice(device="test", chip="TEST")
            assert dev._log_offset == 42

    def test_log_offset_none_when_no_log_file(self):
        with patch("eab.hil.hil_device.os.path.getsize", side_effect=OSError):
            dev = HilDevice(device="test", chip="TEST")
            assert dev._log_offset is None
