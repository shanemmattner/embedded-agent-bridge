"""DSS (Debug Server Scripting) transport for persistent C2000 debug sessions.

Wraps TI's dss.sh + dss_bridge.js as a subprocess with JSON stdin/stdout
protocol. Keeps the JTAG session open for fast repeated reads (~1-5ms per
read vs ~50ms with DSLite per-command subprocess).

Implements the same memory_read/memory_write interface as XDS110Probe so
callers can swap transports transparently.
"""

from __future__ import annotations

import json
import logging
import shutil
import subprocess
from pathlib import Path
from typing import Optional

logger = logging.getLogger(__name__)

# Common CCS dss.sh paths (macOS + Linux)
_DSS_SEARCH_PATHS = [
    Path("/Applications/ti/ccs2041/ccs/ccs_base/scripting/bin/dss.sh"),
    Path("/Applications/ti/ccs2040/ccs/ccs_base/scripting/bin/dss.sh"),
    Path("/Applications/ti/ccs/ccs/ccs_base/scripting/bin/dss.sh"),
    Path.home() / "ti/ccs2041/ccs/ccs_base/scripting/bin/dss.sh",
    Path.home() / "ti/ccs/ccs/ccs_base/scripting/bin/dss.sh",
    Path("/opt/ti/ccs2041/ccs/ccs_base/scripting/bin/dss.sh"),
    Path("/opt/ti/ccs/ccs/ccs_base/scripting/bin/dss.sh"),
]

_BRIDGE_JS = Path(__file__).parent / "dss_bridge.js"


def find_dss() -> Optional[str]:
    """Find the DSS scripting shell (dss.sh / dss.bat).

    Returns:
        Path to dss.sh, or None if not found.
    """
    # Check PATH first
    for name in ("dss.sh", "dss.bat"):
        found = shutil.which(name)
        if found:
            return found

    # Search CCS installations
    for p in _DSS_SEARCH_PATHS:
        if p.exists():
            return str(p)

    return None


class DSSTransport:
    """Persistent debug session via TI DSS for high-frequency memory access.

    Launches dss.sh with dss_bridge.js and communicates via JSON over
    stdin/stdout. The JTAG session stays open between commands.

    Args:
        ccxml: Path to CCXML target configuration file.
        dss_path: Explicit path to dss.sh (auto-detected if None).
        timeout: Command timeout in seconds.
    """

    def __init__(
        self,
        ccxml: str,
        dss_path: Optional[str] = None,
        timeout: float = 10.0,
    ):
        self._ccxml = ccxml
        self._dss_path = dss_path or find_dss()
        self._timeout = timeout
        self._proc: Optional[subprocess.Popen] = None

    def start(self) -> bool:
        """Launch DSS subprocess with bridge script.

        Returns:
            True if DSS connected successfully.

        Raises:
            FileNotFoundError: If dss.sh or bridge script not found.
        """
        if self._dss_path is None:
            raise FileNotFoundError(
                "DSS not found. Install TI Code Composer Studio."
            )

        if not _BRIDGE_JS.exists():
            raise FileNotFoundError(f"Bridge script not found: {_BRIDGE_JS}")

        self._proc = subprocess.Popen(
            [self._dss_path, str(_BRIDGE_JS), self._ccxml],
            stdin=subprocess.PIPE,
            stdout=subprocess.PIPE,
            stderr=subprocess.PIPE,
            text=True,
        )

        # Wait for "connected" status
        try:
            response = self._read_response()
            if response and response.get("ok") and response.get("status") == "connected":
                logger.info("DSS connected to %s", self._ccxml)
                return True
            logger.error("DSS connect failed: %s", response)
            return False
        except Exception as e:
            logger.error("DSS start failed: %s", e)
            self.stop()
            return False

    def stop(self) -> None:
        """Send quit command and terminate subprocess."""
        if self._proc is None:
            return

        try:
            self._send_command({"cmd": "quit"})
        except Exception:
            pass

        try:
            self._proc.terminate()
            self._proc.wait(timeout=5)
        except Exception:
            try:
                self._proc.kill()
            except Exception:
                pass

        self._proc = None

    def _send_command(self, cmd: dict) -> dict:
        """Send JSON command to DSS, read JSON response.

        Args:
            cmd: Command dict (e.g., {"cmd": "read", "addr": 0xC002, "size": 4}).

        Returns:
            Response dict from DSS.

        Raises:
            RuntimeError: If DSS is not running or communication fails.
        """
        if self._proc is None or self._proc.poll() is not None:
            raise RuntimeError("DSS process is not running")

        line = json.dumps(cmd) + "\n"
        self._proc.stdin.write(line)
        self._proc.stdin.flush()

        return self._read_response()

    def _read_response(self) -> dict:
        """Read one JSON line from DSS stdout.

        Returns:
            Parsed JSON response dict.

        Raises:
            RuntimeError: On timeout or parse error.
        """
        if self._proc is None:
            raise RuntimeError("DSS process is not running")

        # Use a simple readline with the process
        line = self._proc.stdout.readline()
        if not line:
            stderr = ""
            try:
                stderr = self._proc.stderr.read()
            except Exception:
                pass
            raise RuntimeError(f"DSS process closed. stderr: {stderr}")

        try:
            return json.loads(line.strip())
        except json.JSONDecodeError as e:
            raise RuntimeError(f"Invalid JSON from DSS: {line.strip()!r}") from e

    def memory_read(self, address: int, size: int) -> Optional[bytes]:
        """Read memory from target.

        Same interface as XDS110Probe.memory_read.

        Args:
            address: Memory address (word address on C2000).
            size: Number of bytes to read.

        Returns:
            Raw bytes, or None on failure.
        """
        try:
            response = self._send_command({
                "cmd": "read",
                "addr": address,
                "size": size,
            })
            if response.get("ok") and "data" in response:
                return bytes(response["data"])
            logger.error("DSS read failed: %s", response.get("error", "unknown"))
            return None
        except Exception as e:
            logger.error("DSS read error: %s", e)
            return None

    def memory_write(self, address: int, data: bytes) -> bool:
        """Write memory to target.

        Args:
            address: Memory address (word address on C2000).
            data: Bytes to write.

        Returns:
            True if write succeeded.
        """
        try:
            response = self._send_command({
                "cmd": "write",
                "addr": address,
                "data": list(data),
            })
            return response.get("ok", False)
        except Exception as e:
            logger.error("DSS write error: %s", e)
            return False

    def halt(self) -> bool:
        """Halt the CPU."""
        try:
            return self._send_command({"cmd": "halt"}).get("ok", False)
        except Exception:
            return False

    def resume(self) -> bool:
        """Resume CPU execution."""
        try:
            return self._send_command({"cmd": "resume"}).get("ok", False)
        except Exception:
            return False

    def reset(self) -> bool:
        """Reset the target."""
        try:
            return self._send_command({"cmd": "reset"}).get("ok", False)
        except Exception:
            return False

    @property
    def is_running(self) -> bool:
        """Check if DSS subprocess is alive."""
        return self._proc is not None and self._proc.poll() is None

    def __enter__(self):
        self.start()
        return self

    def __exit__(self, *args):
        self.stop()
