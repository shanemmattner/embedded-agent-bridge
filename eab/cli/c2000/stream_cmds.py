"""C2000 variable streaming and DLOG capture commands."""

from __future__ import annotations

from typing import Optional

from eab.cli.helpers import _print


def cmd_stream_vars(
    *,
    map_file: str,
    var_specs: list[str],
    interval_ms: int = 100,
    count: int = 0,
    output: Optional[str] = None,
    json_mode: bool = False,
) -> int:
    """Stream variable values from C2000 target.

    Variables are specified as name:address:type (e.g., "speedRef:0xC100:float32").

    Args:
        map_file: Path to MAP file (for future symbol resolution).
        var_specs: List of variable specs in "name:address:type" format.
        interval_ms: Polling interval in milliseconds.
        count: Number of samples (0 = infinite).
        output: Optional output file path.
        json_mode: If True, output JSON instead of human-readable text.

    Returns:
        Exit code (0 = success, 2 = error).
    """
    from eab.analyzers.type_decode import parse_type_string
    from eab.analyzers.var_stream import StreamVar, VarStream

    variables = []
    for spec in var_specs:
        parts = spec.split(":")
        if len(parts) != 3:
            _print(
                {"error": f"Invalid var spec '{spec}'. Format: name:address:type"},
                json_mode=json_mode,
            )
            return 2
        name, addr_str, type_str = parts
        try:
            address = int(addr_str, 0)
        except ValueError:
            _print({"error": f"Invalid address '{addr_str}'"}, json_mode=json_mode)
            return 2
        try:
            c2000_type = parse_type_string(type_str)
        except ValueError as e:
            _print({"error": str(e)}, json_mode=json_mode)
            return 2
        variables.append(StreamVar(name=name, address=address, c2000_type=c2000_type))

    result = {
        "variables": [
            {"name": v.name, "address": f"0x{v.address:X}", "type": v.c2000_type.value, "size_bytes": v.size_bytes}
            for v in variables
        ],
        "interval_ms": interval_ms,
        "count": count,
        "status": "configured (no probe connected)",
    }
    _print(result, json_mode=json_mode)
    return 0


def cmd_dlog_capture(
    *,
    status_addr: Optional[str] = None,
    size_addr: Optional[str] = None,
    buffer_specs: list[str],
    buffer_size: int = 200,
    output: Optional[str] = None,
    output_format: str = "json",
    json_mode: bool = False,
) -> int:
    """Capture DLOG buffers from C2000 target.

    Buffers are specified as name:address (e.g., "dBuff1:0xC100").

    Args:
        status_addr: Optional DLOG status register address.
        size_addr: Optional DLOG size register address.
        buffer_specs: List of buffer specs in "name:address" format.
        buffer_size: Number of samples per buffer.
        output: Optional output file path.
        output_format: Output format (json, csv, jsonl).
        json_mode: If True, output JSON instead of human-readable text.

    Returns:
        Exit code (0 = success, 2 = error).
    """
    buffers = {}
    for spec in buffer_specs:
        parts = spec.split(":")
        if len(parts) != 2:
            _print(
                {"error": f"Invalid buffer spec '{spec}'. Format: name:address"},
                json_mode=json_mode,
            )
            return 2
        name = parts[0]
        try:
            addr = int(parts[1], 0)
        except ValueError:
            _print({"error": f"Invalid address '{parts[1]}'"}, json_mode=json_mode)
            return 2
        buffers[name] = addr

    result = {
        "buffers": {name: f"0x{addr:X}" for name, addr in buffers.items()},
        "buffer_size": buffer_size,
        "output_format": output_format,
        "status": "configured (no probe connected)",
    }
    _print(result, json_mode=json_mode)
    return 0
