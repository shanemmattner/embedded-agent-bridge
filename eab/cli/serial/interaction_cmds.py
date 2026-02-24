"""Interactive serial communication commands for eabctl."""

from __future__ import annotations

import os
import re
import time
from typing import Any, Optional

from eab.command_file import append_command

from eab.cli.helpers import (
    _now_iso,
    _print,
    _parse_log_line,
)

from ._helpers import _await_log_ack, _await_event


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


def cmd_wait(*, base_dir: str, pattern: str, timeout_s: float,
             scan_all: bool = False, scan_from: int | None = None,
             json_mode: bool) -> int:
    """Block until a regex *pattern* appears in ``latest.log`` or timeout.

    Args:
        base_dir: Session directory containing ``latest.log``.
        pattern: Regex pattern to match against new log lines.
        timeout_s: Maximum seconds to wait.
        scan_all: Scan from beginning of log instead of end.
        scan_from: Scan from this byte offset in the log file.
        json_mode: Emit machine-parseable JSON output.

    Returns:
        Exit code: 0 if matched, 1 on timeout.
    """
    log_path = os.path.join(base_dir, "latest.log")
    regex = re.compile(pattern)

    started = time.time()

    try:
        with open(log_path, "r", encoding="utf-8", errors="replace") as f:
            if scan_from is not None:
                f.seek(scan_from)
            elif not scan_all:
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
