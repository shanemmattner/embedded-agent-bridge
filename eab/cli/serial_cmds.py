"""Serial monitoring and communication commands for eabctl."""

from __future__ import annotations

import json
import os
import re
import time
from dataclasses import asdict
from typing import Any, Optional

from eab.command_file import append_command
from eab.capture import capture_between_markers
from eab.singleton import check_singleton

from eab.cli.helpers import (
    _now_iso,
    _print,
    _read_text,
    _tail_lines,
    _tail_events,
    _parse_log_line,
    _parse_event_line,
    _event_matches,
)


def _await_log_ack(log_path: str, marker: str, timeout_s: float) -> bool:
    """Tail *log_path* until *marker* appears or *timeout_s* expires.

    Args:
        log_path: Path to the log file to tail.
        marker: Substring to search for in new log lines.
        timeout_s: Maximum seconds to wait.

    Returns:
        True if the marker was found, False on timeout or missing file.
    """
    start = time.time()
    try:
        with open(log_path, "r", encoding="utf-8", errors="replace") as f:
            f.seek(0, os.SEEK_END)
            pos = f.tell()
            while time.time() - start < timeout_s:
                f.seek(pos)
                chunk = f.read()
                if chunk:
                    for line in chunk.splitlines():
                        if marker in line:
                            return True
                    pos = f.tell()
                time.sleep(0.05)
    except FileNotFoundError:
        return False
    return False


def _await_event(
    events_path: str,
    *,
    event_type: Optional[str],
    contains: Optional[str],
    command: Optional[str],
    timeout_s: float,
) -> Optional[dict[str, Any]]:
    """Tail *events_path* (JSONL) for a matching event.

    Args:
        events_path: Path to the ``events.jsonl`` file.
        event_type: If set, only match events with this ``type`` field.
        contains: If set, only match events whose JSON contains this substring.
        command: If set, only match events whose ``data.command`` equals this.
        timeout_s: Maximum seconds to wait.

    Returns:
        The matched event dict, or None on timeout / missing file.
    """
    start = time.time()
    try:
        with open(events_path, "r", encoding="utf-8", errors="replace") as f:
            f.seek(0, os.SEEK_END)
            pos = f.tell()
            while time.time() - start < timeout_s:
                f.seek(pos)
                chunk = f.read()
                if chunk:
                    for line in chunk.splitlines():
                        event = _parse_event_line(line)
                        if _event_matches(
                            event,
                            event_type=event_type,
                            contains=contains,
                            command=command,
                        ):
                            return event
                    pos = f.tell()
                time.sleep(0.05)
    except FileNotFoundError:
        return None
    return None


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


def cmd_send(
    *,
    base_dir: str,
    text: str,
    await_ack: bool,
    await_event: bool,
    timeout_s: float,
    json_mode: bool,
) -> int:
    """Queue a text command to the device and optionally wait for acknowledgement.

    Writes *text* to ``cmd.txt``; the daemon picks it up and sends it over
    serial.  With ``--await`` or ``--await-event``, blocks until the daemon
    logs or emits an event confirming the send.

    Args:
        base_dir: Session directory containing ``cmd.txt``.
        text: Command string to send.
        await_ack: Wait for the command to appear in ``latest.log``.
        await_event: Wait for a ``command_sent`` event in ``events.jsonl``.
        timeout_s: Maximum seconds to wait for acknowledgement.
        json_mode: Emit machine-parseable JSON output.

    Returns:
        Exit code: 0 on success (or if no ack requested), 1 on ack timeout.
    """
    cmd_path = os.path.join(base_dir, "cmd.txt")
    log_path = os.path.join(base_dir, "latest.log")
    events_path = os.path.join(base_dir, "events.jsonl")

    started = time.time()
    append_command(cmd_path, text)

    acknowledged = False
    ack_source: Optional[str] = None
    ack_event: Optional[dict[str, Any]] = None

    if await_event:
        ack_event = _await_event(
            events_path,
            event_type="command_sent",
            contains=None,
            command=text,
            timeout_s=timeout_s,
        )
        acknowledged = ack_event is not None
        ack_source = "event"

    if await_ack and not acknowledged:
        marker = f">>> CMD: {text}"
        acknowledged = _await_log_ack(log_path, marker, timeout_s=timeout_s)
        ack_source = "log"

    duration_ms = int((time.time() - started) * 1000)

    result = {
        "schema_version": 1,
        "timestamp": _now_iso(),
        "command": text,
        "queued_to": cmd_path,
        "acknowledged": acknowledged,
        "ack_source": ack_source,
        "ack_event": ack_event,
        "duration_ms": duration_ms,
    }

    if json_mode:
        _print(result, json_mode=True)
    else:
        print(f"sent: {text}")
        if await_ack or await_event:
            print("ack: ok" if acknowledged else "ack: timeout")

    return 0 if (not await_ack and not await_event) or acknowledged else 1


