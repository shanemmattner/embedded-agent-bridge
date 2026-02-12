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
from eab.chips.zephyr import ZephyrProfile
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


def _wait_for_port(port: str, timeout_s: float = 10) -> bool:
    """Wait for a serial port to appear (USB-JTAG re-enumeration after reset).

    Args:
        port: Serial port path (e.g., /dev/cu.usbmodem1101).
        timeout_s: Maximum seconds to wait.

    Returns:
        True if port appeared within timeout, False otherwise.
    """
    deadline = time.time() + timeout_s
    while time.time() < deadline:
        if os.path.exists(port):
            # Port file exists — give USB stack a moment to stabilize
            time.sleep(0.5)
            logger.info("Port %s ready", port)
            return True
        time.sleep(0.5)
    logger.warning("Port %s did not appear within %ds", port, timeout_s)
    return False


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
    device: Optional[str] = None,
    reset_after: bool = True,
    net_firmware: Optional[str] = None,
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

    # Check APPROTECT on nRF5340 and auto-recover if enabled
    approtect_recovery_performed = False
    if isinstance(profile, ZephyrProfile):
        variant_lower = (profile.variant or "").lower()
        if "nrf" in variant_lower and "5340" in variant_lower:
            # Check APPROTECT status on APP core
            approtect_status = profile.check_approtect(core="app")
            
            if approtect_status.get("enabled") is True:
                logger.warning("APPROTECT is enabled on nRF5340 APP core - running recovery")
                
                # Run nrfjprog --recover to disable APPROTECT
                try:
                    result = subprocess.run(
                        ["nrfjprog", "--recover"],
                        capture_output=True,
                        text=True,
                        timeout=60.0,
                    )
                    
                    if result.returncode == 0:
                        approtect_recovery_performed = True
                        logger.info("APPROTECT recovery successful - flash is now erased and ready")
                    else:
                        logger.warning("APPROTECT recovery failed: %s", result.stderr)
                        _print({
                            "error": f"APPROTECT recovery failed: {result.stderr}",
                            "success": False,
                        }, json_mode=json_mode)
                        return 1
                        
                except subprocess.TimeoutExpired:
                    _print({
                        "error": "APPROTECT recovery timed out after 60s",
                        "success": False,
                    }, json_mode=json_mode)
                    return 1
                except FileNotFoundError:
                    _print({
                        "error": "nrfjprog not found - cannot recover from APPROTECT",
                        "success": False,
                    }, json_mode=json_mode)
                    return 1
            elif approtect_status.get("enabled") is None:
                # Could not determine APPROTECT status - log warning but continue
                logger.warning("Could not check APPROTECT status: %s", approtect_status.get("error"))

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
    if net_firmware:
        kwargs["net_core_firmware"] = net_firmware

    # Use chip-appropriate default address when none specified
    if not address and chip.lower().startswith("stm32"):
        address = "0x08000000"
    elif not address and chip.lower().startswith("esp"):
        address = "0x10000"

    # Check if multi-core flash is needed (Zephyr with net_firmware)
    is_zephyr = isinstance(profile, ZephyrProfile)
    use_multi_core = is_zephyr and net_firmware

    # Check if J-Link direct flash is requested for Zephyr targets
    use_jlink = False
    jlink_script_path = None
    if tool == "jlink":
        if isinstance(profile, ZephyrProfile):
            # Use J-Link direct flash path
            # Default to NRF5340_XXAA_APP if not specified
            jlink_device = device or "NRF5340_XXAA_APP"
            
            try:
                flash_cmd = profile.get_jlink_flash_command(
                    firmware_path=firmware,
                    device=jlink_device,
                    reset_after=reset_after,
                )
                use_jlink = True
                # Extract script path for cleanup
                jlink_script_path = flash_cmd.env.get("JLINK_SCRIPT_PATH")
                logger.info("Using J-Link direct flash for %s (device: %s, reset_after: %s)", 
                           chip, jlink_device, reset_after)
            except ValueError as e:
                _print({"error": str(e)}, json_mode=json_mode)
                return 1
        else:
            _print({"error": f"--tool jlink is only supported for Zephyr targets, not {chip}"}, json_mode=json_mode)
            return 2

    # For ESP32 USB-JTAG: prefer OpenOCD JTAG flashing over esptool serial.
    # The USB-Serial/JTAG peripheral's serial data stream is unreliable for
    # large transfers (>~50KB), but JTAG transport works flawlessly.
    use_openocd = False
    esptool_cfg_path = None
    if not use_jlink and not use_multi_core and chip.lower().startswith("esp"):
        from eab.chips.esp32 import ESP32Profile

        if ESP32Profile.is_usb_jtag_port(port or ""):
            openocd_cmd = profile.get_openocd_flash_command(
                firmware_path=firmware,
                **({"address": address} if address else {}),
            )
            if openocd_cmd:
                flash_cmd = openocd_cmd
                use_openocd = True
                logger.info("USB-JTAG detected on %s — using OpenOCD JTAG flash (not esptool)", port)

    if not use_openocd and not use_jlink and not use_multi_core:
        flash_cmd = profile.get_flash_command(
            firmware_path=firmware,
            port=port or "",
            **({"address": address} if address else {}),
            **kwargs,
        )

        # For ESP32 USB-JTAG without OpenOCD: use esptool.cfg with increased timeouts
        if chip.lower().startswith("esp"):
            from eab.chips.esp32 import ESP32Profile

            if ESP32Profile.is_usb_jtag_port(port or ""):
                esptool_cfg_path = _write_esptool_cfg_for_usb_jtag()

    # Execute flash command(s)
    if use_multi_core:
        # Multi-core flash: get ordered list of commands and execute them
        flash_cmds = profile.get_flash_commands(
            firmware_path=firmware,
            port=port or "",
            **({"address": address} if address else {}),
            **kwargs,
        )
        
        # Execute all commands in order, fail fast
        all_success = True
        all_stdout = []
        all_stderr = []
        total_attempts = 0
        methods = []
        
        for step_num, flash_cmd in enumerate(flash_cmds, start=1):
            core_label = "NET" if step_num == 1 else "APP"
            logger.info("Step %d/%d: Flashing %s core", step_num, len(flash_cmds), core_label)
            
            cmd_list = [flash_cmd.tool] + flash_cmd.args
            run_env = {**os.environ, **flash_cmd.env} if flash_cmd.env else None
            
            total_attempts += 1
            logger.info("Flash attempt %d: %s", total_attempts, " ".join(cmd_list))
            
            # Determine method based on tool and args
            if flash_cmd.tool == "west":
                methods.append("west_flash")
            elif flash_cmd.tool == "JLink":
                methods.append("jlink_loadfile")
            else:
                methods.append(flash_cmd.tool)
            
            try:
                result = subprocess.run(
                    cmd_list,
                    capture_output=True,
                    text=True,
                    timeout=flash_cmd.timeout,
                    env=run_env,
                )
                step_success = result.returncode == 0
                all_stdout.append(f"--- {core_label} core ---\n{result.stdout}")
                all_stderr.append(f"--- {core_label} core ---\n{result.stderr}")
            except subprocess.TimeoutExpired:
                step_success = False
                all_stdout.append(f"--- {core_label} core ---\n")
                all_stderr.append(f"--- {core_label} core ---\nTimeout after {flash_cmd.timeout}s")
            except FileNotFoundError:
                step_success = False
                all_stdout.append(f"--- {core_label} core ---\n")
                all_stderr.append(f"--- {core_label} core ---\nTool not found: {flash_cmd.tool}")
            
            if not step_success:
                logger.warning("Flash step %d (%s core) failed", step_num, core_label)
                all_success = False
                break  # Fail fast: don't continue to next core
        
        success = all_success
        stdout = "\n".join(all_stdout)
        stderr = "\n".join(all_stderr)
        attempt = total_attempts
        retried_with_cur = False
        esp32_retried = False
        
    else:
        # Single-core flash: execute single command
        cmd_list = [flash_cmd.tool] + flash_cmd.args
        # Merge profile env (e.g. ZEPHYR_BASE) into parent env when present.
        # None inherits parent env; explicit dict overrides specific keys.
        run_env = {**os.environ, **flash_cmd.env} if flash_cmd.env else None

        if esptool_cfg_path:
            if run_env is None:
                run_env = {**os.environ}
            run_env["ESPTOOL_CFGFILE"] = esptool_cfg_path
            logger.info("Using esptool.cfg: %s", esptool_cfg_path)

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

    # Auto-retry with connect-under-reset if connection failed (STM32 only, not for multi-core)
    if not use_multi_core:
        retried_with_cur = False
    if not use_multi_core and not success and chip.lower().startswith("stm32") and not connect_under_reset:
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
    # Strategy: up to 3 retries with --no-stub at 115200 baud, wait for port between.
    _ESP32_MAX_RETRIES = 3
    if not use_multi_core:
        esp32_retried = False
    if not use_multi_core and not success and chip.lower().startswith("esp") and not retried_with_cur:
        esp_retry_errors = [
            "serial data stream stopped",
            "chip stopped responding",
            "no serial data received",
            "protocol error",
            "timed out waiting for packet",
            "device not configured",
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

                # Wait for port to reappear (USB-JTAG disappears after failed flash/reset)
                if port:
                    _wait_for_port(port, timeout_s=10)

                flash_cmd = profile.get_flash_command(
                    firmware_path=firmware,
                    port=port or "",
                    **({"address": address} if address else {}),
                    **retry_kwargs,
                )
                cmd_list = [flash_cmd.tool] + flash_cmd.args
                attempt += 1
                logger.info("ESP32 retry attempt %d: %s", attempt, " ".join(cmd_list))

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
    if jlink_script_path and os.path.exists(jlink_script_path):
        try:
            os.unlink(jlink_script_path)
            logger.debug("Cleaned up J-Link script: %s", jlink_script_path)
        except Exception:
            pass  # Best effort cleanup

    # Determine flash method for reporting
    if use_multi_core:
        method = "+".join(methods) if methods else "multi_core"
        tool_name = "multi_core"
        command_list = ["multi-core flash sequence"]
    elif use_jlink:
        method = "jlink_direct"
        tool_name = flash_cmd.tool
        command_list = cmd_list
    elif use_openocd:
        method = "openocd_jtag"
        tool_name = flash_cmd.tool
        command_list = cmd_list
    else:
        method = "esptool_serial" if chip.lower().startswith("esp") else "default"
        tool_name = flash_cmd.tool
        command_list = cmd_list

    payload = {
        "schema_version": 1,
        "timestamp": _now_iso(),
        "success": success,
        "chip": chip,
        "firmware": original_firmware_path,  # Show original path, not temp file
        "address": address,
        "tool": tool_name,
        "method": method,
        "command": command_list,
        "attempts": attempt,
        "retried_with_connect_under_reset": retried_with_cur,
        "retried_with_no_stub": esp32_retried,
        "approtect_recovery_performed": approtect_recovery_performed,
        "stdout": stdout,
        "stderr": stderr,
        "duration_ms": duration_ms,
    }
    
    # Add net_firmware field if multi-core flash
    if use_multi_core and net_firmware:
        payload["net_firmware"] = net_firmware

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
    core: str = "app",
    json_mode: bool,
) -> int:
    """Erase flash memory using chip-specific tool."""
    started = time.time()

    try:
        profile = get_chip_profile(chip)
    except ValueError as e:
        _print({"error": str(e)}, json_mode=json_mode)
        return 2

    kwargs = {"connect_under_reset": connect_under_reset, "core": core}
    if tool:
        kwargs["tool"] = tool
    if runner:
        kwargs["runner"] = runner

    try:
        erase_cmd = profile.get_erase_command(port=port or "", **kwargs)
    except RuntimeError as e:
        # Handle blocked operations (e.g., nRF5340 NET core erase)
        _print({"error": str(e), "success": False}, json_mode=json_mode)
        return 1

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
        "core": core,
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
    device: Optional[str] = None,
    json_mode: bool,
) -> int:
    """Hardware reset device using chip-specific reset tools.

    Supports:
    - STM32: st-flash reset or STM32CubeProgrammer with connect-under-reset
    - Zephyr/nRF: nrfjprog --reset
    - Zephyr/MCXN947: OpenOCD reset via CMSIS-DAP
    - Generic J-Link: JLinkExe script with reset sequence

    Args:
        chip: Chip type identifier (e.g. ``"stm32l4"``, ``"nrf5340"``).
        method: Reset method — ``"hard"``, ``"soft"``, or ``"bootloader"``.
        connect_under_reset: If True, skip st-flash and use CubeProgrammer directly.
        device: J-Link device string (e.g., ``"NRF5340_XXAA_APP"``). Required for J-Link reset.
        json_mode: Emit machine-parseable JSON output.

    Returns:
        Exit code: 0 on success, 1 on failure, 2 for invalid arguments.
    """
    started = time.time()
    retried_with_cur = False
    temp_script_path = None  # Track temp files for cleanup

    try:
        profile = get_chip_profile(chip)
    except ValueError as e:
        _print({"error": str(e)}, json_mode=json_mode)
        return 2

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
    # For Zephyr targets (nRF, MCXN947, etc.), use chip profile reset command
    elif hasattr(profile, "get_reset_command"):
        if isinstance(profile, ZephyrProfile):
            try:
                reset_cmd = profile.get_reset_command(device=device)
                cmd_list = [reset_cmd.tool] + reset_cmd.args
                
                # Track temp file if JLinkExe script was created
                if reset_cmd.tool == "JLinkExe" and "-CommandFile" in reset_cmd.args:
                    idx = reset_cmd.args.index("-CommandFile")
                    if idx + 1 < len(reset_cmd.args):
                        temp_script_path = reset_cmd.args[idx + 1]
                
                result = subprocess.run(
                    cmd_list,
                    capture_output=True,
                    text=True,
                    timeout=reset_cmd.timeout,
                )
                success = result.returncode == 0
                stdout = result.stdout
                stderr = result.stderr
            except NotImplementedError as e:
                success = False
                stdout = ""
                stderr = str(e)
                cmd_list = []
            except ValueError as e:
                success = False
                stdout = ""
                stderr = str(e)
                cmd_list = []
            except subprocess.TimeoutExpired:
                success = False
                stdout = ""
                stderr = f"Timeout after {reset_cmd.timeout}s"
            except FileNotFoundError:
                success = False
                stdout = ""
                stderr = f"Tool not found: {reset_cmd.tool}"
        else:
            # Non-Zephyr profile without reset support
            success = False
            stdout = ""
            stderr = f"Reset for {chip} not yet implemented."
            cmd_list = []
    else:
        # For ESP32 and other chips without reset command
        success = False
        stdout = ""
        stderr = f"Reset for {chip} not yet implemented. Use OpenOCD: eabctl openocd cmd --command 'reset run'"
        cmd_list = []

    duration_ms = int((time.time() - started) * 1000)

    # Clean up temp files
    if temp_script_path and os.path.exists(temp_script_path):
        try:
            os.unlink(temp_script_path)
        except Exception:
            pass  # Best effort cleanup

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
