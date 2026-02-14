#!/usr/bin/env python3
"""
Singleton Daemon Enforcement for Embedded Agent Bridge.

Ensures only one EAB daemon runs per machine using a PID file with portalocker.
"""

import os
import sys
import errno
import portalocker
import atexit
import signal
from typing import Optional
from dataclasses import dataclass


DEFAULT_DEVICES_DIR = os.path.join(os.environ.get("EAB_RUN_DIR", "/tmp"), "eab-devices")


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

    def __init__(self, logger=None, device_name: str = ""):
        self._logger = logger
        self._lock_fd: Optional[int] = None
        self._owns_lock = False
        self._device_name = device_name

        if device_name:
            # Per-device mode: PID/info files inside device session dir
            device_dir = os.path.join(DEFAULT_DEVICES_DIR, device_name)
            self.PID_FILE = os.path.join(device_dir, "daemon.pid")
            self.INFO_FILE = os.path.join(device_dir, "daemon.info")
        else:
            # Legacy global singleton mode
            self.PID_FILE = self.LEGACY_PID_FILE
            self.INFO_FILE = self.LEGACY_INFO_FILE

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
        if not os.path.exists(self.PID_FILE):
            return None

        try:
            with open(self.PID_FILE, 'r') as f:
                pid = int(f.read().strip())
        except (ValueError, IOError):
            return None

        # Check if process is alive
        is_alive = self._is_process_alive(pid)

        # Read info file if exists
        port = "unknown"
        base_dir = "unknown"
        started = "unknown"
        device_name = self._device_name
        device_type = "serial"
        chip = ""

        if os.path.exists(self.INFO_FILE):
            try:
                with open(self.INFO_FILE, 'r') as f:
                    for line in f:
                        key_val = line.strip().split("=", 1)
                        if len(key_val) != 2:
                            continue
                        key, val = key_val
                        if key == "port":
                            port = val
                        elif key == "base_dir":
                            base_dir = val
                        elif key == "started":
                            started = val
                        elif key == "device_name":
                            device_name = val
                        elif key == "type":
                            device_type = val
                        elif key == "chip":
                            chip = val
            except IOError:
                pass

        return ExistingDaemon(
            pid=pid,
            is_alive=is_alive,
            port=port,
            base_dir=base_dir,
            started=started,
            device_name=device_name,
            device_type=device_type,
            chip=chip,
        )

    def _is_process_alive(self, pid: int) -> bool:
        """Check if a process is still running."""
        try:
            os.kill(pid, 0)
            return True
        except ProcessLookupError:
            return False
        except PermissionError:
            # Some sandboxed environments disallow signaling other processes
            # (even with signal 0). Treat this as "unknown but likely alive"
            # so higher-level coordination can fall back to file-based control.
            return True
        except OSError as e:
            if getattr(e, "errno", None) == errno.EPERM:
                return True
            return False

    def _kill_process(self, pid: int, timeout: float = 5.0) -> bool:
        """Kill a process and wait for it to die."""
        import time

        if not self._is_process_alive(pid):
            return True

        # Try SIGTERM first
        try:
            os.kill(pid, signal.SIGTERM)
        except OSError:
            return True

        # Wait for process to die
        start = time.time()
        while time.time() - start < timeout:
            if not self._is_process_alive(pid):
                return True
            time.sleep(0.1)

        # Force kill with SIGKILL
        try:
            os.kill(pid, signal.SIGKILL)
            time.sleep(0.5)
        except OSError:
            pass

        return not self._is_process_alive(pid)

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
        from datetime import datetime
        try:
            with open(self.INFO_FILE, 'w') as f:
                f.write(f"pid={os.getpid()}\n")
                f.write(f"port={port}\n")
                f.write(f"base_dir={base_dir}\n")
                f.write(f"started={datetime.now().isoformat()}\n")
                f.write(f"device_name={self._device_name}\n")
                f.write(f"type={device_type}\n")
                f.write(f"chip={chip}\n")
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


def list_devices() -> list[ExistingDaemon]:
    """Scan /tmp/eab-devices/ for all registered devices.

    Returns a list of ExistingDaemon objects, one per device directory
    that contains a daemon.info file.
    """
    devices: list[ExistingDaemon] = []
    if not os.path.isdir(DEFAULT_DEVICES_DIR):
        return devices

    for name in sorted(os.listdir(DEFAULT_DEVICES_DIR)):
        device_dir = os.path.join(DEFAULT_DEVICES_DIR, name)
        info_file = os.path.join(device_dir, "daemon.info")
        if not os.path.isfile(info_file):
            continue

        singleton = SingletonDaemon(device_name=name)
        existing = singleton.get_existing()
        if existing:
            # get_existing returns None if no PID file — for debug-only devices
            # we still want to list them, so handle that below
            devices.append(existing)
        else:
            # No PID file but daemon.info exists (debug-only device, never started a daemon)
            # Parse info file directly
            port = ""
            base_dir = device_dir
            started = ""
            device_type = "debug"
            chip = ""
            try:
                with open(info_file, 'r') as f:
                    for line in f:
                        key_val = line.strip().split("=", 1)
                        if len(key_val) != 2:
                            continue
                        key, val = key_val
                        if key == "port":
                            port = val
                        elif key == "base_dir":
                            base_dir = val
                        elif key == "started":
                            started = val
                        elif key == "type":
                            device_type = val
                        elif key == "chip":
                            chip = val
            except IOError:
                pass

            devices.append(ExistingDaemon(
                pid=0,
                is_alive=False,
                port=port,
                base_dir=base_dir,
                started=started,
                device_name=name,
                device_type=device_type,
                chip=chip,
            ))

    return devices


def register_device(name: str, device_type: str = "debug", chip: str = "") -> str:
    """Register a device (creates session dir and daemon.info without starting a daemon).

    Args:
        name: Device name (e.g., 'nrf5340').
        device_type: 'serial' or 'debug'.
        chip: Chip identifier (e.g., 'nrf5340', 'stm32l476rg').

    Returns:
        Path to the device session directory.
    """
    from datetime import datetime
    device_dir = os.path.join(DEFAULT_DEVICES_DIR, name)
    os.makedirs(device_dir, exist_ok=True)

    info_file = os.path.join(device_dir, "daemon.info")
    with open(info_file, 'w') as f:
        f.write(f"pid=0\n")
        f.write(f"port=\n")
        f.write(f"base_dir={device_dir}\n")
        f.write(f"started={datetime.now().isoformat()}\n")
        f.write(f"device_name={name}\n")
        f.write(f"type={device_type}\n")
        f.write(f"chip={chip}\n")

    return device_dir


def unregister_device(name: str) -> bool:
    """Unregister a device (removes session dir).

    Refuses to remove if a daemon is still running for this device.

    Args:
        name: Device name.

    Returns:
        True if removed, False if device not found or daemon still running.
    """
    import shutil
    device_dir = os.path.join(DEFAULT_DEVICES_DIR, name)
    if not os.path.isdir(device_dir):
        return False

    # Check if daemon is still running
    existing = check_singleton(device_name=name)
    if existing and existing.is_alive:
        return False

    shutil.rmtree(device_dir, ignore_errors=True)
    return True
