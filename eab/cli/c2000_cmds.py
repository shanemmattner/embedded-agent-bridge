"""C2000-specific CLI commands for eabctl.

Commands:
- reg-read: Read and decode a register or register group
- erad-status: Show ERAD profiler state
- stream-vars: Poll variables from C2000 target via memory reads
- dlog-capture: Read DLOG_4CH circular buffers
- c2000-trace-export: Export ERAD/DLOG/log data to Perfetto JSON
"""

from __future__ import annotations

import json
import sys
import time
from typing import Optional

from eab.cli.helpers import _print


def _find_register(reg_map, name: str):
    """Find a register by name across all groups."""
    for grp in reg_map.groups.values():
        if name in grp.registers:
            return grp.registers[name]
    return None


def cmd_reg_read(
    *,
    chip: str,
    register: Optional[str] = None,
    group: Optional[str] = None,
    ccxml: Optional[str] = None,
    json_mode: bool = False,
) -> int:
    """Read and decode a register or register group."""
    from eab.register_maps import load_register_map

    try:
        reg_map = load_register_map(chip)
    except FileNotFoundError as e:
        _print({"error": str(e)}, json_mode=json_mode)
        return 2

    if register:
        reg = _find_register(reg_map, register)
        if reg is None:
            _print({"error": f"Register '{register}' not found in {chip}"}, json_mode=json_mode)
            return 2

        result = {
            "register": reg.name,
            "address": f"0x{reg.address:X}",
            "size": reg.size,
            "description": reg.description,
            "fields": {f.name: {"mask": f"0x{f.mask:X}", "description": f.description}
                       for f in reg.bit_fields},
        }
        _print(result if json_mode else _format_register_info(reg), json_mode=json_mode)
        return 0

    if group:
        grp = reg_map.get_group(group)
        if grp is None:
            _print({"error": f"Group '{group}' not found in {chip}"}, json_mode=json_mode)
            return 2

        result = {
            "group": grp.name,
            "registers": [
                {
                    "name": r.name,
                    "address": f"0x{r.address:X}",
                    "size": r.size,
                    "description": r.description,
                }
                for r in grp.registers.values()
            ],
        }
        _print(result if json_mode else _format_group_info(grp), json_mode=json_mode)
        return 0

    # List all available groups and registers
    all_regs = reg_map.all_registers()
    result = {
        "chip": chip,
        "groups": list(reg_map.groups.keys()),
        "register_count": len(all_regs),
    }
    _print(
        result if json_mode
        else f"Chip: {chip}\nGroups: {', '.join(result['groups'])}\nRegisters: {result['register_count']}",
        json_mode=json_mode,
    )
    return 0


def cmd_erad_status(
    *,
    chip: str = "f28003x",
    json_mode: bool = False,
) -> int:
    """Show ERAD register definitions and configuration info."""
    from eab.register_maps import load_register_map

    try:
        reg_map = load_register_map(chip)
    except FileNotFoundError as e:
        _print({"error": str(e)}, json_mode=json_mode)
        return 2

    erad_group = reg_map.get_group("erad")
    if erad_group is None:
        _print({"error": f"No ERAD registers defined for {chip}"}, json_mode=json_mode)
        return 2

    result = {
        "chip": chip,
        "erad_registers": [
            {
                "name": r.name,
                "address": f"0x{r.address:X}",
                "size": r.size,
                "description": r.description,
            }
            for r in erad_group.registers.values()
        ],
    }
    if json_mode:
        _print(result, json_mode=True)
    else:
        lines = [f"ERAD Registers ({chip}):"]
        for r in erad_group.registers.values():
            lines.append(f"  {r.name:25s} 0x{r.address:05X}  ({r.size}B)  {r.description}")
        _print("\n".join(lines), json_mode=False)
    return 0


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


def cmd_c2000_trace_export(
    *,
    output_file: str,
    erad_data: Optional[str] = None,
    dlog_data: Optional[str] = None,
    log_file: Optional[str] = None,
    process_name: str = "C2000 Debug",
    json_mode: bool = False,
) -> int:
    """Export C2000 debug data to Perfetto JSON trace."""
    from eab.analyzers.perfetto_export import (
        DLOGTrack,
        ERADSpan,
        LogEvent,
        PerfettoExporter,
    )

    exporter = PerfettoExporter(process_name=process_name)

    if erad_data:
        try:
            with open(erad_data) as f:
                data = json.load(f)
            for span in data.get("spans", []):
                exporter.add_erad_span(ERADSpan(
                    name=span["name"],
                    start_us=span.get("start_us", 0),
                    duration_us=span["duration_us"],
                    cpu_cycles=span.get("cpu_cycles", 0),
                ))
        except (FileNotFoundError, json.JSONDecodeError, KeyError) as e:
            _print({"error": f"Failed to load ERAD data: {e}"}, json_mode=json_mode)
            return 2

    if dlog_data:
        try:
            with open(dlog_data) as f:
                data = json.load(f)
            for name, values in data.get("buffers", {}).items():
                exporter.add_dlog_track(DLOGTrack(name=name, values=values))
        except (FileNotFoundError, json.JSONDecodeError) as e:
            _print({"error": f"Failed to load DLOG data: {e}"}, json_mode=json_mode)
            return 2

    if log_file:
        try:
            with open(log_file) as f:
                for i, line in enumerate(f):
                    line = line.strip()
                    if line:
                        exporter.add_log_event(LogEvent(
                            timestamp_us=float(i) * 1000,
                            message=line,
                        ))
        except FileNotFoundError as e:
            _print({"error": f"Log file not found: {e}"}, json_mode=json_mode)
            return 2

    summary = exporter.write(output_file)
    _print(summary, json_mode=json_mode)
    return 0


# =========================================================================
# Formatting helpers
# =========================================================================


def _format_register_info(reg) -> str:
    """Format register info for human display."""
    lines = [f"{reg.name} @ 0x{reg.address:X} ({reg.size}B)"]
    lines.append(f"  {reg.description}")
    if reg.bit_fields:
        lines.append("  Fields:")
        for f in reg.bit_fields:
            lines.append(f"    {f.name:20s} mask=0x{f.mask:X}  {f.description}")
    return "\n".join(lines)


def _format_group_info(grp) -> str:
    """Format register group info for human display."""
    lines = [f"Group: {grp.name}"]
    for r in grp.registers.values():
        lines.append(f"  {r.name:25s} 0x{r.address:05X}  ({r.size}B)  {r.description}")
    return "\n".join(lines)
