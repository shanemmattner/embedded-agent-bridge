"""Status and monitoring commands for eabctl."""

from __future__ import annotations

import json
import os
from dataclasses import asdict
from typing import Any, Optional

from eab.singleton import check_singleton

from eab.cli.helpers import (
    _now_iso,
    _print,
    _read_text,
    _tail_lines,
    _tail_events,
    _parse_log_line,
)


def cmd_status(*, base_dir: str, json_mode: bool) -> int:
    """Show daemon and device status.

    Reads the singleton PID file and ``status.json`` to build a combined
    status payload.  In plain-text mode, prints a human-readable summary.

    Args:
        base_dir: Session directory for daemon state files.
        json_mode: Emit machine-parseable JSON output.

    Returns:
        Exit code: 0 if daemon is running, 1 otherwise.
    """
    existing = check_singleton()
    status_path = os.path.join(base_dir, "status.json")

    status: Optional[dict[str, Any]]
    try:
        status = json.loads(_read_text(status_path))
    except FileNotFoundError:
        status = None
    except json.JSONDecodeError:
        status = {"error": "invalid_json", "path": status_path}

    payload: dict[str, Any] = {
        "schema_version": 1,
        "timestamp": _now_iso(),
        "daemon": asdict(existing) if existing else {"running": False},
        "paths": {
            "base_dir": base_dir,
            "status_json": status_path,
            "latest_log": os.path.join(base_dir, "latest.log"),
            "alerts_log": os.path.join(base_dir, "alerts.log"),
            "events_log": os.path.join(base_dir, "events.jsonl"),
            "data_bin": os.path.join(base_dir, "data.bin"),
            "stream_json": os.path.join(base_dir, "stream.json"),
            "cmd_txt": os.path.join(base_dir, "cmd.txt"),
            "pause_txt": os.path.join(base_dir, "pause.txt"),
        },
        "status": status,
    }

    if json_mode:
        _print(payload, json_mode=True)
    else:
        if existing and existing.is_alive:
            print("EAB daemon: RUNNING")
            print(f"  pid: {existing.pid}")
            print(f"  port: {existing.port}")
            print(f"  base_dir: {existing.base_dir}")
            print(f"  started: {existing.started}")
        else:
            print("EAB daemon: NOT RUNNING")
        if status is not None:
            print("")
            print("status.json:")
            print(json.dumps(status, indent=2, sort_keys=True))

    return 0 if (existing and existing.is_alive) else 1


def cmd_tail(*, base_dir: str, lines: int, json_mode: bool) -> int:
    log_path = os.path.join(base_dir, "latest.log")
    raw = _tail_lines(log_path, lines)
    if json_mode:
        _print(
            {
                "schema_version": 1,
                "timestamp": _now_iso(),
                "path": log_path,
                "lines": [_parse_log_line(l) for l in raw],
            },
            json_mode=True,
        )
    else:
        for line in raw:
            print(line)
    return 0


def cmd_alerts(*, base_dir: str, lines: int, json_mode: bool) -> int:
    alerts_path = os.path.join(base_dir, "alerts.log")
    raw = _tail_lines(alerts_path, lines)
    if json_mode:
        _print(
            {
                "schema_version": 1,
                "timestamp": _now_iso(),
                "path": alerts_path,
                "lines": [_parse_log_line(l) for l in raw],
            },
            json_mode=True,
        )
    else:
        for line in raw:
            print(line)
    return 0


def cmd_events(*, base_dir: str, lines: int, json_mode: bool) -> int:
    events_path = os.path.join(base_dir, "events.jsonl")
    if json_mode:
        _print(
            {
                "schema_version": 1,
                "timestamp": _now_iso(),
                "path": events_path,
                "events": _tail_events(events_path, lines),
            },
            json_mode=True,
        )
    else:
        for event in _tail_events(events_path, lines):
            print(json.dumps(event, sort_keys=True))
    return 0
