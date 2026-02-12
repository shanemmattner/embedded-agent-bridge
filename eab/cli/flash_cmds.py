"""Flash, erase, reset, and hardware verification commands for eabctl."""

from __future__ import annotations

import logging
import os
import re
import subprocess
import tempfile
import time
from typing import Any, Optional

logger = logging.getLogger(__name__)

from eab.chips import get_chip_profile
from eab.chips.stm32 import _find_stm32_programmer_cli
from eab.openocd_bridge import OpenOCDBridge

from eab.cli.helpers import (
    _now_iso,
    _print,
)

# esptool.cfg with increased timeouts for flaky USB-JTAG connections.
# Default esptool timeouts are too aggressive for USB-Serial/JTAG when
# sharing a USB bus with other devices.  See:
# - https://docs.espressif.com/projects/esptool/en/latest/esp32c6/esptool/configuration-file.html
# - https://github.com/espressif/esptool/issues/967
_ESPTOOL_USB_JTAG_CFG = """\
[esptool]
timeout = 10
max_timeout = 240
serial_write_timeout = 20
erase_write_timeout_per_mb = 60
connect_attempts = 10
write_block_attempts = 5
reset_delay = 0.25
"""


def _write_esptool_cfg_for_usb_jtag() -> str | None:
    """Write a temporary esptool.cfg with increased timeouts for USB-JTAG.

    Returns:
        Path to the temp config file, or None on failure.
    """
    try:
        fd, path = tempfile.mkstemp(prefix="esptool_", suffix=".cfg")
        with os.fdopen(fd, "w") as f:
            f.write(_ESPTOOL_USB_JTAG_CFG)
        return path
    except OSError:
        logger.warning("Failed to create esptool.cfg temp file")
        return None


def cmd_flash(
    *,
    firmware: str,
    chip: str,
    address: Optional[str],
    port: Optional[str],
    tool: Optional[str],
    baud: int,
    connect_under_reset: bool,
    board: Optional[str] = None,
    runner: Optional[str] = None,
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

    # Check if firmware is an ELF file and convert if needed (chip-specific).
    # Skip for directories (ESP-IDF build dirs handle their own binaries).
    if not os.path.isdir(firmware):
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
    if board:
        kwargs["board"] = board
    if runner:
        kwargs["runner"] = runner

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
    # Merge profile env (e.g. ZEPHYR_BASE) into parent env when present.
    # None inherits parent env; explicit dict overrides specific keys.
    run_env = {**os.environ, **flash_cmd.env} if flash_cmd.env else None

    # For ESP32 USB-JTAG: generate esptool.cfg with increased timeouts/retries
    esptool_cfg_path = None
    if chip.lower().startswith("esp"):
        from eab.chips.esp32 import ESP32Profile

        if ESP32Profile.is_usb_jtag_port(port or ""):
            esptool_cfg_path = _write_esptool_cfg_for_usb_jtag()
            if esptool_cfg_path:
                if run_env is None:
                    run_env = {**os.environ}
                run_env["ESPTOOL_CFGFILE"] = esptool_cfg_path
                logger.info("USB-JTAG detected on %s — using esptool.cfg: %s", port, esptool_cfg_path)

    attempt = 1
    logger.info("Flash attempt %d: %s", attempt, " ".join(cmd_list))

    try:
        result = subprocess.run(
            cmd_list,
            capture_output=True,
            text=True,
            timeout=flash_cmd.timeout,
            env=run_env,
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

    if not success:
        logger.warning("Flash attempt %d failed: %s", attempt, stderr[:200])

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
            attempt += 1
            logger.info("STM32 retry (connect-under-reset), attempt %d: %s", attempt, " ".join(cmd_list))
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

    # Auto-retry for ESP32 USB-JTAG failures with --no-stub and lower baud.
    # USB-JTAG serial is inherently flaky — retries often succeed on next attempt.
    # Strategy: up to 3 retries with --no-stub at 115200 baud, 2s pause between.
    _ESP32_MAX_RETRIES = 3
    esp32_retried = False
    if not success and chip.lower().startswith("esp") and not retried_with_cur:
        esp_retry_errors = [
            "serial data stream stopped",
            "chip stopped responding",
            "no serial data received",
            "protocol error",
            "timed out waiting for packet",
        ]
        stderr_lower = stderr.lower()
        should_retry = any(err in stderr_lower for err in esp_retry_errors)

        if should_retry:
            esp32_retried = True
            retry_baud = 115200
            retry_kwargs = {**kwargs, "no_stub": True, "baud": retry_baud}

            for retry_num in range(_ESP32_MAX_RETRIES):
                logger.info(
                    "ESP32 USB-JTAG flash failed (%s). Retry %d/%d with --no-stub, baud=%d...",
                    stderr.strip().split("\n")[-1][:100],
                    retry_num + 1,
                    _ESP32_MAX_RETRIES,
                    retry_baud,
                )
                flash_cmd = profile.get_flash_command(
                    firmware_path=firmware,
                    port=port or "",
                    **({"address": address} if address else {}),
                    **retry_kwargs,
                )
                cmd_list = [flash_cmd.tool] + flash_cmd.args
                attempt += 1
                logger.info("ESP32 retry attempt %d: %s", attempt, " ".join(cmd_list))

                # Pause to let USB bus settle between attempts
                time.sleep(2.0)

                try:
                    result = subprocess.run(
                        cmd_list,
                        capture_output=True,
                        text=True,
                        timeout=flash_cmd.timeout,
                        env=run_env,
                    )
                    success = result.returncode == 0
                    stdout = result.stdout
                    stderr = result.stderr
                except subprocess.TimeoutExpired:
                    success = False
                    stdout = ""
                    stderr = f"Timeout after {flash_cmd.timeout}s (no-stub retry {retry_num + 1})"
                except FileNotFoundError:
                    success = False
                    stdout = ""
                    stderr = f"Tool not found: {flash_cmd.tool}"
                    break  # No point retrying if tool is missing

                if success:
                    logger.info("ESP32 flash succeeded on attempt %d", attempt)
                    break

                logger.warning("ESP32 retry attempt %d failed: %s", attempt, stderr[:200])

                # Check if this retry also had a retryable error
                stderr_lower = stderr.lower()
                if not any(err in stderr_lower for err in esp_retry_errors):
                    logger.info("Non-retryable error, stopping retries")
                    break

    duration_ms = int((time.time() - started) * 1000)

    # Clean up temp files
    if temp_bin_path and os.path.exists(temp_bin_path):
        try:
            os.unlink(temp_bin_path)
        except Exception:
            pass  # Best effort cleanup
    if esptool_cfg_path and os.path.exists(esptool_cfg_path):
        try:
            os.unlink(esptool_cfg_path)
        except Exception:
            pass

    payload = {
        "schema_version": 1,
        "timestamp": _now_iso(),
        "success": success,
        "chip": chip,
        "firmware": original_firmware_path,  # Show original path, not temp file
        "address": address,
        "tool": flash_cmd.tool,
        "command": cmd_list,
        "attempts": attempt,
        "retried_with_connect_under_reset": retried_with_cur,
        "retried_with_no_stub": esp32_retried,
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
    runner: Optional[str] = None,
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
    if runner:
        kwargs["runner"] = runner

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
