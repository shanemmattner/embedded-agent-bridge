"""Fault analysis commands for eabctl."""

from __future__ import annotations

from typing import Optional

from eab.debug_probes import get_debug_probe
from eab.chips.zephyr import ZephyrProfile
from eab.fault_analyzer import analyze_fault, format_report
from eab.cli.helpers import _print


def cmd_fault_analyze(
    *,
    base_dir: str,
    device: str,
    elf: Optional[str],
    chip: str,
    probe_type: str,
    json_mode: bool,
) -> int:
    """Analyze fault registers via GDB (J-Link or OpenOCD).

    Uses the pluggable decoder for the given chip to read and decode
    architecture-specific fault registers.

    Args:
        base_dir: Session directory for probe state files.
        device: Device string (e.g., NRF5340_XXAA_APP, MCXN947).
        elf: Optional path to ELF file for GDB symbols.
        chip: Chip type for GDB executable selection and decoder lookup.
        probe_type: Debug probe type ('jlink' or 'openocd').
        json_mode: Emit machine-parseable JSON output.

    Returns:
        Exit code: 0 on success, 1 if analysis found faults, 2 on error.
    """
    probe_kwargs: dict = {}

    if probe_type == "openocd":
        # Build OpenOCD config from chip profile
        profile = ZephyrProfile(variant=chip)
        ocd_cfg = profile.get_openocd_config()
        probe_kwargs["interface_cfg"] = ocd_cfg.interface_cfg
        probe_kwargs["target_cfg"] = ocd_cfg.target_cfg
        if ocd_cfg.transport:
            probe_kwargs["transport"] = ocd_cfg.transport
        probe_kwargs["extra_commands"] = ocd_cfg.extra_commands
        probe_kwargs["halt_command"] = ocd_cfg.halt_command

    probe = get_debug_probe(probe_type, base_dir=base_dir, **probe_kwargs)

    report = analyze_fault(probe, device, elf=elf, chip=chip)

    if json_mode:
        json_out: dict = {
            "fault_registers": {k: f"0x{v:08X}" for k, v in report.fault_registers.items()},
            "faults": report.faults,
            "suggestions": report.suggestions,
            "core_regs": {k: f"0x{v:08X}" for k, v in report.core_regs.items()},
            "backtrace": report.backtrace,
        }
        if report.stacked_pc is not None:
            json_out["stacked_pc"] = f"0x{report.stacked_pc:08X}"
        if report.arch:
            json_out["arch"] = report.arch
        _print(json_out, json_mode=True)
    else:
        _print(format_report(report), json_mode=False)

    return 0
