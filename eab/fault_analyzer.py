"""Cortex-M33 fault register readout and decoding via J-Link GDB.

When a Zephyr target crashes, reads CFSR/HFSR/MMFAR/BFAR/SFSR/SFAR + core
registers + backtrace, decodes bitfields, and returns a structured FaultReport
with human-readable fault descriptions and actionable suggestions.

Architecture:
    analyze_fault()
        -> JLinkBridge.start_gdb_server(device)
        -> run_gdb_batch() reads fault registers + core regs + backtrace
        -> decode_fault_registers() interprets bitfields
        -> JLinkBridge.stop_gdb_server()
        -> returns FaultReport
"""

from __future__ import annotations

import logging
import re
from dataclasses import dataclass, field
from typing import Optional

from .gdb_bridge import run_gdb_batch

logger = logging.getLogger(__name__)

# =============================================================================
# ARM v8-M / Cortex-M33 Fault Register Addresses
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
    3: ("APTS", "Attribution processing table security violation"),  # reserved on some
    4: ("INVTRAN", "Invalid transition (lazy state error)"),
    5: ("LSPERR", "Lazy state preservation error"),
    7: ("LSERR", "Lazy state error flag valid"),  # SFARVALID
}


# =============================================================================
# FaultReport Dataclass
# =============================================================================

@dataclass
class FaultReport:
    """Structured result from fault register analysis."""
    cfsr: int = 0
    hfsr: int = 0
    mmfar: int = 0
    bfar: int = 0
    sfsr: int = 0
    sfar: int = 0
    core_regs: dict[str, int] = field(default_factory=dict)
    backtrace: str = ""
    faults: list[str] = field(default_factory=list)
    suggestions: list[str] = field(default_factory=list)
    raw_gdb_output: str = ""


# =============================================================================
# Decode Functions
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


def generate_suggestions(faults: list[str], mmfar: int, bfar: int) -> list[str]:
    """Generate actionable suggestions based on decoded faults."""
    suggestions = []
    fault_text = "\n".join(faults).lower()

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
# GDB Output Parsers
# =============================================================================

# Matches: 0xe000ed28:	0x00000100
_GDB_MEMORY_RE = re.compile(r"0x[0-9a-fA-F]+:\s+(0x[0-9a-fA-F]+)")

# Matches: r0             0x20000100       536871168
_GDB_REG_RE = re.compile(r"^(\w+)\s+(0x[0-9a-fA-F]+)\s", re.MULTILINE)


def _parse_gdb_memory_read(output: str, address: int) -> Optional[int]:
    """Parse a GDB `x/wx <addr>` output line and return the value."""
    addr_hex = f"0x{address:08x}"
    # Search for line containing our address
    for line in output.splitlines():
        if addr_hex in line.lower() or f"0x{address:x}" in line.lower():
            m = _GDB_MEMORY_RE.search(line)
            if m:
                return int(m.group(1), 16)
    # Fallback: find any memory read line near our address pattern
    m = _GDB_MEMORY_RE.search(output)
    if m:
        return int(m.group(1), 16)
    return None


def _parse_gdb_registers(output: str) -> dict[str, int]:
    """Parse `info registers` output into a dict of register name -> value."""
    regs: dict[str, int] = {}
    for m in _GDB_REG_RE.finditer(output):
        name = m.group(1)
        try:
            regs[name] = int(m.group(2), 16)
        except ValueError:
            pass
    return regs


def _parse_gdb_backtrace(output: str) -> str:
    """Extract backtrace section from GDB output."""
    lines = output.splitlines()
    bt_lines = []
    in_bt = False
    for line in lines:
        # Backtrace lines start with #N
        if re.match(r"^#\d+\s", line.strip()):
            in_bt = True
            bt_lines.append(line.rstrip())
        elif in_bt:
            # End of backtrace when we hit a non-frame line
            if line.strip() and not line.strip().startswith("#"):
                break
    return "\n".join(bt_lines)


# =============================================================================
# Main Analysis Pipeline
# =============================================================================

# GDB commands to read all fault registers, core regs, and backtrace
_FAULT_GDB_COMMANDS = [
    "monitor halt",
    f"x/wx 0x{CFSR_ADDR:08X}",
    f"x/wx 0x{HFSR_ADDR:08X}",
    f"x/wx 0x{MMFAR_ADDR:08X}",
    f"x/wx 0x{BFAR_ADDR:08X}",
    f"x/wx 0x{SFSR_ADDR:08X}",
    f"x/wx 0x{SFAR_ADDR:08X}",
    "info registers",
    "bt",
]


