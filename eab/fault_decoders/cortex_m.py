"""ARM Cortex-M fault decoder (M0+/M3/M4/M7/M23/M33/M55).

Reads CFSR/HFSR/MMFAR/BFAR/SFSR/SFAR via GDB, decodes bitfields,
parses PSP exception frame for stacked PC, and generates suggestions.
"""

from __future__ import annotations

import re
from typing import Optional

from .base import FaultDecoder, FaultReport

# =============================================================================
# ARM v8-M / Cortex-M Fault Register Addresses
# =============================================================================

CFSR_ADDR = 0xE000ED28   # Configurable Fault Status Register
HFSR_ADDR = 0xE000ED2C   # HardFault Status Register
MMFAR_ADDR = 0xE000ED34  # MemManage Fault Address Register
BFAR_ADDR = 0xE000ED38   # BusFault Address Register
SFSR_ADDR = 0xE000EDE4   # SecureFault Status Register (M33 TrustZone)
SFAR_ADDR = 0xE000EDE8   # SecureFault Address Register (M33 TrustZone)

# =============================================================================
# CFSR Bitfield Definitions
# =============================================================================

# MemManage faults [7:0]
CFSR_MMFAULTS = {
    0: ("IACCVIOL", "Instruction access violation"),
    1: ("DACCVIOL", "Data access violation"),
    3: ("MUNSTKERR", "MemManage fault on unstacking for return from exception"),
    4: ("MSTKERR", "MemManage fault on stacking for exception entry"),
    5: ("MLSPERR", "MemManage fault during floating-point lazy state preservation"),
    7: ("MMARVALID", "MMFAR holds a valid fault address"),
}

# BusFault faults [15:8]
CFSR_BUSFAULTS = {
    8: ("IBUSERR", "Instruction bus error"),
    9: ("PRECISERR", "Precise data bus error"),
    10: ("IMPRECISERR", "Imprecise data bus error"),
    11: ("UNSTKERR", "BusFault on unstacking for return from exception"),
    12: ("STKERR", "BusFault on stacking for exception entry"),
    13: ("LSPERR", "BusFault during floating-point lazy state preservation"),
    15: ("BFARVALID", "BFAR holds a valid fault address"),
}

# UsageFault faults [31:16]
CFSR_USAGEFAULTS = {
    16: ("UNDEFINSTR", "Undefined instruction"),
    17: ("INVSTATE", "Invalid state (e.g., Thumb bit not set)"),
    18: ("INVPC", "Invalid PC load (e.g., bad EXC_RETURN)"),
    19: ("NOCP", "No coprocessor (attempted coprocessor access)"),
    20: ("STKOF", "Stack overflow detected by hardware stack limit"),
    24: ("UNALIGNED", "Unaligned memory access"),
    25: ("DIVBYZERO", "Divide by zero"),
}

# =============================================================================
# HFSR Bitfield Definitions
# =============================================================================

HFSR_BITS = {
    1: ("VECTTBL", "Vector table hard fault (bus error on vector read)"),
    30: ("FORCED", "Forced hard fault (escalated from configurable fault)"),
    31: ("DEBUGEVT", "Debug event caused hard fault"),
}

# =============================================================================
# SFSR Bitfield Definitions (TrustZone / Cortex-M33)
# =============================================================================

SFSR_BITS = {
    0: ("INVEP", "Invalid entry point (branch to non-secure code at invalid address)"),
    1: ("INVIS", "Invalid integrity signature in exception stack frame"),
    2: ("INVER", "Invalid exception return"),
    3: ("APTS", "Attribution processing table security violation"),
    4: ("INVTRAN", "Invalid transition (lazy state error)"),
    5: ("LSPERR", "Lazy state preservation error"),
    7: ("LSERR", "Lazy state error flag valid"),
}


# =============================================================================
# Bitfield Decode Functions
# =============================================================================

def decode_cfsr(value: int) -> list[str]:
    """Decode CFSR bitfields into human-readable fault strings."""
    faults = []
    all_bits = {**CFSR_MMFAULTS, **CFSR_BUSFAULTS, **CFSR_USAGEFAULTS}
    for bit, (name, desc) in sorted(all_bits.items()):
        if value & (1 << bit):
            faults.append(f"{name}: {desc}")
    return faults


def decode_hfsr(value: int) -> list[str]:
    """Decode HFSR bitfields into human-readable fault strings."""
    faults = []
    for bit, (name, desc) in sorted(HFSR_BITS.items()):
        if value & (1 << bit):
            faults.append(f"{name}: {desc}")
    return faults


def decode_sfsr(value: int) -> list[str]:
    """Decode SFSR (TrustZone SecureFault) bitfields into human-readable fault strings."""
    faults = []
    for bit, (name, desc) in sorted(SFSR_BITS.items()):
        if value & (1 << bit):
            faults.append(f"{name}: {desc}")
    return faults


