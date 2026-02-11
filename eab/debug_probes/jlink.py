"""J-Link debug probe — thin wrapper around JLinkBridge GDB server methods."""

from __future__ import annotations

from .base import DebugProbe, GDBServerStatus


class JLinkProbe(DebugProbe):
    """Adapts JLinkBridge to the DebugProbe interface.

    Delegates start/stop to the existing JLinkBridge subprocess manager.
    Default port: 2331 (JLinkGDBServer default).
    """

    def __init__(self, bridge, port: int = 2331):
        self._bridge = bridge
        self._port = port

    def start_gdb_server(self, **kwargs) -> GDBServerStatus:
        device = kwargs.get("device", "")
        port = kwargs.get("port", self._port)
        status = self._bridge.start_gdb_server(device=device, port=port)
        return GDBServerStatus(
            running=status.running,
            pid=status.pid,
            port=status.port,
            last_error=status.last_error,
        )

    def stop_gdb_server(self) -> None:
        self._bridge.stop_gdb_server()

    @property
    def gdb_port(self) -> int:
        return self._port

    @property
    def name(self) -> str:
        return "J-Link"

    @property
    def bridge(self):
        """Access the underlying JLinkBridge (for RTT operations)."""
        return self._bridge
