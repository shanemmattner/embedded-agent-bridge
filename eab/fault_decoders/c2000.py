"""TI C2000 fault decoder using register map + DSLite memory reads.

Unlike Cortex-M (which uses GDB), C2000 reads fault registers via DSLite
memory commands through the XDS110 probe. The register definitions come
from the f28003x.json register map — no hardcoded addresses in this file.

Decodes: NMI flags, PIE errors, reset cause, watchdog state.
"""

from __future__ import annotations

from typing import Optional

from .base import FaultDecoder, FaultReport
from ..register_maps import load_register_map
from ..register_maps.decoder import decode_register, DecodedRegister


def _generate_c2000_suggestions(
    nmi_flags: list[str],
    reset_flags: list[str],
    wd_disabled: bool,
    wd_flag: bool,
) -> list[str]:
    """Generate actionable suggestions based on C2000 fault state."""
    suggestions = []

    if "CLOCKFAIL" in nmi_flags:
        suggestions.append(
            "Clock failure detected — check external crystal, "
            "verify CLKSRCCTL1 oscillator source, inspect PLL lock"
        )

    if "RAMUNCERR" in nmi_flags:
        suggestions.append(
            "RAM uncorrectable ECC error — possible memory corruption, "
            "check for wild pointers or DMA overruns"
        )

    if "FLUNCERR" in nmi_flags:
        suggestions.append(
            "Flash uncorrectable ECC error — flash may be corrupted, "
            "try erasing and reflashing"
        )

    if "PIEVECTERR" in nmi_flags:
        suggestions.append(
            "PIE vector fetch error — interrupt vector table corrupted, "
            "check for stack overflows or wild writes near 0x0D00"
        )

    if "WDRSN" in reset_flags or "NMIWDRSN" in reset_flags:
        suggestions.append(
            "Watchdog caused reset — firmware is not servicing the watchdog, "
            "check for infinite loops or blocked ISRs"
        )

    if wd_flag and not wd_disabled:
        suggestions.append(
            "Watchdog reset status flag is set — a watchdog reset occurred "
            "since last POR. Service watchdog more frequently or increase prescaler."
        )

    if not wd_disabled:
        suggestions.append("Watchdog is enabled (WDDIS=0)")
    else:
        suggestions.append("Watchdog is disabled (WDDIS=1) — consider enabling for production")

    if not suggestions:
        suggestions.append("No active faults detected — system appears healthy")

    return suggestions


class C2000Decoder(FaultDecoder):
    """C2000 fault decoder using register maps and DSLite memory reads.

    Unlike the GDB-based CortexMDecoder, this decoder takes a memory_reader
    callable that reads target memory (typically XDS110Probe.memory_read).

    Usage:
        decoder = C2000Decoder()
        report = decoder.analyze(memory_reader, chip="f28003x")
    """

    def __init__(self, chip: str = "f28003x"):
        self._chip = chip

    @property
    def name(self) -> str:
        return "TI C2000"

    def gdb_commands(self) -> list[str]:
        """C2000 doesn't use GDB — returns empty list."""
        return []

    def parse_and_decode(self, gdb_output: str) -> FaultReport:
        """Not used for C2000 — use analyze() instead.

        Provided for interface compatibility. Returns empty report.
        """
        return FaultReport(arch="c2000")

    def analyze(
        self,
        memory_reader,
        chip: str | None = None,
    ) -> FaultReport:
        """Read and decode C2000 fault registers via memory reads.

        Args:
            memory_reader: Callable(address: int, size: int) -> bytes | None.
                Typically XDS110Probe.memory_read.
            chip: Register map name (default: "f28003x").

        Returns:
            FaultReport with decoded NMI, reset, PIE, and watchdog state.
        """
        chip_name = chip or self._chip
        regmap = load_register_map(chip_name)

        report = FaultReport(arch="c2000")
        decoded_registers: list[DecodedRegister] = []

        # Read fault registers
        fault_group = regmap.get_group("fault_registers")
        if fault_group:
            for reg in fault_group.registers.values():
                data = memory_reader(reg.address, reg.size)
                if data is not None:
                    raw = int.from_bytes(data[:reg.size], "little")
                    report.fault_registers[reg.name] = raw
                    decoded_registers.append(decode_register(reg, raw))

        # Read watchdog registers
        wd_group = regmap.get_group("watchdog")
        if wd_group:
            for reg in wd_group.registers.values():
                data = memory_reader(reg.address, reg.size)
                if data is not None:
                    raw = int.from_bytes(data[:reg.size], "little")
                    report.fault_registers[reg.name] = raw
                    decoded_registers.append(decode_register(reg, raw))

        # Collect active flags from all decoded registers
        nmi_flags: list[str] = []
        reset_flags: list[str] = []
        wd_disabled = False
        wd_flag = False

        for dreg in decoded_registers:
            if dreg.name == "NMIFLG":
                nmi_flags = dreg.active_flags
                for flag in nmi_flags:
                    report.faults.append(f"NMI: {flag}")

            elif dreg.name == "NMISHDFLG":
                if dreg.raw_value != 0:
                    report.faults.append(
                        f"NMI shadow flags latched: 0x{dreg.raw_value:04X}"
                    )

            elif dreg.name == "RESC":
                reset_flags = dreg.active_flags
                for flag in reset_flags:
                    report.faults.append(f"Reset cause: {flag}")

            elif dreg.name == "WDCR":
                for f in dreg.fields:
                    if f.name == "WDDIS":
                        wd_disabled = f.raw_value == 1
                    elif f.name == "WDFLG":
                        wd_flag = f.raw_value == 1

            elif dreg.name.startswith("PIEIFR"):
                if dreg.raw_value != 0:
                    report.faults.append(
                        f"Pending interrupts in {dreg.name}: 0x{dreg.raw_value:04X}"
                    )

        # Generate suggestions
        report.suggestions = _generate_c2000_suggestions(
            nmi_flags, reset_flags, wd_disabled, wd_flag,
        )

        return report

    def format_report(self, report: FaultReport) -> str:
        """Format a FaultReport as human-readable text."""
        lines = [f"=== {self.name} Fault Analysis ===", ""]

        if not report.faults:
            lines.append("No active faults detected.")
        else:
            lines.append("Active Faults:")
            for f in report.faults:
                lines.append(f"  - {f}")

        lines.append("")
        lines.append("Register Values:")
        for name, value in sorted(report.fault_registers.items()):
            lines.append(f"  {name:20s} = 0x{value:08X}")

        if report.suggestions:
            lines.append("")
            lines.append("Suggestions:")
            for s in report.suggestions:
                lines.append(f"  - {s}")

        return "\n".join(lines)

    def to_json(self, report: FaultReport) -> dict:
        """Convert FaultReport to JSON-serializable dict."""
        return {
            "arch": report.arch,
            "faults": report.faults,
            "registers": {
                name: f"0x{val:08X}"
                for name, val in report.fault_registers.items()
            },
            "suggestions": report.suggestions,
            "has_faults": len(report.faults) > 0,
        }
