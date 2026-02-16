"""Internal helpers for debug commands."""

from __future__ import annotations

from typing import Optional

from eab.debug_probes import get_debug_probe
from eab.chips.zephyr import ZephyrProfile
from eab.debug_probes.base import DebugProbe


def _build_probe(
    probe_type: str,
    base_dir: str,
    chip: str,
    port: Optional[int] = None,
) -> DebugProbe:
    """Create a debug probe with OpenOCD or J-Link config.

    Args:
        probe_type: 'jlink' or 'openocd'.
        base_dir: Session directory for probe state files.
        chip: Chip type for ZephyrProfile lookup.
        port: Optional GDB server port override.

    Returns:
        Configured DebugProbe instance.
    """
    probe_kwargs: dict = {}
    if probe_type == "openocd":
        profile = ZephyrProfile(variant=chip)
        ocd_cfg = profile.get_openocd_config()
        probe_kwargs["interface_cfg"] = ocd_cfg.interface_cfg
        probe_kwargs["target_cfg"] = ocd_cfg.target_cfg
        if ocd_cfg.transport:
            probe_kwargs["transport"] = ocd_cfg.transport
        probe_kwargs["extra_commands"] = ocd_cfg.extra_commands
        probe_kwargs["halt_command"] = ocd_cfg.halt_command
    elif probe_type == "xds110":
        # XDS110 probe for TI C2000 — no GDB server, uses dslite
        from eab.chips.c2000 import C2000Profile
        profile = C2000Profile(variant=chip)
        probe_kwargs["dslite_path"] = profile.dslite
        probe_kwargs["ccxml"] = profile.ccxml
    elif probe_type == "jlink" and port is not None:
        probe_kwargs["port"] = port
    return get_debug_probe(probe_type, base_dir=base_dir, **probe_kwargs)
