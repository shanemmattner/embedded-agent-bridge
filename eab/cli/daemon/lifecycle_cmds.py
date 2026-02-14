"""Daemon lifecycle commands - start, stop, pause, resume."""

from __future__ import annotations

import json
import os
import signal
import subprocess
import sys
import time

from eab.singleton import check_singleton, kill_existing_daemon
from eab.port_lock import list_all_locks, cleanup_dead_locks

from eab.cli.helpers import _now_iso, _print
from eab.cli.daemon._helpers import _clear_session_files


def cmd_start(
    *,
    base_dir: str,
    port: str,
    baud: int,
    force: bool,
    json_mode: bool,
    log_max_size_mb: int = 100,
    log_max_files: int = 5,
    log_compress: bool = True,
    device_name: str = "",
) -> int:
    """Start the EAB daemon in the background.

    Spawns the daemon process, optionally force-killing any existing instance
    first. Detects the correct Python interpreter from the eabctl shebang.

    Args:
        base_dir: Session directory for daemon state files.
        port: Serial port (or ``"auto"`` to auto-detect).
        baud: Baud rate for the serial connection.
        force: Kill existing daemon before starting.
        json_mode: Emit machine-parseable JSON output.
        log_max_size_mb: Max log file size in MB before rotation.
        log_max_files: Max rotated log files to keep.
        log_compress: Whether to gzip rotated log files.
        device_name: Per-device session name (empty for legacy global mode).

    Returns:
        Exit code: 0 on success, 1 if daemon already running (without --force).
    """
    existing = check_singleton(device_name=device_name)
    if existing and existing.is_alive:
        if not force:
            suffix = f" for {device_name}" if device_name else ""
            payload = {
                "schema_version": 1,
                "timestamp": _now_iso(),
                "started": False,
                "message": f"Daemon already running{suffix}",
                "pid": existing.pid,
            }
            _print(payload, json_mode=json_mode)
            return 1
        kill_existing_daemon(device_name=device_name)

    if force:
        # Best-effort: kill any other EAB instances still holding port locks (covers cases where
        # multiple daemons exist but only one is referenced by the singleton files).
        killed: list[int] = []
        for owner in list_all_locks():
            if owner.pid == os.getpid():
                continue
            try:
                os.kill(owner.pid, signal.SIGTERM)
                killed.append(owner.pid)
            except Exception:
                pass
        if killed:
            time.sleep(0.5)
            for pid in killed:
                try:
                    os.kill(pid, 0)
                except Exception:
                    continue
                try:
                    os.kill(pid, signal.SIGKILL)
                except Exception:
                    pass

        # Clean stale lock artifacts from dead processes (safe).
        cleanup_dead_locks()

    # Clear stale session files before starting new daemon.
    _clear_session_files(base_dir)

    # Use the Python that can actually import eab — sys.executable can differ
    # from the interpreter running eabctl (e.g. system Python vs homebrew).
    import shutil

    python = sys.executable
    eabctl_path = shutil.which("eabctl")
    if eabctl_path:
        try:
            with open(eabctl_path, "r") as f:
                shebang = f.readline().strip()
            if shebang.startswith("#!") and "python" in shebang:
                candidate = shebang[2:].strip()
                if os.path.isfile(candidate):
                    python = candidate
        except Exception:
            pass

    args = [
        python,
        "-m",
        "eab",
        "--port",
        port,
        "--baud",
        str(baud),
        "--base-dir",
        base_dir,
        "--log-max-size",
        str(log_max_size_mb),
        "--log-max-files",
        str(log_max_files),
    ]
    if not log_compress:
        args.append("--no-log-compress")
    if device_name:
        args.extend(["--device-name", device_name])

    if device_name:
        log_path = os.path.join(base_dir, "daemon.log")
        err_path = os.path.join(base_dir, "daemon.err")
    else:
        log_path = "/tmp/eab-daemon.log"
        err_path = "/tmp/eab-daemon.err"

    daemon_cwd = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
    env = dict(os.environ)
    # Ensure the local checkout is importable when we spawn the daemon.
    env["PYTHONPATH"] = (
        daemon_cwd
        if not env.get("PYTHONPATH")
        else daemon_cwd + os.pathsep + env["PYTHONPATH"]
    )
    with open(log_path, "a", encoding="utf-8") as out, open(err_path, "a", encoding="utf-8") as err:
        proc = subprocess.Popen(
            args,
            stdout=out,
            stderr=err,
            cwd=daemon_cwd,
            env=env,
            start_new_session=True,
        )

    # Write placeholder status.json immediately to avoid race condition
    # where `eabctl status` is called before daemon has initialized
    status_path = os.path.join(base_dir, "status.json")
    os.makedirs(base_dir, exist_ok=True)
    placeholder_status = {
        "health": {"status": "starting"},
        "connection": {"status": "starting"}
    }
    with open(status_path, "w", encoding="utf-8") as f:
        f.write(json.dumps(placeholder_status, indent=2))

    payload = {
        "schema_version": 1,
        "timestamp": _now_iso(),
        "started": True,
        "pid": proc.pid,
        "log_path": log_path,
        "err_path": err_path,
    }
    _print(payload, json_mode=json_mode)
    return 0


