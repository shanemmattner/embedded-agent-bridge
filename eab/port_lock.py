#!/usr/bin/env python3
"""
Port Locking Module for Embedded Agent Bridge.

Provides:
- File-based port locking to prevent multiple processes from fighting
- Detection of other processes using the port
- Logging of contention events
"""

import fcntl
import os
import sys
import time
from dataclasses import dataclass
from datetime import datetime
from pathlib import Path
from typing import Optional, List
import json
import errno


@dataclass
class PortOwner:
    """Information about the current port owner."""
    pid: int
    process_name: str
    started: datetime
    port: str
    lock_file: str


class PortLock:
    """
    File-based port lock with contention detection.

    Usage:
        lock = PortLock("/dev/cu.usbmodem123")
        if lock.acquire():
            # Use the port
            lock.release()
        else:
            print(f"Port in use by: {lock.get_owner()}")
    """

    LOCK_DIR = os.path.join(os.environ.get("EAB_RUN_DIR", "/tmp"), "eab-locks")

    def __init__(self, port: str, logger=None):
        self._port = port
        self._logger = logger
        self._lock_fd = None
        self._lock_path = self._get_lock_path(port)
        self._info_path = self._lock_path + ".info"

        # Ensure lock directory exists
        Path(self.LOCK_DIR).mkdir(parents=True, exist_ok=True)

    def _log(self, msg: str) -> None:
        if self._logger:
            self._logger.info(msg)
        else:
            print(f"[PortLock] {msg}")

    def _log_warning(self, msg: str) -> None:
        if self._logger:
            self._logger.warning(msg)
        else:
            print(f"[PortLock] WARNING: {msg}")

    def _log_error(self, msg: str) -> None:
        if self._logger:
            self._logger.error(msg)
        else:
            print(f"[PortLock] ERROR: {msg}")

    @staticmethod
    def _get_lock_path(port: str) -> str:
        """Convert port path to lock file path."""
        # /dev/cu.usbmodem123 -> /tmp/eab-locks/dev_cu.usbmodem123.lock
        safe_name = port.replace("/", "_").replace("\\", "_")
        return os.path.join(PortLock.LOCK_DIR, f"{safe_name}.lock")

    def acquire(self, timeout: float = 0, force: bool = False) -> bool:
        """
        Acquire the port lock.

        Args:
            timeout: How long to wait for lock (0 = no wait)
            force: If True, steal lock from dead processes

        Returns:
            True if lock acquired, False otherwise
        """
        start_time = time.time()

        while True:
            try:
                # Try to open/create lock file
                self._lock_fd = open(self._lock_path, "w")

                # Try non-blocking exclusive lock
                fcntl.flock(self._lock_fd.fileno(), fcntl.LOCK_EX | fcntl.LOCK_NB)

                # Got the lock! Write our info
                self._write_owner_info()
                self._log(f"Acquired lock for {self._port}")
                return True

            except (IOError, OSError) as e:
                # Lock is held by someone else
                if self._lock_fd:
                    self._lock_fd.close()
                    self._lock_fd = None

                owner = self.get_owner()

                # Check if owner process is dead
                if owner and force:
                    if not self._is_process_alive(owner.pid):
                        self._log_warning(f"Stealing lock from dead process {owner.pid}")
                        self._cleanup_stale_lock()
                        continue

                # Check timeout
                elapsed = time.time() - start_time
                if timeout > 0 and elapsed < timeout:
                    time.sleep(0.1)
                    continue

                # Log contention
                if owner:
                    self._log_warning(
                        f"Port {self._port} locked by PID {owner.pid} "
                        f"({owner.process_name}) since {owner.started}"
                    )
                else:
                    self._log_warning(f"Port {self._port} locked by unknown process")

                return False

    def release(self) -> None:
        """Release the port lock."""
        if self._lock_fd:
            try:
                fcntl.flock(self._lock_fd.fileno(), fcntl.LOCK_UN)
                self._lock_fd.close()
            except Exception:
                pass
            self._lock_fd = None

        # Clean up info file
        try:
            if os.path.exists(self._info_path):
                os.unlink(self._info_path)
        except Exception:
            pass

        self._log(f"Released lock for {self._port}")

    def get_owner(self) -> Optional[PortOwner]:
        """Get information about the current lock owner."""
        try:
            if not os.path.exists(self._info_path):
                return None

            with open(self._info_path, "r") as f:
                info = json.load(f)

            return PortOwner(
                pid=info["pid"],
                process_name=info["process_name"],
                started=datetime.fromisoformat(info["started"]),
                port=info["port"],
                lock_file=self._lock_path,
            )
        except Exception:
            return None

    def _write_owner_info(self) -> None:
        """Write owner information to info file."""
        info = {
            "pid": os.getpid(),
            "process_name": self._get_process_name(),
            "started": datetime.now().isoformat(),
            "port": self._port,
        }

        # Atomic write to avoid corrupt JSON on crash.
        tmp_path = f"{self._info_path}.tmp.{os.getpid()}"
        with open(tmp_path, "w") as f:
            json.dump(info, f, indent=2)
        os.replace(tmp_path, self._info_path)

    @staticmethod
    def _get_process_name() -> str:
        """Get the name of the current process."""
        try:
            # Try to get a meaningful name
            if len(sys.argv) > 0:
                return " ".join(sys.argv[:3])[:50]
        except Exception:
            pass
        return f"python:{os.getpid()}"

    @staticmethod
    def _is_process_alive(pid: int) -> bool:
        """Check if a process is still running."""
        try:
            os.kill(pid, 0)
            return True
        except PermissionError:
            # Some environments disallow signaling other processes (even with signal 0).
            # Treat as "unknown but likely alive" to avoid unsafe lock stealing.
            return True
        except ProcessLookupError:
            return False
        except OSError as e:
            if getattr(e, "errno", None) == errno.EPERM:
                return True
            return False

    def _cleanup_stale_lock(self) -> None:
        """Remove stale lock files from dead processes."""
        try:
            if os.path.exists(self._lock_path):
                os.unlink(self._lock_path)
            if os.path.exists(self._info_path):
                os.unlink(self._info_path)
        except Exception:
            pass

    def __enter__(self):
        if not self.acquire():
            raise RuntimeError(f"Could not acquire lock for {self._port}")
        return self

    def __exit__(self, exc_type, exc_val, exc_tb):
        self.release()
        return False


