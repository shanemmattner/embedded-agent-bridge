"""High-speed data stream commands for eabctl."""

from __future__ import annotations

import base64
import json
import os
from typing import Any, Optional

from eab.cli.helpers import (
    _now_iso,
    _print,
    _read_bytes,
)


def cmd_stream_start(
    *,
    base_dir: str,
    mode: str,
    chunk_size: int,
    marker: Optional[str],
    pattern_matching: bool,
    truncate: bool,
    json_mode: bool,
) -> int:
    stream_path = os.path.join(base_dir, "stream.json")
    payload = {
        "enabled": True,
        "mode": mode,
        "chunk_size": chunk_size,
        "marker": marker,
        "pattern_matching": pattern_matching,
        "truncate": truncate,
    }
    os.makedirs(base_dir, exist_ok=True)
    with open(stream_path, "w", encoding="utf-8") as f:
        json.dump(payload, f, indent=2, sort_keys=True)

    result = {
        "schema_version": 1,
        "timestamp": _now_iso(),
        "stream_path": stream_path,
        "config": payload,
    }
    _print(result, json_mode=json_mode)
    return 0


def cmd_stream_stop(*, base_dir: str, json_mode: bool) -> int:
    stream_path = os.path.join(base_dir, "stream.json")
    try:
        os.remove(stream_path)
    except FileNotFoundError:
        pass

    result = {
        "schema_version": 1,
        "timestamp": _now_iso(),
        "stream_path": stream_path,
        "disabled": True,
    }
    _print(result, json_mode=json_mode)
    return 0


def cmd_recv(
    *,
    base_dir: str,
    offset: int,
    length: int,
    output_path: Optional[str],
    base64_output: bool,
    json_mode: bool,
) -> int:
    data_path = os.path.join(base_dir, "data.bin")
    try:
        payload = _read_bytes(data_path, offset, length)
    except FileNotFoundError:
        result = {
            "schema_version": 1,
            "timestamp": _now_iso(),
            "error": "missing_data",
            "data_path": data_path,
        }
        _print(result, json_mode=json_mode)
        return 1

    if output_path:
        with open(output_path, "wb") as f:
            f.write(payload)
        result = {
            "schema_version": 1,
            "timestamp": _now_iso(),
            "data_path": data_path,
            "offset": offset,
            "length": len(payload),
            "output_path": output_path,
        }
        _print(result, json_mode=json_mode)
        return 0

    result: dict[str, Any] = {
        "schema_version": 1,
        "timestamp": _now_iso(),
        "data_path": data_path,
        "offset": offset,
        "length": len(payload),
    }
    if base64_output:
        result["data_base64"] = base64.b64encode(payload).decode("ascii")
    _print(result, json_mode=json_mode)
    return 0


def cmd_recv_latest(
    *,
    base_dir: str,
    length: int,
    output_path: Optional[str],
    base64_output: bool,
    json_mode: bool,
) -> int:
    data_path = os.path.join(base_dir, "data.bin")
    try:
        size = os.path.getsize(data_path)
    except FileNotFoundError:
        size = 0
    offset = max(0, size - length)
    return cmd_recv(
        base_dir=base_dir,
        offset=offset,
        length=length,
        output_path=output_path,
        base64_output=base64_output,
        json_mode=json_mode,
    )
