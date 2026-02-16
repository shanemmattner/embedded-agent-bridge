"""XDS110 debug probe — TI's on-board debug probe for C2000 LaunchPad kits.

Uses TI's dslite CLI for target operations. The C2000 C28x ISA is not ARM,
so there is no standard GDB server. Instead, this probe provides:

1. Memory read/write via dslite subprocess calls
2. Target halt/resume/reset
3. A pseudo "GDB server" status for interface compatibility

For variable reading, use the C2000 MAP file parser + memory reads
rather than GDB (which doesn't support C28x).
"""

from __future__ import annotations

import logging
import subprocess
from pathlib import Path
from typing import Optional

from .base import DebugProbe, GDBServerStatus
from ..process_utils import pid_alive, read_pid_file, cleanup_pid_file

logger = logging.getLogger(__name__)


class XDS110Probe(DebugProbe):
    """Debug probe for TI XDS110 (C2000 LaunchPad on-board probe).

    Unlike ARM probes, XDS110 + C2000 doesn't provide a GDB server.
    The start/stop_gdb_server methods manage a dslite debug session instead.

    Args:
        base_dir: Directory for PID/log files.
        dslite_path: Path to dslite binary (auto-detected if None).
        ccxml: Path to CCXML target configuration file.
    """

    def __init__(
        self,
        base_dir: str,
        *,
        dslite_path: Optional[str] = None,
        ccxml: Optional[str] = None,
    ):
        self._base_dir = Path(base_dir)
        self._base_dir.mkdir(parents=True, exist_ok=True)
        self._dslite_path = dslite_path or "dslite"
        self._ccxml = ccxml
        self._pid_path = self._base_dir / "xds110_probe.pid"
        self._log_path = self._base_dir / "xds110_probe.log"

    def start_gdb_server(self, **kwargs) -> GDBServerStatus:
        """XDS110 doesn't provide a persistent GDB server.

        Returns a status indicating the probe is available for
        one-shot memory read/write operations via DSLite.
        Verifies connectivity using 'DSLite identifyProbe --config=<ccxml>'.
        """
        # Verify DSLite is available and XDS110 is connected
        try:
            cmd = [self._dslite_path, "identifyProbe"]
            if self._ccxml:
                cmd.append(f"--config={self._ccxml}")
            result = subprocess.run(
                cmd,
                capture_output=True,
                text=True,
                timeout=15.0,
            )
            if result.returncode == 0:
                return GDBServerStatus(running=True, pid=None, port=0)
            else:
                return GDBServerStatus(
                    running=False,
                    last_error=result.stderr.strip() or result.stdout.strip() or "XDS110 not detected",
                )
        except FileNotFoundError:
            return GDBServerStatus(
                running=False,
                last_error=f"DSLite not found at: {self._dslite_path}",
            )
        except subprocess.TimeoutExpired:
            return GDBServerStatus(
                running=False,
                last_error="DSLite identifyProbe timed out",
            )

    def stop_gdb_server(self) -> None:
        """No persistent server to stop — cleanup PID file if any."""
        cleanup_pid_file(self._pid_path)

    @property
    def gdb_port(self) -> int:
        """XDS110 doesn't use a GDB server port for C2000."""
        return 0

    @property
    def name(self) -> str:
        return "XDS110"

    def memory_read(self, address: int, size: int) -> Optional[bytes]:
        """Read memory from target via DSLite.

        DSLite v20.4 syntax: DSLite memory --config=<ccxml> --range=addr,len --output=<file>
        Reads to a temp file and returns the contents.

        Args:
            address: Memory address to read.
            size: Number of bytes to read.

        Returns:
            Raw bytes read from target, or None on failure.
        """
        import tempfile
        with tempfile.NamedTemporaryFile(suffix=".bin", delete=False) as tmp:
            tmp_path = tmp.name

        args = [
            self._dslite_path, "memory",
        ]
        if self._ccxml:
            args.append(f"--config={self._ccxml}")
        args.extend([
            f"--range=0x{address:08X},{size}",
            f"--output={tmp_path}",
        ])

        try:
            result = subprocess.run(
                args,
                capture_output=True,
                text=True,
                timeout=30.0,
            )
            if result.returncode == 0:
                data = Path(tmp_path).read_bytes()
                Path(tmp_path).unlink(missing_ok=True)
                return data
            logger.error("DSLite memory read failed: %s", result.stderr.strip())
            Path(tmp_path).unlink(missing_ok=True)
            return None
        except (FileNotFoundError, subprocess.TimeoutExpired) as e:
            logger.error("DSLite memory read error: %s", e)
            Path(tmp_path).unlink(missing_ok=True)
            return None

    def reset_target(self) -> bool:
        """Reset the C2000 target via DSLite.

        DSLite v20.4 uses 'load --config=<ccxml> --reset' for target reset.

        Returns:
            True if reset succeeded.
        """
        args = [self._dslite_path, "load"]
        if self._ccxml:
            args.append(f"--config={self._ccxml}")
        args.append("--reset")

        try:
            result = subprocess.run(
                args,
                capture_output=True,
                text=True,
                timeout=15.0,
            )
            return result.returncode == 0
        except (FileNotFoundError, subprocess.TimeoutExpired) as e:
            logger.error("DSLite reset failed: %s", e)
            return False