def cmd_wait(*, base_dir: str, pattern: str, timeout_s: float, json_mode: bool) -> int:
    """Block until a regex *pattern* appears in ``latest.log`` or timeout.

    Args:
        base_dir: Session directory containing ``latest.log``.
        pattern: Regex pattern to match against new log lines.
        timeout_s: Maximum seconds to wait.
        json_mode: Emit machine-parseable JSON output.

    Returns:
        Exit code: 0 if matched, 1 on timeout.
    """
    log_path = os.path.join(base_dir, "latest.log")
    regex = re.compile(pattern)

    started = time.time()

    try:
        with open(log_path, "r", encoding="utf-8", errors="replace") as f:
            f.seek(0, os.SEEK_END)
            pos = f.tell()

            while time.time() - started < timeout_s:
                f.seek(pos)
                chunk = f.read()
                if chunk:
                    for line in chunk.splitlines():
                        if regex.search(line):
                            result = {
                                "schema_version": 1,
                                "timestamp": _now_iso(),
                                "pattern": pattern,
                                "matched": True,
                                "line": _parse_log_line(line),
                                "duration_ms": int((time.time() - started) * 1000),
                            }
                            _print(result, json_mode=json_mode)
                            return 0
                    pos = f.tell()
                time.sleep(0.05)
    except FileNotFoundError:
        pass

    result = {
        "schema_version": 1,
        "timestamp": _now_iso(),
        "pattern": pattern,
        "matched": False,
        "duration_ms": int((time.time() - started) * 1000),
    }
    _print(result, json_mode=json_mode)
    return 1


def cmd_wait_event(
    *,
    base_dir: str,
    event_type: Optional[str],
    contains: Optional[str],
    command: Optional[str],
    timeout_s: float,
    json_mode: bool,
) -> int:
    """Block until a matching event appears in ``events.jsonl`` or timeout.

    Args:
        base_dir: Session directory containing ``events.jsonl``.
        event_type: If set, only match events with this ``type`` field.
        contains: If set, only match events whose JSON contains this substring.
        command: If set, only match events whose ``data.command`` equals this.
        timeout_s: Maximum seconds to wait.
        json_mode: Emit machine-parseable JSON output.

    Returns:
        Exit code: 0 if matched, 1 on timeout.
    """
    events_path = os.path.join(base_dir, "events.jsonl")
    started = time.time()

    event = _await_event(
        events_path,
        event_type=event_type,
        contains=contains,
        command=command,
        timeout_s=timeout_s,
    )

    result = {
        "schema_version": 1,
        "timestamp": _now_iso(),
        "event_type": event_type,
        "contains": contains,
        "command": command,
        "matched": event is not None,
        "event": event,
        "duration_ms": int((time.time() - started) * 1000),
    }
    _print(result, json_mode=json_mode)
    return 0 if event is not None else 1


def cmd_capture_between(
    *,
    base_dir: str,
    start_marker: str,
    end_marker: str,
    output_path: str,
    timeout_s: float,
    from_start: bool,
    strip_timestamps: bool,
    filter_mode: str,
    decode_base64: bool,
    json_mode: bool,
) -> int:
    """Capture payload lines between two markers in ``latest.log``.

    Scans for *start_marker* and *end_marker*, extracts lines between them,
    optionally filters to base64-only content, and writes to *output_path*.

    Args:
        base_dir: Session directory containing ``latest.log``.
        start_marker: Line that signals the start of the payload.
        end_marker: Line that signals the end of the payload.
        output_path: Destination file path.
        timeout_s: Maximum seconds to wait for both markers.
        from_start: Scan from the beginning of the log instead of tailing.
        strip_timestamps: Remove ``[HH:MM:SS.mmm]`` prefixes before filtering.
        filter_mode: ``"base64"`` or ``"none"``.
        decode_base64: Decode captured base64 payload to bytes before writing.
        json_mode: Emit machine-parseable JSON output.

    Returns:
        Exit code: 0 if both markers found, 1 otherwise.
    """
    log_path = os.path.join(base_dir, "latest.log")
    result = capture_between_markers(
        log_path=log_path,
        start_marker=start_marker,
        end_marker=end_marker,
        output_path=output_path,
        timeout_s=timeout_s,
        from_end=not from_start,
        strip_timestamps=strip_timestamps,
        filter_mode=filter_mode,  # type: ignore[arg-type]
        decode_base64=decode_base64,
    )

    payload = {
        "schema_version": 1,
        "timestamp": _now_iso(),
        "log_path": log_path,
        "start_marker": start_marker,
        "end_marker": end_marker,
        "output_path": output_path,
        "result": asdict(result),
    }
    _print(payload, json_mode=json_mode)
    return 0 if (result.start_seen and result.end_seen) else 1
