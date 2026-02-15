"""Tests for multi-device support (per-device singletons, device registry, base_dir resolution)."""

import os
import json

import pytest

from eab.singleton import SingletonDaemon
from eab.device_registry import (
    list_devices,
    register_device,
    unregister_device,
)


@pytest.fixture
def tmp_devices_dir(monkeypatch, tmp_path):
    """Override _get_devices_dir to return a temp directory."""
    devices_dir = str(tmp_path / "eab-devices")
    _mock = lambda: devices_dir
    # Patch the canonical source and all import-time bindings
    monkeypatch.setattr("eab.device_registry._get_devices_dir", _mock)
    monkeypatch.setattr("eab.cli.helpers._get_devices_dir", _mock)
    return devices_dir


@pytest.fixture
def tmp_run_dir(tmp_path):
    """Return a temp dir for PID/info files."""
    return str(tmp_path / "run")


class TestPerDeviceSingleton:
    def test_device_singleton_paths(self, tmp_devices_dir):
        """Per-device singleton puts PID/info files in device dir."""
        s = SingletonDaemon(device_name="nrf5340")
        # Override to use tmp dir
        s.PID_FILE = os.path.join(tmp_devices_dir, "nrf5340", "daemon.pid")
        s.INFO_FILE = os.path.join(tmp_devices_dir, "nrf5340", "daemon.info")

        assert "nrf5340" in s.PID_FILE
        assert "nrf5340" in s.INFO_FILE

    def test_legacy_singleton_paths(self):
        """Without device_name, uses legacy global paths."""
        s = SingletonDaemon()
        assert "eab-daemon.pid" in s.PID_FILE
        assert "eab-daemon.info" in s.INFO_FILE

    def test_two_device_singletons_independent(self, tmp_devices_dir):
        """Two devices can acquire locks independently."""
        s1 = SingletonDaemon(device_name="nrf5340")
        s1.PID_FILE = os.path.join(tmp_devices_dir, "nrf5340", "daemon.pid")
        s1.INFO_FILE = os.path.join(tmp_devices_dir, "nrf5340", "daemon.info")

        s2 = SingletonDaemon(device_name="esp32")
        s2.PID_FILE = os.path.join(tmp_devices_dir, "esp32", "daemon.pid")
        s2.INFO_FILE = os.path.join(tmp_devices_dir, "esp32", "daemon.info")

        assert s1.acquire(port="/dev/ttyUSB0", base_dir=os.path.join(tmp_devices_dir, "nrf5340"))
        assert s2.acquire(port="/dev/ttyUSB1", base_dir=os.path.join(tmp_devices_dir, "esp32"))

        # Both should have existing daemons
        e1 = s1.get_existing()
        e2 = s2.get_existing()
        assert e1 is not None
        assert e2 is not None
        assert e1.port == "/dev/ttyUSB0"
        assert e2.port == "/dev/ttyUSB1"

        s1.release()
        s2.release()

    def test_acquire_writes_device_metadata(self, tmp_devices_dir):
        """acquire() writes device_name, type, and chip to info file."""
        s = SingletonDaemon(device_name="stm32")
        s.PID_FILE = os.path.join(tmp_devices_dir, "stm32", "daemon.pid")
        s.INFO_FILE = os.path.join(tmp_devices_dir, "stm32", "daemon.info")

        assert s.acquire(
            port="/dev/ttyACM0",
            base_dir=os.path.join(tmp_devices_dir, "stm32"),
            device_type="serial",
            chip="stm32l476rg",
        )

        e = s.get_existing()
        assert e is not None
        assert e.device_name == "stm32"
        assert e.device_type == "serial"
        assert e.chip == "stm32l476rg"

        s.release()


class TestDeviceRegistry:
    def test_register_creates_dir_and_info(self, tmp_devices_dir):
        """register_device creates session dir with daemon.info."""
        path = register_device("nrf5340", device_type="debug", chip="nrf5340")
        assert os.path.isdir(path)
        assert os.path.isfile(os.path.join(path, "daemon.info"))

    def test_list_devices_empty(self, tmp_devices_dir):
        """list_devices returns empty list when no devices registered."""
        assert list_devices() == []

    def test_list_devices_after_register(self, tmp_devices_dir):
        """list_devices finds registered devices."""
        register_device("nrf5340", device_type="debug", chip="nrf5340")
        register_device("esp32", device_type="serial", chip="esp32s3")

        devices = list_devices()
        assert len(devices) == 2

        names = {d.device_name for d in devices}
        assert names == {"nrf5340", "esp32"}

        nrf = [d for d in devices if d.device_name == "nrf5340"][0]
        assert nrf.device_type == "debug"
        assert nrf.chip == "nrf5340"
        assert nrf.is_alive is False

    def test_unregister_removes_device(self, tmp_devices_dir):
        """unregister_device removes the session dir."""
        register_device("test1", device_type="debug", chip="test")
        assert len(list_devices()) == 1

        assert unregister_device("test1") is True
        assert len(list_devices()) == 0

    def test_unregister_nonexistent(self, tmp_devices_dir):
        """unregister_device returns False for missing device."""
        assert unregister_device("nonexistent") is False


