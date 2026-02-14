"""Variable and memory inspection commands via GDB."""

from __future__ import annotations

import tempfile
from pathlib import Path
from typing import Optional

from eab.gdb_bridge import (
    run_gdb_python,
    generate_struct_inspector,
    generate_thread_inspector,
    generate_watchpoint_logger,
    generate_memory_dump_script,
)
from eab.cli.helpers import _print
from eab.cli.debug._helpers import _build_probe


def cmd_inspect(
    *,
    base_dir: str,
    variable: str,
    device: Optional[str],
    elf: Optional[str],
    chip: str,
    probe_type: str,
    port: Optional[int],
    json_mode: bool,
) -> int:
    """Inspect a struct variable via GDB.

    Generates a struct inspector script on-the-fly and executes it via
    the debug probe to read struct fields from the target device.

    Args:
        base_dir: Session directory for probe state files.
        variable: Variable name to inspect (e.g., "_kernel", "g_state").
        device: Device string (e.g., NRF5340_XXAA_APP) for J-Link.
        elf: Optional path to ELF file for GDB symbols.
        chip: Chip type for GDB executable selection.
        probe_type: Debug probe type ('jlink' or 'openocd').
        port: Optional GDB server port override.
        json_mode: Emit machine-parseable JSON output.

    Returns:
        Exit code: 0 on success, 1 on failure.
    """
    probe = _build_probe(probe_type, base_dir, chip, port)

    # Start GDB server
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
        # Generate and execute inspector script
        script_content = generate_struct_inspector(
            elf_path=elf or "",
            struct_name="",  # Auto-detect from variable type
            var_name=variable,
        )

        # Write script to temp file
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
                "variable": variable,
            }

            if res.json_result is not None:
                output.update(res.json_result)
            else:
                output["stdout"] = res.stdout
                output["stderr"] = res.stderr

            _print(output, json_mode=json_mode)
            return 0 if res.success else 1

        finally:
            # Clean up temp script
            Path(script_path).unlink(missing_ok=True)

    finally:
        # Stop GDB server
        probe.stop_gdb_server()


def cmd_threads(
    *,
    base_dir: str,
    device: Optional[str],
    elf: Optional[str],
    chip: str,
    rtos: str,
    probe_type: str,
    port: Optional[int],
    json_mode: bool,
) -> int:
    """List RTOS threads via GDB.

    Generates a thread inspector script for the specified RTOS and executes
    it via the debug probe to walk thread lists and extract thread state.

    Args:
        base_dir: Session directory for probe state files.
        device: Device string (e.g., NRF5340_XXAA_APP) for J-Link.
        elf: Optional path to ELF file for GDB symbols.
        chip: Chip type for GDB executable selection.
        rtos: RTOS type (currently only 'zephyr' is supported).
        probe_type: Debug probe type ('jlink' or 'openocd').
        port: Optional GDB server port override.
        json_mode: Emit machine-parseable JSON output.

    Returns:
        Exit code: 0 on success, 1 on failure.
    """
    probe = _build_probe(probe_type, base_dir, chip, port)

    # Start GDB server
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
        # Generate and execute thread inspector script
        script_content = generate_thread_inspector(rtos=rtos)

        # Write script to temp file
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
                "rtos": rtos,
            }

            if res.json_result is not None:
                output.update(res.json_result)
            else:
                output["stdout"] = res.stdout
                output["stderr"] = res.stderr

            _print(output, json_mode=json_mode)
            return 0 if res.success else 1

        finally:
            # Clean up temp script
            Path(script_path).unlink(missing_ok=True)

    finally:
        # Stop GDB server
        probe.stop_gdb_server()


def cmd_watch(
    *,
    base_dir: str,
    variable: str,
    device: Optional[str],
    elf: Optional[str],
    chip: str,
    max_hits: int,
    probe_type: str,
    port: Optional[int],
    json_mode: bool,
) -> int:
    """Set a watchpoint on a variable and log hits with backtraces.

    Generates a watchpoint logger script and executes it via the debug
    probe. The script sets a watchpoint and continues execution, logging
    each hit with value and backtrace until max_hits is reached.

    Args:
        base_dir: Session directory for probe state files.
        variable: Variable name to watch (e.g., "g_counter").
        device: Device string (e.g., NRF5340_XXAA_APP) for J-Link.
        elf: Optional path to ELF file for GDB symbols.
        chip: Chip type for GDB executable selection.
        max_hits: Maximum number of watchpoint hits to log.
        probe_type: Debug probe type ('jlink' or 'openocd').
        port: Optional GDB server port override.
        json_mode: Emit machine-parseable JSON output.

    Returns:
        Exit code: 0 on success, 1 on failure.
    """
    probe = _build_probe(probe_type, base_dir, chip, port)

    # Start GDB server
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
        # Generate and execute watchpoint logger script
        script_content = generate_watchpoint_logger(var_name=variable, max_hits=max_hits)

        # Write script to temp file
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
                "variable": variable,
                "max_hits": max_hits,
            }

            if res.json_result is not None:
                output.update(res.json_result)
            else:
                output["stdout"] = res.stdout
                output["stderr"] = res.stderr

            _print(output, json_mode=json_mode)
            return 0 if res.success else 1

        finally:
            # Clean up temp script
            Path(script_path).unlink(missing_ok=True)

    finally:
        # Stop GDB server
        probe.stop_gdb_server()


def cmd_memdump(
    *,
    base_dir: str,
    start_addr: str,
    size: int,
    device: Optional[str],
    elf: Optional[str],
    chip: str,
    output_path: str,
    probe_type: str,
    port: Optional[int],
    json_mode: bool,
) -> int:
    """Dump a memory region to a file via GDB.

    Generates a memory dump script and executes it via the debug probe
    to read a region of memory from the target and write it to a file.

    Args:
        base_dir: Session directory for probe state files.
        start_addr: Starting memory address (hex string like "0x20000000").
        size: Number of bytes to dump.
        device: Device string (e.g., NRF5340_XXAA_APP) for J-Link.
        elf: Optional path to ELF file for GDB symbols.
        chip: Chip type for GDB executable selection.
        output_path: Path where memory dump should be written.
        probe_type: Debug probe type ('jlink' or 'openocd').
        port: Optional GDB server port override.
        json_mode: Emit machine-parseable JSON output.

    Returns:
        Exit code: 0 on success, 1 on failure.
    """
    # Parse address
    try:
        addr = int(start_addr, 0)  # Support both hex and decimal
    except ValueError:
        _print(
            {
                "success": False,
                "error": f"Invalid address: {start_addr}",
            },
            json_mode=json_mode,
        )
        return 1

    probe = _build_probe(probe_type, base_dir, chip, port)

    # Start GDB server
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
        # Generate and execute memory dump script
        script_content = generate_memory_dump_script(
            start_addr=addr,
            size=size,
            output_path=output_path,
        )

        # Write script to temp file
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
                "start_addr": start_addr,
                "size": size,
                "output_path": output_path,
            }

            if res.json_result is not None:
                output.update(res.json_result)
            else:
                output["stdout"] = res.stdout
                output["stderr"] = res.stderr

            _print(output, json_mode=json_mode)
            return 0 if res.success else 1

        finally:
            # Clean up temp script
            Path(script_path).unlink(missing_ok=True)

    finally:
        # Stop GDB server
        probe.stop_gdb_server()
