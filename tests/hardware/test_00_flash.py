"""End-to-end HIL tests: build, flash, and boot verification.

Runs first alphabetically (test_00_*) so firmware is flashed before
other test modules. Uses the ``firmware`` fixture from conftest which
handles build + flash, then verifies the CPU is actually executing code.
"""

from __future__ import annotations

import re
import time

import pytest


pytestmark = pytest.mark.hardware


def test_firmware_ready(board_config, firmware):
    """Firmware builds (or pre-built binary exists) and flashes successfully.

    The ``firmware`` fixture does the actual build + flash work.
    If we reach this assertion, both succeeded.
    """
    assert firmware is not None
    assert firmware.exists(), f"Build output missing: {firmware}"


def test_firmware_boots(board_config, firmware, probe, gdb):
    """CPU is executing code after flash — not stuck in a tight loop.

    Strategy:
      1. Halt CPU, read PC
      2. Resume CPU, wait 500ms
      3. Halt CPU, read PC again
      4. Assert PCs differ by >16 bytes (real code execution, not a spin loop)
    """
    resume_cmd = "monitor go" if board_config.probe == "jlink" else "monitor resume"

    # First sample: halt and read PC
    result = gdb.cmd("monitor halt")
    assert result.success, f"halt failed: {result.stderr}"

    result1 = gdb.cmd("info registers pc")
    assert result1.success, f"PC read #1 failed: {result1.stderr}"

    pc1 = _parse_pc(result1.stdout)
    assert pc1 is not None, f"Could not parse PC from: {result1.stdout}"

    # Resume and let CPU run
    result = gdb.cmd(resume_cmd)
    assert result.success, f"resume failed: {result.stderr}"
    time.sleep(0.5)

    # Second sample: halt and read PC again
    result = gdb.cmd("monitor halt")
    assert result.success, f"halt #2 failed: {result.stderr}"

    result2 = gdb.cmd("info registers pc")
    assert result2.success, f"PC read #2 failed: {result2.stderr}"

    pc2 = _parse_pc(result2.stdout)
    assert pc2 is not None, f"Could not parse PC from: {result2.stdout}"

    # CPU should have moved well beyond a tight loop
    pc_diff = abs(pc2 - pc1)
    assert pc_diff > 16, (
        f"CPU appears stuck — PC barely moved: "
        f"0x{pc1:08x} → 0x{pc2:08x} (delta={pc_diff} bytes)"
    )

    # Resume CPU so it's running for subsequent tests
    gdb.cmd(resume_cmd)


def _parse_pc(gdb_output: str) -> int | None:
    """Extract PC value from GDB 'info registers pc' output.

    Handles both ARM and RISC-V formats:
      ARM:   ``pc             0x08001234  0x8001234 <main+12>``
      RISCV: ``pc             0x42000100  0x42000100``
    """
    match = re.search(r"pc\s+(0x[0-9a-fA-F]+)", gdb_output)
    if match:
        return int(match.group(1), 16)
    return None
