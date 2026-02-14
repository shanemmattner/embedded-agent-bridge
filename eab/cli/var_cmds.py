"""Variable inspection commands for eabctl.

Commands:
    vars       - List global/static variables from ELF symbol table
    read-vars  - Read variable values from target via debug probe
"""

from __future__ import annotations

import fnmatch
import tempfile
from pathlib import Path
from typing import Optional

import logging

from eab.cli.helpers import _print
from eab.elf_inspect import parse_symbols, parse_map_file

logger = logging.getLogger(__name__)
from eab.gdb_bridge import (
    run_gdb_python,
    generate_batch_variable_reader,
)
from eab.cli.debug._helpers import _build_probe


def cmd_vars(
    *,
    elf: str,
    map_file: Optional[str] = None,
    filter_pattern: Optional[str] = None,
    json_mode: bool,
) -> int:
    """List global/static variables from ELF symbol table.

    Parses the ELF file with ``nm`` to discover all data symbols
    (global and static variables). Optionally merges with MAP file
    data for richer region/size information.

    Args:
        elf: Path to ELF binary with debug symbols.
        map_file: Optional path to GNU ld .map file.
        filter_pattern: Optional glob pattern to filter variable names.
        json_mode: Emit machine-parseable JSON output.

    Returns:
        Exit code: 0 on success, 1 on failure.
    """
    try:
        symbols = parse_symbols(elf)
    except FileNotFoundError as e:
        _print({"error": str(e)}, json_mode=json_mode)
        return 1
    except Exception as e:
        _print({"error": f"Failed to parse ELF: {e}"}, json_mode=json_mode)
        return 1

    # Optionally merge MAP file data
    map_symbols = {}
    if map_file:
        try:
            for ms in parse_map_file(map_file):
                map_symbols[ms.name] = ms
        except Exception as e:
            # MAP parsing is best-effort — warn but don't fail the command
            logger.warning("Failed to parse MAP file %s: %s", map_file, e)

    # Apply filter
    if filter_pattern:
        symbols = [s for s in symbols if fnmatch.fnmatch(s.name, filter_pattern)]

    # Build output
    results = []
    for sym in symbols:
        entry = {
            "name": sym.name,
            "address": f"0x{sym.address:08x}",
            "size": sym.size,
            "type": sym.sym_type,
            "section": sym.section,
        }
        # Enrich with MAP data if available
        if sym.name in map_symbols:
            ms = map_symbols[sym.name]
            entry["region"] = ms.region
            if ms.size > 0 and sym.size == 0:
                entry["size"] = ms.size

        results.append(entry)

    output = {
        "elf": elf,
        "count": len(results),
        "variables": results,
    }
    if filter_pattern:
        output["filter"] = filter_pattern
    if map_file:
        output["map_file"] = map_file

    _print(output, json_mode=json_mode)
    return 0


def cmd_read_vars(
    *,
    base_dir: str,
    elf: str,
    var_names: list[str],
    read_all: bool = False,
    filter_pattern: Optional[str] = None,
    device: Optional[str] = None,
    chip: str = "nrf5340",
    probe_type: str = "jlink",
    port: Optional[int] = None,
    json_mode: bool,
) -> int:
    """Read variable values from a running target via debug probe.

    Generates a GDB Python script to read the named variables (or all
    variables matching a filter) and executes it via the debug probe.

    Args:
        base_dir: Session directory for probe state files.
        elf: Path to ELF file with debug symbols.
        var_names: List of variable names to read.
        read_all: If True, read all variables (optionally filtered).
        filter_pattern: Glob pattern to filter when read_all is True.
        device: Device string (e.g., NRF5340_XXAA_APP) for J-Link.
        chip: Chip type for GDB executable selection.
        probe_type: Debug probe type ('jlink' or 'openocd').
        port: Optional GDB server port override.
        json_mode: Emit machine-parseable JSON output.

    Returns:
        Exit code: 0 on success, 1 on failure.
    """
    # If --all, discover variables from ELF first
    if read_all:
        try:
            symbols = parse_symbols(elf)
        except Exception as e:
            _print({"error": f"Failed to parse ELF: {e}"}, json_mode=json_mode)
            return 1

        if filter_pattern:
            symbols = [s for s in symbols if fnmatch.fnmatch(s.name, filter_pattern)]

        var_names = [s.name for s in symbols]

        if not var_names:
            _print(
                {
                    "error": "No variables found matching filter",
                    "filter": filter_pattern,
                },
                json_mode=json_mode,
            )
            return 1

    if not var_names:
        _print({"error": "No variable names specified"}, json_mode=json_mode)
        return 1

    # Build probe and start GDB server
    probe = _build_probe(probe_type, base_dir, chip, port)
    status = probe.start_gdb_server(device=device) if probe_type == "jlink" else probe.start_gdb_server()

    if not status.running:
        _print(
            {
                "success": False,
                "error": "Failed to start GDB server",
                "last_error": status.last_error,
            },
            json_mode=json_mode,
        )
        return 1

    try:
        # Generate and execute batch reader script
        script_content = generate_batch_variable_reader(var_names)

        with tempfile.NamedTemporaryFile(mode="w", suffix=".py", delete=False) as f:
            f.write(script_content)
            script_path = f.name

        try:
            target_port = port if port is not None else probe.gdb_port
            res = run_gdb_python(
                chip=chip,
                script_path=script_path,
                target=f"localhost:{target_port}",
                elf=elf,
            )

            output = {
                "success": res.success,
                "returncode": res.returncode,
                "gdb_path": res.gdb_path,
                "elf": elf,
                "var_count": len(var_names),
            }

            if res.json_result is not None:
                output.update(res.json_result)
            else:
                output["stdout"] = res.stdout
                output["stderr"] = res.stderr

            _print(output, json_mode=json_mode)
            return 0 if res.success else 1

        finally:
            Path(script_path).unlink(missing_ok=True)

    finally:
        probe.stop_gdb_server()
