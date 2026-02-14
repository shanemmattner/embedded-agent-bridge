"""Chip information command."""

from __future__ import annotations

import subprocess
import time
from typing import Optional

from eab.chips import get_chip_profile
from eab.cli.helpers import _now_iso, _print


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
