"""Unit tests for parse_test() / run_test() multi-device path."""

from __future__ import annotations

import os
import tempfile
import textwrap
from unittest.mock import MagicMock, patch

import pytest

from eab.cli.regression.runner import parse_test, _parse_devices, _resolve_step_device
from eab.cli.regression.models import DeviceSpec, StepSpec, TestSpec


def _write_yaml(content: str) -> str:
    f = tempfile.NamedTemporaryFile(mode="w", suffix=".yaml", delete=False)
    f.write(textwrap.dedent(content))
    f.close()
    return f.name


# --- _parse_devices -----------------------------------------------------------

class TestParseDevices:
    def test_basic_parsing(self):
        raw = {
            "peripheral": {"device": "nrf5340-peripheral", "chip": "NRF5340_XXAA_APP"},
            "central": {"device": "nrf5340-central", "chip": "NRF5340_XXAA_APP", "probe": "123"},
        }
        result = _parse_devices(raw)
        assert result["peripheral"].device == "nrf5340-peripheral"
        assert result["peripheral"].chip == "NRF5340_XXAA_APP"
        assert result["peripheral"].probe is None
        assert result["central"].probe == "123"

    def test_missing_device_key_raises(self):
        raw = {"central": {"chip": "NRF5340_XXAA_APP"}}
        with pytest.raises(KeyError):
            _parse_devices(raw)

    def test_non_dict_spec_raises(self):
        raw = {"central": "not-a-dict"}
        with pytest.raises(ValueError, match="must be a mapping"):
            _parse_devices(raw)


# --- parse_test() -------------------------------------------------------------

class TestParseTest:
    def test_parse_devices_block(self):
        path = _write_yaml("""
            name: multi_dev_test
            devices:
              peripheral:
                device: nrf5340-peripheral
                chip: NRF5340_XXAA_APP
                probe: "001050285282"
              central:
                device: nrf5340-central
                chip: NRF5340_XXAA_APP
            steps:
              - ble_connect:
                  device: central
                  timeout: 10
        """)
        spec = parse_test(path)
        os.unlink(path)

        assert "peripheral" in spec.devices
        assert "central" in spec.devices
        assert spec.devices["peripheral"].device == "nrf5340-peripheral"
        assert spec.devices["peripheral"].probe == "001050285282"
        assert spec.devices["central"].chip == "NRF5340_XXAA_APP"
        assert spec.devices["central"].probe is None

    def test_parse_legacy_single_device(self):
        path = _write_yaml("""
            name: legacy_test
            device: nrf5340
            chip: NRF5340_XXAA_APP
            steps:
              - wait:
                  pattern: "boot"
        """)
        spec = parse_test(path)
        os.unlink(path)

        assert spec.device == "nrf5340"
        assert spec.chip == "NRF5340_XXAA_APP"
        assert spec.devices == {}

    def test_parse_missing_device_key_raises(self):
        path = _write_yaml("""
            name: bad_test
            devices:
              central:
                chip: NRF5340_XXAA_APP
        """)
        with pytest.raises((KeyError, ValueError)):
            parse_test(path)
        os.unlink(path)

    def test_no_devices_block_yields_empty_dict(self):
        path = _write_yaml("""
            name: simple
            steps: []
        """)
        spec = parse_test(path)
        os.unlink(path)
        assert spec.devices == {}

    def test_step_device_param_preserved(self):
        path = _write_yaml("""
            name: multi
            devices:
              central:
                device: nrf5340-central
                chip: NRF5340_XXAA_APP
            steps:
              - ble_scan:
                  device: central
                  target_name: MyDev
        """)
        spec = parse_test(path)
        os.unlink(path)
        assert spec.steps[0].params["device"] == "central"
        assert spec.steps[0].params["target_name"] == "MyDev"

    def test_timeout_parsed(self):
        path = _write_yaml("""
            name: t
            timeout: 120
            steps: []
        """)
        spec = parse_test(path)
        os.unlink(path)
        assert spec.timeout == 120


# --- _resolve_step_device() ---------------------------------------------------

class TestResolveStepDevice:
    def _spec(self, devices=None, device=None, chip=None):
        return TestSpec(
            name="test", file="test.yaml",
            device=device, chip=chip,
            devices=devices or {},
        )

    def test_resolves_from_devices_map(self):
        spec = self._spec(
            devices={
                "central": DeviceSpec(device="nrf5340-central", chip="NRF5340_XXAA_APP"),
            }
        )
        step = StepSpec("ble_scan", {"device": "central"})
        dev, chip = _resolve_step_device(step, spec)
        assert dev == "nrf5340-central"
        assert chip == "NRF5340_XXAA_APP"

    def test_falls_back_to_legacy_device(self):
        spec = self._spec(device="nrf5340", chip="NRF5340_XXAA_APP")
        step = StepSpec("wait", {"pattern": "boot"})
        dev, chip = _resolve_step_device(step, spec)
        assert dev == "nrf5340"
        assert chip == "NRF5340_XXAA_APP"

    def test_literal_device_name_without_devices_block(self):
        spec = self._spec(chip="NRF5340_XXAA_APP")
        step = StepSpec("flash", {"device": "nrf5340-dev"})
        dev, chip = _resolve_step_device(step, spec)
        assert dev == "nrf5340-dev"
        assert chip == "NRF5340_XXAA_APP"

    def test_unknown_slot_falls_back_to_legacy(self):
        spec = self._spec(
            device="nrf5340", chip="NRF5340_XXAA_APP",
            devices={"central": DeviceSpec(device="nrf5340-central")},
        )
        # 'peripheral' slot not in devices map — falls through to legacy
        step = StepSpec("wait", {"device": "peripheral", "pattern": "boot"})
        dev, chip = _resolve_step_device(step, spec)
        # Slot not in devices, devices is non-empty → falls to (spec.device, spec.chip)
        assert dev == "nrf5340"
        assert chip == "NRF5340_XXAA_APP"

    def test_no_device_param_uses_legacy(self):
        spec = self._spec(device="default-dev", chip="CHIP")
        step = StepSpec("reset", {})
        dev, chip = _resolve_step_device(step, spec)
        assert dev == "default-dev"
        assert chip == "CHIP"
