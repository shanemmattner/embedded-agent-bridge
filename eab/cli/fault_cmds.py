"""Fault analysis commands for eabctl."""

from __future__ import annotations

from typing import Optional

from eab.jlink_bridge import JLinkBridge
from eab.fault_analyzer import analyze_fault, format_report, FaultReport
from eab.cli.helpers import _print


def cmd_fault_analyze(
    *,
    base_dir: str,
    device: str,
    elf: Optional[str],
    chip: str,
    json_mode: bool,
) -> int:
    """Analyze Cortex-M33 fault registers via J-Link GDB.

    Reads CFSR/HFSR/MMFAR/BFAR/SFSR/SFAR, decodes bitfields, and
    prints a structured fault diagnosis.

    Args:
        base_dir: Session directory for J-Link state files.
        device: J-Link device string (e.g., NRF5340_XXAA_APP).
        elf: Optional path to ELF file for GDB symbols.
        chip: Chip type for GDB executable selection.
        json_mode: Emit machine-parseable JSON output.

    Returns:
        Exit code: 0 on success, 1 if analysis found faults, 2 on error.
    """
    bridge = JLinkBridge(base_dir)

    report = analyze_fault(bridge, device, elf=elf, chip=chip)

    if json_mode:
        _print(
            {
                "cfsr": f"0x{report.cfsr:08X}",
                "hfsr": f"0x{report.hfsr:08X}",
                "mmfar": f"0x{report.mmfar:08X}",
                "bfar": f"0x{report.bfar:08X}",
                "sfsr": f"0x{report.sfsr:08X}",
                "sfar": f"0x{report.sfar:08X}",
                "faults": report.faults,
                "suggestions": report.suggestions,
                "core_regs": {k: f"0x{v:08X}" for k, v in report.core_regs.items()},
                "backtrace": report.backtrace,
            },
            json_mode=True,
        )
    else:
        _print(format_report(report), json_mode=False)

    return 0
