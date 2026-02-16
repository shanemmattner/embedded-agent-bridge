"""DSS (Debug Server Scripting) transport for persistent C2000 debug sessions.

Uses TI CCS 2041's native Python scripting API (cloud agent + websockets).
Keeps the JTAG session open for fast repeated reads (~1-5ms per read vs
~50ms with DSLite per-command subprocess).

Implements the same memory_read/memory_write interface as XDS110Probe so
callers can swap transports transparently.

Requirements:
    - CCS 2041+ installed (Theia-based, not Eclipse)
    - The CCS scripting Python package (auto-discovered from CCS install)
"""

from __future__ import annotations

import logging
import struct
import sys
from pathlib import Path
from typing import Optional

logger = logging.getLogger(__name__)

# Common CCS installation roots (macOS + Linux)
_CCS_SEARCH_PATHS = [
    Path("/Applications/ti/ccs2041/ccs"),
    Path("/Applications/ti/ccs2040/ccs"),
    Path("/Applications/ti/ccs/ccs"),
    Path.home() / "ti/ccs2041/ccs",
    Path.home() / "ti/ccs/ccs",
    Path("/opt/ti/ccs2041/ccs"),
    Path("/opt/ti/ccs/ccs"),
]

# Legacy dss.sh paths (for find_dss() backward compat)
_DSS_SEARCH_PATHS = [p / "ccs_base/scripting/bin/dss.sh" for p in _CCS_SEARCH_PATHS]

_BRIDGE_JS = Path(__file__).parent / "dss_bridge.js"


def find_ccs_root() -> Optional[Path]:
    """Find the CCS installation root directory.

    Returns:
        Path to CCS root (e.g. /Applications/ti/ccs2041/ccs), or None.
    """
    for p in _CCS_SEARCH_PATHS:
        scripting_pkg = p / "scripting/python/site-packages/scripting"
        if scripting_pkg.exists():
            return p
    return None


def find_dss() -> Optional[str]:
    """Find the DSS scripting shell (backward compat).

    Returns:
        Path to dss.sh, or None if not found.
    """
    for p in _DSS_SEARCH_PATHS:
        if p.exists():
            return str(p)
    return None


def _ensure_scripting_importable(ccs_root: Optional[Path] = None) -> Path:
    """Add CCS scripting site-packages to sys.path if needed.

    Returns:
        The CCS root path.

    Raises:
        FileNotFoundError: If CCS scripting not found.
    """
    ccs_root = ccs_root or find_ccs_root()
    if ccs_root is None:
        raise FileNotFoundError(
            "CCS 2041+ not found. Install TI Code Composer Studio."
        )

    site_pkg = str(ccs_root / "scripting/python/site-packages")
    if site_pkg not in sys.path:
        sys.path.insert(0, site_pkg)

    return ccs_root


class DSSTransport:
    """Persistent debug session via TI CCS scripting for high-frequency memory access.

    Uses CCS 2041's Python scripting API (cloud agent + websockets) to maintain
    a persistent JTAG session. Much faster than DSLite subprocess per command.

    Args:
        ccxml: Path to CCXML target configuration file.
        dss_path: Deprecated. Kept for backward compat (ignored).
        ccs_root: Explicit CCS root path (auto-detected if None).
        timeout: Command timeout in milliseconds.
        core_pattern: Regex pattern to match the debug core (default ".*").
    """

    def __init__(
        self,
        ccxml: str,
        dss_path: Optional[str] = None,
        ccs_root: Optional[str] = None,
        timeout: float = 10.0,
        core_pattern: str = ".*",
    ):
        self._ccxml = ccxml
        self._ccs_root = Path(ccs_root) if ccs_root else None
        self._timeout_ms = int(timeout * 1000)
        self._core_pattern = core_pattern
        self._ds = None  # scripting DS object
        self._session = None  # debug session

    def start(self) -> bool:
        """Initialize CCS scripting and connect to target.

        Returns:
            True if connected successfully.
        """
        try:
            ccs_root = _ensure_scripting_importable(self._ccs_root)
            from scripting import ScriptingOptions, initScripting

            options = ScriptingOptions(
                ccsRoot=str(ccs_root),
                timeout=self._timeout_ms,
                suppressMessages=True,
            )
            self._ds = initScripting(options)
            self._ds.configure(self._ccxml)
            self._session = self._ds.openSession(self._core_pattern)
            self._session.target.connect()
            logger.info("DSS connected to %s", self._ccxml)
            return True
        except Exception as e:
            logger.error("DSS start failed: %s", e)
            self.stop()
            return False

    def stop(self) -> None:
        """Disconnect and shut down the scripting session."""
        if self._session is not None:
            try:
                self._session.target.disconnect()
            except Exception:
                pass
            self._session = None

        if self._ds is not None:
            try:
                self._ds.shutdown()
            except Exception:
                pass
            self._ds = None

    def memory_read(self, address: int, size: int) -> Optional[bytes]:
        """Read memory from target.

        Same interface as XDS110Probe.memory_read.

        Args:
            address: Memory address (word address on C2000).
            size: Number of bytes to read.

        Returns:
            Raw bytes (little-endian), or None on failure.
        """
        if self._session is None:
            logger.error("DSS not connected")
            return None

        try:
            # C2000 is 16-bit word addressed; read() returns word values
            word_count = (size + 1) // 2
            words = self._session.memory.read(address, word_count)

            # Convert 16-bit words to byte array (little-endian)
            result = bytearray()
            for w in words:
                result.extend(struct.pack("<H", w & 0xFFFF))

            return bytes(result[:size])
        except Exception as e:
            logger.error("DSS read error at 0x%X: %s", address, e)
            return None

    def memory_write(self, address: int, data: bytes) -> bool:
        """Write memory to target.

        Args:
            address: Memory address (word address on C2000).
            data: Bytes to write.

        Returns:
            True if write succeeded.
        """
        if self._session is None:
            logger.error("DSS not connected")
            return False

        try:
            # Convert bytes to 16-bit words (little-endian)
            words = []
            for i in range(0, len(data), 2):
                lo = data[i]
                hi = data[i + 1] if i + 1 < len(data) else 0
                words.append(lo | (hi << 8))

            self._session.memory.write(address, words)
            return True
        except Exception as e:
            logger.error("DSS write error at 0x%X: %s", address, e)
            return False

    def halt(self) -> bool:
        """Halt the CPU."""
        if self._session is None:
            return False
        try:
            self._session.target.halt()
            return True
        except Exception:
            return False

    def resume(self) -> bool:
        """Resume CPU execution."""
        if self._session is None:
            return False
        try:
            self._session.target.run()
            return True
        except Exception:
            return False

    def reset(self) -> bool:
        """Reset the target."""
        if self._session is None:
            return False
        try:
            self._session.target.reset()
            return True
        except Exception:
            return False

    @property
    def is_running(self) -> bool:
        """Check if DSS session is active."""
        return self._session is not None

    def __enter__(self):
        self.start()
        return self

    def __exit__(self, *args):
        self.stop()
