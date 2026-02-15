"""Flash firmware command — main orchestrator."""

from __future__ import annotations

import logging
import os
import subprocess
import time
from typing import Optional

from eab.chips import get_chip_profile
from eab.chips.zephyr import ZephyrProfile
from eab.cli.helpers import _now_iso, _print

from eab.cli.flash._helpers import _write_esptool_cfg_for_usb_jtag
from eab.cli.flash._retries import (
    _retry_stm32_connect_under_reset,
    _retry_esp32_usb_jtag,
)
from eab.cli.flash._detection import _detect_esp_idf_project, _prepare_firmware
from eab.cli.flash._execute import _execute_multi_core, _execute_single_core

logger = logging.getLogger(__name__)


def cmd_flash(
    *,
    firmware: str,
    chip: Optional[str],
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
    no_stub: bool = False,
    extra_esptool_args: Optional[list[str]] = None,
    json_mode: bool,
) -> int:
    """Flash firmware to device using chip-specific tool.
    
    Args:
        firmware: Path to firmware file or build directory
        chip: Chip type identifier (e.g., "esp32", "nrf5340", "stm32l4")
        address: Flash address offset (chip-specific defaults if None)
        port: Serial port path (for serial-based flashing)
        tool: Flash tool override (e.g., "jlink" for J-Link direct flash)
        baud: Baud rate for serial flashing
        connect_under_reset: Use connect-under-reset for STM32 targets
        board: Zephyr board name override
        runner: Zephyr flash runner override (e.g., "jlink", "openocd")
        device: J-Link device string (e.g., "NRF5340_XXAA_APP") for J-Link flash
        reset_after: Whether to reset device after flashing (default: True)
        net_firmware: Path to NET core firmware for dual-core targets (e.g., nRF5340)
        no_stub: Use ROM bootloader instead of RAM stub for ESP32 (slower but more reliable)
        extra_esptool_args: Additional arguments to pass to esptool for ESP32 flashing
        json_mode: Emit machine-parseable JSON output
        
    Returns:
        Exit code: 0 on success, 1 on failure, 2 for invalid chip
    """
    started = time.time()
    original_firmware_path = firmware

    # --- Phase 1: Detect project type and chip ---
    is_esp_idf_project, chip, err = _detect_esp_idf_project(firmware, chip, json_mode)
    if err is not None:
        return err

    try:
        profile = get_chip_profile(chip)
    except ValueError as e:
        _print({"error": str(e)}, json_mode=json_mode)
        return 2

    # --- Phase 2: APPROTECT recovery (nRF5340) ---
    approtect_recovery_performed = _check_approtect(profile, chip, json_mode)
    if approtect_recovery_performed is None:
        return 1  # Recovery failed
    
    # --- Phase 3: Prepare firmware (ELF→BIN conversion) ---
    firmware, temp_bin_path, converted_from_elf, err = _prepare_firmware(
        firmware, profile, json_mode
    )
    if err is not None:
        return err

    # --- Phase 4: Build flash command ---
    kwargs = {"baud": baud, "connect_under_reset": connect_under_reset}
    if tool:
        kwargs["tool"] = tool
    if board:
        kwargs["board"] = board
    if runner:
        kwargs["runner"] = runner
    if net_firmware:
        kwargs["net_core_firmware"] = net_firmware
    if chip and chip.lower().startswith("esp"):
        if no_stub:
            kwargs["no_stub"] = True
        if extra_esptool_args:
            kwargs["extra_args"] = extra_esptool_args

    # Use chip-appropriate default address when none specified
    if not address and chip.lower().startswith("stm32"):
        address = "0x08000000"
    elif not address and chip.lower().startswith("esp"):
        address = "0x10000"

    is_zephyr = isinstance(profile, ZephyrProfile)
    use_multi_core = is_zephyr and net_firmware

    # --- Phase 5: Determine flash method and build command ---
    flash_cmd, use_jlink, use_openocd, jlink_script_path, esptool_cfg_path, err = (
        _build_flash_command(
            profile, chip, firmware, port, address, tool, device,
            reset_after, use_multi_core, kwargs, json_mode,
        )
    )
    if err is not None:
        return err

    # --- Phase 6: Execute flash ---
    if use_multi_core:
        result = _execute_multi_core(profile, firmware, port, address, kwargs)
    else:
        result = _execute_single_core(
            flash_cmd, esptool_cfg_path
        )

    success = result["success"]
    stdout = result["stdout"]
    stderr = result["stderr"]
    attempt = result["attempts"]
    methods = result.get("methods", [])

    # --- Phase 7: Auto-retries ---
    retried_with_cur = False
    esp32_retried = False

    if not use_multi_core and not success:
        # STM32 connect-under-reset retry
        if chip.lower().startswith("stm32") and not connect_under_reset:
            retry = _retry_stm32_connect_under_reset(
                profile, firmware, port, address, kwargs, stderr, attempt
            )
            if retry is not None:
                success = retry["success"]
                stdout = retry["stdout"]
                stderr = retry["stderr"]
                attempt = retry["attempts"]
                retried_with_cur = True

        # ESP32 USB-JTAG retry
        if not success and chip.lower().startswith("esp") and not retried_with_cur:
            retry = _retry_esp32_usb_jtag(
                profile, firmware, port, address, kwargs, stderr, attempt,
                run_env=result.get("run_env"),
            )
            if retry is not None:
                success = retry["success"]
                stdout = retry["stdout"]
                stderr = retry["stderr"]
                attempt = retry["attempts"]
                esp32_retried = True

    duration_ms = int((time.time() - started) * 1000)

    # --- Phase 8: Cleanup temp files ---
    _cleanup_temp_files(temp_bin_path, esptool_cfg_path, jlink_script_path)

    # --- Phase 9: Report results ---
    method, tool_name, command_list = _determine_method(
        use_multi_core, use_jlink, use_openocd, chip, flash_cmd, methods,
        result.get("cmd_list", []),
    )

    payload = {
        "schema_version": 1,
        "timestamp": _now_iso(),
        "success": success,
        "chip": chip,
        "firmware": original_firmware_path,
        "address": address,
        "tool": tool_name,
        "method": method,
        "command": command_list,
        "attempts": attempt,
        "retried_with_connect_under_reset": retried_with_cur,
        "retried_with_no_stub": esp32_retried,
        "approtect_recovery_performed": approtect_recovery_performed,
        "no_stub": no_stub,
        "stdout": stdout,
        "stderr": stderr,
        "duration_ms": duration_ms,
    }
    
    if use_multi_core and net_firmware:
        payload["net_firmware"] = net_firmware
    if converted_from_elf:
        payload["converted_from"] = "elf"

    _print(payload, json_mode=json_mode)
    return 0 if success else 1


