"""Flash, erase, reset, and hardware verification commands for eabctl."""

from __future__ import annotations

import os
import re
import subprocess
import time
from typing import Any, Optional

from eab.chips import get_chip_profile
from eab.chips.stm32 import _find_stm32_programmer_cli
from eab.openocd_bridge import OpenOCDBridge

from eab.cli.helpers import (
    _now_iso,
    _print,
)


def cmd_flash(
    *,
    firmware: str,
    chip: str,
    address: Optional[str],
    port: Optional[str],
    tool: Optional[str],
    baud: int,
    connect_under_reset: bool,
    json_mode: bool,
) -> int:
    """Flash firmware to device using chip-specific tool."""
    started = time.time()
    temp_bin_path = None
    converted_from_elf = False
    original_firmware_path = firmware  # Track original path for reporting

    try:
        profile = get_chip_profile(chip)
    except ValueError as e:
        _print({"error": str(e)}, json_mode=json_mode)
        return 2

    # Check if firmware is an ELF file and convert if needed (chip-specific)
    try:
        firmware, converted_from_elf = profile.prepare_firmware(firmware)
        if converted_from_elf:
            temp_bin_path = firmware  # Track for cleanup
    except FileNotFoundError as e:
        _print({"error": str(e)}, json_mode=json_mode)
        return 1
    except RuntimeError as e:
        _print({"error": str(e)}, json_mode=json_mode)
        return 1
    except Exception as e:
        _print({"error": f"Failed to read firmware file: {e}"}, json_mode=json_mode)
        return 1

    # Build flash command from chip profile
    kwargs = {"baud": baud, "connect_under_reset": connect_under_reset}
    if tool:
        kwargs["tool"] = tool

    # Use chip-appropriate default address when none specified
    if not address and chip.lower().startswith("stm32"):
        address = "0x08000000"
    elif not address and chip.lower().startswith("esp"):
        address = "0x10000"

    flash_cmd = profile.get_flash_command(
        firmware_path=firmware,
        port=port or "",
        **({"address": address} if address else {}),
        **kwargs,
    )

    # Execute flash command
    cmd_list = [flash_cmd.tool] + flash_cmd.args
    try:
        result = subprocess.run(
            cmd_list,
            capture_output=True,
            text=True,
            timeout=flash_cmd.timeout,
        )
        success = result.returncode == 0
        stdout = result.stdout
        stderr = result.stderr
    except subprocess.TimeoutExpired:
        success = False
        stdout = ""
        stderr = f"Timeout after {flash_cmd.timeout}s"
    except FileNotFoundError:
        success = False
        stdout = ""
        stderr = f"Tool not found: {flash_cmd.tool}. Install with: brew install stlink"

    # Auto-retry with connect-under-reset if connection failed (STM32 only)
    retried_with_cur = False
    if not success and chip.lower().startswith("stm32") and not connect_under_reset:
        if "Can not connect" in stderr or "unable to get core" in stderr.lower():
            # Retry with connect-under-reset using STM32CubeProgrammer
            retried_with_cur = True
            kwargs["connect_under_reset"] = True
            flash_cmd = profile.get_flash_command(
                firmware_path=firmware,
                port=port or "",
                address=address or "0x08000000",
                **kwargs,
            )
            cmd_list = [flash_cmd.tool] + flash_cmd.args
            try:
                result = subprocess.run(
                    cmd_list,
                    capture_output=True,
                    text=True,
                    timeout=flash_cmd.timeout,
                )
                success = result.returncode == 0
                stdout = result.stdout
                stderr = result.stderr
            except subprocess.TimeoutExpired:
                stdout = ""
                stderr = f"Timeout after {flash_cmd.timeout}s (connect-under-reset retry)"
            except FileNotFoundError:
                stdout = ""
                stderr = f"Tool not found: {flash_cmd.tool}"

    duration_ms = int((time.time() - started) * 1000)

    # Clean up temp file if created
    if temp_bin_path and os.path.exists(temp_bin_path):
        try:
            os.unlink(temp_bin_path)
        except Exception:
            pass  # Best effort cleanup

    payload = {
        "schema_version": 1,
        "timestamp": _now_iso(),
        "success": success,
        "chip": chip,
        "firmware": original_firmware_path,  # Show original path, not temp file
        "address": address,
        "tool": flash_cmd.tool,
        "command": cmd_list,
        "retried_with_connect_under_reset": retried_with_cur,
        "stdout": stdout,
        "stderr": stderr,
        "duration_ms": duration_ms,
    }
    
    # Add converted_from field if ELF conversion happened
    if converted_from_elf:
        payload["converted_from"] = "elf"
    
    _print(payload, json_mode=json_mode)
    return 0 if success else 1


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
    except (subprocess.TimeoutExpired, FileNotFoundError) as e:
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


def cmd_erase(
    *,
    chip: str,
    port: Optional[str],
    tool: Optional[str],
    connect_under_reset: bool,
    json_mode: bool,
) -> int:
    """Erase flash memory using chip-specific tool."""
    started = time.time()

    try:
        profile = get_chip_profile(chip)
    except ValueError as e:
        _print({"error": str(e)}, json_mode=json_mode)
        return 2

    kwargs = {"connect_under_reset": connect_under_reset}
    if tool:
        kwargs["tool"] = tool

    erase_cmd = profile.get_erase_command(port=port or "", **kwargs)

    cmd_list = [erase_cmd.tool] + erase_cmd.args
    try:
        result = subprocess.run(
            cmd_list,
            capture_output=True,
            text=True,
            timeout=erase_cmd.timeout,
        )
        success = result.returncode == 0
        stdout = result.stdout
        stderr = result.stderr
    except subprocess.TimeoutExpired:
        success = False
        stdout = ""
        stderr = f"Timeout after {erase_cmd.timeout}s"
    except FileNotFoundError:
        success = False
        stdout = ""
        stderr = f"Tool not found: {erase_cmd.tool}"

    duration_ms = int((time.time() - started) * 1000)

    payload = {
        "schema_version": 1,
        "timestamp": _now_iso(),
        "success": success,
        "chip": chip,
        "tool": erase_cmd.tool,
        "command": cmd_list,
        "stdout": stdout,
        "stderr": stderr,
        "duration_ms": duration_ms,
    }
    _print(payload, json_mode=json_mode)
    return 0 if success else 1


