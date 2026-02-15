"""GDB batch and script execution commands."""

from __future__ import annotations

from typing import Optional

from eab.gdb_bridge import run_gdb_batch, run_gdb_python
from eab.cli.helpers import _print
from eab.cli.debug._helpers import _build_probe


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
    """Execute one-shot GDB batch commands against a running GDB server.

    Sends the provided commands to GDB in batch mode (non-interactive)
    and returns the captured output. The caller is responsible for
    starting the GDB server beforehand.

    Args:
        base_dir: Session directory (unused; kept for API symmetry).
        chip: Chip type for GDB executable selection.
        target: GDB server address (e.g., 'localhost:2331').
        elf: Optional path to ELF file for GDB symbols.
        gdb_path: Optional explicit path to GDB executable.
        commands: List of GDB commands to execute.
        timeout_s: Timeout in seconds for the GDB process.
        json_mode: Emit machine-parseable JSON output.

    Returns:
        Exit code: 0 on success, 1 on failure.
    """
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
