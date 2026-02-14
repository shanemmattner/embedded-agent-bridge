"""Payload capture commands for eabctl."""

from __future__ import annotations

import os
from dataclasses import asdict

from eab.capture import capture_between_markers

from eab.cli.helpers import (
    _now_iso,
    _print,
)


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
