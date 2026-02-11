"""OpenOCD and GDB debugging commands for eabctl."""

from __future__ import annotations

from typing import Optional

from eab.openocd_bridge import OpenOCDBridge, DEFAULT_TELNET_PORT, DEFAULT_GDB_PORT, DEFAULT_TCL_PORT
from eab.gdb_bridge import run_gdb_batch

from eab.cli.helpers import _print


def cmd_openocd_status(*, base_dir: str, json_mode: bool) -> int:
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