def cmd_stop(*, json_mode: bool, device_name: str = "") -> int:
    """Stop the running EAB daemon.

    Sends SIGTERM (then SIGKILL) to the daemon process found via the
    singleton PID file.

    Args:
        json_mode: Emit machine-parseable JSON output.
        device_name: If set, stop the per-device daemon.

    Returns:
        Exit code: 0 on success, 1 if daemon not running or kill failed.
    """
    existing = check_singleton(device_name=device_name)
    if not existing or not existing.is_alive:
        suffix = f" for {device_name}" if device_name else ""
        payload = {
            "schema_version": 1,
            "timestamp": _now_iso(),
            "stopped": False,
            "message": f"Daemon not running{suffix}",
        }
        _print(payload, json_mode=json_mode)
        return 1

    ok = kill_existing_daemon(device_name=device_name)
    payload = {
        "schema_version": 1,
        "timestamp": _now_iso(),
        "stopped": ok,
        "pid": existing.pid,
    }
    _print(payload, json_mode=json_mode)
    return 0 if ok else 1


def cmd_pause(*, base_dir: str, seconds: int, json_mode: bool) -> int:
    """Pause the daemon for *seconds* by writing a pause file.

    The daemon checks for ``pause.txt`` and releases the serial port while
    the pause is active, allowing external tools to access the device.

    Args:
        base_dir: Session directory containing ``pause.txt``.
        seconds: Duration to pause in seconds.
        json_mode: Emit machine-parseable JSON output.

    Returns:
        Exit code: always 0.
    """
    pause_path = os.path.join(base_dir, "pause.txt")
    pause_until = time.time() + seconds
    os.makedirs(base_dir, exist_ok=True)
    with open(pause_path, "w", encoding="utf-8") as f:
        f.write(str(pause_until))

    payload = {
        "schema_version": 1,
        "timestamp": _now_iso(),
        "paused": True,
        "pause_until": pause_until,
        "pause_path": pause_path,
    }
    _print(payload, json_mode=json_mode)
    return 0


def cmd_resume(*, base_dir: str, json_mode: bool) -> int:
    """Resume the daemon early by removing the pause file.

    Args:
        base_dir: Session directory containing ``pause.txt``.
        json_mode: Emit machine-parseable JSON output.

    Returns:
        Exit code: always 0.
    """
    pause_path = os.path.join(base_dir, "pause.txt")
    try:
        os.remove(pause_path)
    except FileNotFoundError:
        pass

    payload = {
        "schema_version": 1,
        "timestamp": _now_iso(),
        "paused": False,
        "pause_path": pause_path,
    }
    _print(payload, json_mode=json_mode)
    return 0