def _check_approtect(profile, chip: str, json_mode: bool) -> bool | None:
    """Check and recover from APPROTECT on nRF5340.
    
    Returns:
        True if recovery was performed, False if not needed, None on failure.
    """
    if not isinstance(profile, ZephyrProfile):
        return False
    
    variant_lower = (profile.variant or "").lower()
    if "nrf" not in variant_lower or "5340" not in variant_lower:
        return False

    approtect_status = profile.check_approtect(core="app")
    
    if approtect_status.get("enabled") is not True:
        if approtect_status.get("enabled") is None:
            logger.warning("Could not check APPROTECT status: %s", approtect_status.get("error"))
        return False

    logger.warning("APPROTECT is enabled on nRF5340 APP core - running recovery")
    
    try:
        result = subprocess.run(
            ["nrfjprog", "--recover"],
            capture_output=True,
            text=True,
            timeout=60.0,
        )
        
        if result.returncode == 0:
            logger.info("APPROTECT recovery successful - flash is now erased and ready")
            return True
        else:
            logger.warning("APPROTECT recovery failed: %s", result.stderr)
            _print({
                "error": f"APPROTECT recovery failed: {result.stderr}",
                "success": False,
            }, json_mode=json_mode)
            return None
            
    except subprocess.TimeoutExpired:
        _print({
            "error": "APPROTECT recovery timed out after 60s",
            "success": False,
        }, json_mode=json_mode)
        return None
    except FileNotFoundError:
        _print({
            "error": "nrfjprog not found - cannot recover from APPROTECT",
            "success": False,
        }, json_mode=json_mode)
        return None


def _build_flash_command(
    profile, chip, firmware, port, address, tool, device,
    reset_after, use_multi_core, kwargs, json_mode,
):
    """Build the flash command based on target type.
    
    Returns:
        (flash_cmd, use_jlink, use_openocd, jlink_script_path, esptool_cfg_path, err)
    """
    use_jlink = False
    use_openocd = False
    jlink_script_path = None
    esptool_cfg_path = None
    flash_cmd = None

    # Check if J-Link direct flash is requested for Zephyr targets
    if tool == "jlink":
        if isinstance(profile, ZephyrProfile):
            jlink_device = device or "NRF5340_XXAA_APP"
            try:
                flash_cmd = profile.get_jlink_flash_command(
                    firmware_path=firmware,
                    device=jlink_device,
                    reset_after=reset_after,
                )
                use_jlink = True
                jlink_script_path = flash_cmd.env.get("JLINK_SCRIPT_PATH")
                logger.info("Using J-Link direct flash for %s (device: %s, reset_after: %s)",
                           chip, jlink_device, reset_after)
            except ValueError as e:
                _print({"error": str(e)}, json_mode=json_mode)
                return None, False, False, None, None, 1
        else:
            _print({"error": f"--tool jlink is only supported for Zephyr targets, not {chip}"}, json_mode=json_mode)
            return None, False, False, None, None, 2

    # For ESP32 USB-JTAG: prefer OpenOCD JTAG flashing
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

    return flash_cmd, use_jlink, use_openocd, jlink_script_path, esptool_cfg_path, None


def _cleanup_temp_files(*paths: str | None) -> None:
    """Best-effort cleanup of temporary files."""
    for path in paths:
        if path and os.path.exists(path):
            try:
                os.unlink(path)
            except Exception:
                pass


def _determine_method(
    use_multi_core, use_jlink, use_openocd, chip, flash_cmd, methods, cmd_list,
):
    """Determine flash method string for reporting."""
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

    return method, tool_name, command_list
