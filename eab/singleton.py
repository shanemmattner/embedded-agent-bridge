#!/usr/bin/env python3
"""
Singleton Daemon Enforcement for Embedded Agent Bridge.

Ensures only one EAB daemon runs per machine using a PID file with portalocker.
"""

from __future__ import annotations

import os
import sys
import portalocker
import atexit
from typing import Optional
from dataclasses import dataclass

from .process_utils import pid_alive, read_pid_file, stop_process_graceful


@dataclass
class ExistingDaemon:
    """Information about an existing daemon."""
    pid: int
    is_alive: bool
    port: str
    base_dir: str
    started: str
    device_name: str = ""
    device_type: str = "serial"
    chip: str = ""


class SingletonDaemon:
    """
    Ensures only one EAB daemon runs at a time.

    Uses a PID file with exclusive flock for atomic locking.
    Provides options to:
    - Check if another daemon is running
    - Kill existing daemon and take over
    - Gracefully refuse to start

    Usage:
        singleton = SingletonDaemon()

        # Check and optionally take over
        if not singleton.acquire(kill_existing=True):
            print("Could not acquire singleton lock")
            sys.exit(1)

        # ... run daemon ...

        # Cleanup on exit (automatic via atexit)
    """

    # Legacy global singleton paths (backward compat)
    LEGACY_PID_FILE = os.path.join(os.environ.get("EAB_RUN_DIR", "/tmp"), "eab-daemon.pid")
    LEGACY_INFO_FILE = os.path.join(os.environ.get("EAB_RUN_DIR", "/tmp"), "eab-daemon.info")

    def __init__(self, logger: object = None, device_name: str = "default"):
        self._logger = logger
        self._lock_fd: Optional[int] = None
        self._owns_lock = False
        self._device_name = device_name

        # Always per-device: PID/info files inside device session dir
        from eab.device_registry import _get_devices_dir
        device_dir = os.path.join(_get_devices_dir(), device_name)
        self.PID_FILE = os.path.join(device_dir, "daemon.pid")
        self.INFO_FILE = os.path.join(device_dir, "daemon.info")

    def _log(self, msg: str) -> None:
        if self._logger:
            self._logger.info(f"[Singleton] {msg}")
        else:
            print(f"[Singleton] {msg}")

    def _log_warning(self, msg: str) -> None:
        if self._logger:
            self._logger.warning(f"[Singleton] {msg}")
        else:
            print(f"[Singleton] WARNING: {msg}")

    def _log_error(self, msg: str) -> None:
        if self._logger:
            self._logger.error(f"[Singleton] {msg}")
        else:
            print(f"[Singleton] ERROR: {msg}", file=sys.stderr)

    def get_existing(self) -> Optional[ExistingDaemon]:
        """Check if another daemon is already running."""
        pid = read_pid_file(self.PID_FILE)
        if pid is None:
            return None

        # Check if process is alive
        is_alive = self._is_process_alive(pid)

        # Read info file if exists
        from eab.device_registry import _parse_info_file
        info = _parse_info_file(self.INFO_FILE) if os.path.exists(self.INFO_FILE) else {}

        return ExistingDaemon(
            pid=pid,
            is_alive=is_alive,
            port=info.get("port", "unknown"),
            base_dir=info.get("base_dir", "unknown"),
            started=info.get("started", "unknown"),
            device_name=info.get("device_name", self._device_name),
            device_type=info.get("type", "serial"),
            chip=info.get("chip", ""),
        )

    def _is_process_alive(self, pid: int) -> bool:
        """Check if a process is still running."""
        return pid_alive(pid)

    def _kill_process(self, pid: int, timeout: float = 5.0) -> bool:
        """Kill a process and wait for it to die."""
        return stop_process_graceful(pid, timeout)

    def acquire(self, kill_existing: bool = False, port: str = "", base_dir: str = "",
                device_type: str = "serial", chip: str = "") -> bool:
        """
        Acquire the singleton lock.

        Args:
            kill_existing: If True, kill any existing daemon first
            port: Serial port being used (for info file)
            base_dir: Base directory (for info file)

        Returns:
            True if lock acquired, False otherwise
        """
        existing = self.get_existing()

        if existing:
            if existing.is_alive:
                if kill_existing:
                    self._log_warning(f"Killing existing daemon (PID {existing.pid})...")
                    if not self._kill_process(existing.pid):
                        self._log_error(f"Could not kill existing daemon (PID {existing.pid})")
                        return False
                    self._log(f"Killed existing daemon")
                else:
                    self._log_error(
                        f"Another EAB daemon is already running:\n"
                        f"  PID: {existing.pid}\n"
                        f"  Port: {existing.port}\n"
                        f"  Base dir: {existing.base_dir}\n"
                        f"  Started: {existing.started}\n"
                        f"Use --force to kill it and take over."
                    )
                    return False
            else:
                # Stale PID file
                self._log(f"Removing stale PID file (PID {existing.pid} not running)")
                try:
                    os.unlink(self.PID_FILE)
                except OSError:
                    pass

        # Ensure parent directory exists (for per-device mode)
        os.makedirs(os.path.dirname(self.PID_FILE), exist_ok=True)

        # Try to acquire lock
        try:
            self._lock_fd = os.open(self.PID_FILE, os.O_CREAT | os.O_RDWR, 0o644)
            portalocker.lock(self._lock_fd, portalocker.LOCK_EX | portalocker.LOCK_NB)
        except (OSError, IOError) as e:
            self._log_error(f"Could not acquire lock: {e}")
            if self._lock_fd:
                os.close(self._lock_fd)
                self._lock_fd = None
            return False

        # Write our PID
        os.ftruncate(self._lock_fd, 0)
        os.write(self._lock_fd, f"{os.getpid()}\n".encode())
        os.fsync(self._lock_fd)

        # Write info file
        from eab.device_registry import _write_info_file
        try:
            _write_info_file(
                self.INFO_FILE,
                pid=os.getpid(),
                port=port,
                base_dir=base_dir,
                device_name=self._device_name,
                device_type=device_type,
                chip=chip,
            )
        except IOError as e:
            self._log_warning(f"Could not write info file: {e}")

        self._owns_lock = True

        # Register cleanup
        atexit.register(self.release)

        self._log(f"Acquired singleton lock (PID {os.getpid()})")
        return True

    def release(self) -> None:
        """Release the singleton lock."""
        if not self._owns_lock:
            return

        self._owns_lock = False

        # Remove info file
        try:
            os.unlink(self.INFO_FILE)
        except OSError:
            pass

        # Release lock and remove PID file
        if self._lock_fd:
            try:
                portalocker.unlock(self._lock_fd)
                os.close(self._lock_fd)
            except OSError:
                pass
            self._lock_fd = None

        try:
            os.unlink(self.PID_FILE)
        except OSError:
            pass

        self._log("Released singleton lock")


def check_singleton(device_name: str = "") -> Optional[ExistingDaemon]:
    """Quick check if a daemon is already running.

    Args:
        device_name: If set, check for a per-device daemon. Otherwise check legacy global.
    """
    return SingletonDaemon(device_name=device_name).get_existing()


def kill_existing_daemon(timeout: float = 5.0, device_name: str = "") -> bool:
    """Kill any existing daemon.

    Args:
        timeout: Seconds to wait for process to die.
        device_name: If set, kill the per-device daemon. Otherwise kill legacy global.
    """
    singleton = SingletonDaemon(device_name=device_name)
    existing = singleton.get_existing()

    if not existing:
        return True

    if not existing.is_alive:
        # Clean up stale files
        try:
            os.unlink(singleton.PID_FILE)
            os.unlink(singleton.INFO_FILE)
        except OSError:
            pass
        return True

    return singleton._kill_process(existing.pid, timeout)



# Backward-compat re-exports — callers should migrate to eab.device_registry
from eab.device_registry import (  # noqa: F401, E402
    list_devices,
    register_device,
    unregister_device,
    _get_devices_dir,
)
