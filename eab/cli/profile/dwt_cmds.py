"""DWT status command for eabctl."""

from __future__ import annotations

from typing import Optional

from eab.cli.helpers import _print

from ._helpers import _setup_openocd_probe


def cmd_dwt_status(
    *,
    base_dir: str,
    device: Optional[str],
    probe_type: str = "jlink",
    chip: Optional[str] = None,
    json_mode: bool,
) -> int:
    """Display DWT register state.

    Supports both J-Link (pylink) and OpenOCD probe backends.

    Args:
        base_dir: Session directory for probe state files.
        device: Device string for J-Link (e.g., NRF5340_XXAA_APP).
        probe_type: Debug probe type ('jlink' or 'openocd').
        chip: Chip type for OpenOCD config lookup.
        json_mode: Emit machine-parseable JSON output.

    Returns:
        Exit code: 0 on success, 1 on read failure, 2 on config error.
    """
    from eab.dwt_profiler import DEMCR_TRCENA, DWT_CTRL_CYCCNTENA

    if probe_type == "openocd":
        if not chip:
            _print({"error": "missing_chip", "message": "--chip is required with --probe openocd"}
                   if json_mode else "Error: --chip is required with --probe openocd",
                   json_mode=json_mode)
            return 2

        from eab.dwt_profiler import get_dwt_status_openocd

        probe = None
        try:
            probe, bridge = _setup_openocd_probe(base_dir, chip)
            status = get_dwt_status_openocd(bridge)

            trcena_enabled = bool(status["DEMCR"] & DEMCR_TRCENA)
            cyccntena_enabled = bool(status["DWT_CTRL"] & DWT_CTRL_CYCCNTENA)
            dwt_enabled = trcena_enabled and cyccntena_enabled

            if json_mode:
                _print({
                    "DEMCR": f"0x{status['DEMCR']:08X}",
                    "DWT_CTRL": f"0x{status['DWT_CTRL']:08X}",
                    "DWT_CYCCNT": status["DWT_CYCCNT"],
                    "TRCENA": trcena_enabled,
                    "CYCCNTENA": cyccntena_enabled,
                    "enabled": dwt_enabled,
                    "probe": "openocd",
                }, json_mode=True)
            else:
                _print(
                    f"DWT Status (via OpenOCD):\n"
                    f"  DEMCR:      0x{status['DEMCR']:08X} (TRCENA={'enabled' if trcena_enabled else 'disabled'})\n"
                    f"  DWT_CTRL:   0x{status['DWT_CTRL']:08X} (CYCCNTENA={'enabled' if cyccntena_enabled else 'disabled'})\n"
                    f"  DWT_CYCCNT: {status['DWT_CYCCNT']:,} cycles\n"
                    f"  Status:     {'Enabled' if dwt_enabled else 'Disabled'}",
                    json_mode=False)
            return 0

        except Exception as e:
            _print({"error": "read_failed", "message": f"Failed to read DWT status via OpenOCD: {e}"}
                   if json_mode else f"Error: Failed to read DWT status via OpenOCD: {e}",
                   json_mode=json_mode)
            return 1
        finally:
            if probe:
                try:
                    probe.stop_gdb_server()
                except Exception:
                    pass

    else:
        # J-Link path (existing)
        try:
            import pylink
        except ImportError:
            error_msg = "pylink module not found. Install with: pip install pylink-square"
            _print({"error": "missing_pylink", "message": error_msg} if json_mode else f"Error: {error_msg}",
                   json_mode=json_mode)
            return 2

        if not device:
            _print({"error": "missing_device", "message": "--device is required with --probe jlink"}
                   if json_mode else "Error: --device is required with --probe jlink",
                   json_mode=json_mode)
            return 2

        from eab.dwt_profiler import get_dwt_status

        jlink = pylink.JLink()
        try:
            jlink.open()
            jlink.set_tif(pylink.enums.JLinkInterfaces.SWD)
            jlink.connect(device)

            status = get_dwt_status(jlink)

            trcena_enabled = bool(status["DEMCR"] & DEMCR_TRCENA)
            cyccntena_enabled = bool(status["DWT_CTRL"] & DWT_CTRL_CYCCNTENA)
            dwt_enabled = trcena_enabled and cyccntena_enabled

            if json_mode:
                _print({
                    "DEMCR": f"0x{status['DEMCR']:08X}",
                    "DWT_CTRL": f"0x{status['DWT_CTRL']:08X}",
                    "DWT_CYCCNT": status["DWT_CYCCNT"],
                    "TRCENA": trcena_enabled,
                    "CYCCNTENA": cyccntena_enabled,
                    "enabled": dwt_enabled,
                    "probe": "jlink",
                }, json_mode=True)
            else:
                _print(
                    f"DWT Status:\n"
                    f"  DEMCR:      0x{status['DEMCR']:08X} (TRCENA={'enabled' if trcena_enabled else 'disabled'})\n"
                    f"  DWT_CTRL:   0x{status['DWT_CTRL']:08X} (CYCCNTENA={'enabled' if cyccntena_enabled else 'disabled'})\n"
                    f"  DWT_CYCCNT: {status['DWT_CYCCNT']:,} cycles\n"
                    f"  Status:     {'Enabled' if dwt_enabled else 'Disabled'}",
                    json_mode=False)
            return 0

        except Exception as e:
            _print({"error": "read_failed", "message": f"Failed to read DWT status: {e}"}
                   if json_mode else f"Error: Failed to read DWT status: {e}",
                   json_mode=json_mode)
            return 1
        finally:
            try:
                jlink.close()
            except Exception:
                pass
