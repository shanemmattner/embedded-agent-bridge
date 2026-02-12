"""DWT profiling commands for eabctl."""

from __future__ import annotations

from typing import Optional

from eab.cli.helpers import _print


# CPU frequency defaults by chip type (Hz)
CHIP_CPU_FREQ = {
    "nrf5340": 128_000_000,  # nRF5340 Application core at 128 MHz
    "nrf52840": 64_000_000,   # nRF52840 at 64 MHz
    "mcxn947": 150_000_000,   # MCXN947 at 150 MHz
    "stm32f4": 168_000_000,   # STM32F4 typical at 168 MHz
    "stm32h7": 480_000_000,   # STM32H7 at 480 MHz
}


def _detect_cpu_freq(device: str) -> Optional[int]:
    """Auto-detect CPU frequency from device string.
    
    Args:
        device: Device string (e.g., NRF5340_XXAA_APP, MCXN947)
        
    Returns:
        CPU frequency in Hz, or None if not recognized
    """
    device_lower = device.lower()
    for chip, freq in CHIP_CPU_FREQ.items():
        if chip in device_lower:
            return freq
    return None


def cmd_profile_function(
    *,
    base_dir: str,
    device: str,
    elf: str,
    function: str,
    cpu_freq: Optional[int],
    json_mode: bool,
) -> int:
    """Profile a function using DWT cycle counter via J-Link.
    
    Connects to target via J-Link, parses ELF to find function address,
    enables DWT cycle counter, sets hardware breakpoints at function
    entry/exit, runs target, and measures cycle count.
    
    Args:
        base_dir: Session directory for J-Link state files
        device: J-Link device string (e.g., NRF5340_XXAA_APP, MCXN947)
        elf: Path to ELF file with debug symbols
        function: Function name to profile
        cpu_freq: CPU frequency in Hz (None for auto-detect)
        json_mode: Emit machine-parseable JSON output
        
    Returns:
        Exit code: 0 on success, 1 on profiling error, 2 on missing dependencies
    """
    # Import pylink at function level to provide helpful error message
    try:
        import pylink
    except ImportError:
        error_msg = (
            "pylink module not found. Install with: pip install pylink-square"
        )
        if json_mode:
            _print({"error": "missing_pylink", "message": error_msg}, json_mode=True)
        else:
            _print(f"Error: {error_msg}", json_mode=False)
        return 2
    
    from eab.jlink_bridge import JLinkBridge
    from eab.dwt_profiler import profile_function
    
    # Auto-detect CPU frequency if not provided
    if cpu_freq is None:
        cpu_freq = _detect_cpu_freq(device)
        if cpu_freq is None:
            error_msg = (
                f"Cannot auto-detect CPU frequency for device '{device}'. "
                "Please specify --cpu-freq manually."
            )
            if json_mode:
                _print({"error": "unknown_device", "message": error_msg}, json_mode=True)
            else:
                _print(f"Error: {error_msg}", json_mode=False)
            return 2
    
    # Create J-Link connection
    jlink = pylink.JLink()
    try:
        jlink.open()
        jlink.set_tif(pylink.enums.JLinkInterfaces.SWD)
        jlink.connect(device)
        
        # Profile the function
        result = profile_function(
            jlink=jlink,
            elf_path=elf,
            function_name=function,
            cpu_freq_hz=cpu_freq,
            timeout_s=10.0,
        )
        
        # Format output
        if json_mode:
            output = {
                "function": result.function,
                "address": f"0x{result.address:08X}",
                "cycles": result.cycles,
                "time_us": round(result.time_us, 2),
                "cpu_freq_hz": result.cpu_freq_hz,
            }
            _print(output, json_mode=True)
        else:
            output = (
                f"Function: {result.function}\n"
                f"Address:  0x{result.address:08X}\n"
                f"Cycles:   {result.cycles}\n"
                f"Time:     {result.time_us:.2f} µs\n"
                f"CPU Freq: {result.cpu_freq_hz / 1_000_000:.1f} MHz"
            )
            _print(output, json_mode=False)
        
        return 0
        
    except FileNotFoundError as e:
        error_msg = str(e)
        if json_mode:
            _print({"error": "file_not_found", "message": error_msg}, json_mode=True)
        else:
            _print(f"Error: {error_msg}", json_mode=False)
        return 1
        
    except ValueError as e:
        error_msg = str(e)
        if json_mode:
            _print({"error": "value_error", "message": error_msg}, json_mode=True)
        else:
            _print(f"Error: {error_msg}", json_mode=False)
        return 1
        
    except TimeoutError as e:
        error_msg = str(e)
        if json_mode:
            _print({"error": "timeout", "message": error_msg}, json_mode=True)
        else:
            _print(f"Error: {error_msg}", json_mode=False)
        return 1
        
    except Exception as e:
        error_msg = f"Profiling failed: {e}"
        if json_mode:
            _print({"error": "profiling_failed", "message": error_msg}, json_mode=True)
        else:
            _print(f"Error: {error_msg}", json_mode=False)
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
    device: str,
    cpu_freq: Optional[int],
    json_mode: bool,
) -> int:
    """Profile an address region using DWT cycle counter via J-Link.
    
    Connects to target via J-Link, enables DWT cycle counter, sets hardware
    breakpoints at start/end addresses, runs target, and measures cycle count.
    
    Args:
        base_dir: Session directory for J-Link state files
        start_addr: Start address for profiling
        end_addr: End address for profiling
        device: J-Link device string (e.g., NRF5340_XXAA_APP, MCXN947)
        cpu_freq: CPU frequency in Hz (None for auto-detect)
        json_mode: Emit machine-parseable JSON output
        
    Returns:
        Exit code: 0 on success, 1 on profiling error, 2 on missing dependencies
    """
    # Import pylink at function level to provide helpful error message
    try:
        import pylink
    except ImportError:
        error_msg = (
            "pylink module not found. Install with: pip install pylink-square"
        )
        if json_mode:
            _print({"error": "missing_pylink", "message": error_msg}, json_mode=True)
        else:
            _print(f"Error: {error_msg}", json_mode=False)
        return 2
    
    from eab.jlink_bridge import JLinkBridge
    from eab.dwt_profiler import profile_region
    
    # Auto-detect CPU frequency if not provided
    if cpu_freq is None:
        cpu_freq = _detect_cpu_freq(device)
        if cpu_freq is None:
            error_msg = (
                f"Cannot auto-detect CPU frequency for device '{device}'. "
                "Please specify --cpu-freq manually."
            )
            if json_mode:
                _print({"error": "unknown_device", "message": error_msg}, json_mode=True)
            else:
                _print(f"Error: {error_msg}", json_mode=False)
            return 2
    
    # Create J-Link connection
    jlink = pylink.JLink()
    try:
        jlink.open()
        jlink.set_tif(pylink.enums.JLinkInterfaces.SWD)
        jlink.connect(device)
        
        # Profile the region
        result = profile_region(
            jlink=jlink,
            start_addr=start_addr,
            end_addr=end_addr,
            cpu_freq_hz=cpu_freq,
            timeout_s=10.0,
        )
        
        # Format output
        if json_mode:
            output = {
                "function": result.function,
                "address": f"0x{result.address:08X}",
                "cycles": result.cycles,
                "time_us": round(result.time_us, 2),
                "cpu_freq_hz": result.cpu_freq_hz,
            }
            _print(output, json_mode=True)
        else:
            output = (
                f"Region:   0x{start_addr:08X} to 0x{end_addr:08X}\n"
                f"Cycles:   {result.cycles}\n"
                f"Time:     {result.time_us:.2f} µs\n"
                f"CPU Freq: {result.cpu_freq_hz / 1_000_000:.1f} MHz"
            )
            _print(output, json_mode=False)
        
        return 0
        
    except TimeoutError as e:
        error_msg = str(e)
        if json_mode:
            _print({"error": "timeout", "message": error_msg}, json_mode=True)
        else:
            _print(f"Error: {error_msg}", json_mode=False)
        return 1
        
    except Exception as e:
        error_msg = f"Profiling failed: {e}"
        if json_mode:
            _print({"error": "profiling_failed", "message": error_msg}, json_mode=True)
        else:
            _print(f"Error: {error_msg}", json_mode=False)
        return 1
        
    finally:
        try:
            jlink.close()
        except Exception:
            pass


