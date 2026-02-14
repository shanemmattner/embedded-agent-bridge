"""Fault analysis orchestrator — thin pipeline over pluggable decoders.

When a Zephyr target crashes, starts GDB, reads fault state via the
architecture-specific decoder, parses core registers + backtrace, and
returns a structured FaultReport with human-readable diagnostics.

Architecture:
    analyze_fault()
        -> get_fault_decoder(chip) selects decoder
        -> probe.start_gdb_server() (DebugProbe abstraction)
        -> run_gdb_batch() with decoder.gdb_commands() + info regs + bt
        -> decoder.parse_and_decode() interprets arch-specific registers
        -> probe.stop_gdb_server()
        -> returns FaultReport
"""

from __future__ import annotations

import logging
import re
from typing import Optional

from .debug_probes.base import DebugProbe
from .fault_decoders import FaultDecoder, FaultReport, get_fault_decoder
from .gdb_bridge import run_gdb_batch

logger = logging.getLogger(__name__)


# =============================================================================
# Universal GDB Output Parsers
# =============================================================================

# Matches: r0             0x20000100       536871168
_GDB_REG_RE = re.compile(r"^(\w+)\s+(0x[0-9a-fA-F]+)\s", re.MULTILINE)


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
        if re.match(r"^#\d+\s", line.strip()):
            in_bt = True
            bt_lines.append(line.rstrip())
        elif in_bt:
            if line.strip() and not line.strip().startswith("#"):
                break
    return "\n".join(bt_lines)


# =============================================================================
# Main Analysis Pipeline
# =============================================================================

def analyze_fault(
    probe: DebugProbe,
    device: str,
    *,
    decoder: Optional[FaultDecoder] = None,
    elf: Optional[str] = None,
    chip: str = "nrf5340",
    restart_rtt: bool = False,
    rtt_bridge=None,
) -> FaultReport:
    """Full fault analysis pipeline: start GDB server, read registers, decode, stop.

    J-Link single-client constraint (issue #66):
    RTT stop/start only happens if rtt_bridge is provided. OpenOCD doesn't
    have this constraint.

    Args:
        probe: DebugProbe instance.
        device: Device string (e.g., NRF5340_XXAA_APP, MCXN947)
        decoder: Optional FaultDecoder override (defaults to chip-based lookup)
        elf: Optional path to ELF file for symbols
        chip: Chip type for GDB selection and decoder lookup (default: nrf5340)
        restart_rtt: Whether to restart RTT after analysis
        rtt_bridge: Separate RTT bridge for J-Link RTT stop/start (optional)

    Returns:
        FaultReport with decoded fault information
    """
    if decoder is None:
        decoder = get_fault_decoder(chip)

    effective_port = probe.gdb_port

    report = FaultReport()
    rtt_was_running = False

    try:
        # Step 1: Check/stop RTT (only if rtt_bridge provided — J-Link constraint)
        if rtt_bridge is not None:
            rtt_status = rtt_bridge.rtt_status()
            if rtt_status.running:
                logger.info("RTT is running — stopping for GDB access (J-Link single-client)")
                rtt_bridge.stop_rtt()
                rtt_was_running = True

        # Step 2: Start GDB server via probe
        gdb_status = probe.start_gdb_server(device=device, port=effective_port)
        if not gdb_status.running:
            logger.error("Failed to start GDB server: %s", gdb_status.last_error)
            report.faults = [f"GDB server failed to start: {gdb_status.last_error}"]
            return report

        # Step 3: Build GDB command list
        commands = (
            ["monitor halt"]
            + decoder.gdb_commands()
            + ["info registers", "bt"]
        )

        # Step 4: Run GDB batch
        target = f"localhost:{effective_port}"
        result = run_gdb_batch(
            chip=chip,
            target=target,
            elf=elf,
            commands=commands,
        )
        report.raw_gdb_output = result.stdout

        if not result.success:
            logger.warning("GDB batch returned non-zero: %s", result.stderr)

        # Step 5: Decoder parses arch-specific fault registers
        report = decoder.parse_and_decode(result.stdout)
        report.raw_gdb_output = result.stdout

        # Step 6: Parse universal sections (core regs, backtrace)
        report.core_regs = _parse_gdb_registers(result.stdout)
        report.backtrace = _parse_gdb_backtrace(result.stdout)

    finally:
        # Step 7: Stop GDB server
        try:
            probe.stop_gdb_server()
        except Exception:
            logger.exception("Failed to stop GDB server")

        # Step 8: Restart RTT if it was running and requested
        if rtt_was_running and restart_rtt and rtt_bridge is not None:
            try:
                rtt_bridge.start_rtt(device=device)
            except Exception:
                logger.exception("Failed to restart RTT")

    return report


# =============================================================================
# Report Formatter
# =============================================================================

def format_report(report: FaultReport) -> str:
    """Format a FaultReport as human-readable multi-line text."""
    lines = []
    title = f"{report.arch.upper() or 'FAULT'} ANALYSIS"
    lines.append("=" * 60)
    lines.append(title)
    lines.append("=" * 60)

    if report.fault_registers:
        lines.append("")
        lines.append("FAULT REGISTERS:")
        for name, val in report.fault_registers.items():
            lines.append(f"  {name:6s} = 0x{val:08X}")
        if report.stacked_pc is not None:
            lines.append(f"  Stacked PC = 0x{report.stacked_pc:08X}  (from exception frame)")

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
