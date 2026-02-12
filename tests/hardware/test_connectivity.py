"""Basic connectivity tests — is the board alive?"""

import pytest


pytestmark = pytest.mark.hardware


def test_probe_connects(probe):
    """Probe starts and GDB server comes up (implicit in fixture)."""
    # If we got here, the probe fixture succeeded — board is connected
    assert probe.gdb_port > 0


def test_sram_readable(board_config, gdb):
    """Can read 64 bytes from SRAM base address."""
    result = gdb.read_memory(board_config.sram_base, count=64)
    assert result.success, f"SRAM read failed: {result.stderr}"
    # GDB should have printed hex bytes
    assert "0x" in result.stdout


def test_fault_registers_readable(board_config, gdb):
    """Can read info registers — gets a valid register dump."""
    result = gdb.cmd("info registers")
    assert result.success, f"Register read failed: {result.stderr}"
    # Should contain at least one register line with hex value
    assert "0x" in result.stdout
