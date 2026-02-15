"""Shared process-management utilities for EAB.

Extracted from duplicated patterns in jlink_bridge, openocd_bridge,
debug_probes/openocd, and singleton.
"""

from __future__ import annotations

import errno
import os
import signal
import subprocess
import time
from pathlib import Path
from typing import Optional, Union


def pid_alive(pid: int) -> bool:
    """Check if a process is alive via ``os.kill(pid, 0)``.

    Returns ``True`` if the process exists (even if we lack permission to
    signal it), ``False`` otherwise.
    """
    try:
        os.kill(pid, 0)
        return True
    except ProcessLookupError:
        return False
    except PermissionError:
        # Can't signal it, but it exists.
        return True
    except OSError as exc:
        if getattr(exc, "errno", None) == errno.EPERM:
            return True
        return False


def read_pid_file(path: Union[str, Path]) -> Optional[int]:
    """Read a PID from *path*, returning ``None`` on any error."""
    p = Path(path)
    if not p.exists():
        return None
    try:
        return int(p.read_text().strip())
    except (ValueError, OSError):
        return None


def cleanup_pid_file(path: Union[str, Path]) -> None:
    """Remove a PID file if it exists (ignoring errors)."""
    try:
        Path(path).unlink(missing_ok=True)
    except OSError:
        pass


def stop_process_graceful(pid: int, timeout_s: float = 5.0) -> bool:
    """Send SIGTERM, wait up to *timeout_s*, then SIGKILL if still alive.

    Returns ``True`` if the process is no longer alive after the call.
    """
    if not pid_alive(pid):
        return True

    try:
        os.kill(pid, signal.SIGTERM)
    except OSError:
        return True

    deadline = time.time() + timeout_s
    while time.time() < deadline:
        if not pid_alive(pid):
            return True
        time.sleep(0.1)

    # Force-kill
    try:
        os.kill(pid, signal.SIGKILL)
        time.sleep(0.5)
    except OSError:
        pass

    return not pid_alive(pid)


def popen_is_alive(proc: subprocess.Popen) -> bool:
    """Check if a :class:`subprocess.Popen` process is still running."""
    return proc.poll() is None