def analyze_fault(
    bridge,
    device: str,
    *,
    elf: Optional[str] = None,
    chip: str = "nrf5340",
    port: int = 2331,
    restart_rtt: bool = False,
) -> FaultReport:
    """Full fault analysis pipeline: start GDB server, read registers, decode, stop.

    Handles J-Link single-client constraint (issue #66):
    1. Checks if RTT is running
    2. Stops RTT if needed (J-Link only allows one client)
    3. Starts GDB server, reads fault registers
    4. Stops GDB server
    5. Optionally restarts RTT

    Args:
        bridge: JLinkBridge instance
        device: J-Link device string (e.g., NRF5340_XXAA_APP)
        elf: Optional path to ELF file for symbols
        chip: Chip type for GDB selection (default: nrf5340)
        port: GDB server port (default: 2331)
        restart_rtt: Whether to restart RTT after analysis

    Returns:
        FaultReport with decoded fault information
    """
    report = FaultReport()
    rtt_was_running = False

    try:
        # Step 1: Check/stop RTT (J-Link single-client constraint)
        rtt_status = bridge.rtt_status()
        if rtt_status.running:
            logger.info("RTT is running — stopping for GDB access (J-Link single-client)")
            bridge.stop_rtt()
            rtt_was_running = True

        # Step 2: Start GDB server
        gdb_status = bridge.start_gdb_server(device=device, port=port)
        if not gdb_status.running:
            logger.error("Failed to start GDB server: %s", gdb_status.last_error)
            report.faults = [f"GDB server failed to start: {gdb_status.last_error}"]
            return report

        # Step 3: Run GDB batch to read fault registers
        target = f"localhost:{port}"
        result = run_gdb_batch(
            chip=chip,
            target=target,
            elf=elf,
            commands=_FAULT_GDB_COMMANDS,
        )
        report.raw_gdb_output = result.stdout

        if not result.success:
            logger.warning("GDB batch returned non-zero: %s", result.stderr)

        # Step 4: Parse register values from GDB output
        report.cfsr = _parse_gdb_memory_read(result.stdout, CFSR_ADDR) or 0
        report.hfsr = _parse_gdb_memory_read(result.stdout, HFSR_ADDR) or 0
        report.mmfar = _parse_gdb_memory_read(result.stdout, MMFAR_ADDR) or 0
        report.bfar = _parse_gdb_memory_read(result.stdout, BFAR_ADDR) or 0
        report.sfsr = _parse_gdb_memory_read(result.stdout, SFSR_ADDR) or 0
        report.sfar = _parse_gdb_memory_read(result.stdout, SFAR_ADDR) or 0

        # Step 5: Parse core registers and backtrace
        report.core_regs = _parse_gdb_registers(result.stdout)
        report.backtrace = _parse_gdb_backtrace(result.stdout)

        # Step 6: Decode fault registers
        report.faults = (
            decode_cfsr(report.cfsr)
            + decode_hfsr(report.hfsr)
            + decode_sfsr(report.sfsr)
        )

        # Step 7: Generate suggestions
        report.suggestions = generate_suggestions(report.faults, report.mmfar, report.bfar)

    finally:
        # Step 8: Stop GDB server
        try:
            bridge.stop_gdb_server()
        except Exception:
            logger.exception("Failed to stop GDB server")

        # Step 9: Restart RTT if it was running and requested
        if rtt_was_running and restart_rtt:
            try:
                bridge.start_rtt(device=device)
            except Exception:
                logger.exception("Failed to restart RTT")

    return report


# =============================================================================
# Report Formatter
# =============================================================================

def format_report(report: FaultReport) -> str:
    """Format a FaultReport as human-readable multi-line text."""
    lines = []
    lines.append("=" * 60)
    lines.append("CORTEX-M33 FAULT ANALYSIS")
    lines.append("=" * 60)

    lines.append("")
    lines.append("FAULT REGISTERS:")
    lines.append(f"  CFSR  = 0x{report.cfsr:08X}")
    lines.append(f"  HFSR  = 0x{report.hfsr:08X}")
    lines.append(f"  MMFAR = 0x{report.mmfar:08X}")
    lines.append(f"  BFAR  = 0x{report.bfar:08X}")
    lines.append(f"  SFSR  = 0x{report.sfsr:08X}")
    lines.append(f"  SFAR  = 0x{report.sfar:08X}")

    if report.faults:
        lines.append("")
        lines.append("DECODED FAULTS:")
        for f in report.faults:
            lines.append(f"  - {f}")

    if report.suggestions:
        lines.append("")
        lines.append("SUGGESTIONS:")
        for s in report.suggestions:
            lines.append(f"  - {s}")

    if report.core_regs:
        lines.append("")
        lines.append("CORE REGISTERS:")
        for name, val in sorted(report.core_regs.items()):
            lines.append(f"  {name:6s} = 0x{val:08X}")

    if report.backtrace:
        lines.append("")
        lines.append("BACKTRACE:")
        for bt_line in report.backtrace.splitlines():
            lines.append(f"  {bt_line}")

    lines.append("")
    lines.append("=" * 60)
    return "\n".join(lines)
