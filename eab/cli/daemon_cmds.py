"""Daemon management commands for eabctl."""

from __future__ import annotations

import json
import os
import signal
import subprocess
import sys
import time
from typing import Any, Optional

from eab.singleton import (
    check_singleton, kill_existing_daemon, list_devices,
    register_device, unregister_device, DEFAULT_DEVICES_DIR,
)
from eab.port_lock import list_all_locks, cleanup_dead_locks

from eab.cli.helpers import (
    _now_iso,
    _print,
    _read_text,
)


def _clear_session_files(base_dir: str) -> None:
    """Remove or reset session files in the base directory.

    Cleans up status.json, alerts.log, and events.jsonl files,
    handling missing files gracefully.

    Args:
        base_dir: Session directory containing state files.
    """
    files_to_clear = ["status.json", "alerts.log", "events.jsonl"]
    for filename in files_to_clear:
        filepath = os.path.join(base_dir, filename)
        try:
            os.remove(filepath)
        except FileNotFoundError:
            pass


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

    Returns:
        Exit code: 0 on success, 1 if daemon already running (without --force).
    """
    existing = check_singleton(device_name=device_name)
    if existing and existing.is_alive:
        if not force:
            payload = {
                "schema_version": 1,
                "timestamp": _now_iso(),
                "started": False,
                "message": f"Daemon already running{' for ' + device_name if device_name else ''}",
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
        os.makedirs(base_dir, exist_ok=True)
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
        payload = {
            "schema_version": 1,
            "timestamp": _now_iso(),
            "stopped": False,
            "message": f"Daemon not running{' for ' + device_name if device_name else ''}",
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


def cmd_diagnose(*, base_dir: str, json_mode: bool) -> int:
    """Run health checks on the daemon and device, with recommendations.

    Inspects the singleton PID, ``status.json``, connection state, and
    pattern counters to produce a pass/warn/error summary.

    Args:
        base_dir: Session directory for daemon state files.
        json_mode: Emit machine-parseable JSON output.

    Returns:
        Exit code: 0 if all checks pass, 1 otherwise.
    """
    existing = check_singleton()  # Legacy check for diagnose
    status_path = os.path.join(base_dir, "status.json")

    checks: list[dict[str, str]] = []
    recommendations: list[str] = []

    if existing and existing.is_alive:
        checks.append({"name": "daemon", "status": "ok", "message": f"Running PID {existing.pid}"})
    else:
        checks.append({"name": "daemon", "status": "error", "message": "Daemon not running"})
        recommendations.append("Run: eabctl start")

    status: Optional[dict[str, Any]] = None
    try:
        status = json.loads(_read_text(status_path))
        checks.append({"name": "status_json", "status": "ok", "message": f"Readable: {status_path}"})
    except FileNotFoundError:
        checks.append({"name": "status_json", "status": "error", "message": f"Missing: {status_path}"})
        recommendations.append("Run: eabctl start")
    except json.JSONDecodeError:
        checks.append({"name": "status_json", "status": "error", "message": f"Invalid JSON: {status_path}"})

    if status:
        conn = status.get("connection", {})
        conn_status = conn.get("status")
        if conn_status == "connected":
            checks.append({"name": "connection", "status": "ok", "message": f"Connected: {conn.get('port')}"})
        elif conn_status:
            checks.append({"name": "connection", "status": "warn", "message": f"{conn_status}: {conn.get('port')}"})
            recommendations.append("Try: eabctl reset")
        else:
            checks.append({"name": "connection", "status": "warn", "message": "Unknown connection status"})

        health = status.get("health", {})
        health_status = health.get("status")
        idle_seconds = health.get("idle_seconds")
        if health_status in {"healthy", "idle"}:
            checks.append({"name": "health", "status": "ok", "message": f"{health_status} (idle={idle_seconds}s)"})
        elif health_status:
            checks.append({"name": "health", "status": "warn", "message": f"{health_status} (idle={idle_seconds}s)"})
            recommendations.append("Check cable; then run: eabctl reset")
        else:
            checks.append({"name": "health", "status": "warn", "message": "Missing health.status"})

        patterns = status.get("patterns", {})
        watchdog = int(patterns.get("WATCHDOG", 0) or 0)
        boot = int(patterns.get("BOOT", 0) or 0)
        if watchdog >= 25 or boot >= 25:
            checks.append(
                {
                    "name": "boot_loop",
                    "status": "warn",
                    "message": f"High boot indicators (WATCHDOG={watchdog}, BOOT={boot})",
                }
            )
            recommendations.append("Device may be in a boot loop. Consider: eabctl flash <project_dir>")
        else:
            checks.append({"name": "boot_loop", "status": "ok", "message": f"WATCHDOG={watchdog}, BOOT={boot}"})

    healthy = all(c["status"] == "ok" for c in checks)

    payload = {
        "schema_version": 1,
        "timestamp": _now_iso(),
        "healthy": healthy,
        "checks": checks,
        "recommendations": recommendations,
    }
    _print(payload, json_mode=json_mode)
    return 0 if healthy else 1


def cmd_devices(*, json_mode: bool) -> int:
    """List all registered devices and their status.

    Args:
        json_mode: Emit machine-parseable JSON output.

    Returns:
        Exit code: always 0.
    """
    devices = list_devices()

    if json_mode:
        payload = {
            "schema_version": 1,
            "timestamp": _now_iso(),
            "devices": [
                {
                    "name": d.device_name,
                    "type": d.device_type,
                    "chip": d.chip,
                    "status": "running" if d.is_alive else "stopped",
                    "pid": d.pid,
                    "port": d.port,
                    "base_dir": d.base_dir,
                    "started": d.started,
                }
                for d in devices
            ],
        }
        _print(payload, json_mode=True)
    else:
        if not devices:
            print("No devices registered. Use: eabctl device add <name> --type debug --chip <chip>")
        else:
            for d in devices:
                status = "running" if d.is_alive else "stopped"
                chip_str = f" ({d.chip})" if d.chip else ""
                port_str = f" port={d.port}" if d.port else ""
                pid_str = f" pid={d.pid}" if d.pid else ""
                print(f"  {d.device_name:<16} {d.device_type:<8} {status:<10}{chip_str}{port_str}{pid_str}")

    return 0


def cmd_device_add(*, name: str, device_type: str, chip: str, json_mode: bool) -> int:
    """Register a new device.

    Args:
        name: Device name (e.g., 'nrf5340').
        device_type: 'serial' or 'debug'.
        chip: Chip identifier.
        json_mode: Emit machine-parseable JSON output.

    Returns:
        Exit code: 0 on success.
    """
    device_dir = register_device(name, device_type=device_type, chip=chip)
    payload = {
        "schema_version": 1,
        "timestamp": _now_iso(),
        "registered": True,
        "name": name,
        "type": device_type,
        "chip": chip,
        "base_dir": device_dir,
    }
    _print(payload, json_mode=json_mode)
    return 0


def cmd_device_remove(*, name: str, json_mode: bool) -> int:
    """Unregister a device.

    Args:
        name: Device name to remove.
        json_mode: Emit machine-parseable JSON output.

    Returns:
        Exit code: 0 on success, 1 if device not found or daemon running.
    """
    ok = unregister_device(name)
    if ok:
        payload = {
            "schema_version": 1,
            "timestamp": _now_iso(),
            "removed": True,
            "name": name,
        }
        _print(payload, json_mode=json_mode)
        return 0
    else:
        # Check if daemon is running
        existing = check_singleton(device_name=name)
        if existing and existing.is_alive:
            msg = f"Cannot remove '{name}': daemon still running (PID {existing.pid}). Stop it first."
        else:
            msg = f"Device '{name}' not found"
        payload = {
            "schema_version": 1,
            "timestamp": _now_iso(),
            "removed": False,
            "name": name,
            "message": msg,
        }
        _print(payload, json_mode=json_mode)
        return 1
