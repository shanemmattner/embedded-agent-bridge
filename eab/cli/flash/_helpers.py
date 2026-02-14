"""Shared helpers for flash subpackage."""

from __future__ import annotations

import logging
import os
import tempfile
import time

logger = logging.getLogger(__name__)

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
