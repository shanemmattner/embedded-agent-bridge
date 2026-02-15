"""Hardware preflight verification command."""

from __future__ import annotations

import re
import subprocess
import time
from typing import Optional

from eab.chips import get_chip_profile
from eab.openocd_bridge import OpenOCDBridge
from eab.cli.helpers import _print


def cmd_preflight_hw(
    *,
    base_dir: str,
    chip: str,
    stock_firmware: str,
    address: Optional[str],
    timeout: int,
    json_mode: bool,
) -> int:
    """
    Verify hardware chain by flashing stock firmware and checking functionality.

    This is the FIRST step before any debugging session. It answers:
    - Is the hardware OK?
    - Is the debugger OK?
    - If stock fails, it's hardware/driver - not your code.

    Steps:
    1. Flash stock firmware
    2. Wait for boot
    3. Check if CPU is running (not stuck in infinite loop)
    4. Report PASS/FAIL with diagnosis
    """
    started = time.time()
    checks = []
    overall_pass = True

    try:
        profile = get_chip_profile(chip)
    except ValueError as e:
        _print({"error": str(e), "success": False}, json_mode=json_mode)
        return 2

    # Step 1: Flash stock firmware
    flash_address = address or ("0x08000000" if chip.lower().startswith("stm32") else "0x0")
    flash_cmd = profile.get_flash_command(
        firmware_path=stock_firmware,
        port="",
        address=flash_address,
    )

    cmd_list = [flash_cmd.tool] + flash_cmd.args
    try:
        result = subprocess.run(
            cmd_list,
            capture_output=True,
            text=True,
            timeout=flash_cmd.timeout,
        )
        flash_success = result.returncode == 0
    except (subprocess.TimeoutExpired, FileNotFoundError):
        flash_success = False
        result = None

    checks.append({
        "name": "flash_stock_firmware",
        "passed": flash_success,
        "message": "Stock firmware flashed successfully" if flash_success else f"Flash failed: {str(e) if result is None else result.stderr}",
    })

    if not flash_success:
        overall_pass = False
        _print({
            "success": False,
            "checks": checks,
            "diagnosis": "Flash failed - check debugger connection, try power cycle",
            "duration_ms": int((time.time() - started) * 1000),
        }, json_mode=json_mode)
        return 1

    # Step 2: Wait for boot
    time.sleep(timeout / 2)  # Give firmware time to boot

    # Step 3: Check if CPU is running (not stuck)
    # Use OpenOCD to halt, get PC, resume, halt again, compare PCs
    bridge = OpenOCDBridge(base_dir)

    # Try to start OpenOCD if not running
    try:
        openocd_config = profile.get_openocd_config()
        bridge.start(
            interface_cfg=openocd_config.interface_cfg,
            target_cfg=openocd_config.target_cfg,
        )
        time.sleep(1)  # Let OpenOCD connect
    except Exception as e:
        checks.append({
            "name": "openocd_start",
            "passed": False,
            "message": f"Failed to start OpenOCD: {e}",
        })
        overall_pass = False

    # Sample PC twice to detect if CPU is stuck
    pc_samples = []
    cpu_stuck = False

    try:
        # First sample
        bridge.cmd("halt", timeout_s=5)
        time.sleep(0.2)
        halt_output1 = bridge.cmd("reg pc", timeout_s=2)
        pc_samples.append(halt_output1)

        # Resume and wait
        bridge.cmd("resume", timeout_s=2)
        time.sleep(1)

        # Second sample
        bridge.cmd("halt", timeout_s=5)
        time.sleep(0.2)
        halt_output2 = bridge.cmd("reg pc", timeout_s=2)
        pc_samples.append(halt_output2)

        # Check if PC changed (indicating CPU is running, not stuck)
        # Parse PC from output (format varies by OpenOCD version)
        pc_pattern = r"pc[:\s]+(?:0x)?([0-9a-fA-F]+)"

        pc1_match = re.search(pc_pattern, halt_output1, re.IGNORECASE)
        pc2_match = re.search(pc_pattern, halt_output2, re.IGNORECASE)

        if pc1_match and pc2_match:
            pc1 = int(pc1_match.group(1), 16)
            pc2 = int(pc2_match.group(1), 16)

            # If PC is in a very small range (< 16 bytes), likely stuck in tight loop
            pc_diff = abs(pc2 - pc1)
            cpu_stuck = pc_diff < 16

            checks.append({
                "name": "cpu_running",
                "passed": not cpu_stuck,
                "message": f"CPU running (PC moved {pc_diff} bytes)" if not cpu_stuck else f"CPU STUCK at 0x{pc1:08x} (PC unchanged)",
                "pc_samples": [f"0x{pc1:08x}", f"0x{pc2:08x}"],
            })
        else:
            # Couldn't parse PC, try simpler check - did we get any output?
            got_output = bool(halt_output1.strip() and halt_output2.strip())
            checks.append({
                "name": "cpu_running",
                "passed": got_output,
                "message": "CPU responding to debug commands" if got_output else "No response from CPU",
            })
            cpu_stuck = not got_output

    except Exception as e:
        checks.append({
            "name": "cpu_running",
            "passed": False,
            "message": f"Failed to check CPU state: {e}",
        })
        cpu_stuck = True
    finally:
        # Resume CPU and stop OpenOCD
        try:
            bridge.cmd("resume", timeout_s=2)
        except Exception:
            pass
        bridge.stop()

    if cpu_stuck:
        overall_pass = False

    # Final diagnosis
    if overall_pass:
        diagnosis = "Hardware chain VERIFIED - ready for custom firmware"
    elif not flash_success:
        diagnosis = "Flash failed - check debugger connection, try power cycle"
    elif cpu_stuck:
        diagnosis = "CPU stuck in infinite loop - stock firmware has bug or hardware issue"
    else:
        diagnosis = "Preflight check failed - see individual checks"

    duration_ms = int((time.time() - started) * 1000)

    payload = {
        "success": overall_pass,
        "checks": checks,
        "diagnosis": diagnosis,
        "chip": chip,
        "stock_firmware": stock_firmware,
        "duration_ms": duration_ms,
    }

    _print(payload, json_mode=json_mode)
    return 0 if overall_pass else 1
