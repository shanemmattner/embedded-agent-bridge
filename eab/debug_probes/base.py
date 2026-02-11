"""Debug probe abstraction — ABC for GDB server lifecycle.

Any debug probe that can start/stop a GDB server and expose a port
implements this interface. The fault analyzer uses it to decouple
from J-Link vs OpenOCD vs other probe types.
"""

from __future__ import annotations

from abc import ABC, abstractmethod
from dataclasses import dataclass
from typing import Optional


@dataclass(frozen=True)
class GDBServerStatus:
    """Status of a GDB server launched by a debug probe."""

    running: bool
    pid: Optional[int] = None
    port: int = 2331
    last_error: Optional[str] = None


class DebugProbe(ABC):
    """Abstract base for debug probes that provide GDB server access."""

    @abstractmethod
    def start_gdb_server(self, **kwargs) -> GDBServerStatus:
        """Start the GDB server. Returns status with port and PID."""

    @abstractmethod
    def stop_gdb_server(self) -> None:
        """Stop the GDB server."""

    @property
    @abstractmethod
    def gdb_port(self) -> int:
        """Port the GDB server listens on."""

    @property
    @abstractmethod
    def name(self) -> str:
        """Human-readable probe name (e.g. 'J-Link', 'OpenOCD')."""
