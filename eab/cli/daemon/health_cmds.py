"""Daemon health monitoring and diagnostics commands."""

from __future__ import annotations

import json
import os
from typing import Any, Optional

from eab.cli.helpers import _now_iso, _print, _read_text
from eab.singleton import check_singleton


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
