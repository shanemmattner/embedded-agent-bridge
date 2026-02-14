"""J-Link bridge utilities for EAB.

Manages J-Link services:
- RTT (SEGGER Real-Time Transfer) via JLinkRTTLogger subprocess — delegated to JLinkRTTManager
- SWO Viewer (Serial Wire Output / ITM trace) via subprocess
- GDB Server (J-Link GDB Server) via subprocess

JLinkBridge is the unified facade. RTT logic lives in jlink_rtt.py.
"""

from __future__ import annotations

import asyncio
import logging
import os
import subprocess
import time
from dataclasses import dataclass
from pathlib import Path
from typing import Callable, Optional

from .file_utils import read_json_file, write_json_file, tail_file
from .jlink_rtt import JLinkRTTManager, JLinkRTTStatus
from .process_utils import pid_alive, read_pid_file, cleanup_pid_file, stop_process_graceful, popen_is_alive

logger = logging.getLogger(__name__)


@dataclass(frozen=True)
class JLinkSWOStatus:
    running: bool
    pid: Optional[int]
    device: Optional[str]
    log_path: str
    last_error: Optional[str] = None


@dataclass(frozen=True)
class JLinkGDBStatus:
    running: bool
    pid: Optional[int]
    device: Optional[str]
    port: int = 2331
    swo_port: int = 2332
    telnet_port: int = 2333
    last_error: Optional[str] = None


