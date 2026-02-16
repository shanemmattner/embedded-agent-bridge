"""CCS Scripting Debug Client — Python wrapper for the persistent debug server.

Spawns debug_server.mjs as a subprocess and communicates via JSON lines
over stdin/stdout. Provides a clean Python API for C2000 debugging.

Usage:
    client = CCSDebugClient(
        ccxml="/path/to/TMS320F280039C_LaunchPad.ccxml",
        out_file="/path/to/firmware.out",
    )
    client.connect()
    val = client.read_var("test_enabled")
    client.write_var("test_enabled", 1)
    client.close()
"""

from __future__ import annotations

import json
import logging
import subprocess
import threading
from pathlib import Path
from typing import Any, Optional

logger = logging.getLogger(__name__)

_SCRIPT_DIR = Path(__file__).parent / "ccs_scripts"
_DEBUG_SERVER = _SCRIPT_DIR / "debug_server.mjs"

# Default CCS install paths by platform
_CCS_PATHS = [
    Path("/Applications/ti/ccs2041/ccs/scripting/run.sh"),  # macOS
    Path.home() / "ti/ccs2041/ccs/scripting/run.sh",  # Linux user install
    Path("/opt/ti/ccs2041/ccs/scripting/run.sh"),  # Linux system install
]


def _find_ccs_runner() -> Optional[Path]:
    """Find the CCS Scripting runner on this system."""
    for p in _CCS_PATHS:
        if p.exists():
            return p
    return None


class CCSDebugClient:
    """Persistent debug client backed by CCS Scripting debug server."""

    def __init__(
        self,
        ccxml: str,
        out_file: Optional[str] = None,
        ccs_runner: Optional[str] = None,
        timeout: float = 15.0,
    ):
        self._ccxml = ccxml
        self._out_file = out_file
        self._timeout = timeout
        self._proc: Optional[subprocess.Popen] = None
        self._id_counter = 0
        self._lock = threading.Lock()

        if ccs_runner:
            self._runner = Path(ccs_runner)
        else:
            self._runner = _find_ccs_runner()

        if not self._runner or not self._runner.exists():
            raise FileNotFoundError(
                f"CCS Scripting runner not found. Searched: {[str(p) for p in _CCS_PATHS]}"
            )

    def connect(self) -> dict:
        """Start the debug server and connect to the target.

        Returns the ready message from the server with core list.
        """
        cmd = [str(self._runner), str(_DEBUG_SERVER), self._ccxml]
        if self._out_file:
            cmd.append(self._out_file)

        logger.info("Starting CCS debug server: %s", " ".join(cmd))
        self._proc = subprocess.Popen(
            cmd,
            stdin=subprocess.PIPE,
            stdout=subprocess.PIPE,
            stderr=subprocess.PIPE,
            text=True,
            bufsize=1,  # line buffered
        )

        # Read the ready message
        ready = self._read_response()
        if ready.get("type") == "error":
            raise RuntimeError(f"Debug server init failed: {ready.get('message')}")
        if ready.get("type") != "ready":
            raise RuntimeError(f"Unexpected init response: {ready}")

        logger.info("Connected. Cores: %s", ready.get("cores"))
        return ready

    def close(self):
        """Shut down the debug server."""
        if self._proc and self._proc.poll() is None:
            try:
                self._send_command("quit")
            except Exception:
                pass
            try:
                self._proc.wait(timeout=5)
            except subprocess.TimeoutExpired:
                self._proc.kill()
        self._proc = None

    def read_var(self, name: str) -> Any:
        """Read a variable by name (requires .out loaded for symbols)."""
        resp = self._send_command("read_var", name=name)
        return resp["value"]

    def write_var(self, name: str, value: Any) -> Any:
        """Write a variable by name. Returns verified value."""
        resp = self._send_command("write_var", name=name, value=value)
        return resp["value"]

    def read_mem(
        self, address: int, count: int = 1, bit_size: int = 16
    ) -> int | list[int]:
        """Read memory at address. Returns int for count=1, list otherwise."""
        addr_str = f"0x{address:x}"
        resp = self._send_command(
            "read_mem", address=addr_str, count=count, bitSize=bit_size
        )
        if count == 1:
            return resp["value"]
        return resp["values"]

    def write_mem(self, address: int, value: int, bit_size: int = 16) -> int:
        """Write memory at address. Returns verified value."""
        addr_str = f"0x{address:x}"
        resp = self._send_command(
            "write_mem", address=addr_str, value=value, bitSize=bit_size
        )
        return resp["value"]

    def halt(self):
        """Halt target execution."""
        return self._send_command("halt")

    def run(self):
        """Resume target execution."""
        return self._send_command("run")

    def reset(self):
        """Reset the target."""
        return self._send_command("reset")

    def status(self) -> dict:
        """Get connection status."""
        return self._send_command("status")

    def load_program(self, path: str) -> dict:
        """Load a program (.out) for symbol resolution."""
        return self._send_command("load_program", path=path)

    def list_cores(self) -> list[str]:
        """List available debug cores."""
        resp = self._send_command("list_cores")
        return resp["cores"]

    # --- Internal ---

    def _send_command(self, cmd: str, **kwargs) -> dict:
        """Send a command and return the response."""
        if not self._proc or self._proc.poll() is not None:
            raise RuntimeError("Debug server not running")

        with self._lock:
            self._id_counter += 1
            msg = {"id": self._id_counter, "cmd": cmd}
            if kwargs:
                msg["args"] = kwargs

            line = json.dumps(msg) + "\n"
            logger.debug(">>> %s", line.strip())
            self._proc.stdin.write(line)
            self._proc.stdin.flush()

            resp = self._read_response()
            logger.debug("<<< %s", resp)

            if not resp.get("ok", False) and cmd != "quit":
                raise RuntimeError(
                    f"Command '{cmd}' failed: {resp.get('error', 'unknown')}"
                )
            return resp

    def _read_response(self) -> dict:
        """Read one JSON line from stdout, skipping non-JSON lines (GEL output)."""
        if not self._proc:
            raise RuntimeError("Debug server not running")

        while True:
            line = self._proc.stdout.readline()
            if not line:
                stderr = ""
                if self._proc.stderr:
                    stderr = self._proc.stderr.read()
                raise RuntimeError(
                    f"Debug server exited unexpectedly. stderr: {stderr}"
                )

            line = line.strip()
            if not line:
                continue

            # Skip GEL output and other non-JSON lines
            if line.startswith("{"):
                try:
                    return json.loads(line)
                except json.JSONDecodeError:
                    logger.debug("Skipping malformed JSON: %s", line)
                    continue
            else:
                logger.debug("Skipping non-JSON: %s", line)
                continue

    def __enter__(self):
        self.connect()
        return self

    def __exit__(self, *_):
        self.close()

    def __del__(self):
        self.close()
