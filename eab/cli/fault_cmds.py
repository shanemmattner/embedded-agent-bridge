"""Fault analysis commands for eabctl."""

from __future__ import annotations

from typing import Optional

from eab.jlink_bridge import JLinkBridge
from eab.fault_analyzer import analyze_fault, format_report
from eab.fault_decoders import FaultReport
from eab.cli.helpers import _print


def cmd_fault_analyze(
    *,
    base_dir: str,
    device: str,
    elf: Optional[str],
    chip: str,
    json_mode: bool,
) -> int:
    """Analyze fault registers via J-Link GDB.

    Uses the pluggable decoder for the given chip to read and decode
    architecture-specific fault registers.

    Args:
        base_dir: Session directory for J-Link state files.
        device: J-Link device string (e.g., NRF5340_XXAA_APP).
        elf: Optional path to ELF file for GDB symbols.
        chip: Chip type for GDB executable selection and decoder lookup.
        json_mode: Emit machine-parseable JSON output.

    Returns:
        Exit code: 0 on success, 1 if analysis found faults, 2 on error.
    """
    bridge = JLinkBridge(base_dir)

    report = analyze_fault(bridge, device, elf=elf, chip=chip)

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
