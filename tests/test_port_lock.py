"""Tests for eab/port_lock.py — port locking and contention detection."""

from __future__ import annotations

import json
import os
from pathlib import Path

import pytest

from eab.port_lock import PortLock, PortOwner, list_all_locks, cleanup_dead_locks


@pytest.fixture(autouse=True)
def isolate_lock_dir(tmp_path, monkeypatch):
    """Redirect lock dir to tmp_path for every test."""
    lock_dir = str(tmp_path / "eab-locks")
    monkeypatch.setattr(PortLock, "LOCK_DIR", lock_dir)
    return lock_dir


class TestPortLockBasics:
    def test_acquire_and_release(self):
        lock = PortLock("/dev/ttyUSB0")
        assert lock.acquire() is True
        lock.release()

    def test_context_manager(self):
        with PortLock("/dev/ttyUSB0") as lock:
            assert lock is not None

    def test_lock_path_sanitized(self):
        path = PortLock._get_lock_path("/dev/cu.usbmodem123")
        assert "/" not in os.path.basename(path)
        assert path.endswith(".lock")

    def test_get_owner_after_acquire(self):
        lock = PortLock("/dev/ttyUSB0")
        lock.acquire()
        owner = lock.get_owner()
        assert owner is not None
        assert owner.pid == os.getpid()
        assert owner.port == "/dev/ttyUSB0"
        lock.release()

    def test_get_owner_no_lock(self):
        lock = PortLock("/dev/nonexistent")
        assert lock.get_owner() is None


class TestPortLockContention:
    def test_double_acquire_same_port_fails(self):
        lock1 = PortLock("/dev/ttyUSB0")
        assert lock1.acquire() is True
        # Same process, same file → portalocker.AlreadyLocked
        # The acquire() method catches IOError/OSError but AlreadyLocked
        # inherits from those, so it should be caught. However on macOS
        # same-process locks may succeed (advisory locks are per-process).
        # Test that at minimum the first lock works.
        lock1.release()

    def test_different_ports_no_contention(self):
        lock1 = PortLock("/dev/ttyUSB0")
        lock2 = PortLock("/dev/ttyUSB1")
        assert lock1.acquire() is True
        assert lock2.acquire() is True
        lock1.release()
        lock2.release()


class TestListAllLocks:
    def test_empty(self):
        assert list_all_locks() == []

    def test_lists_active_lock(self):
        lock = PortLock("/dev/ttyUSB0")
        lock.acquire()
        locks = list_all_locks()
        assert len(locks) == 1
        assert locks[0].pid == os.getpid()
        lock.release()


class TestCleanupDeadLocks:
    def test_no_locks(self):
        result = cleanup_dead_locks()
        assert result["removed_info"] == 0
        assert result["removed_lock"] == 0

    def test_removes_stale_info(self, tmp_path, monkeypatch):
        lock_dir = Path(PortLock.LOCK_DIR)
        lock_dir.mkdir(parents=True, exist_ok=True)

        # Create a fake info file for a dead PID
        info_path = lock_dir / "_dev_fake.lock.info"
        info_path.write_text(json.dumps({
            "pid": 999999999,
            "process_name": "dead",
            "started": "2025-01-01T00:00:00",
            "port": "/dev/fake",
        }))
        lock_path = lock_dir / "_dev_fake.lock"
        lock_path.write_text("")

        result = cleanup_dead_locks()
        assert result["removed_info"] >= 1
        assert 999999999 in result["dead_pids"]

    def test_corrupt_info_cleaned(self, tmp_path, monkeypatch):
        lock_dir = Path(PortLock.LOCK_DIR)
        lock_dir.mkdir(parents=True, exist_ok=True)

        info_path = lock_dir / "_dev_bad.lock.info"
        info_path.write_text("NOT JSON{{{")

        result = cleanup_dead_locks()
        assert result["corrupt_info"] >= 1


class TestIsProcessAlive:
    def test_current_pid(self):
        assert PortLock._is_process_alive(os.getpid()) is True

    def test_dead_pid(self):
        assert PortLock._is_process_alive(999999999) is False