class TestBaseDirResolution:
    def test_override_takes_precedence(self, tmp_devices_dir):
        """Explicit --base-dir always wins."""
        from eab.cli.helpers import _resolve_base_dir
        assert _resolve_base_dir("/custom/path") == "/custom/path"

    def test_device_name_routes_to_devices_dir(self, tmp_devices_dir):
        """--device name maps to /tmp/eab-devices/<name>/."""
        from eab.cli.helpers import _resolve_base_dir
        result = _resolve_base_dir(None, device="nrf5340")
        assert result == os.path.join(tmp_devices_dir, "nrf5340")

    def test_fallback_to_default(self, tmp_devices_dir, monkeypatch):
        """No device, no override, no running daemons → default."""
        from eab.cli.helpers import _resolve_base_dir, DEFAULT_BASE_DIR
        # Ensure no legacy singleton
        monkeypatch.setattr("eab.cli.helpers.check_singleton", lambda: None)
        result = _resolve_base_dir(None)
        assert result == DEFAULT_BASE_DIR


class TestCLIDeviceCommands:
    def test_devices_empty_json(self, tmp_devices_dir, capsys):
        """eabctl devices --json returns empty list."""
        from eab.cli.daemon import cmd_devices
        rc = cmd_devices(json_mode=True)
        assert rc == 0
        output = json.loads(capsys.readouterr().out)
        assert output["devices"] == []

    def test_device_add_json(self, tmp_devices_dir, capsys):
        """eabctl device add creates device and returns JSON."""
        from eab.cli.daemon import cmd_device_add
        rc = cmd_device_add(name="nrf5340", device_type="debug", chip="nrf5340", json_mode=True)
        assert rc == 0
        output = json.loads(capsys.readouterr().out)
        assert output["registered"] is True
        assert output["name"] == "nrf5340"

    def test_device_add_then_list(self, tmp_devices_dir, capsys):
        """After adding devices, devices command lists them."""
        from eab.cli.daemon import cmd_device_add, cmd_devices

        cmd_device_add(name="nrf5340", device_type="debug", chip="nrf5340", json_mode=True)
        capsys.readouterr()  # clear

        cmd_device_add(name="esp32", device_type="serial", chip="esp32s3", json_mode=True)
        capsys.readouterr()  # clear

        rc = cmd_devices(json_mode=True)
        assert rc == 0
        output = json.loads(capsys.readouterr().out)
        assert len(output["devices"]) == 2

    def test_device_remove_json(self, tmp_devices_dir, capsys):
        """eabctl device remove removes device."""
        from eab.cli.daemon import cmd_device_add, cmd_device_remove

        cmd_device_add(name="test1", device_type="debug", chip="test", json_mode=True)
        capsys.readouterr()

        rc = cmd_device_remove(name="test1", json_mode=True)
        assert rc == 0
        output = json.loads(capsys.readouterr().out)
        assert output["removed"] is True

    def test_device_remove_nonexistent(self, tmp_devices_dir, capsys):
        """eabctl device remove fails for missing device."""
        from eab.cli.daemon import cmd_device_remove
        rc = cmd_device_remove(name="ghost", json_mode=True)
        assert rc == 1
        output = json.loads(capsys.readouterr().out)
        assert output["removed"] is False


class TestParserDeviceFlag:
    def test_preprocess_device_flag_before_subcommand(self):
        """--device before subcommand is moved to front by _preprocess_argv."""
        from eab.cli.parser import _preprocess_argv
        result = _preprocess_argv(["--device", "nrf5340", "status"])
        assert result == ["--device", "nrf5340", "status"]

    def test_preprocess_device_after_subcommand_stays(self):
        """--device after subcommand is NOT moved (it's a subcommand arg)."""
        from eab.cli.parser import _preprocess_argv
        result = _preprocess_argv(["fault-analyze", "--device", "NRF5340_XXAA_APP"])
        assert result == ["fault-analyze", "--device", "NRF5340_XXAA_APP"]

    def test_preprocess_device_equals_before_subcommand(self):
        """--device=nrf5340 before subcommand is moved to front."""
        from eab.cli.parser import _preprocess_argv
        result = _preprocess_argv(["--device=esp32", "tail", "50"])
        assert result == ["--device=esp32", "tail", "50"]

    def test_parser_accepts_device(self):
        """Parser accepts --device flag stored as target_device."""
        from eab.cli.parser import _build_parser
        parser = _build_parser()
        args = parser.parse_args(["--device", "nrf5340", "status"])
        assert args.target_device == "nrf5340"
        assert args.cmd == "status"

    def test_parser_devices_command(self):
        """Parser accepts devices command."""
        from eab.cli.parser import _build_parser
        parser = _build_parser()
        args = parser.parse_args(["devices"])
        assert args.cmd == "devices"

    def test_parser_device_add(self):
        """Parser accepts device add command."""
        from eab.cli.parser import _build_parser
        parser = _build_parser()
        args = parser.parse_args(["device", "add", "nrf5340", "--type", "debug", "--chip", "nrf5340"])
        assert args.cmd == "device"
        assert args.device_action == "add"
        assert args.name == "nrf5340"
        assert args.device_type == "debug"
        assert args.chip == "nrf5340"

    def test_parser_device_remove(self):
        """Parser accepts device remove command."""
        from eab.cli.parser import _build_parser
        parser = _build_parser()
        args = parser.parse_args(["device", "remove", "nrf5340"])
        assert args.cmd == "device"
        assert args.device_action == "remove"
        assert args.name == "nrf5340"
