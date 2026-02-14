"""Auto-retry logic for flash failures (STM32 connect-under-reset, ESP32 USB-JTAG)."""

from __future__ import annotations

import logging
import subprocess
from typing import Any, Optional

from eab.cli.flash._helpers import _wait_for_port

logger = logging.getLogger(__name__)

# Maximum retries for ESP32 USB-JTAG flash failures
_ESP32_MAX_RETRIES = 3


def _retry_stm32_connect_under_reset(
    profile, firmware, port, address, kwargs, stderr, attempt,
) -> Optional[dict[str, Any]]:
    """Retry STM32 flash with connect-under-reset if connection failed.
    
    Returns:
        Result dict if retry was attempted, None if retry not applicable.
    """
    if "Can not connect" not in stderr and "unable to get core" not in stderr.lower():
        return None

    retry_kwargs = {**kwargs, "connect_under_reset": True}
    flash_cmd = profile.get_flash_command(
        firmware_path=firmware,
        port=port or "",
        address=address or "0x08000000",
        **retry_kwargs,
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
        return {
            "success": result.returncode == 0,
            "stdout": result.stdout,
            "stderr": result.stderr,
            "attempts": attempt,
        }
    except subprocess.TimeoutExpired:
        return {
            "success": False,
            "stdout": "",
            "stderr": f"Timeout after {flash_cmd.timeout}s (connect-under-reset retry)",
            "attempts": attempt,
        }
    except FileNotFoundError:
        return {
            "success": False,
            "stdout": "",
            "stderr": f"Tool not found: {flash_cmd.tool}",
            "attempts": attempt,
        }


def _retry_esp32_usb_jtag(
    profile, firmware, port, address, kwargs, stderr, attempt,
    run_env=None,
) -> Optional[dict[str, Any]]:
    """Retry ESP32 flash with --no-stub and lower baud for USB-JTAG failures.
    
    Returns:
        Result dict if retry was attempted, None if retry not applicable.
    """
    esp_retry_errors = [
        "serial data stream stopped",
        "chip stopped responding",
        "no serial data received",
        "protocol error",
        "timed out waiting for packet",
        "device not configured",
    ]
    stderr_lower = stderr.lower()
    if not any(err in stderr_lower for err in esp_retry_errors):
        return None

    retry_baud = 115200
    retry_kwargs = {**kwargs, "no_stub": True, "baud": retry_baud}
    success = False
    stdout = ""

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

    return {
        "success": success,
        "stdout": stdout,
        "stderr": stderr,
        "attempts": attempt,
    }