def generate_suggestions(
    faults: list[str], mmfar: int, bfar: int, *, cfsr: int = 0, hfsr: int = 0,
) -> list[str]:
    """Generate actionable suggestions based on decoded faults."""
    suggestions = []
    fault_text = "\n".join(faults).lower()

    # CFSR cleared by RTOS but HFSR shows escalated fault
    if cfsr == 0 and (hfsr & (1 << 30)):
        suggestions.append(
            "CFSR was cleared by the RTOS fault handler — "
            "check RTT/serial output for the original fault details"
        )

    if "stkof" in fault_text or "stack overflow" in fault_text:
        suggestions.append("Stack overflow — increase CONFIG_MAIN_STACK_SIZE or thread stack size in prj.conf")
        suggestions.append("Check for deep recursion or large local arrays on the stack")

    if "daccviol" in fault_text or "iaccviol" in fault_text:
        if mmfar == 0 or bfar == 0:
            suggestions.append("Fault address is 0x00000000 — likely a NULL pointer dereference")
        elif mmfar < 0x100 or bfar < 0x100:
            suggestions.append(f"Fault address is very low (0x{mmfar:08X}) — likely a NULL pointer or small offset dereference")
        else:
            suggestions.append(f"Memory access violation at 0x{mmfar:08X} — check pointer validity and MPU regions")

    if "preciserr" in fault_text or "impreciserr" in fault_text:
        if bfar != 0 and bfar != 0xE000ED38:
            suggestions.append(f"Bus error accessing 0x{bfar:08X} — verify peripheral address and clock enable")
        else:
            suggestions.append("Bus error — check peripheral clock enables and address validity")

    if "undefinstr" in fault_text:
        suggestions.append("Undefined instruction — possible code corruption, wrong build target, or Thumb/ARM mode mismatch")

    if "unaligned" in fault_text:
        suggestions.append("Unaligned access — use __packed structs or memcpy for unaligned reads/writes")

    if "divbyzero" in fault_text:
        suggestions.append("Division by zero — add a zero-check before the divide operation")

    if "invstate" in fault_text:
        suggestions.append("Invalid state — Thumb bit not set in branch target (check function pointer LSB)")

    if "invpc" in fault_text:
        suggestions.append("Invalid PC load — corrupted EXC_RETURN or link register; check stack integrity")

    if "forced" in fault_text:
        suggestions.append("Hard fault was escalated from a configurable fault — check CFSR for root cause")

    if "invep" in fault_text or "invis" in fault_text or "inver" in fault_text:
        suggestions.append("TrustZone secure fault — check NS/S partition boundaries and NSC entry points")

    if not suggestions:
        suggestions.append("Inspect the backtrace and faulting address for more context")

    return suggestions


# =============================================================================
# GDB Output Parsers (Cortex-M specific)
# =============================================================================

# Matches: 0xe000ed28:	0x00000100
_GDB_MEMORY_RE = re.compile(r"0x[0-9a-fA-F]+:\s+(0x[0-9a-fA-F]+)")


def _parse_gdb_memory_read(output: str, address: int) -> Optional[int]:
    """Parse a GDB `x/wx <addr>` output line and return the value."""
    addr_hex = f"0x{address:08x}"
    for line in output.splitlines():
        if addr_hex in line.lower() or f"0x{address:x}" in line.lower():
            m = _GDB_MEMORY_RE.search(line)
            if m:
                return int(m.group(1), 16)
    m = _GDB_MEMORY_RE.search(output)
    if m:
        return int(m.group(1), 16)
    return None


def _parse_psp_frame(output: str) -> Optional[int]:
    """Parse PSP exception stack frame to extract stacked PC.

    The frame layout (8 words from PSP) is:
        r0, r1, r2, r3, r12, lr, pc, xpsr
    We want word index 6 (the stacked PC).
    """
    values: list[int] = []
    for line in output.splitlines():
        m = re.match(r"^\s*0x[0-9a-fA-F]+:\s+(.*)", line)
        if m and "0x2" in line[:20]:
            for val_m in re.finditer(r"0x([0-9a-fA-F]+)", m.group(1)):
                values.append(int(val_m.group(1), 16))
    if len(values) >= 7:
        return values[6]  # stacked PC is at index 6
    return None


# =============================================================================
# CortexMDecoder
# =============================================================================

_REGISTER_READS = [
    ("CFSR", CFSR_ADDR),
    ("HFSR", HFSR_ADDR),
    ("MMFAR", MMFAR_ADDR),
    ("BFAR", BFAR_ADDR),
    ("SFSR", SFSR_ADDR),
    ("SFAR", SFAR_ADDR),
]


class CortexMDecoder(FaultDecoder):
    """ARM Cortex-M fault decoder (all variants: M0+/M3/M4/M7/M23/M33/M55)."""

    @property
    def name(self) -> str:
        return "ARM Cortex-M"

    def gdb_commands(self) -> list[str]:
        """GDB commands to read fault registers + PSP exception frame."""
        cmds = [f"x/wx 0x{addr:08X}" for _, addr in _REGISTER_READS]
        cmds.append("x/8wx $psp")
        return cmds

    def parse_and_decode(self, gdb_output: str) -> FaultReport:
        """Parse GDB output, decode Cortex-M fault registers, generate suggestions."""
        report = FaultReport(arch="cortex-m")

        # Parse fault register values
        for name, addr in _REGISTER_READS:
            val = _parse_gdb_memory_read(gdb_output, addr) or 0
            report.fault_registers[name] = val

        cfsr = report.fault_registers.get("CFSR", 0)
        hfsr = report.fault_registers.get("HFSR", 0)
        sfsr = report.fault_registers.get("SFSR", 0)
        mmfar = report.fault_registers.get("MMFAR", 0)
        bfar = report.fault_registers.get("BFAR", 0)

        # Parse PSP exception frame
        report.stacked_pc = _parse_psp_frame(gdb_output)

        # Decode bitfields
        report.faults = decode_cfsr(cfsr) + decode_hfsr(hfsr) + decode_sfsr(sfsr)

        # Generate suggestions
        report.suggestions = generate_suggestions(
            report.faults, mmfar, bfar, cfsr=cfsr, hfsr=hfsr,
        )

        return report
