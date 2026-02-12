"""OpenOCD and GDB debugging commands for eabctl."""

from __future__ import annotations

import tempfile
from pathlib import Path
from typing import Optional

from eab.openocd_bridge import OpenOCDBridge, DEFAULT_TELNET_PORT, DEFAULT_GDB_PORT, DEFAULT_TCL_PORT
from eab.gdb_bridge import (
    run_gdb_batch,
    run_gdb_python,
    generate_struct_inspector,
    generate_thread_inspector,
    generate_watchpoint_logger,
    generate_memory_dump_script,
)
from eab.debug_probes import get_debug_probe
from eab.chips.zephyr import ZephyrProfile

from eab.cli.helpers import _print


def cmd_openocd_status(*, base_dir: str, json_mode: bool) -> int:
    """Report whether OpenOCD is running and its connection details.

    Args:
        base_dir: Session directory where OpenOCD state files live.
        json_mode: Emit machine-parseable JSON output.

    Returns:
        Exit code: always 0.
    """
    bridge = OpenOCDBridge(base_dir)
    st = bridge.status()
    _print(
        {
            "running": st.running,
            "pid": st.pid,
            "cfg_path": st.cfg_path,
            "log_path": st.log_path,
            "err_path": st.err_path,
            "last_error": st.last_error,
            "telnet_port": st.telnet_port,
            "gdb_port": st.gdb_port,
            "tcl_port": st.tcl_port,
        },
        json_mode=json_mode,
    )
    return 0


def cmd_openocd_start(
    *,
    base_dir: str,
    chip: str,
    vid: str,
    pid: str,
    telnet_port: int,
    gdb_port: int,
    tcl_port: int,
    json_mode: bool,
) -> int:
    """Start OpenOCD for JTAG/SWD debugging.

    Args:
        base_dir: Session directory for OpenOCD state files.
        chip: Chip identifier used to select OpenOCD config.
        vid: USB vendor ID of the debug adapter.
        pid: USB product ID of the debug adapter.
        telnet_port: OpenOCD telnet command port.
        gdb_port: OpenOCD GDB server port.
        tcl_port: OpenOCD TCL server port.
        json_mode: Emit machine-parseable JSON output.

    Returns:
        Exit code: 0 if OpenOCD started, 1 on failure.
    """
    bridge = OpenOCDBridge(base_dir)
    st = bridge.start(
        chip=chip,
        vid=vid,
        pid=pid,
        telnet_port=telnet_port,
        gdb_port=gdb_port,
        tcl_port=tcl_port,
    )
    _print(
        {
            "running": st.running,
            "pid": st.pid,
            "cfg_path": st.cfg_path,
            "log_path": st.log_path,
            "err_path": st.err_path,
            "last_error": st.last_error,
            "telnet_port": st.telnet_port,
            "gdb_port": st.gdb_port,
            "tcl_port": st.tcl_port,
        },
        json_mode=json_mode,
    )
    return 0 if st.running else 1


def cmd_openocd_stop(*, base_dir: str, json_mode: bool) -> int:
    """Stop the running OpenOCD instance.

    Args:
        base_dir: Session directory for OpenOCD state files.
        json_mode: Emit machine-parseable JSON output.

    Returns:
        Exit code: always 0.
    """
    bridge = OpenOCDBridge(base_dir)
    st = bridge.stop()
    _print(
        {
            "running": st.running,
            "pid": st.pid,
        },
        json_mode=json_mode,
    )
    return 0


def cmd_openocd_cmd(
    *,
    base_dir: str,
    command: str,
    telnet_port: int,
    timeout_s: float,
    json_mode: bool,
) -> int:
    """Send a single command to OpenOCD via its telnet interface.

    Args:
        base_dir: Session directory for OpenOCD state files.
        command: OpenOCD command string to execute.
        telnet_port: OpenOCD telnet port to connect to.
        timeout_s: Socket timeout in seconds.
        json_mode: Emit machine-parseable JSON output.

    Returns:
        Exit code: always 0.
    """
    bridge = OpenOCDBridge(base_dir)
    out = bridge.cmd(command, telnet_port=telnet_port, timeout_s=timeout_s)
    _print({"command": command, "output": out}, json_mode=json_mode)
    return 0


def cmd_gdb(
    *,
    base_dir: str,
    chip: str,
    target: str,
    elf: Optional[str],
    gdb_path: Optional[str],
    commands: list[str],
    timeout_s: float,
    json_mode: bool,
) -> int:
    # base_dir is currently unused; included for symmetry and future session logging.
    res = run_gdb_batch(
        chip=chip,
        target=target,
        elf=elf,
        gdb_path=gdb_path,
        commands=commands,
        timeout_s=timeout_s,
    )
    _print(
        {
            "success": res.success,
            "returncode": res.returncode,
            "gdb_path": res.gdb_path,
            "stdout": res.stdout,
            "stderr": res.stderr,
        },
        json_mode=json_mode,
    )
    return 0 if res.success else 1


