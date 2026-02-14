"""probe-rs bridge utilities for EAB.

Manages probe-rs CLI operations for unified debug interface across multiple probe types
(J-Link, ST-Link, CMSIS-DAP). probe-rs is a Rust-based debug toolchain that provides:
- Flash programming
- RTT (Real-Time Transfer) streaming  
- Memory read/write
- Target reset
- Probe discovery

Supported architectures: ARM Cortex-M, RISC-V
NOT supported: Xtensa (ESP32/ESP32-S3)

This is a subprocess-based wrapper, similar to jlink_bridge.py and openocd_bridge.py.
"""

from __future__ import annotations

import json
import logging
import os
import shutil
import signal
import subprocess
import time
from dataclasses import dataclass
from pathlib import Path
from typing import Optional

logger = logging.getLogger(__name__)


def _pid_alive(pid: int) -> bool:
    """Check if a process is alive."""
    try:
        os.kill(pid, 0)
        return True
    except OSError:
        return False


def _find_probe_rs() -> Optional[str]:
    """Find probe-rs CLI binary.
    
    Returns:
        Path to probe-rs binary, or None if not found.
    """
    # Check if probe-rs is on PATH
    binary = shutil.which("probe-rs")
    if binary:
        return binary
    
    # Check common installation locations
    candidates = [
        Path.home() / ".cargo" / "bin" / "probe-rs",
        Path("/usr/local/bin/probe-rs"),
        Path("/opt/homebrew/bin/probe-rs"),
    ]
    
    for path in candidates:
        if path.exists() and os.access(str(path), os.X_OK):
            return str(path)
    
    return None


@dataclass(frozen=True)
class ProbeInfo:
    """Information about a connected probe."""
    identifier: str
    vendor_id: str
    product_id: str
    serial_number: Optional[str]
    probe_type: str  # "JLink", "STLink", "CMSIS-DAP", etc.


@dataclass(frozen=True)
class ProbeRsRTTStatus:
    """Status of probe-rs RTT streaming."""
    running: bool
    pid: Optional[int]
    chip: Optional[str]
    channel: int
    log_path: str
    last_error: Optional[str] = None


