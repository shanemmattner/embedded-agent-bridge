"""Flash command execution (single-core and multi-core)."""

from __future__ import annotations

import logging
import os
import subprocess
from typing import Any

logger = logging.getLogger(__name__)


def _execute_multi_core(profile, firmware, port, address, kwargs) -> dict[str, Any]:
    """Execute multi-core flash sequence (e.g., nRF5340 APP + NET cores).
    
    Returns:
        Dict with keys: success, stdout, stderr, attempts, methods.
    """
    flash_cmds = profile.get_flash_commands(
        firmware_path=firmware,
        port=port or "",
        **({"address": address} if address else {}),
        **kwargs,
    )
    
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
    
    return {
        "success": all_success,
        "stdout": "\n".join(all_stdout),
        "stderr": "\n".join(all_stderr),
        "attempts": total_attempts,
        "methods": methods,
    }


def _execute_single_core(flash_cmd, esptool_cfg_path=None) -> dict[str, Any]:
    """Execute single flash command.
    
    Returns:
        Dict with keys: success, stdout, stderr, attempts, cmd_list, run_env.
    """
    cmd_list = [flash_cmd.tool] + flash_cmd.args
    run_env = {**os.environ, **flash_cmd.env} if flash_cmd.env else None

    if esptool_cfg_path:
        if run_env is None:
            run_env = {**os.environ}
        run_env["ESPTOOL_CFGFILE"] = esptool_cfg_path
        logger.info("Using esptool.cfg: %s", esptool_cfg_path)

    logger.info("Flash attempt 1: %s", " ".join(cmd_list))

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
        logger.warning("Flash attempt 1 failed: %s", stderr[:200])

    return {
        "success": success,
        "stdout": stdout,
        "stderr": stderr,
        "attempts": 1,
        "cmd_list": cmd_list,
        "run_env": run_env,
    }