def cmd_chip_info(
    *,
    chip: str,
    port: Optional[str],
    json_mode: bool,
) -> int:
    """Get chip information using chip-specific tool.

    Runs ``st-info --probe`` (STM32) or equivalent and returns probe output.

    Args:
        chip: Chip type identifier (e.g. ``"stm32l4"``).
        port: Serial port (ESP32) or ignored (STM32 uses USB).
        json_mode: Emit machine-parseable JSON output.

    Returns:
        Exit code: 0 on success, 1 on failure, 2 for invalid chip.
    """
    started = time.time()

    try:
        profile = get_chip_profile(chip)
    except ValueError as e:
        _print({"error": str(e)}, json_mode=json_mode)
        return 2

    info_cmd = profile.get_chip_info_command(port=port or "")

    cmd_list = [info_cmd.tool] + info_cmd.args
    try:
        result = subprocess.run(
            cmd_list,
            capture_output=True,
            text=True,
            timeout=info_cmd.timeout,
        )
        success = result.returncode == 0
        stdout = result.stdout
        stderr = result.stderr
    except subprocess.TimeoutExpired:
        success = False
        stdout = ""
        stderr = f"Timeout after {info_cmd.timeout}s"
    except FileNotFoundError:
        success = False
        stdout = ""
        stderr = f"Tool not found: {info_cmd.tool}"

    duration_ms = int((time.time() - started) * 1000)

    payload = {
        "schema_version": 1,
        "timestamp": _now_iso(),
        "success": success,
        "chip": chip,
        "tool": info_cmd.tool,
        "command": cmd_list,
        "stdout": stdout,
        "stderr": stderr,
        "duration_ms": duration_ms,
    }
    _print(payload, json_mode=json_mode)
    return 0 if success else 1


def cmd_reset(
    *,
    chip: str,
    method: str,
    connect_under_reset: bool,
    json_mode: bool,
) -> int:
    """Hardware reset device using st-flash reset or STM32CubeProgrammer.

    Tries st-flash first; auto-retries with STM32CubeProgrammer in
    connect-under-reset mode if the initial attempt fails to connect.

    Args:
        chip: Chip type identifier (e.g. ``"stm32l4"``).
        method: Reset method — ``"hard"``, ``"soft"``, or ``"bootloader"``.
        connect_under_reset: If True, skip st-flash and use CubeProgrammer directly.
        json_mode: Emit machine-parseable JSON output.

    Returns:
        Exit code: 0 on success, 1 on failure.
    """
    started = time.time()
    retried_with_cur = False

    # For STM32, use st-flash reset command directly
    if chip.lower().startswith("stm32"):
        # Try st-flash first (unless connect-under-reset requested)
        if not connect_under_reset:
            cmd_list = ["st-flash", "reset"]
            try:
                result = subprocess.run(
                    cmd_list,
                    capture_output=True,
                    text=True,
                    timeout=30.0,
                )
                success = result.returncode == 0
                stdout = result.stdout
                stderr = result.stderr

                # Auto-retry with connect-under-reset if normal reset fails
                if not success and ("Can not connect" in stderr or "unable to get core" in stderr.lower()):
                    connect_under_reset = True
                    retried_with_cur = True
            except subprocess.TimeoutExpired:
                success = False
                stdout = ""
                stderr = "Timeout after 30s"
                connect_under_reset = True
                retried_with_cur = True
            except FileNotFoundError:
                success = False
                stdout = ""
                stderr = "st-flash not found. Install with: brew install stlink"

        # Use STM32CubeProgrammer with connect-under-reset
        if connect_under_reset:
            cubeprog = _find_stm32_programmer_cli()
            cmd_list = [cubeprog, "-c", "port=SWD mode=UR reset=HWrst", "-rst"]
            try:
                result = subprocess.run(
                    cmd_list,
                    capture_output=True,
                    text=True,
                    timeout=30.0,
                )
                success = result.returncode == 0
                stdout = result.stdout
                stderr = result.stderr
            except subprocess.TimeoutExpired:
                success = False
                stdout = ""
                stderr = "Timeout after 30s (connect-under-reset)"
            except FileNotFoundError:
                success = False
                stdout = ""
                stderr = f"STM32CubeProgrammer not found: {cubeprog}"
    else:
        # For ESP32, would need OpenOCD or esptool
        success = False
        stdout = ""
        stderr = f"Reset for {chip} not yet implemented. Use OpenOCD: eabctl openocd cmd --command 'reset run'"
        cmd_list = []

    duration_ms = int((time.time() - started) * 1000)

    payload = {
        "schema_version": 1,
        "timestamp": _now_iso(),
        "success": success,
        "chip": chip,
        "method": method,
        "connect_under_reset": connect_under_reset,
        "retried_with_connect_under_reset": retried_with_cur,
        "command": cmd_list,
        "stdout": stdout,
        "stderr": stderr,
        "duration_ms": duration_ms,
    }
    _print(payload, json_mode=json_mode)
    return 0 if success else 1
