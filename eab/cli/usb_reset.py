"""USB device reset utility using pyusb (libusb)."""

from __future__ import annotations

import logging
import time
from typing import Optional

logger = logging.getLogger(__name__)


def reset_usb_device(vid: int, pid: int, wait_seconds: float = 5.0) -> dict:
    """Reset a USB device by VID:PID using libusb_reset_device.

    This recovers USB devices stuck in a bad state (e.g., ST-Link V3 after
    probe-rs SIGKILL on macOS). The reset forces the device to re-enumerate
    on the USB bus without physical re-plug.

    Args:
        vid: USB Vendor ID (e.g., 0x0483 for STMicroelectronics)
        pid: USB Product ID (e.g., 0x3754 for ST-Link V3)
        wait_seconds: Seconds to wait after reset for re-enumeration (default 5.0)

    Returns:
        Dict with status, old_address, new_address, manufacturer, product
    """
    try:
        import usb.core
        import usb.util
    except ImportError:
        return {"success": False, "error": "pyusb not installed (pip install pyusb)"}

    dev = usb.core.find(idVendor=vid, idProduct=pid)
    if dev is None:
        return {
            "success": False,
            "error": f"USB device {vid:04x}:{pid:04x} not found",
        }

    old_addr = dev.address
    manufacturer = None
    product = None
    try:
        manufacturer = dev.manufacturer
        product = dev.product
    except Exception:
        pass

    logger.info("Found %s %s at bus=%d addr=%d, sending USB reset...",
                manufacturer or "?", product or "?", dev.bus, old_addr)

    # Dispose resources first (release kernel drivers)
    try:
        usb.util.dispose_resources(dev)
    except Exception:
        pass

    # Send USB bus reset
    try:
        dev.reset()
    except Exception as e:
        # Reset may raise even on success (device disappears momentarily)
        logger.warning("USB reset raised %s (may still succeed)", e)

    # Wait for re-enumeration
    time.sleep(wait_seconds)

    # Verify device re-appeared
    dev2 = usb.core.find(idVendor=vid, idProduct=pid)
    if dev2 is None:
        return {
            "success": False,
            "error": "Device did not re-enumerate after reset",
            "old_address": old_addr,
        }

    new_addr = dev2.address
    logger.info("Device re-enumerated: bus=%d addr=%d (was %d)",
                dev2.bus, new_addr, old_addr)

    return {
        "success": True,
        "old_address": old_addr,
        "new_address": new_addr,
        "re_enumerated": old_addr != new_addr,
        "manufacturer": manufacturer,
        "product": product,
    }


# Common VID:PID pairs for debug probes
KNOWN_PROBES = {
    "stlink-v3": (0x0483, 0x3754),
    "stlink-v2": (0x0483, 0x3748),
    "stlink-v2-1": (0x0483, 0x374B),
    "jlink": (0x1366, 0x0105),
    "cmsis-dap": (0x1FC9, 0x0143),
    "esp-usb-jtag": (0x303A, 0x1001),
}


def cmd_usb_reset(vid: Optional[str] = None, pid: Optional[str] = None,
                  probe: Optional[str] = None, wait: float = 5.0,
                  json_mode: bool = False) -> int:
    """CLI entry point for ``eabctl usb-reset``."""
    from eab.cli.helpers import _print

    if probe:
        key = probe.lower()
        if key not in KNOWN_PROBES:
            _print({"error": f"Unknown probe '{probe}'. Known: {', '.join(KNOWN_PROBES)}"},
                   json_mode=json_mode)
            return 1
        vid_int, pid_int = KNOWN_PROBES[key]
    elif vid and pid:
        vid_int = int(vid, 16) if isinstance(vid, str) else vid
        pid_int = int(pid, 16) if isinstance(pid, str) else pid
    else:
        _print({"error": "Specify --probe <name> or --vid/--pid"}, json_mode=json_mode)
        return 1

    result = reset_usb_device(vid_int, pid_int, wait_seconds=wait)
    _print(result, json_mode=json_mode)
    return 0 if result["success"] else 1
