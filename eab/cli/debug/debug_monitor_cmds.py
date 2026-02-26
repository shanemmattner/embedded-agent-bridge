"""CLI command handlers for Debug Monitor mode control."""

from __future__ import annotations

import sys
from typing import Optional

from eab.cli.helpers import _print


def cmd_debug_monitor_enable(
    device: str,
    priority: int = 3,
    json_mode: bool = False,
) -> int:
    """Enable ARM Debug Monitor exception on the target.

    Connects to the device via J-Link, sets MON_EN + TRCENA in DEMCR,
    and programs the exception priority in SHPR3.

    Args:
        device: J-Link device string (e.g., NRF5340_XXAA_APP).
        priority: Debug monitor exception priority (0–7, lower = higher priority).
        json_mode: Output JSON instead of human-readable text.

    Returns:
        0 on success, 1 on error.
    """
    try:
        import pylink as _pylink
        from eab.debug_monitor import DebugMonitor

        jl = _pylink.JLink()
        jl.open()
        jl.set_tif(_pylink.enums.JLinkInterfaces.SWD)
        jl.connect(device)

        dm = DebugMonitor(jl)
        dm.enable(priority=priority)
        st = dm.status()

        _print(
            {
                "success": True,
                "enabled": st.enabled,
                "priority": st.priority,
                "raw_demcr": f"0x{st.raw_demcr:08X}",
                "device": device,
            },
            json_mode=json_mode,
        )
        return 0

    except ImportError as exc:
        _print({"error": str(exc), "success": False}, json_mode=json_mode)
        return 1
    except Exception as exc:
        _print({"error": str(exc), "success": False}, json_mode=json_mode)
        return 1


def cmd_debug_monitor_disable(
    device: str,
    json_mode: bool = False,
) -> int:
    """Disable ARM Debug Monitor exception on the target.

    Args:
        device: J-Link device string.
        json_mode: Output JSON.

    Returns:
        0 on success, 1 on error.
    """
    try:
        import pylink as _pylink
        from eab.debug_monitor import DebugMonitor

        jl = _pylink.JLink()
        jl.open()
        jl.set_tif(_pylink.enums.JLinkInterfaces.SWD)
        jl.connect(device)

        dm = DebugMonitor(jl)
        dm.disable()
        st = dm.status()

        _print(
            {
                "success": True,
                "enabled": st.enabled,
                "raw_demcr": f"0x{st.raw_demcr:08X}",
                "device": device,
            },
            json_mode=json_mode,
        )
        return 0

    except ImportError as exc:
        _print({"error": str(exc), "success": False}, json_mode=json_mode)
        return 1
    except Exception as exc:
        _print({"error": str(exc), "success": False}, json_mode=json_mode)
        return 1


def cmd_debug_monitor_status(
    device: str,
    json_mode: bool = False,
) -> int:
    """Report current Debug Monitor mode status.

    Args:
        device: J-Link device string.
        json_mode: Output JSON.

    Returns:
        0 on success, 1 on error.
    """
    try:
        import pylink as _pylink
        from eab.debug_monitor import DebugMonitor

        jl = _pylink.JLink()
        jl.open()
        jl.set_tif(_pylink.enums.JLinkInterfaces.SWD)
        jl.connect(device)

        dm = DebugMonitor(jl)
        st = dm.status()

        _print(
            {
                "success": True,
                "enabled": st.enabled,
                "mon_step": st.mon_step,
                "mon_pend": st.mon_pend,
                "priority": st.priority,
                "raw_demcr": f"0x{st.raw_demcr:08X}",
                "device": device,
            },
            json_mode=json_mode,
        )
        return 0

    except ImportError as exc:
        _print({"error": str(exc), "success": False}, json_mode=json_mode)
        return 1
    except Exception as exc:
        _print({"error": str(exc), "success": False}, json_mode=json_mode)
        return 1


def cmd_preflight_ble_safe(
    device: str,
    build_dir: str,
    json_mode: bool = False,
) -> int:
    """Preflight check: warn if BLE build + halt-mode debug conflict.

    Reads the Zephyr Kconfig from build_dir to detect if CONFIG_BT=y.
    If BLE is enabled and monitor mode is NOT active, prints a warning
    to stderr and returns exit code 1.

    Args:
        device: J-Link device string.
        build_dir: Path to the Zephyr build directory.
        json_mode: Output JSON.

    Returns:
        0 if safe (BLE not detected OR monitor mode already enabled).
        1 if BLE build + halt mode conflict detected.
    """
    from eab.chips.zephyr import ZephyrProfile

    ble_detected = ZephyrProfile.detect_ble_from_kconfig(build_dir)

    monitor_active = False
    monitor_check_error: Optional[str] = None

    try:
        import pylink as _pylink
        from eab.debug_monitor import DebugMonitor

        jl = _pylink.JLink()
        jl.open()
        jl.set_tif(_pylink.enums.JLinkInterfaces.SWD)
        jl.connect(device)

        dm = DebugMonitor(jl)
        st = dm.status()
        monitor_active = st.enabled

    except Exception as exc:
        monitor_check_error = str(exc)

    if ble_detected and not monitor_active:
        msg = (
            "WARNING: BLE build detected (CONFIG_BT=y) and debug monitor mode "
            "is NOT enabled. Halt-mode debugging will drop BLE connections. "
            "Run: eabctl debug-monitor enable --device <device> to enable monitor mode."
        )
        print(msg, file=sys.stderr)
        _print(
            {
                "success": False,
                "ble_detected": True,
                "monitor_active": False,
                "warning": msg,
                "device": device,
                "build_dir": build_dir,
            },
            json_mode=json_mode,
        )
        return 1

    _print(
        {
            "success": True,
            "ble_detected": ble_detected,
            "monitor_active": monitor_active,
            "device": device,
            "build_dir": build_dir,
            **({"monitor_check_error": monitor_check_error} if monitor_check_error else {}),
        },
        json_mode=json_mode,
    )
    return 0
