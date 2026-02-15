"""Tests for eab/singleton.py — singleton daemon enforcement."""

from __future__ import annotations

import os
from unittest.mock import patch

import pytest

from eab.singleton import SingletonDaemon, ExistingDaemon, check_singleton


class TestSingletonDaemonInit:
    def test_default_device_paths(self, tmp_path, monkeypatch):
        monkeypatch.setenv("EAB_RUN_DIR", str(tmp_path))
        s = SingletonDaemon()
        # Default device: PID/INFO at eab-devices/default/
        assert "default" in s.PID_FILE
        assert s.PID_FILE.endswith("daemon.pid")
        assert s.INFO_FILE.endswith("daemon.info")

    def test_device_mode_paths(self, tmp_path, monkeypatch):
        monkeypatch.setenv("EAB_RUN_DIR", str(tmp_path))
        s = SingletonDaemon(device_name="nrf")
        assert "nrf" in s.PID_FILE
        assert s.PID_FILE.endswith("daemon.pid")
        assert s.INFO_FILE.endswith("daemon.info")


class TestGetExisting:
    def test_no_pid_file_returns_none(self, tmp_path, monkeypatch):
        monkeypatch.setenv("EAB_RUN_DIR", str(tmp_path))
        s = SingletonDaemon()
        assert s.get_existing() is None

    def test_stale_pid_file(self, tmp_path, monkeypatch):
        monkeypatch.setenv("EAB_RUN_DIR", str(tmp_path))
        s = SingletonDaemon()
        os.makedirs(os.path.dirname(s.PID_FILE), exist_ok=True)
        with open(s.PID_FILE, "w") as f:
            f.write("999999999\n")  # Non-existent PID
        existing = s.get_existing()
        assert existing is not None
        assert existing.is_alive is False

    def test_corrupt_pid_file(self, tmp_path, monkeypatch):
        monkeypatch.setenv("EAB_RUN_DIR", str(tmp_path))
        s = SingletonDaemon()
        os.makedirs(os.path.dirname(s.PID_FILE), exist_ok=True)
        with open(s.PID_FILE, "w") as f:
            f.write("not_a_number\n")
        assert s.get_existing() is None


class TestIsProcessAlive:
    def test_current_process_is_alive(self):
        s = SingletonDaemon()
        assert s._is_process_alive(os.getpid()) is True

    def test_nonexistent_pid(self):
        s = SingletonDaemon()
        assert s._is_process_alive(999999999) is False


class TestAcquireRelease:
    def test_acquire_and_release(self, tmp_path, monkeypatch):
        monkeypatch.setenv("EAB_RUN_DIR", str(tmp_path))
        s = SingletonDaemon()
        assert s.acquire(port="/dev/test", base_dir=str(tmp_path)) is True
        assert os.path.exists(s.PID_FILE)
        assert os.path.exists(s.INFO_FILE)
        s.release()
        assert not os.path.exists(s.PID_FILE)

    def test_acquire_removes_stale(self, tmp_path, monkeypatch):
        monkeypatch.setenv("EAB_RUN_DIR", str(tmp_path))
        s = SingletonDaemon()
        os.makedirs(os.path.dirname(s.PID_FILE), exist_ok=True)
        with open(s.PID_FILE, "w") as f:
            f.write("999999999\n")
        assert s.acquire(port="test") is True
        s.release()

    def test_acquire_refuses_if_alive(self, tmp_path, monkeypatch):
        monkeypatch.setenv("EAB_RUN_DIR", str(tmp_path))
        s = SingletonDaemon()
        os.makedirs(os.path.dirname(s.PID_FILE), exist_ok=True)
        with open(s.PID_FILE, "w") as f:
            f.write(f"{os.getpid()}\n")
        s2 = SingletonDaemon()
        # Can't acquire because current PID is "alive"
        assert s2.acquire() is False

    def test_per_device_acquire(self, tmp_path, monkeypatch):
        monkeypatch.setenv("EAB_RUN_DIR", str(tmp_path))
        s = SingletonDaemon(device_name="dev1")
        assert s.acquire(port="/dev/test") is True
        assert "dev1" in s.PID_FILE
        s.release()


class TestCheckSingleton:
    def test_no_daemon(self, tmp_path, monkeypatch):
        monkeypatch.setenv("EAB_RUN_DIR", str(tmp_path))
        assert check_singleton() is None

    def test_with_device_name(self, tmp_path, monkeypatch):
        monkeypatch.setenv("EAB_RUN_DIR", str(tmp_path))
        assert check_singleton(device_name="nrf") is None
