"""Tests for eab/device_registry.py — device registration and listing."""

from __future__ import annotations

import os
from pathlib import Path
from unittest.mock import patch

import pytest

from eab.device_registry import (
    _get_devices_dir,
    _parse_info_file,
    _write_info_file,
    _info_to_existing,
    list_devices,
    register_device,
    unregister_device,
)
from eab.singleton import ExistingDaemon


class TestGetDevicesDir:
    def test_default_returns_tmp_eab_devices(self, monkeypatch):
        monkeypatch.delenv("EAB_RUN_DIR", raising=False)
        assert _get_devices_dir() == "/tmp/eab-devices"

    def test_env_override(self, monkeypatch):
        monkeypatch.setenv("EAB_RUN_DIR", "/custom/run")
        assert _get_devices_dir() == "/custom/run/eab-devices"


class TestParseInfoFile:
    def test_valid_file(self, tmp_path):
        info = tmp_path / "daemon.info"
        info.write_text("pid=1234\nport=/dev/ttyUSB0\ntype=serial\nchip=nrf5340\n")
        result = _parse_info_file(str(info))
        assert result["pid"] == "1234"
        assert result["port"] == "/dev/ttyUSB0"
        assert result["type"] == "serial"
        assert result["chip"] == "nrf5340"

    def test_missing_file_returns_empty(self, tmp_path):
        result = _parse_info_file(str(tmp_path / "nonexistent"))
        assert result == {}

    def test_corrupt_file_skips_bad_lines(self, tmp_path):
        info = tmp_path / "daemon.info"
        info.write_text("pid=1234\nbad line no equals\nchip=stm32\n")
        result = _parse_info_file(str(info))
        assert result["pid"] == "1234"
        assert result["chip"] == "stm32"
        assert len(result) == 2

    def test_value_with_equals(self, tmp_path):
        info = tmp_path / "daemon.info"
        info.write_text("base_dir=/tmp/path=with=equals\n")
        result = _parse_info_file(str(info))
        assert result["base_dir"] == "/tmp/path=with=equals"


class TestWriteInfoFile:
    def test_writes_all_fields(self, tmp_path):
        path = str(tmp_path / "daemon.info")
        _write_info_file(path, pid=42, port="/dev/tty0", base_dir="/tmp/s",
                         device_name="nrf", device_type="debug", chip="nrf5340")
        result = _parse_info_file(path)
        assert result["pid"] == "42"
        assert result["port"] == "/dev/tty0"
        assert result["base_dir"] == "/tmp/s"
        assert result["device_name"] == "nrf"
        assert result["type"] == "debug"
        assert result["chip"] == "nrf5340"
        assert "started" in result

    def test_defaults(self, tmp_path):
        path = str(tmp_path / "daemon.info")
        _write_info_file(path)
        result = _parse_info_file(path)
        assert result["pid"] == "0"
        assert result["type"] == "debug"


class TestInfoToExisting:
    def test_builds_existing_daemon(self):
        info = {"port": "/dev/tty0", "base_dir": "/tmp/x", "started": "2025-01-01",
                "type": "serial", "chip": "esp32"}
        ed = _info_to_existing(info, name="mydev", device_dir="/tmp/fallback")
        assert ed.pid == 0
        assert ed.is_alive is False
        assert ed.port == "/dev/tty0"
        assert ed.base_dir == "/tmp/x"
        assert ed.device_name == "mydev"
        assert ed.device_type == "serial"
        assert ed.chip == "esp32"

    def test_missing_fields_use_defaults(self):
        ed = _info_to_existing({}, name="dev1", device_dir="/fallback")
        assert ed.port == ""
        assert ed.base_dir == "/fallback"
        assert ed.device_type == "debug"


class TestListDevices:
    def test_empty_dir(self, tmp_path, monkeypatch):
        monkeypatch.setenv("EAB_RUN_DIR", str(tmp_path))
        devices_dir = tmp_path / "eab-devices"
        devices_dir.mkdir()
        assert list_devices() == []

    def test_nonexistent_dir(self, tmp_path, monkeypatch):
        monkeypatch.setenv("EAB_RUN_DIR", str(tmp_path))
        assert list_devices() == []

    def test_device_without_info_skipped(self, tmp_path, monkeypatch):
        monkeypatch.setenv("EAB_RUN_DIR", str(tmp_path))
        devices_dir = tmp_path / "eab-devices"
        (devices_dir / "orphan").mkdir(parents=True)
        assert list_devices() == []

    def test_lists_registered_devices(self, tmp_path, monkeypatch):
        monkeypatch.setenv("EAB_RUN_DIR", str(tmp_path))
        register_device("nrf5340", device_type="debug", chip="nrf5340")
        register_device("esp32", device_type="serial", chip="esp32c6")
        devices = list_devices()
        names = sorted(d.device_name for d in devices)
        assert names == ["esp32", "nrf5340"]


class TestRegisterDevice:
    def test_creates_dir_and_info(self, tmp_path, monkeypatch):
        monkeypatch.setenv("EAB_RUN_DIR", str(tmp_path))
        path = register_device("test1", device_type="debug", chip="nrf5340")
        assert os.path.isdir(path)
        info = _parse_info_file(os.path.join(path, "daemon.info"))
        assert info["device_name"] == "test1"
        assert info["type"] == "debug"
        assert info["chip"] == "nrf5340"

    def test_idempotent_register(self, tmp_path, monkeypatch):
        monkeypatch.setenv("EAB_RUN_DIR", str(tmp_path))
        p1 = register_device("x", chip="a")
        p2 = register_device("x", chip="b")
        assert p1 == p2
        info = _parse_info_file(os.path.join(p2, "daemon.info"))
        assert info["chip"] == "b"  # overwrites


class TestUnregisterDevice:
    def test_removes_existing(self, tmp_path, monkeypatch):
        monkeypatch.setenv("EAB_RUN_DIR", str(tmp_path))
        path = register_device("gone")
        assert os.path.isdir(path)
        assert unregister_device("gone") is True
        assert not os.path.isdir(path)

    def test_missing_returns_false(self, tmp_path, monkeypatch):
        monkeypatch.setenv("EAB_RUN_DIR", str(tmp_path))
        assert unregister_device("noexist") is False

    def test_refuses_if_alive(self, tmp_path, monkeypatch):
        monkeypatch.setenv("EAB_RUN_DIR", str(tmp_path))
        register_device("alive")
        # Fake a running daemon — check_singleton is imported inside the function
        from eab import singleton as singleton_mod
        monkeypatch.setattr(
            singleton_mod, "check_singleton",
            lambda device_name="": ExistingDaemon(
                pid=1, is_alive=True, port="", base_dir="", started="",
                device_name=device_name,
            ),
        )
        assert unregister_device("alive") is False
