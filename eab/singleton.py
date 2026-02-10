#!/usr/bin/env python3
"""
Singleton Daemon Enforcement for Embedded Agent Bridge.

Ensures only one EAB daemon runs per machine using a PID file with flock.
"""

import os
import sys
import errno
import fcntl
import atexit
import signal
from typing import Optional
from dataclasses import dataclass


@dataclass
class ExistingDaemon:
    """Information about an existing daemon."""
    pid: int
    is_alive: bool
    port: str
    base_dir: str
    started: str


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

    PID_FILE = os.path.join(os.environ.get("EAB_RUN_DIR", "/tmp"), "eab-daemon.pid")
    INFO_FILE = os.path.join(os.environ.get("EAB_RUN_DIR", "/tmp"), "eab-daemon.info")

    def __init__(self, logger=None):
        self._logger = logger
        self._lock_fd: Optional[int] = None
        self._owns_lock = False

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

        if os.path.exists(self.INFO_FILE):
            try:
                with open(self.INFO_FILE, 'r') as f:
                    for line in f:
                        if line.startswith("port="):
                            port = line.strip().split("=", 1)[1]
                        elif line.startswith("base_dir="):
                            base_dir = line.strip().split("=", 1)[1]
                        elif line.startswith("started="):
                            started = line.strip().split("=", 1)[1]
            except IOError:
                pass

        return ExistingDaemon(
            pid=pid,
            is_alive=is_alive,
            port=port,
            base_dir=base_dir,
            started=started,
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

    def acquire(self, kill_existing: bool = False, port: str = "", base_dir: str = "") -> bool:
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

        # Try to acquire lock
        try:
            self._lock_fd = os.open(self.PID_FILE, os.O_CREAT | os.O_RDWR, 0o644)
            fcntl.flock(self._lock_fd, fcntl.LOCK_EX | fcntl.LOCK_NB)
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
                fcntl.flock(self._lock_fd, fcntl.LOCK_UN)
                os.close(self._lock_fd)
            except OSError:
                pass
            self._lock_fd = None

        try:
            os.unlink(self.PID_FILE)
        except OSError:
            pass

        self._log("Released singleton lock")


def check_singleton() -> Optional[ExistingDaemon]:
    """Quick check if a daemon is already running."""
    return SingletonDaemon().get_existing()


def kill_existing_daemon(timeout: float = 5.0) -> bool:
    """Kill any existing daemon."""
    singleton = SingletonDaemon()
    existing = singleton.get_existing()

    if not existing:
        return True

    if not existing.is_alive:
        # Clean up stale files
        try:
            os.unlink(SingletonDaemon.PID_FILE)
            os.unlink(SingletonDaemon.INFO_FILE)
        except OSError:
            pass
        return True

    return singleton._kill_process(existing.pid, timeout)
