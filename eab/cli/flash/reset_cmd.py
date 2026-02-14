"""Hardware reset command."""

from __future__ import annotations

import logging
import os
import subprocess
import time
from typing import Optional

from eab.chips import get_chip_profile
from eab.chips.stm32 import _find_stm32_programmer_cli
from eab.chips.zephyr import ZephyrProfile
from eab.cli.helpers import _now_iso, _print

logger = logging.getLogger(__name__)


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