def cmd_gdb_script(
    *,
    base_dir: str,
    script_path: str,
    device: Optional[str],
    elf: Optional[str],
    chip: str,
    probe_type: str,
    port: Optional[int],
    json_mode: bool,
) -> int:
    """Execute a custom GDB Python script via debug probe.

    Manages GDB server lifecycle via JLinkBridge or OpenOCD and executes
    the provided Python script. The script should write results to the
    file path provided in GDB's $result_file convenience variable.

    Args:
        base_dir: Session directory for probe state files.
        script_path: Path to the GDB Python script to execute.
        device: Device string (e.g., NRF5340_XXAA_APP) for J-Link.
        elf: Optional path to ELF file for GDB symbols.
        chip: Chip type for GDB executable selection.
        probe_type: Debug probe type ('jlink' or 'openocd').
        port: Optional GDB server port override.
        json_mode: Emit machine-parseable JSON output.

    Returns:
        Exit code: 0 on success, 1 on failure.
    """
    probe_kwargs: dict = {}

    if probe_type == "openocd":
        # Build OpenOCD config from chip profile
        profile = ZephyrProfile(variant=chip)
        ocd_cfg = profile.get_openocd_config()
        probe_kwargs["interface_cfg"] = ocd_cfg.interface_cfg
        probe_kwargs["target_cfg"] = ocd_cfg.target_cfg
        if ocd_cfg.transport:
            probe_kwargs["transport"] = ocd_cfg.transport
        probe_kwargs["extra_commands"] = ocd_cfg.extra_commands
        probe_kwargs["halt_command"] = ocd_cfg.halt_command
    elif probe_type == "jlink" and port is not None:
        probe_kwargs["port"] = port

    probe = get_debug_probe(probe_type, base_dir=base_dir, **probe_kwargs)

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
        # Run the Python script
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
            "stdout": res.stdout,
            "stderr": res.stderr,
        }
        
        if res.json_result is not None:
            output["result"] = res.json_result

        _print(output, json_mode=json_mode)
        return 0 if res.success else 1

    finally:
        # Stop GDB server
        probe.stop_gdb_server()


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
    probe_kwargs: dict = {}

    if probe_type == "openocd":
        profile = ZephyrProfile(variant=chip)
        ocd_cfg = profile.get_openocd_config()
        probe_kwargs["interface_cfg"] = ocd_cfg.interface_cfg
        probe_kwargs["target_cfg"] = ocd_cfg.target_cfg
        if ocd_cfg.transport:
            probe_kwargs["transport"] = ocd_cfg.transport
        probe_kwargs["extra_commands"] = ocd_cfg.extra_commands
        probe_kwargs["halt_command"] = ocd_cfg.halt_command
    elif probe_type == "jlink" and port is not None:
        probe_kwargs["port"] = port

    probe = get_debug_probe(probe_type, base_dir=base_dir, **probe_kwargs)

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
    probe_kwargs: dict = {}

    if probe_type == "openocd":
        profile = ZephyrProfile(variant=chip)
        ocd_cfg = profile.get_openocd_config()
        probe_kwargs["interface_cfg"] = ocd_cfg.interface_cfg
        probe_kwargs["target_cfg"] = ocd_cfg.target_cfg
        if ocd_cfg.transport:
            probe_kwargs["transport"] = ocd_cfg.transport
        probe_kwargs["extra_commands"] = ocd_cfg.extra_commands
        probe_kwargs["halt_command"] = ocd_cfg.halt_command
    elif probe_type == "jlink" and port is not None:
        probe_kwargs["port"] = port

    probe = get_debug_probe(probe_type, base_dir=base_dir, **probe_kwargs)

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
    probe_kwargs: dict = {}

    if probe_type == "openocd":
        profile = ZephyrProfile(variant=chip)
        ocd_cfg = profile.get_openocd_config()
        probe_kwargs["interface_cfg"] = ocd_cfg.interface_cfg
        probe_kwargs["target_cfg"] = ocd_cfg.target_cfg
        if ocd_cfg.transport:
            probe_kwargs["transport"] = ocd_cfg.transport
        probe_kwargs["extra_commands"] = ocd_cfg.extra_commands
        probe_kwargs["halt_command"] = ocd_cfg.halt_command
    elif probe_type == "jlink" and port is not None:
        probe_kwargs["port"] = port

    probe = get_debug_probe(probe_type, base_dir=base_dir, **probe_kwargs)

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

    probe_kwargs: dict = {}

    if probe_type == "openocd":
        profile = ZephyrProfile(variant=chip)
        ocd_cfg = profile.get_openocd_config()
        probe_kwargs["interface_cfg"] = ocd_cfg.interface_cfg
        probe_kwargs["target_cfg"] = ocd_cfg.target_cfg
        if ocd_cfg.transport:
            probe_kwargs["transport"] = ocd_cfg.transport
        probe_kwargs["extra_commands"] = ocd_cfg.extra_commands
        probe_kwargs["halt_command"] = ocd_cfg.halt_command
    elif probe_type == "jlink" and port is not None:
        probe_kwargs["port"] = port

    probe = get_debug_probe(probe_type, base_dir=base_dir, **probe_kwargs)

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
