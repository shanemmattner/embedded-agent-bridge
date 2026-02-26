"""Unit tests for BLE YAML step executors — no hardware required."""

from __future__ import annotations

from unittest.mock import MagicMock, patch

import pytest

from eab.cli.regression.ble_steps import (
    _run_ble_scan,
    _run_ble_connect,
    _run_ble_subscribe,
    _run_ble_assert_notify,
    _run_ble_write,
    _run_ble_disconnect,
    _run_ble_read,
    BLE_STEP_DISPATCH,
)
from eab.cli.regression.models import StepResult, StepSpec


def _make_send_ok() -> MagicMock:
    return MagicMock(passed=True, error=None, output={})


def _make_wait_ok(line: str) -> MagicMock:
    return MagicMock(passed=True, error=None, output={"line": line})


def _make_wait_fail(error: str) -> MagicMock:
    return MagicMock(passed=False, error=error, output={})


def _make_send_fail(error: str) -> MagicMock:
    return MagicMock(passed=False, error=error, output={})


# --- BLE_STEP_DISPATCH registration -----------------------------------------

class TestBleStepDispatch:
    def test_all_ble_step_types_registered(self):
        from eab.cli.regression.steps import _STEP_DISPATCH
        expected = [
            "ble_scan", "ble_connect", "ble_disconnect",
            "ble_subscribe", "ble_assert_notify", "ble_write", "ble_read",
        ]
        for step_type in expected:
            assert step_type in _STEP_DISPATCH, f"{step_type!r} not in _STEP_DISPATCH"

    def test_ble_step_dispatch_dict_has_all_keys(self):
        assert set(BLE_STEP_DISPATCH.keys()) == {
            "ble_scan", "ble_connect", "ble_disconnect",
            "ble_subscribe", "ble_assert_notify", "ble_write", "ble_read",
        }


# --- ble_scan -----------------------------------------------------------------

class TestBleScanStep:
    def test_success_parses_address(self):
        step = StepSpec("ble_scan", {"target_name": "EAB-Peripheral", "timeout": 10})
        with patch("eab.cli.regression.ble_steps._run_send", return_value=_make_send_ok()), \
             patch("eab.cli.regression.ble_steps._run_wait",
                   return_value=_make_wait_ok("SCAN_RESULT: EAB-Peripheral AA:BB:CC:DD:EE:FF")):
            result = _run_ble_scan(step, device="nrf5340-central", chip="NRF5340_XXAA_APP",
                                   timeout=15)
        assert result.passed
        assert result.output["address"] == "AA:BB:CC:DD:EE:FF"
        assert result.step_type == "ble_scan"

    def test_send_failure_propagates(self):
        step = StepSpec("ble_scan", {"target_name": "X"})
        with patch("eab.cli.regression.ble_steps._run_send",
                   return_value=_make_send_fail("eabctl not found")):
            result = _run_ble_scan(step, device="dev", chip="chip", timeout=10)
        assert not result.passed
        assert "eabctl not found" in result.error

    def test_wait_failure_propagates(self):
        step = StepSpec("ble_scan", {"target_name": "X", "timeout": 5})
        with patch("eab.cli.regression.ble_steps._run_send", return_value=_make_send_ok()), \
             patch("eab.cli.regression.ble_steps._run_wait",
                   return_value=_make_wait_fail("SCAN_TIMEOUT")):
            result = _run_ble_scan(step, device="dev", chip="chip", timeout=5)
        assert not result.passed

    def test_step_timeout_overrides_global(self):
        step = StepSpec("ble_scan", {"target_name": "X", "timeout": 7})
        captured = {}
        def fake_send(s, *, device, chip, timeout):
            captured["timeout"] = timeout
            return _make_send_ok()
        with patch("eab.cli.regression.ble_steps._run_send", side_effect=fake_send), \
             patch("eab.cli.regression.ble_steps._run_wait",
                   return_value=_make_wait_ok("SCAN_RESULT: X 11:22:33:44:55:66")):
            _run_ble_scan(step, device="dev", chip="chip", timeout=60)
        assert captured["timeout"] == 7

    def test_no_address_in_line(self):
        step = StepSpec("ble_scan", {"target_name": "X"})
        with patch("eab.cli.regression.ble_steps._run_send", return_value=_make_send_ok()), \
             patch("eab.cli.regression.ble_steps._run_wait",
                   return_value=_make_wait_ok("SCAN_RESULT: X")):
            result = _run_ble_scan(step, device="dev", chip="chip", timeout=10)
        assert result.passed
        assert "address" not in result.output


# --- ble_connect --------------------------------------------------------------

