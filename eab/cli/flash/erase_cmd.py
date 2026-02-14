"""Erase flash memory command."""

from __future__ import annotations

import subprocess
import time
from typing import Optional

from eab.chips import get_chip_profile
from eab.cli.helpers import _now_iso, _print


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
    """Erase flash memory using chip-specific tool.
    
    Args:
        chip: Chip type identifier (e.g., "nrf5340", "stm32l4")
        port: Serial port (ignored for most targets)
        tool: Flash tool override
        connect_under_reset: Use connect-under-reset for STM32 targets
        runner: Flash runner override (e.g., "jlink", "openocd")
        core: Target core for multi-core chips ("app" or "net", default: "app")
        json_mode: Emit machine-parseable JSON output
        
    Returns:
        Exit code: 0 on success, 1 on failure, 2 for invalid chip
    """
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
