"""Debug probe registry — factory for probe types.

Usage:
    from eab.debug_probes import get_debug_probe, DebugProbe, GDBServerStatus

    probe = get_debug_probe("openocd", base_dir="/tmp/eab-session",
                            interface_cfg="interface/cmsis-dap.cfg")
"""

from .base import DebugProbe, GDBServerStatus
from .jlink import JLinkProbe
from .openocd import OpenOCDProbe

__all__ = [
    "DebugProbe",
    "GDBServerStatus",
    "JLinkProbe",
    "OpenOCDProbe",
    "get_debug_probe",
]

_PROBES: dict[str, type[DebugProbe]] = {
    "jlink": JLinkProbe,
    "openocd": OpenOCDProbe,
}


def get_debug_probe(probe_type: str, base_dir: str, **kwargs) -> DebugProbe:
    """Create a debug probe by type name.

    Args:
        probe_type: 'jlink' or 'openocd'.
        base_dir: Session directory for state files.
        **kwargs: Passed to the probe constructor.
            For jlink: bridge (required), port.
            For openocd: interface_cfg, target_cfg, transport, extra_commands, gdb_port.

    Raises:
        ValueError: If probe_type is not registered.
    """
    cls = _PROBES.get(probe_type.lower())
    if cls is None:
        supported = ", ".join(sorted(_PROBES.keys()))
        raise ValueError(f"Unknown probe type: {probe_type!r}. Supported: {supported}")

    if cls is JLinkProbe:
        bridge = kwargs.pop("bridge", None)
        if bridge is None:
            from eab.jlink_bridge import JLinkBridge
            bridge = JLinkBridge(base_dir)
        port = kwargs.pop("port", 2331)
        return JLinkProbe(bridge=bridge, port=port)

    if cls is OpenOCDProbe:
        return OpenOCDProbe(base_dir=base_dir, **kwargs)

    return cls(base_dir=base_dir, **kwargs)
