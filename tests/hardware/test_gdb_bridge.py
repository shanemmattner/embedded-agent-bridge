"""GDB bridge operation tests."""

import re

import pytest


pytestmark = pytest.mark.hardware


def test_register_read(board_config, gdb):
    """Read core registers — should be present and PC should be non-zero.

    SP/LR/RA may be zero on RISC-V boards with no firmware loaded,
    so we only assert non-zero for PC.
    """
    if board_config.arch == "arm":
        regs = ["pc", "sp", "lr"]
    else:
        regs = ["pc", "sp", "ra"]

    result = gdb.cmd("info registers")
    assert result.success, f"info registers failed: {result.stderr}"

    for reg in regs:
        pattern = rf"^{reg}\s+(0x[0-9a-fA-F]+)"
        match = re.search(pattern, result.stdout, re.MULTILINE)
        assert match, f"Register {reg!r} not found in output"
        value = int(match.group(1), 16)
        if reg == "pc":
            assert value != 0, f"PC is zero — target may not be running"


def test_memory_read(board_config, gdb):
    """Read SRAM — should return bytes."""
    result = gdb.read_memory(board_config.sram_base, count=32)
    assert result.success, f"Memory read failed: {result.stderr}"

    # Count hex byte values in output (0xNN pattern)
    hex_bytes = re.findall(r"0x[0-9a-fA-F]{2}", result.stdout)
    assert len(hex_bytes) >= 16, (
        f"Expected at least 16 hex bytes, got {len(hex_bytes)}"
    )


def test_gdb_halt_resume(board_config, gdb):
    """Halt and resume the target via GDB monitor commands."""
    # J-Link uses 'monitor go', OpenOCD uses 'monitor resume'
    resume_cmd = "monitor go" if board_config.probe == "jlink" else "monitor resume"

    # Halt
    result = gdb.cmd("monitor halt")
    assert result.success, f"monitor halt failed: {result.stderr}"

    # Read PC while halted (should succeed)
    result = gdb.cmd("info registers pc")
    assert result.success, f"PC read while halted failed: {result.stderr}"
    assert "0x" in result.stdout

    # Resume
    result = gdb.cmd(resume_cmd)
    assert result.success, f"{resume_cmd} failed: {result.stderr}"