def list_all_locks() -> List[PortOwner]:
    """List all currently held port locks."""
    locks = []
    lock_dir = Path(PortLock.LOCK_DIR)

    if not lock_dir.exists():
        return locks

    for info_file in lock_dir.glob("*.info"):
        try:
            with open(info_file, "r") as f:
                info = json.load(f)

            owner = PortOwner(
                pid=info["pid"],
                process_name=info["process_name"],
                started=datetime.fromisoformat(info["started"]),
                port=info["port"],
                lock_file=str(info_file).replace(".info", ""),
            )

            # Only include if process is still alive
            if PortLock._is_process_alive(owner.pid):
                locks.append(owner)
        except Exception:
            pass

    return locks


def cleanup_dead_locks(*, logger=None) -> dict:
    """Remove lock artifacts for dead processes.

    Safety: we only delete `.lock` files when we can prove the recorded PID is dead.
    If we cannot parse `.info`, we only delete the `.info` file (never the `.lock`),
    because deleting a lock file while a live process holds a flock can cause a second
    process to create a new lock inode and 'double-own' the lock.
    """
    lock_dir = Path(PortLock.LOCK_DIR)
    removed_info = 0
    removed_lock = 0
    corrupt_info = 0
    dead_pids: list[int] = []

    def log(msg: str) -> None:
        if logger:
            try:
                logger.info(msg)
            except Exception:
                pass

    if not lock_dir.exists():
        return {
            "removed_info": 0,
            "removed_lock": 0,
            "corrupt_info": 0,
            "dead_pids": [],
        }

    for info_path in lock_dir.glob("*.lock.info"):
        lock_path = str(info_path).removesuffix(".info")
        try:
            info = json.loads(info_path.read_text(encoding="utf-8", errors="replace"))
            pid = int(info.get("pid", -1))
        except Exception:
            # Corrupt JSON: safe cleanup is to delete only the info file.
            corrupt_info += 1
            try:
                info_path.unlink(missing_ok=True)
                removed_info += 1
                log(f"Removed corrupt lock info: {info_path}")
            except Exception:
                pass
            continue

        if pid > 0 and not PortLock._is_process_alive(pid):
            dead_pids.append(pid)
            # Remove info first.
            try:
                info_path.unlink(missing_ok=True)
                removed_info += 1
            except Exception:
                pass

            # Only now safe to remove the lock file (no process holds the lock anymore).
            try:
                os.unlink(lock_path)
                removed_lock += 1
            except Exception:
                pass

    return {
        "removed_info": removed_info,
        "removed_lock": removed_lock,
        "corrupt_info": corrupt_info,
        "dead_pids": dead_pids,
    }


def find_port_users(port: str) -> List[dict]:
    """
    Find all processes that might be using a serial port.

    Returns list of dicts with pid, name, cmdline.
    """
    users = []

    try:
        import subprocess

        # Use lsof to find processes with the port open
        result = subprocess.run(
            ["lsof", port],
            capture_output=True,
            text=True,
            timeout=5,
        )

        if result.returncode == 0:
            lines = result.stdout.strip().split("\n")
            # Skip header line
            for line in lines[1:]:
                parts = line.split()
                if len(parts) >= 2:
                    users.append({
                        "name": parts[0],
                        "pid": int(parts[1]),
                        "cmdline": " ".join(parts),
                    })
    except Exception:
        pass

    return users


def kill_port_users(port: str, signal: int = 15) -> List[int]:
    """
    Kill all processes using a port.

    Args:
        port: Serial port path
        signal: Signal to send (15=SIGTERM, 9=SIGKILL)

    Returns:
        List of PIDs that were signaled
    """
    killed = []
    users = find_port_users(port)

    for user in users:
        pid = user["pid"]
        if pid != os.getpid():  # Don't kill ourselves
            try:
                os.kill(pid, signal)
                killed.append(pid)
            except Exception:
                pass

    return killed