class TestBleConnectStep:
    def test_success(self):
        step = StepSpec("ble_connect", {"timeout": 10})
        with patch("eab.cli.regression.ble_steps._run_send", return_value=_make_send_ok()), \
             patch("eab.cli.regression.ble_steps._run_wait",
                   return_value=_make_wait_ok("CONNECTED: AA:BB:CC:DD:EE:FF")):
            result = _run_ble_connect(step, device="dev", chip="chip", timeout=15)
        assert result.passed
        assert result.step_type == "ble_connect"

    def test_explicit_addr_in_command(self):
        step = StepSpec("ble_connect", {"addr": "AA:BB:CC:DD:EE:FF"})
        captured = {}
        def fake_send(s, *, device, chip, timeout):
            captured["text"] = s.params["text"]
            return _make_send_ok()
        with patch("eab.cli.regression.ble_steps._run_send", side_effect=fake_send), \
             patch("eab.cli.regression.ble_steps._run_wait",
                   return_value=_make_wait_ok("CONNECTED: AA:BB:CC:DD:EE:FF")):
            _run_ble_connect(step, device="dev", chip="chip", timeout=10)
        assert "AA:BB:CC:DD:EE:FF" in captured["text"]

    def test_failure_propagates(self):
        step = StepSpec("ble_connect", {})
        with patch("eab.cli.regression.ble_steps._run_send", return_value=_make_send_ok()), \
             patch("eab.cli.regression.ble_steps._run_wait",
                   return_value=_make_wait_fail("CONNECT_FAIL")):
            result = _run_ble_connect(step, device="dev", chip="chip", timeout=10)
        assert not result.passed


# --- ble_disconnect -----------------------------------------------------------

class TestBleDisconnectStep:
    def test_success(self):
        step = StepSpec("ble_disconnect", {"timeout": 5})
        with patch("eab.cli.regression.ble_steps._run_send", return_value=_make_send_ok()), \
             patch("eab.cli.regression.ble_steps._run_wait",
                   return_value=_make_wait_ok("DISCONNECTED")):
            result = _run_ble_disconnect(step, device="dev", chip="chip", timeout=10)
        assert result.passed
        assert result.step_type == "ble_disconnect"


# --- ble_subscribe ------------------------------------------------------------

class TestBleSubscribeStep:
    def test_success(self):
        step = StepSpec("ble_subscribe", {"char_uuid": "EAB20002", "timeout": 10})
        with patch("eab.cli.regression.ble_steps._run_send", return_value=_make_send_ok()), \
             patch("eab.cli.regression.ble_steps._run_wait",
                   return_value=_make_wait_ok("SUBSCRIBED: EAB20002")):
            result = _run_ble_subscribe(step, device="dev", chip="chip", timeout=10)
        assert result.passed
        assert result.step_type == "ble_subscribe"

    def test_uuid_alias(self):
        step = StepSpec("ble_subscribe", {"uuid": "EAB20002"})
        captured = {}
        def fake_send(s, *, device, chip, timeout):
            captured["text"] = s.params["text"]
            return _make_send_ok()
        with patch("eab.cli.regression.ble_steps._run_send", side_effect=fake_send), \
             patch("eab.cli.regression.ble_steps._run_wait",
                   return_value=_make_wait_ok("SUBSCRIBED: EAB20002")):
            _run_ble_subscribe(step, device="dev", chip="chip", timeout=10)
        assert "EAB20002" in captured["text"]


# --- ble_assert_notify --------------------------------------------------------

class TestBleAssertNotifyStep:
    def test_values_parsed_into_output(self):
        step = StepSpec("ble_assert_notify",
                        {"char_uuid": "EAB20002", "count": 3, "timeout": 20})
        with patch("eab.cli.regression.ble_steps._run_send", return_value=_make_send_ok()), \
             patch("eab.cli.regression.ble_steps._run_wait",
                   return_value=_make_wait_ok("NOTIFY_DONE: EAB20002 3 AA BB CC")):
            result = _run_ble_assert_notify(step, device="dev", chip="chip", timeout=20)
        assert result.passed
        assert result.output["notify_values"] == ["AA", "BB", "CC"]

    def test_expect_value_mismatch_fails(self):
        step = StepSpec("ble_assert_notify",
                        {"char_uuid": "EAB20002", "count": 1,
                         "expect_value": "0A", "timeout": 10})
        with patch("eab.cli.regression.ble_steps._run_send", return_value=_make_send_ok()), \
             patch("eab.cli.regression.ble_steps._run_wait",
                   return_value=_make_wait_ok("NOTIFY_DONE: EAB20002 1 FF")):
            result = _run_ble_assert_notify(step, device="dev", chip="chip", timeout=10)
        assert not result.passed
        assert "expected last value" in result.error

    def test_expect_value_match_passes(self):
        step = StepSpec("ble_assert_notify",
                        {"char_uuid": "EAB20002", "count": 1,
                         "expect_value": "AA", "timeout": 10})
        with patch("eab.cli.regression.ble_steps._run_send", return_value=_make_send_ok()), \
             patch("eab.cli.regression.ble_steps._run_wait",
                   return_value=_make_wait_ok("NOTIFY_DONE: EAB20002 1 AA")):
            result = _run_ble_assert_notify(step, device="dev", chip="chip", timeout=10)
        assert result.passed

    def test_wait_failure_propagates(self):
        step = StepSpec("ble_assert_notify", {"char_uuid": "EAB20002", "count": 1})
        with patch("eab.cli.regression.ble_steps._run_send", return_value=_make_send_ok()), \
             patch("eab.cli.regression.ble_steps._run_wait",
                   return_value=_make_wait_fail("NOTIFY_TIMEOUT")):
            result = _run_ble_assert_notify(step, device="dev", chip="chip", timeout=10)
        assert not result.passed