class ProbeRsBackend:
    """Wrapper for probe-rs CLI operations.
    
    Provides unified interface for:
    - Flash programming
    - RTT streaming
    - Memory operations  
    - Target reset
    - Probe discovery
    """

    def __init__(self, base_dir: str | Path):
        """Initialize probe-rs backend.
        
        Args:
            base_dir: Directory for state files, logs, and PIDs.
        """
        self.base_dir = Path(base_dir)
        self.base_dir.mkdir(parents=True, exist_ok=True)
        
        # RTT process state
        self.rtt_pid_path = self.base_dir / "probe_rs_rtt.pid"
        self.rtt_log_path = self.base_dir / "probe_rs_rtt.log"
        self.rtt_err_path = self.base_dir / "probe_rs_rtt.err"
        self.rtt_status_path = self.base_dir / "probe_rs_rtt.status.json"
        
        # Check if probe-rs is available
        self._probe_rs_bin = _find_probe_rs()
        if not self._probe_rs_bin:
            logger.warning("probe-rs not found. Install with: cargo install probe-rs --features cli")

    def is_available(self) -> bool:
        """Check if probe-rs is installed and available.
        
        Returns:
            True if probe-rs binary is found.
        """
        return self._probe_rs_bin is not None

    def flash(
        self,
        firmware_path: str,
        chip: str,
        *,
        verify: bool = True,
        reset_halt: bool = False,
        probe_selector: Optional[str] = None,
        timeout: float = 120.0,
    ) -> subprocess.CompletedProcess:
        """Flash firmware to target using probe-rs.
        
        Args:
            firmware_path: Path to firmware file (.bin, .elf, .hex).
            chip: Target chip identifier (e.g., "nrf52840", "stm32f407vg").
            verify: Verify flash after write (default: True).
            reset_halt: Reset and halt target after flash (default: False).
            probe_selector: Probe selector string (e.g., "VID:PID" or "VID:PID:Serial").
            timeout: Command timeout in seconds.
            
        Returns:
            subprocess.CompletedProcess with returncode, stdout, stderr.
            
        Raises:
            FileNotFoundError: If probe-rs is not installed.
            subprocess.TimeoutExpired: If flash operation times out.
        """
        if not self._probe_rs_bin:
            raise FileNotFoundError(
                "probe-rs not found. Install with: cargo install probe-rs --features cli"
            )
        
        cmd = [self._probe_rs_bin, "download", firmware_path, "--chip", chip]
        
        if verify:
            cmd.append("--verify")
        
        if reset_halt:
            cmd.append("--reset-halt")
        
        if probe_selector:
            cmd.extend(["--probe", probe_selector])
        
        logger.info("Flashing with probe-rs: %s", " ".join(cmd))
        
        result = subprocess.run(
            cmd,
            capture_output=True,
            text=True,
            timeout=timeout,
        )
        
        if result.returncode == 0:
            logger.info("Flash successful")
        else:
            logger.error("Flash failed: %s", result.stderr)
        
        return result

    def reset(
        self,
        chip: str,
        *,
        halt: bool = False,
        probe_selector: Optional[str] = None,
        timeout: float = 30.0,
    ) -> subprocess.CompletedProcess:
        """Reset target device.
        
        Args:
            chip: Target chip identifier.
            halt: Halt target after reset (default: False).
            probe_selector: Probe selector string.
            timeout: Command timeout in seconds.
            
        Returns:
            subprocess.CompletedProcess with returncode, stdout, stderr.
            
        Raises:
            FileNotFoundError: If probe-rs is not installed.
            subprocess.TimeoutExpired: If reset operation times out.
        """
        if not self._probe_rs_bin:
            raise FileNotFoundError(
                "probe-rs not found. Install with: cargo install probe-rs --features cli"
            )
        
        cmd = [self._probe_rs_bin, "reset", "--chip", chip]
        
        if halt:
            cmd.append("--halt")
        
        if probe_selector:
            cmd.extend(["--probe", probe_selector])
        
        logger.info("Resetting with probe-rs: %s", " ".join(cmd))
        
        result = subprocess.run(
            cmd,
            capture_output=True,
            text=True,
            timeout=timeout,
        )
        
        if result.returncode == 0:
            logger.info("Reset successful")
        else:
            logger.error("Reset failed: %s", result.stderr)
        
        return result

    def start_rtt(
        self,
        chip: str,
        *,
        channel: int = 0,
        probe_selector: Optional[str] = None,
    ) -> ProbeRsRTTStatus:
        """Start RTT streaming as a background process.
        
        Args:
            chip: Target chip identifier.
            channel: RTT up channel number (default: 0).
            probe_selector: Probe selector string.
            
        Returns:
            ProbeRsRTTStatus with running state and process info.
        """
        # Check current status
        current = self.rtt_status()
        if current.running:
            logger.warning("RTT already running (PID %s)", current.pid)
            return current
        
        if not self._probe_rs_bin:
            return ProbeRsRTTStatus(
                running=False,
                pid=None,
                chip=None,
                channel=0,
                log_path=str(self.rtt_log_path),
                last_error="probe-rs not found. Install with: cargo install probe-rs --features cli",
            )
        
        cmd = [self._probe_rs_bin, "rtt", "--chip", chip, "--up", str(channel)]
        
        if probe_selector:
            cmd.extend(["--probe", probe_selector])
        
        logger.info("Starting RTT: %s", " ".join(cmd))
        
        # Open log files
        self.rtt_log_path.parent.mkdir(parents=True, exist_ok=True)
        log_f = open(self.rtt_log_path, "w", encoding="utf-8")
        err_f = open(self.rtt_err_path, "w", encoding="utf-8")
        
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
        
        # Save PID
        self.rtt_pid_path.write_text(str(proc.pid))
        
        # Check if process started successfully
        time.sleep(0.5)
        alive = _pid_alive(proc.pid) and (proc.poll() is None)
        last_error: Optional[str] = None
        
        if not alive:
            # Process died immediately - read error
            try:
                err_lines = self.rtt_err_path.read_text(encoding="utf-8", errors="replace").splitlines()[-20:]
                last_error = "\n".join(err_lines).strip() or None
            except Exception:
                last_error = None
            self._cleanup_pid(self.rtt_pid_path)
        
        # Write status file
        status = ProbeRsRTTStatus(
            running=alive,
            pid=proc.pid if alive else None,
            chip=chip if alive else None,
            channel=channel,
            log_path=str(self.rtt_log_path),
            last_error=last_error,
        )
        self._write_status(status)
        
        return status

    def stop_rtt(self, timeout_s: float = 5.0) -> ProbeRsRTTStatus:
        """Stop RTT streaming process.
        
        Args:
            timeout_s: Timeout for graceful shutdown (SIGTERM).
            
        Returns:
            ProbeRsRTTStatus with stopped state.
        """
        self._stop_process(self.rtt_pid_path, timeout_s)
        
        status = ProbeRsRTTStatus(
            running=False,
            pid=None,
            chip=None,
            channel=0,
            log_path=str(self.rtt_log_path),
        )
        self._write_status(status)
        
        return status

    def rtt_status(self) -> ProbeRsRTTStatus:
        """Get current RTT streaming status.
        
        Returns:
            ProbeRsRTTStatus with current state.
        """
        pid = self._read_pid(self.rtt_pid_path)
        running = bool(pid) and _pid_alive(pid)
        
        if pid and not running:
            # Stale PID file
            self._cleanup_pid(self.rtt_pid_path)
            pid = None
        
        # Read status file
        chip = None
        channel = 0
        status_data = self._read_status_file(self.rtt_status_path)
        if status_data:
            chip = status_data.get("chip")
            channel = status_data.get("channel", 0)
        
        return ProbeRsRTTStatus(
            running=running,
            pid=pid,
            chip=chip,
            channel=channel,
            log_path=str(self.rtt_log_path),
        )

    def read_memory(
        self,
        address: int,
        length: int,
        chip: str,
        *,
        probe_selector: Optional[str] = None,
        timeout: float = 30.0,
    ) -> bytes:
        """Read memory from target device.
        
        Args:
            address: Memory address to read from.
            length: Number of bytes to read.
            chip: Target chip identifier.
            probe_selector: Probe selector string.
            timeout: Command timeout in seconds.
            
        Returns:
            Bytes read from memory.
            
        Raises:
            FileNotFoundError: If probe-rs is not installed.
            subprocess.TimeoutExpired: If read operation times out.
            RuntimeError: If read operation fails.
        """
        if not self._probe_rs_bin:
            raise FileNotFoundError(
                "probe-rs not found. Install with: cargo install probe-rs --features cli"
            )
        
        cmd = [
            self._probe_rs_bin,
            "read",
            str(address),
            str(length),
            "--chip",
            chip,
        ]
        
        if probe_selector:
            cmd.extend(["--probe", probe_selector])
        
        logger.info("Reading memory: %s", " ".join(cmd))
        
        result = subprocess.run(
            cmd,
            capture_output=True,
            timeout=timeout,
        )
        
        if result.returncode != 0:
            raise RuntimeError(f"Memory read failed: {result.stderr.decode('utf-8', errors='replace')}")
        
        return result.stdout

    def list_probes(self) -> list[ProbeInfo]:
        """List all connected debug probes.
        
        Returns:
            List of ProbeInfo objects for connected probes.
            
        Raises:
            FileNotFoundError: If probe-rs is not installed.
        """
        if not self._probe_rs_bin:
            raise FileNotFoundError(
                "probe-rs not found. Install with: cargo install probe-rs --features cli"
            )
        
        cmd = [self._probe_rs_bin, "list"]
        
        logger.debug("Listing probes: %s", " ".join(cmd))
        
        result = subprocess.run(
            cmd,
            capture_output=True,
            text=True,
            timeout=10.0,
        )
        
        if result.returncode != 0:
            logger.error("Failed to list probes: %s", result.stderr)
            return []
        
        # Parse output - format varies, parse best-effort
        probes = []
        for line in result.stdout.splitlines():
            line = line.strip()
            if not line or line.startswith("The following"):
                continue
            
            # Example line: "[0]: J-Link (J-Link) (VID: 1366, PID: 1015, Serial: 12345678)"
            # Parse identifier, type, VID, PID, serial
            if ":" in line and "(" in line:
                parts = line.split(":", 1)
                if len(parts) == 2:
                    identifier = parts[0].strip()
                    rest = parts[1].strip()
                    
                    # Extract probe type (first parenthetical)
                    probe_type = "Unknown"
                    if "(" in rest:
                        type_start = rest.index("(") + 1
                        type_end = rest.index(")", type_start)
                        probe_type = rest[type_start:type_end]
                    
                    # Extract VID, PID, Serial from remaining text
                    vid = "0000"
                    pid = "0000"
                    serial = None
                    
                    if "VID:" in rest:
                        vid_start = rest.index("VID:") + 4
                        vid_part = rest[vid_start:].split(",")[0].strip()
                        vid = vid_part.split()[0]
                    
                    if "PID:" in rest:
                        pid_start = rest.index("PID:") + 4
                        pid_part = rest[pid_start:].split(",")[0].strip()
                        pid = pid_part.split()[0]
                    
                    if "Serial:" in rest:
                        serial_start = rest.index("Serial:") + 7
                        serial_part = rest[serial_start:].split(")")[0].strip()
                        serial = serial_part if serial_part else None
                    
                    probes.append(ProbeInfo(
                        identifier=identifier,
                        vendor_id=vid,
                        product_id=pid,
                        serial_number=serial,
                        probe_type=probe_type,
                    ))
        
        return probes

    def chip_info(self, chip: str) -> dict:
        """Get information about a chip.
        
        Args:
            chip: Target chip identifier.
            
        Returns:
            Dictionary with chip information.
            
        Raises:
            FileNotFoundError: If probe-rs is not installed.
        """
        if not self._probe_rs_bin:
            raise FileNotFoundError(
                "probe-rs not found. Install with: cargo install probe-rs --features cli"
            )
        
        cmd = [self._probe_rs_bin, "chip", "info", chip]
        
        logger.debug("Getting chip info: %s", " ".join(cmd))
        
        result = subprocess.run(
            cmd,
            capture_output=True,
            text=True,
            timeout=10.0,
        )
        
        if result.returncode != 0:
            return {
                "error": result.stderr,
                "chip": chip,
            }
        
        # Parse output - format is not machine-readable, return raw text
        return {
            "chip": chip,
            "info": result.stdout,
        }

    # =========================================================================
    # Internal Helpers
    # =========================================================================

    def _stop_process(self, pid_path: Path, timeout_s: float = 5.0) -> None:
        """Generic background process stopper."""
        pid = self._read_pid(pid_path)
        if not pid or not _pid_alive(pid):
            self._cleanup_pid(pid_path)
            return
        
        try:
            os.kill(pid, signal.SIGTERM)
        except OSError:
            pass
        
        deadline = time.time() + timeout_s
        while time.time() < deadline:
            if not _pid_alive(pid):
                break
            time.sleep(0.1)
        
        if _pid_alive(pid):
            try:
                os.kill(pid, signal.SIGKILL)
            except OSError:
                pass
        
        self._cleanup_pid(pid_path)

    def _read_pid(self, path: Path) -> Optional[int]:
        """Read PID from a file, return None if missing or invalid."""
        if not path.exists():
            return None
        try:
            return int(path.read_text().strip())
        except (ValueError, OSError):
            return None

    def _cleanup_pid(self, path: Path) -> None:
        """Remove a PID file if it exists."""
        try:
            path.unlink(missing_ok=True)
        except OSError:
            pass

    def _read_status_file(self, path: Path) -> Optional[dict]:
        """Read JSON status file, return None if missing or invalid."""
        if not path.exists():
            return None
        try:
            return json.loads(path.read_text(encoding="utf-8"))
        except (json.JSONDecodeError, OSError):
            return None

    def _write_status(self, status: ProbeRsRTTStatus) -> None:
        """Write RTT status to JSON file."""
        payload = {
            "running": status.running,
            "pid": status.pid,
            "chip": status.chip,
            "channel": status.channel,
            "log_path": status.log_path,
            "last_error": status.last_error,
            "timestamp": time.strftime("%Y-%m-%dT%H:%M:%S", time.localtime()),
        }
        self.rtt_status_path.write_text(json.dumps(payload, indent=2, sort_keys=True))
