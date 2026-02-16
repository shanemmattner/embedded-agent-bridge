"""Region profiling command for eabctl."""

from __future__ import annotations

from typing import Optional

from eab.cli.helpers import _print

from ._helpers import _detect_cpu_freq


def cmd_profile_region(
    *,
    base_dir: str,
    start_addr: int,
    end_addr: int,
    device: Optional[str],
    cpu_freq: Optional[int],
    probe_type: str = "jlink",
    chip: Optional[str] = None,
    probe_selector: Optional[str] = None,
    json_mode: bool,
) -> int:
    """Profile an address region using DWT cycle counter.

    Supports both J-Link (pylink) and OpenOCD probe backends.

    Args:
        base_dir: Session directory for probe state files.
        start_addr: Start address of the region to profile.
        end_addr: End address of the region to profile.
        device: Device string for J-Link (e.g., NRF5340_XXAA_APP).
        cpu_freq: CPU frequency in Hz (None for auto-detect).
        probe_type: Debug probe type ('jlink' or 'openocd').
        chip: Chip type for OpenOCD config and auto-detect.
        json_mode: Emit machine-parseable JSON output.

    Returns:
        Exit code: 0 on success, 1 on profiling error, 2 on config error.
    """
    if cpu_freq is None:
        cpu_freq = _detect_cpu_freq(device, chip)
        if cpu_freq is None:
            id_str = device or chip or "unknown"
            error_msg = (
                f"Cannot auto-detect CPU frequency for '{id_str}'. "
                "Please specify --cpu-freq manually."
            )
            _print({"error": "unknown_device", "message": error_msg} if json_mode else f"Error: {error_msg}",
                   json_mode=json_mode)
            return 2

    from eab.dwt_profiler import profile_region

    if probe_type == "openocd":
        # Same limitation — breakpoint profiling needs GDB, not just telnet
        _print({"error": "not_implemented",
                "message": "Region profiling via OpenOCD requires GDB breakpoints (not yet implemented). "
                           "Use dwt-status to read DWT registers via OpenOCD."}
               if json_mode else
               "Error: Region profiling via OpenOCD not yet implemented. Use dwt-status to read DWT registers.",
               json_mode=json_mode)
        return 2
    else:
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

        jlink = pylink.JLink()
        try:
            jlink.open()
            jlink.set_tif(pylink.enums.JLinkInterfaces.SWD)
            jlink.connect(device)

            result = profile_region(
                jlink=jlink,
                start_addr=start_addr,
                end_addr=end_addr,
                cpu_freq_hz=cpu_freq,
                timeout_s=10.0,
            )

            if json_mode:
                _print({
                    "function": result.function,
                    "address": f"0x{result.address:08X}",
                    "cycles": result.cycles,
                    "time_us": round(result.time_us, 2),
                    "cpu_freq_hz": result.cpu_freq_hz,
                }, json_mode=True)
            else:
                _print(
                    f"Region:   0x{start_addr:08X} to 0x{end_addr:08X}\n"
                    f"Cycles:   {result.cycles}\n"
                    f"Time:     {result.time_us:.2f} µs\n"
                    f"CPU Freq: {result.cpu_freq_hz / 1_000_000:.1f} MHz",
                    json_mode=False)
            return 0

        except (TimeoutError,) as e:
            _print({"error": "timeout", "message": str(e)} if json_mode else f"Error: {e}",
                   json_mode=json_mode)
            return 1
        except Exception as e:
            _print({"error": "profiling_failed", "message": f"Profiling failed: {e}"} if json_mode
                   else f"Error: Profiling failed: {e}", json_mode=json_mode)
            return 1
        finally:
            try:
                jlink.close()
            except Exception:
                pass
