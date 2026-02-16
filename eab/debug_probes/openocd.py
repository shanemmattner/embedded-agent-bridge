"""OpenOCD debug probe — launches OpenOCD subprocess for CMSIS-DAP, ST-Link, etc."""

from __future__ import annotations

import logging
import subprocess
import time
from pathlib import Path
from typing import Optional

from .base import DebugProbe, GDBServerStatus
from ..process_utils import pid_alive, read_pid_file, cleanup_pid_file, stop_process_graceful, popen_is_alive
from ..file_utils import tail_file

logger = logging.getLogger(__name__)

DEFAULT_GDB_PORT = 3333
DEFAULT_TELNET_PORT = 4444
DEFAULT_TCL_PORT = 6666


def _scripts_dir() -> Optional[str]:
    """Find OpenOCD scripts directory."""
    for p in (
        Path("/opt/homebrew/share/openocd/scripts"),
        Path("/usr/local/share/openocd/scripts"),
    ):
        if p.exists():
            return str(p)
    return None


class OpenOCDProbe(DebugProbe):
    """Debug probe that launches OpenOCD for GDB server access.

    Supports CMSIS-DAP (MCXN947, RP2040), ST-Link (STM32), and J-Link
    interfaces via OpenOCD configuration.

    Args:
        base_dir: Directory for PID/log files.
        interface_cfg: OpenOCD interface config (e.g. 'interface/cmsis-dap.cfg').
        target_cfg: OpenOCD target config (e.g. 'target/nrf52.cfg'), or None for inline.
        transport: SWD/JTAG transport (e.g. 'swd').
        extra_commands: Additional OpenOCD commands for inline config.
        gdb_port: GDB server port (default 3333).
    """

    def __init__(
        self,
        base_dir: str,
        *,
        interface_cfg: str = "interface/cmsis-dap.cfg",
        target_cfg: Optional[str] = None,
        transport: Optional[str] = None,
        extra_commands: Optional[list[str]] = None,
        halt_command: str = "halt",
        adapter_serial: Optional[str] = None,
        gdb_port: int = DEFAULT_GDB_PORT,
        telnet_port: int = DEFAULT_TELNET_PORT,
        tcl_port: int = DEFAULT_TCL_PORT,
    ):
        self._base_dir = Path(base_dir)
        self._base_dir.mkdir(parents=True, exist_ok=True)
        self._interface_cfg = interface_cfg
        self._target_cfg = target_cfg
        self._transport = transport
        self._extra_commands = extra_commands or []
        self._halt_command = halt_command
        self._adapter_serial = adapter_serial
        self._gdb_port = gdb_port
        self._telnet_port = telnet_port
        self._tcl_port = tcl_port
        self._pid_path = self._base_dir / "openocd_probe.pid"
        self._log_path = self._base_dir / "openocd_probe.log"
        self._err_path = self._base_dir / "openocd_probe.err"
        self._proc_pid: Optional[int] = None

    def start_gdb_server(self, **kwargs) -> GDBServerStatus:
        gdb_port = kwargs.get("port", self._gdb_port)

        # Check if already running
        pid = self._read_pid()
        if pid and pid_alive(pid):
            return GDBServerStatus(running=True, pid=pid, port=gdb_port)

        scripts = _scripts_dir()
        cmd = ["openocd"]
        if scripts:
            cmd += ["-s", scripts]

        # Adapter serial (must come before interface config to select probe)
        if self._adapter_serial:
            cmd += ["-c", f"adapter serial {self._adapter_serial}"]

        # Interface config
        cmd += ["-f", self._interface_cfg] if self._interface_cfg else []

        # Transport
        if self._transport:
            cmd += ["-c", f"transport select {self._transport}"]

        # Target config or inline commands
        if self._target_cfg:
            cmd += ["-f", self._target_cfg]

        for extra in self._extra_commands:
            cmd += ["-c", extra]

        # Port configuration
        cmd += ["-c", f"gdb_port {gdb_port}"]
        cmd += ["-c", f"telnet_port {self._telnet_port}"]
        cmd += ["-c", f"tcl_port {self._tcl_port}"]
        cmd += ["-c", "init"]
        cmd += ["-c", self._halt_command]

        logger.info("Starting OpenOCD: %s", " ".join(cmd))

        self._log_path.parent.mkdir(parents=True, exist_ok=True)
        log_f = open(self._log_path, "w", encoding="utf-8")
        err_f = open(self._err_path, "w", encoding="utf-8")

        try:
            proc = subprocess.Popen(
                cmd,
                stdin=subprocess.DEVNULL,
                stdout=log_f,
                stderr=err_f,
                cwd=str(self._base_dir),
                start_new_session=True,
            )
        finally:
            log_f.close()
            err_f.close()

        self._pid_path.write_text(str(proc.pid))
        self._proc_pid = proc.pid

        # Wait for startup
        time.sleep(1.0)
        alive = pid_alive(proc.pid) and popen_is_alive(proc)
        last_error: Optional[str] = None

        if not alive:
            err_lines = tail_file(self._err_path, 20)
            last_error = "\n".join(err_lines).strip() or None
            self._cleanup_pid()
            logger.error("OpenOCD failed to start: %s", last_error)

        return GDBServerStatus(
            running=alive,
            pid=proc.pid if alive else None,
            port=gdb_port,
            last_error=last_error,
        )

    def stop_gdb_server(self) -> None:
        pid = self._read_pid()
        if not pid or not pid_alive(pid):
            self._cleanup_pid()
            return

        stop_process_graceful(pid, 5.0)
        self._cleanup_pid()
        self._proc_pid = None

    @property
    def gdb_port(self) -> int:
        return self._gdb_port

    @property
    def name(self) -> str:
        return "OpenOCD"

    def _read_pid(self) -> Optional[int]:
        pid = read_pid_file(self._pid_path)
        return pid if pid is not None else self._proc_pid

    def _cleanup_pid(self) -> None:
        cleanup_pid_file(self._pid_path)