class JLinkBridge:
    """Manages J-Link services (RTT via JLinkRTTLogger, SWO/GDB via subprocess)."""

    def __init__(self, base_dir: str | Path):
        self.base_dir = Path(base_dir)
        self.base_dir.mkdir(parents=True, exist_ok=True)

        # RTT manager (JLinkRTTLogger subprocess)
        self._rtt = JLinkRTTManager(self.base_dir)

        # SWO paths
        self.swo_pid_path = self.base_dir / "jlink_swo.pid"
        self.swo_log_path = self.base_dir / "swo.log"
        self.swo_err_path = self.base_dir / "jlink_swo.err"
        self.swo_status_path = self.base_dir / "jlink_swo.status.json"

        # GDB Server paths
        self.gdb_pid_path = self.base_dir / "jlink_gdb.pid"
        self.gdb_log_path = self.base_dir / "jlink_gdb.log"
        self.gdb_err_path = self.base_dir / "jlink_gdb.err"
        self.gdb_status_path = self.base_dir / "jlink_gdb.status.json"

    # =========================================================================
    # RTT — delegated to JLinkRTTManager
    # =========================================================================

    @property
    def rtt_log_path(self) -> Path:
        return self._rtt.rtt_log_path

    @property
    def rtt_jsonl_path(self) -> Path:
        return self._rtt.rtt_jsonl_path

    @property
    def rtt_status_path(self) -> Path:
        return self._rtt.rtt_status_path

    def rtt_status(self) -> JLinkRTTStatus:
        return self._rtt.status()

    def start_rtt(
        self,
        device: str,
        interface: str = "SWD",
        speed: int = 4000,
        rtt_channel: int = 0,
        block_address: Optional[int] = None,
        queue: Optional[asyncio.Queue] = None,
    ) -> JLinkRTTStatus:
        """Start RTT streaming via JLinkRTTLogger subprocess.

        Args:
            device: J-Link device string (e.g., NRF5340_XXAA_APP)
            interface: Debug interface (SWD or JTAG)
            speed: Interface speed in kHz
            rtt_channel: RTT channel number (default 0)
            block_address: Optional RTT control block address from .map file
            queue: Optional asyncio.Queue for plotter integration
        """
        return self._rtt.start(
            device=device,
            interface=interface,
            speed=speed,
            rtt_channel=rtt_channel,
            block_address=block_address,
            queue=queue,
        )

    def stop_rtt(self, timeout_s: float = 5.0) -> JLinkRTTStatus:
        return self._rtt.stop(timeout_s)

    def reset_rtt_target(self, wait_after_reset_s: float = 1.0) -> JLinkRTTStatus:
        """Stop RTT, reset target via pylink, restart RTT.

        Only works when RTT is active. Returns error status otherwise.
        """
        return self._rtt.reset_target(wait_after_reset_s)

    # =========================================================================
    # SWO Viewer (subprocess)
    # =========================================================================

    def swo_status(self) -> JLinkSWOStatus:
        pid = read_pid_file(self.swo_pid_path)
        running = bool(pid) and pid_alive(pid)
        if pid and not running:
            cleanup_pid_file(self.swo_pid_path)
            pid = None

        device = None
        status_data = read_json_file(self.swo_status_path)
        if status_data:
            device = status_data.get("device")

        return JLinkSWOStatus(
            running=running,
            pid=pid,
            device=device,
            log_path=str(self.swo_log_path),
        )

    def start_swo(
        self,
        device: str,
        swo_freq: int = 4000000,
        cpu_freq: int = 128000000,
        itm_port: int = 0,
    ) -> JLinkSWOStatus:
        """Start JLinkSWOViewerCLExe as a background process.
        
        Args:
            device: J-Link device string (e.g., NRF5340_XXAA_APP)
            swo_freq: SWO frequency in Hz
            cpu_freq: CPU frequency in Hz
            itm_port: ITM port number (default 0)
            
        Returns:
            JLinkSWOStatus with running state and process info
        """
        cur = self.swo_status()
        if cur.running:
            return cur

        cmd = [
            "JLinkSWOViewerCLExe",
            "-device", device,
            "-itmport", str(itm_port),
            "-swofreq", str(swo_freq),
            "-cpufreq", str(cpu_freq),
        ]

        return self._start_process(
            cmd=cmd,
            pid_path=self.swo_pid_path,
            log_path=self.swo_log_path,
            err_path=self.swo_err_path,
            status_path=self.swo_status_path,
            extra_status={"device": device, "swo_freq": swo_freq, "cpu_freq": cpu_freq},
            status_factory=lambda running, pid, last_error: JLinkSWOStatus(
                running=running,
                pid=pid,
                device=device,
                log_path=str(self.swo_log_path),
                last_error=last_error,
            ),
        )

    def stop_swo(self, timeout_s: float = 5.0) -> JLinkSWOStatus:
        self._stop_process(self.swo_pid_path, timeout_s)
        status = JLinkSWOStatus(
            running=False,
            pid=None,
            device=None,
            log_path=str(self.swo_log_path),
        )
        write_json_file(self.swo_status_path, {
            "running": False, "pid": None,
        })
        return status

    # =========================================================================
    # GDB Server (subprocess)
    # =========================================================================

    def gdb_status(self) -> JLinkGDBStatus:
        pid = read_pid_file(self.gdb_pid_path)
        running = bool(pid) and pid_alive(pid)
        if pid and not running:
            cleanup_pid_file(self.gdb_pid_path)
            pid = None

        device = None
        port = 2331
        status_data = read_json_file(self.gdb_status_path)
        if status_data:
            device = status_data.get("device")
            port = status_data.get("port", 2331)

        return JLinkGDBStatus(
            running=running,
            pid=pid,
            device=device,
            port=port,
        )

    def start_gdb_server(
        self,
        device: str,
        port: int = 2331,
        swo_port: int = 2332,
        telnet_port: int = 2333,
        speed: int = 4000,
        interface: str = "SWD",
    ) -> JLinkGDBStatus:
        """Start JLinkGDBServer as a background process.
        
        Args:
            device: J-Link device string (e.g., NRF5340_XXAA_APP)
            port: GDB server port (default 2331)
            swo_port: SWO port (default 2332)
            telnet_port: Telnet port (default 2333)
            speed: Interface speed in kHz (default 4000)
            interface: Debug interface (SWD or JTAG)
            
        Returns:
            JLinkGDBStatus with running state and process info
        """
        cur = self.gdb_status()
        if cur.running:
            return cur

        import shutil
        gdb_server_bin = shutil.which("JLinkGDBServerCLExe") or shutil.which("JLinkGDBServer") or "JLinkGDBServer"

        cmd = [
            gdb_server_bin,
            "-device", device,
            "-if", interface,
            "-speed", str(speed),
            "-port", str(port),
            "-SWOPort", str(swo_port),
            "-TelnetPort", str(telnet_port),
            "-noir",
        ]

        return self._start_process(
            cmd=cmd,
            pid_path=self.gdb_pid_path,
            log_path=self.gdb_log_path,
            err_path=self.gdb_err_path,
            status_path=self.gdb_status_path,
            extra_status={"device": device, "port": port, "swo_port": swo_port, "telnet_port": telnet_port},
            status_factory=lambda running, pid, last_error: JLinkGDBStatus(
                running=running,
                pid=pid,
                device=device,
                port=port,
                swo_port=swo_port,
                telnet_port=telnet_port,
                last_error=last_error,
            ),
        )

    def stop_gdb_server(self, timeout_s: float = 5.0) -> JLinkGDBStatus:
        self._stop_process(self.gdb_pid_path, timeout_s)
        status = JLinkGDBStatus(
            running=False,
            pid=None,
            device=None,
        )
        write_json_file(self.gdb_status_path, {
            "running": False, "pid": None,
        })
        return status

    # =========================================================================
    # Internal Helpers (for subprocess-based services: SWO, GDB)
    # =========================================================================

    def _start_process(
        self,
        *,
        cmd: list[str],
        pid_path: Path,
        log_path: Path,
        err_path: Path,
        status_path: Path,
        extra_status: dict[str, object],
        status_factory: Callable[..., object],
    ):
        """Generic background process launcher.
        
        Opens output files, launches subprocess, closes files immediately.
        
        WHY immediate file close: File handles are passed to Popen for stdout/stderr.
        The subprocess inherits these handles and keeps them open. We close our
        references immediately after Popen to avoid holding extra file descriptors.
        The subprocess continues writing to the files via its inherited handles.
        """
        log_path.parent.mkdir(parents=True, exist_ok=True)
        log_f = open(log_path, "w", encoding="utf-8")
        err_f = open(err_path, "w", encoding="utf-8")

        try:
            proc = subprocess.Popen(
                cmd,
                stdin=subprocess.DEVNULL,
                stdout=log_f,
                stderr=err_f,
                cwd=str(self.base_dir),
                start_new_session=True,
            )
        finally:
            log_f.close()
            err_f.close()
        pid_path.write_text(str(proc.pid))

        time.sleep(0.5)
        alive = pid_alive(proc.pid) and popen_is_alive(proc)
        last_error: Optional[str] = None

        if not alive:
            err_lines = tail_file(err_path, 20)
            last_error = "\n".join(err_lines).strip() or None
            cleanup_pid_file(pid_path)

        status = status_factory(alive, proc.pid if alive else None, last_error)

        payload = {
            **extra_status,
            "running": alive,
            "pid": proc.pid if alive else None,
            "last_error": last_error,
            "timestamp": time.strftime("%Y-%m-%dT%H:%M:%S", time.localtime()),
        }
        write_json_file(status_path, payload)

        return status

    def _stop_process(self, pid_path: Path, timeout_s: float = 5.0) -> None:
        """Generic background process stopper."""
        pid = read_pid_file(pid_path)
        if not pid or not pid_alive(pid):
            cleanup_pid_file(pid_path)
            return

        stop_process_graceful(pid, timeout_s)
        cleanup_pid_file(pid_path)