# --- ble_write ----------------------------------------------------------------

class TestBleWriteStep:
    def test_hex_value_uppercased_in_command(self):
        step = StepSpec("ble_write", {"char_uuid": "EAB20003", "value": "01", "timeout": 10})
        captured = {}
        def fake_send(s, *, device, chip, timeout):
            captured["text"] = s.params["text"]
            return _make_send_ok()
        with patch("eab.cli.regression.ble_steps._run_send", side_effect=fake_send), \
             patch("eab.cli.regression.ble_steps._run_wait",
                   return_value=_make_wait_ok("WRITE_OK")):
            result = _run_ble_write(step, device="dev", chip="chip", timeout=10)
        assert result.passed
        assert "01" in captured["text"]
        assert "norsp" in captured["text"]

    def test_without_response_false_sends_rsp(self):
        step = StepSpec("ble_write",
                        {"char_uuid": "EAB20003", "value": "FF",
                         "without_response": False})
        captured = {}
        def fake_send(s, *, device, chip, timeout):
            captured["text"] = s.params["text"]
            return _make_send_ok()
        with patch("eab.cli.regression.ble_steps._run_send", side_effect=fake_send), \
             patch("eab.cli.regression.ble_steps._run_wait",
                   return_value=_make_wait_ok("WRITE_OK")):
            _run_ble_write(step, device="dev", chip="chip", timeout=10)
        assert "rsp" in captured["text"]
        assert "norsp" not in captured["text"]

    def test_failure_propagates(self):
        step = StepSpec("ble_write", {"char_uuid": "EAB20003", "value": "00"})
        with patch("eab.cli.regression.ble_steps._run_send", return_value=_make_send_ok()), \
             patch("eab.cli.regression.ble_steps._run_wait",
                   return_value=_make_wait_fail("WRITE_FAIL")):
            result = _run_ble_write(step, device="dev", chip="chip", timeout=10)
        assert not result.passed


# --- ble_read -----------------------------------------------------------------

class TestBleReadStep:
    def test_success_extracts_value(self):
        step = StepSpec("ble_read", {"char_uuid": "EAB20004", "timeout": 10})
        with patch("eab.cli.regression.ble_steps._run_send", return_value=_make_send_ok()), \
             patch("eab.cli.regression.ble_steps._run_wait",
                   return_value=_make_wait_ok("READ_RESULT: EAB20004 AABBCC")):
            result = _run_ble_read(step, device="dev", chip="chip", timeout=10)
        assert result.passed
        assert result.output["value"] == "AABBCC"
        assert result.step_type == "ble_read"

    def test_failure_propagates(self):
        step = StepSpec("ble_read", {"char_uuid": "EAB20004"})
        with patch("eab.cli.regression.ble_steps._run_send", return_value=_make_send_ok()), \
             patch("eab.cli.regression.ble_steps._run_wait",
                   return_value=_make_wait_fail("READ_FAIL")):
            result = _run_ble_read(step, device="dev", chip="chip", timeout=10)
        assert not result.passed

    def test_empty_value_on_short_line(self):
        step = StepSpec("ble_read", {"char_uuid": "EAB20004"})
        with patch("eab.cli.regression.ble_steps._run_send", return_value=_make_send_ok()), \
             patch("eab.cli.regression.ble_steps._run_wait",
                   return_value=_make_wait_ok("READ_RESULT: EAB20004")):
            result = _run_ble_read(step, device="dev", chip="chip", timeout=10)
        assert result.passed
        assert result.output["value"] == ""
