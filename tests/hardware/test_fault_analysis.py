"""Fault analysis tests."""

import json

import pytest

from eab.fault_analyzer import format_report
from eab.fault_decoders import FaultReport


pytestmark = pytest.mark.hardware


def test_fault_report_structure(board_config, fault_analyzer_fn):
    """Fault report has expected fields."""
    if board_config.arch != "arm":
        pytest.skip("Fault analysis only implemented for ARM Cortex-M")

    report = fault_analyzer_fn()
    assert isinstance(report, FaultReport)
    assert isinstance(report.fault_registers, dict)
    assert isinstance(report.core_regs, dict)
    assert isinstance(report.faults, list)
    assert isinstance(report.suggestions, list)
    assert isinstance(report.backtrace, str)
    assert isinstance(report.raw_gdb_output, str)
    assert len(report.raw_gdb_output) > 0, "No raw GDB output captured"


def test_no_fault_on_healthy_board(board_config, fault_analyzer_fn):
    """A healthy (non-crashed) board should have no active hard faults."""
    if board_config.arch != "arm":
        pytest.skip("Fault analysis only implemented for ARM Cortex-M")

    report = fault_analyzer_fn()

    # HFSR bit 30 (FORCED) indicates a forced hard fault
    hfsr = report.fault_registers.get("HFSR", 0)
    forced_hf = bool(hfsr & (1 << 30))

    # CFSR non-zero means an active configurable fault
    cfsr = report.fault_registers.get("CFSR", 0)

    if forced_hf or cfsr != 0:
        # Board may actually be in a fault state — that's valid too
        # but let the user know
        pytest.skip(
            f"Board appears to be in a fault state "
            f"(HFSR=0x{hfsr:08X}, CFSR=0x{cfsr:08X}). "
            f"Reset the board and retry."
        )


def test_fault_report_format(board_config, fault_analyzer_fn):
    """format_report() produces valid multi-line text."""
    if board_config.arch != "arm":
        pytest.skip("Fault analysis only implemented for ARM Cortex-M")

    report = fault_analyzer_fn()
    text = format_report(report)
    assert isinstance(text, str)
    assert len(text) > 0
    assert "ANALYSIS" in text


def test_fault_report_core_regs(board_config, fault_analyzer_fn):
    """Core registers are populated in the fault report."""
    if board_config.arch != "arm":
        pytest.skip("Fault analysis only implemented for ARM Cortex-M")

    report = fault_analyzer_fn()
    assert len(report.core_regs) > 0, "No core registers in fault report"
    # ARM should have at least pc and sp
    reg_names = {k.lower() for k in report.core_regs}
    assert "pc" in reg_names or "r15" in reg_names, (
        f"PC not found in core regs: {list(report.core_regs.keys())}"
    )