def cmd_dwt_status(
    *,
    base_dir: str,
    device: str,
    json_mode: bool,
) -> int:
    """Display DWT register state via J-Link.
    
    Connects to target via J-Link and reads DWT control registers:
    - DEMCR (Debug Exception and Monitor Control Register)
    - DWT_CTRL (DWT Control Register)
    - DWT_CYCCNT (Cycle Count Register)
    
    Args:
        base_dir: Session directory for J-Link state files
        device: J-Link device string (e.g., NRF5340_XXAA_APP, MCXN947)
        json_mode: Emit machine-parseable JSON output
        
    Returns:
        Exit code: 0 on success, 1 on error, 2 on missing dependencies
    """
    # Import pylink at function level to provide helpful error message
    try:
        import pylink
    except ImportError:
        error_msg = (
            "pylink module not found. Install with: pip install pylink-square"
        )
        if json_mode:
            _print({"error": "missing_pylink", "message": error_msg}, json_mode=True)
        else:
            _print(f"Error: {error_msg}", json_mode=False)
        return 2
    
    from eab.jlink_bridge import JLinkBridge
    from eab.dwt_profiler import get_dwt_status, DEMCR_TRCENA, DWT_CTRL_CYCCNTENA
    
    # Create J-Link connection
    jlink = pylink.JLink()
    try:
        jlink.open()
        jlink.set_tif(pylink.enums.JLinkInterfaces.SWD)
        jlink.connect(device)
        
        # Read DWT registers
        status = get_dwt_status(jlink)
        
        # Decode status flags
        trcena_enabled = bool(status["DEMCR"] & DEMCR_TRCENA)
        cyccntena_enabled = bool(status["DWT_CTRL"] & DWT_CTRL_CYCCNTENA)
        dwt_enabled = trcena_enabled and cyccntena_enabled
        
        # Format output
        if json_mode:
            output = {
                "DEMCR": f"0x{status['DEMCR']:08X}",
                "DWT_CTRL": f"0x{status['DWT_CTRL']:08X}",
                "DWT_CYCCNT": status["DWT_CYCCNT"],
                "TRCENA": trcena_enabled,
                "CYCCNTENA": cyccntena_enabled,
                "enabled": dwt_enabled,
            }
            _print(output, json_mode=True)
        else:
            output = (
                f"DWT Status:\n"
                f"  DEMCR:      0x{status['DEMCR']:08X} (TRCENA={'enabled' if trcena_enabled else 'disabled'})\n"
                f"  DWT_CTRL:   0x{status['DWT_CTRL']:08X} (CYCCNTENA={'enabled' if cyccntena_enabled else 'disabled'})\n"
                f"  DWT_CYCCNT: {status['DWT_CYCCNT']:,} cycles\n"
                f"  Status:     {'Enabled' if dwt_enabled else 'Disabled'}"
            )
            _print(output, json_mode=False)
        
        return 0
        
    except Exception as e:
        error_msg = f"Failed to read DWT status: {e}"
        if json_mode:
            _print({"error": "read_failed", "message": error_msg}, json_mode=True)
        else:
            _print(f"Error: {error_msg}", json_mode=False)
        return 1
        
    finally:
        try:
            jlink.close()
        except Exception:
            pass
