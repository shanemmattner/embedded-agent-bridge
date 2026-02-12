"""DWT profiling commands for eabctl."""

from __future__ import annotations

from typing import Optional

from eab.cli.helpers import _print


# CPU frequency defaults by chip type (Hz)
CHIP_CPU_FREQ = {
    "nrf5340": 128_000_000,  # nRF5340 Application core at 128 MHz
    "nrf52840": 64_000_000,   # nRF52840 at 64 MHz
    "mcxn947": 150_000_000,   # MCXN947 at 150 MHz
    "stm32l4": 80_000_000,    # STM32L4 at 80 MHz
    "stm32f4": 168_000_000,   # STM32F4 typical at 168 MHz
    "stm32h7": 480_000_000,   # STM32H7 at 480 MHz
}


def _detect_cpu_freq(device: str, chip: Optional[str] = None) -> Optional[int]:
    """Auto-detect CPU frequency from device/chip string.

    Args:
        device: Device string (e.g., NRF5340_XXAA_APP, MCXN947) or None
        chip: Chip type (e.g., stm32l4, mcxn947) or None

    Returns:
        CPU frequency in Hz, or None if not recognized
    """
    for source in (device, chip):
        if source:
            source_lower = source.lower()
            for key, freq in CHIP_CPU_FREQ.items():
                if key in source_lower:
                    return freq
    return None


def _setup_openocd_probe(base_dir: str, chip: str):
    """Create and start an OpenOCD probe for the given chip.

    Returns:
        (probe, bridge, telnet_port) tuple
    """
    from eab.debug_probes import get_debug_probe
    from eab.chips.zephyr import ZephyrProfile
    from eab.openocd_bridge import OpenOCDBridge

    profile = ZephyrProfile(variant=chip)
    ocd_cfg = profile.get_openocd_config()

    probe = get_debug_probe(
        "openocd",
        base_dir=base_dir,
        interface_cfg=ocd_cfg.interface_cfg,
        target_cfg=ocd_cfg.target_cfg,
        transport=ocd_cfg.transport,
        extra_commands=ocd_cfg.extra_commands,
        halt_command=ocd_cfg.halt_command,
    )

    status = probe.start_gdb_server()
    if not status.running:
        raise RuntimeError(f"Failed to start OpenOCD: {status.last_error}")

    bridge = OpenOCDBridge(base_dir)
    return probe, bridge


def cmd_profile_function(
    *,
    base_dir: str,
    device: Optional[str],
    elf: str,
    function: str,
    cpu_freq: Optional[int],
    probe_type: str = "jlink",
    chip: Optional[str] = None,
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


def cmd_profile_region(
    *,
    base_dir: str,
    start_addr: int,
    end_addr: int,
    device: Optional[str],
    cpu_freq: Optional[int],
    probe_type: str = "jlink",
    chip: Optional[str] = None,
    json_mode: bool,
) -> int:
    """Profile an address region using DWT cycle counter.

    Supports both J-Link (pylink) and OpenOCD probe backends.
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
