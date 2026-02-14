"""Internal helpers for DWT profiling commands."""

from __future__ import annotations

from typing import Optional


# CPU frequency defaults by chip type (Hz)
CHIP_CPU_FREQ = {
    "nrf5340": 128_000_000,  # nRF5340 Application core at 128 MHz
    "nrf52840": 64_000_000,   # nRF52840 at 64 MHz
    "mcxn947": 150_000_000,   # MCXN947 at 150 MHz
    "stm32l4": 80_000_000,    # STM32L4 at 80 MHz
    "stm32f4": 168_000_000,   # STM32F4 typical at 168 MHz
    "stm32h7": 480_000_000,   # STM32H7 at 480 MHz
}


def _detect_cpu_freq(device: str, chip: Optional[str] = None) -> Optional[int]:
    """Auto-detect CPU frequency from device/chip string.

    Args:
        device: Device string (e.g., NRF5340_XXAA_APP, MCXN947) or None
        chip: Chip type (e.g., stm32l4, mcxn947) or None

    Returns:
        CPU frequency in Hz, or None if not recognized
    """
    for source in (device, chip):
        if source:
            source_lower = source.lower()
            for key, freq in CHIP_CPU_FREQ.items():
                if key in source_lower:
                    return freq
    return None


def _setup_openocd_probe(base_dir: str, chip: str) -> tuple:
    """Create and start an OpenOCD probe for the given chip.

    Args:
        base_dir: Session directory for probe state files.
        chip: Chip type for ZephyrProfile lookup (e.g., stm32l4, mcxn947).

    Returns:
        (probe, bridge) tuple — OpenOCDProbe and OpenOCDBridge instances.

    Raises:
        RuntimeError: If OpenOCD fails to start.
    """
    from eab.debug_probes import get_debug_probe
    from eab.chips.zephyr import ZephyrProfile
    from eab.openocd_bridge import OpenOCDBridge

    profile = ZephyrProfile(variant=chip)
    ocd_cfg = profile.get_openocd_config()

    probe = get_debug_probe(
        "openocd",
        base_dir=base_dir,
        interface_cfg=ocd_cfg.interface_cfg,
        target_cfg=ocd_cfg.target_cfg,
        transport=ocd_cfg.transport,
        extra_commands=ocd_cfg.extra_commands,
        halt_command=ocd_cfg.halt_command,
    )

    status = probe.start_gdb_server()
    if not status.running:
        raise RuntimeError(f"Failed to start OpenOCD: {status.last_error}")

    bridge = OpenOCDBridge(base_dir)
    return probe, bridge
