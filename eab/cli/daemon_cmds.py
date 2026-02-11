"""Daemon management commands for eabctl."""

from __future__ import annotations

import json
import os
import signal
import subprocess
import sys
import time
from typing import Any, Optional

from eab.singleton import check_singleton, kill_existing_daemon
from eab.port_lock import list_all_locks, cleanup_dead_locks

from eab.cli.helpers import (
    _now_iso,
    _print,
    _read_text,
)


def cmd_start(
    *,
    base_dir: str,
    port: str,
    baud: int,
    force: bool,
    json_mode: bool,
) -> int:
    existing = check_singleton()
    if existing and existing.is_alive:
        if not force:
            payload = {
                "schema_version": 1,
                "timestamp": _now_iso(),
                "started": False,
                "message": "Daemon already running",
                "pid": existing.pid,
            }
            _print(payload, json_mode=json_mode)
            return 1
        kill_existing_daemon()

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
    ]

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


def cmd_stop(*, json_mode: bool) -> int:
    existing = check_singleton()
    if not existing or not existing.is_alive:
        payload = {
            "schema_version": 1,
            "timestamp": _now_iso(),
            "stopped": False,
            "message": "Daemon not running",
        }
        _print(payload, json_mode=json_mode)
        return 1

    ok = kill_existing_daemon()
    payload = {
        "schema_version": 1,
        "timestamp": _now_iso(),
        "stopped": ok,
        "pid": existing.pid,
    }
    _print(payload, json_mode=json_mode)
    return 0 if ok else 1


def cmd_pause(*, base_dir: str, seconds: int, json_mode: bool) -> int:
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
    existing = check_singleton()
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
