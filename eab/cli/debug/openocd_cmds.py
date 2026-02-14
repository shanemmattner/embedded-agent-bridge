"""OpenOCD server management commands."""

from __future__ import annotations

from eab.openocd_bridge import OpenOCDBridge
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
