"""Function profiling command for eabctl."""

from __future__ import annotations

from typing import Optional

from eab.cli.helpers import _print

from ._helpers import _detect_cpu_freq


def cmd_profile_function(
    *,
    base_dir: str,
    device: Optional[str],
    elf: str,
    function: str,
    cpu_freq: Optional[int],
    probe_type: str = "jlink",
    chip: Optional[str] = None,
    probe_selector: Optional[str] = None,
    json_mode: bool,
) -> int:
    """Profile a function using DWT cycle counter.

    Supports both J-Link (pylink) and OpenOCD probe backends.

    Args:
        base_dir: Session directory
        device: Device string for J-Link (e.g., NRF5340_XXAA_APP) or chip identifier
        elf: Path to ELF file with debug symbols
        function: Function name to profile
        cpu_freq: CPU frequency in Hz (None for auto-detect)
        probe_type: 'jlink' or 'openocd'
        chip: Chip type for OpenOCD config (e.g., stm32l4, mcxn947)
        json_mode: Emit machine-parseable JSON output

    Returns:
        Exit code: 0 on success, 1 on profiling error, 2 on missing dependencies
    """
    # Auto-detect CPU frequency if not provided
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

    from eab.dwt_profiler import profile_function

    if probe_type == "openocd":
        # OpenOCD path — DWT registers read via telnet
        if not chip:
            _print({"error": "missing_chip", "message": "--chip is required with --probe openocd"}
                   if json_mode else "Error: --chip is required with --probe openocd",
                   json_mode=json_mode)
            return 2

        # For OpenOCD, we can't use profile_function directly since it uses pylink breakpoints.
        # Instead, we just read DWT status and report — full breakpoint profiling requires GDB.
        _print({"error": "not_implemented",
                "message": "Function profiling via OpenOCD requires GDB breakpoints (not yet implemented). "
                           "Use dwt-status or profile-region with J-Link instead."}
               if json_mode else
               "Error: Function profiling via OpenOCD not yet implemented. Use dwt-status to read DWT registers.",
               json_mode=json_mode)
        return 2
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

        jlink = pylink.JLink()
        try:
            jlink.open()
            jlink.set_tif(pylink.enums.JLinkInterfaces.SWD)
            jlink.connect(device)

            result = profile_function(
                jlink=jlink,
                elf_path=elf,
                function_name=function,
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
                    f"Function: {result.function}\n"
                    f"Address:  0x{result.address:08X}\n"
                    f"Cycles:   {result.cycles}\n"
                    f"Time:     {result.time_us:.2f} µs\n"
                    f"CPU Freq: {result.cpu_freq_hz / 1_000_000:.1f} MHz",
                    json_mode=False)
            return 0

        except TimeoutError as e:
            _print({"error": "timeout", "message": str(e)} if json_mode else f"Error: {e}",
                   json_mode=json_mode)
            return 1
        except (FileNotFoundError, ValueError) as e:
            _print({"error": type(e).__name__.lower(), "message": str(e)} if json_mode else f"Error: {e}",
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
