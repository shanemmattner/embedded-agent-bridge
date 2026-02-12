"""DWT-based cycle counter profiling for ARM Cortex-M targets.

Provides hardware-accurate cycle count profiling using the Data Watchpoint
and Trace (DWT) unit available on Cortex-M3/M4/M7/M33 processors. Uses
J-Link probe to read/write DWT registers and set hardware breakpoints for
region-based profiling.

Architecture:
    enable_dwt() → enables TRCENA in DEMCR and CYCCNTENA in DWT_CTRL
    read_cycle_count() → reads DWT_CYCCNT register
    profile_region() → measures cycles between start/end addresses via breakpoints
    profile_function() → parses ELF to get function address, then profiles region

DWT Register Map:
    DEMCR      0xE000EDFC  Debug Exception and Monitor Control
    DWT_CTRL   0xE0001000  DWT Control Register
    DWT_CYCCNT 0xE0001004  Cycle Count Register
"""

from __future__ import annotations

import logging
import shutil
import subprocess
from dataclasses import dataclass
from pathlib import Path
from typing import Optional

logger = logging.getLogger(__name__)

# Import pylink optionally to provide helpful error if not installed
try:
    import pylink
except ImportError:
    pylink = None  # type: ignore


# =============================================================================
# DWT Register Addresses (ARM Cortex-M)
# =============================================================================

DEMCR_ADDR = 0xE000EDFC
DWT_CTRL_ADDR = 0xE0001000
DWT_CYCCNT_ADDR = 0xE0001004

# DEMCR bit flags
DEMCR_TRCENA = 1 << 24  # Trace enable

# DWT_CTRL bit flags
DWT_CTRL_CYCCNTENA = 1 << 0  # Cycle counter enable


# =============================================================================
# Data Classes
# =============================================================================

@dataclass(frozen=True)
class ProfileResult:
    """Result of a profiling measurement."""
    function: str
    address: int
    cycles: int
    time_us: float
    cpu_freq_hz: int


# =============================================================================
# DWT Register Manipulation
# =============================================================================

def _ensure_pylink_available():
    """Raise helpful error if pylink is not installed."""
    if pylink is None:
        raise ImportError(
            "pylink module not found. Install with: pip install pylink-square"
        )


def enable_dwt(jlink) -> bool:
    """Enable DWT cycle counter by setting TRCENA and CYCCNTENA bits.

    Args:
        jlink: pylink.JLink instance (connected to target)

    Returns:
        True if DWT was successfully enabled, False otherwise

    Raises:
        ImportError: If pylink module is not installed
        Exception: If memory read/write fails
    """
    _ensure_pylink_available()

    try:
        # Step 1: Enable trace system via DEMCR.TRCENA
        demcr = jlink.memory_read32(DEMCR_ADDR, 1)[0]
        if not (demcr & DEMCR_TRCENA):
            demcr |= DEMCR_TRCENA
            jlink.memory_write32(DEMCR_ADDR, [demcr])
            logger.debug("Enabled DEMCR.TRCENA (0x%08X)", demcr)

        # Step 2: Enable cycle counter via DWT_CTRL.CYCCNTENA
        dwt_ctrl = jlink.memory_read32(DWT_CTRL_ADDR, 1)[0]
        if not (dwt_ctrl & DWT_CTRL_CYCCNTENA):
            dwt_ctrl |= DWT_CTRL_CYCCNTENA
            jlink.memory_write32(DWT_CTRL_ADDR, [dwt_ctrl])
            logger.debug("Enabled DWT_CTRL.CYCCNTENA (0x%08X)", dwt_ctrl)

        # Step 3: Verify both bits are set
        demcr_check = jlink.memory_read32(DEMCR_ADDR, 1)[0]
        dwt_ctrl_check = jlink.memory_read32(DWT_CTRL_ADDR, 1)[0]

        enabled = (
            (demcr_check & DEMCR_TRCENA) and
            (dwt_ctrl_check & DWT_CTRL_CYCCNTENA)
        )

        if enabled:
            logger.info("DWT cycle counter enabled successfully")
        else:
            logger.warning("DWT enable verification failed")

        return enabled

    except Exception as e:
        logger.error("Failed to enable DWT: %s", e)
        raise


def read_cycle_count(jlink) -> int:
    """Read current DWT cycle counter value.

    Args:
        jlink: pylink.JLink instance (connected to target)

    Returns:
        Current cycle count (32-bit unsigned)

    Raises:
        ImportError: If pylink module is not installed
        Exception: If memory read fails
    """
    _ensure_pylink_available()

    try:
        cyccnt = jlink.memory_read32(DWT_CYCCNT_ADDR, 1)[0]
        return cyccnt
    except Exception as e:
        logger.error("Failed to read DWT_CYCCNT: %s", e)
        raise


def reset_cycle_count(jlink):
    """Reset DWT cycle counter to zero.

    Args:
        jlink: pylink.JLink instance (connected to target)

    Raises:
        ImportError: If pylink module is not installed
        Exception: If memory write fails
    """
    _ensure_pylink_available()

    try:
        jlink.memory_write32(DWT_CYCCNT_ADDR, [0])
        logger.debug("DWT_CYCCNT reset to 0")
    except Exception as e:
        logger.error("Failed to reset DWT_CYCCNT: %s", e)
        raise


def get_dwt_status(jlink) -> dict:
    """Read and return DWT register values for diagnostics.

    Args:
        jlink: pylink.JLink instance (connected to target)

    Returns:
        Dict with keys: DWT_CTRL, DWT_CYCCNT, DEMCR

    Raises:
        ImportError: If pylink module is not installed
        Exception: If memory read fails
    """
    _ensure_pylink_available()

    try:
        demcr = jlink.memory_read32(DEMCR_ADDR, 1)[0]
        dwt_ctrl = jlink.memory_read32(DWT_CTRL_ADDR, 1)[0]
        dwt_cyccnt = jlink.memory_read32(DWT_CYCCNT_ADDR, 1)[0]

        return {
            "DEMCR": demcr,
            "DWT_CTRL": dwt_ctrl,
            "DWT_CYCCNT": dwt_cyccnt,
        }
    except Exception as e:
        logger.error("Failed to read DWT status: %s", e)
        raise


# =============================================================================
# ELF Symbol Parsing
# =============================================================================

def _which_or_sdk(name: str) -> Optional[str]:
    """Try PATH first, then known SDK directories (Zephyr SDK)."""
    result = shutil.which(name)
    if result:
        return result
    home = Path.home()
    for sdk_dir in sorted(home.glob("zephyr-sdk-*"), reverse=True):
        candidate = sdk_dir / "arm-zephyr-eabi" / "bin" / name
        if candidate.is_file():
            return str(candidate)
    return None


def _parse_symbol_address(elf_path: str, function_name: str) -> Optional[int]:
    """Parse function address from ELF using arm-none-eabi-nm.

    Args:
        elf_path: Path to ELF binary
        function_name: Function symbol name to find

    Returns:
        Function address (int) or None if not found

    Raises:
        FileNotFoundError: If arm-none-eabi-nm is not on PATH
        subprocess.SubprocessError: If nm command fails
    """
    nm_tool = (
        _which_or_sdk("arm-none-eabi-nm")
        or _which_or_sdk("arm-zephyr-eabi-nm")
    )
    if nm_tool is None:
        raise FileNotFoundError(
            "arm-none-eabi-nm (or arm-zephyr-eabi-nm) not found on PATH. "
            "Install ARM GCC toolchain or Zephyr SDK."
        )

    try:
        result = subprocess.run(
            [nm_tool, "-C", elf_path],  # -C for demangling C++
            capture_output=True,
            text=True,
            timeout=10.0,
            check=True,
        )

        # Parse nm output: "00001234 T function_name"
        for line in result.stdout.splitlines():
            parts = line.strip().split()
            if len(parts) >= 3 and parts[-1] == function_name:
                # Symbol type should be T (text) or W (weak)
                if parts[1] in ("T", "t", "W", "w"):
                    return int(parts[0], 16)

        logger.warning("Function '%s' not found in ELF symbols", function_name)
        return None

    except subprocess.CalledProcessError as e:
        logger.error("arm-none-eabi-nm failed: %s", e.stderr)
        raise
    except Exception as e:
        logger.error("Failed to parse ELF symbols: %s", e)
        raise


# =============================================================================
# Hardware Breakpoint Profiling
# =============================================================================

def profile_region(
    jlink,
    start_addr: int,
    end_addr: int,
    cpu_freq_hz: int,
    timeout_s: float = 10.0,
) -> ProfileResult:
    """Profile execution between two addresses using hardware breakpoints.

    Sets hardware breakpoints at start_addr and end_addr, resets cycle
    counter at start, reads cycle count at end, computes elapsed time.

    Args:
        jlink: pylink.JLink instance (connected to target)
        start_addr: Address to start profiling
        end_addr: Address to stop profiling
        cpu_freq_hz: CPU frequency in Hz for time conversion
        timeout_s: Maximum time to wait for breakpoint hits

    Returns:
        ProfileResult with cycle count and timing

    Raises:
        ImportError: If pylink module is not installed
        TimeoutError: If breakpoints not hit within timeout
        Exception: If DWT is not available or breakpoint setup fails
    """
    _ensure_pylink_available()

    try:
        # Step 1: Enable DWT
        if not enable_dwt(jlink):
            raise RuntimeError("DWT not available on this target")

        # Step 2: Set hardware breakpoints
        # Clear existing breakpoints first
        jlink.breakpoint_clear_all()

        # Start breakpoint
        bp_start = jlink.breakpoint_set(start_addr, thumb=True)
        logger.debug("Set breakpoint at start: 0x%08X (handle %d)", start_addr, bp_start)

        # End breakpoint
        bp_end = jlink.breakpoint_set(end_addr, thumb=True)
        logger.debug("Set breakpoint at end: 0x%08X (handle %d)", end_addr, bp_end)

        # Step 3: Run until start breakpoint
        jlink.restart()
        logger.debug("Running to start address 0x%08X...", start_addr)

        if not _wait_for_halt(jlink, timeout_s):
            raise TimeoutError(
                f"Timeout waiting for start breakpoint at 0x{start_addr:08X}"
            )

        pc = jlink.register_read("R15 (PC)")
        logger.debug("Hit start breakpoint, PC=0x%08X", pc)

        # Step 4: Reset cycle counter at start
        reset_cycle_count(jlink)

        # Step 5: Run until end breakpoint
        jlink.restart()
        logger.debug("Running to end address 0x%08X...", end_addr)

        if not _wait_for_halt(jlink, timeout_s):
            raise TimeoutError(
                f"Timeout waiting for end breakpoint at 0x{end_addr:08X}"
            )

        pc = jlink.register_read("R15 (PC)")
        logger.debug("Hit end breakpoint, PC=0x%08X", pc)

        # Step 6: Read cycle count at end
        cycles = read_cycle_count(jlink)

        # Step 7: Compute elapsed time
        time_us = (cycles / cpu_freq_hz) * 1_000_000

        logger.info(
            "Profile complete: %d cycles, %.2f µs @ %d Hz",
            cycles, time_us, cpu_freq_hz,
        )

        return ProfileResult(
            function=f"region_0x{start_addr:08X}_to_0x{end_addr:08X}",
            address=start_addr,
            cycles=cycles,
            time_us=time_us,
            cpu_freq_hz=cpu_freq_hz,
        )

    finally:
        # Cleanup: clear breakpoints
        try:
            jlink.breakpoint_clear_all()
        except Exception:
            pass


def _wait_for_halt(jlink, timeout_s: float) -> bool:
    """Wait for target to halt (e.g., due to breakpoint).

    Args:
        jlink: pylink.JLink instance
        timeout_s: Maximum time to wait

    Returns:
        True if halted, False if timeout
    """
    import time
    deadline = time.time() + timeout_s
    while time.time() < deadline:
        if jlink.halted():
            return True
        time.sleep(0.05)  # Poll every 50ms
    return False


def profile_function(
    jlink,
    elf_path: str,
    function_name: str,
    cpu_freq_hz: int,
    timeout_s: float = 10.0,
) -> ProfileResult:
    """Profile a function by parsing its address from ELF and setting breakpoints.

    Parses the ELF file to find the function's start address, assumes the
    next instruction after the function body is the end address (requires
    function to be contiguous in memory).

    Args:
        jlink: pylink.JLink instance (connected to target)
        elf_path: Path to ELF binary with debug symbols
        function_name: Name of function to profile
        cpu_freq_hz: CPU frequency in Hz for time conversion
        timeout_s: Maximum time to wait for breakpoint hits

    Returns:
        ProfileResult with function name, address, cycles, time

    Raises:
        ImportError: If pylink module is not installed
        FileNotFoundError: If arm-none-eabi-nm not found or symbol missing
        TimeoutError: If breakpoints not hit within timeout
        Exception: If DWT is not available or profiling fails
    """
    _ensure_pylink_available()

    # Step 1: Parse function address from ELF
    func_addr = _parse_symbol_address(elf_path, function_name)
    if func_addr is None:
        raise ValueError(
            f"Function '{function_name}' not found in ELF '{elf_path}'. "
            "Ensure function is not inlined and symbols are present."
        )

    logger.info(
        "Found function '%s' at address 0x%08X",
        function_name, func_addr,
    )

    # Step 2: Read function size via objdump or assume typical size
    # For now, we'll use a heuristic: set end breakpoint at func_addr + 4
    # (first instruction after prologue). For real profiling, you'd parse
    # objdump -d output or use DWARF info to find function end.
    #
    # Better approach: use arm-none-eabi-objdump to find function end:
    end_addr = _find_function_end(elf_path, function_name, func_addr)

    logger.debug(
        "Profiling function '%s' from 0x%08X to 0x%08X",
        function_name, func_addr, end_addr,
    )

    # Step 3: Profile the region
    result = profile_region(
        jlink,
        start_addr=func_addr,
        end_addr=end_addr,
        cpu_freq_hz=cpu_freq_hz,
        timeout_s=timeout_s,
    )

    # Update function name in result
    return ProfileResult(
        function=function_name,
        address=result.address,
        cycles=result.cycles,
        time_us=result.time_us,
        cpu_freq_hz=result.cpu_freq_hz,
    )


def _find_function_end(elf_path: str, function_name: str, start_addr: int) -> int:
    """Find function end address by parsing objdump output.

    Args:
        elf_path: Path to ELF binary
        function_name: Function name
        start_addr: Function start address

    Returns:
        Address of first instruction after function (function end + 1 instruction)
    """
    objdump_tool = (
        _which_or_sdk("arm-none-eabi-objdump")
        or _which_or_sdk("arm-zephyr-eabi-objdump")
    )
    if objdump_tool is None:
        # Fallback: assume function is 32 bytes (8 instructions)
        logger.warning(
            "arm-none-eabi-objdump not found, using heuristic end address"
        )
        return start_addr + 32

    try:
        result = subprocess.run(
            [objdump_tool, "-d", elf_path],
            capture_output=True,
            text=True,
            timeout=10.0,
            check=True,
        )

        # Parse disassembly to find function boundaries
        # Format: "00001234 <function_name>:"
        #         "00001234:  instruction"
        #         "00001238:  instruction"
        #         ...
        #         "00001250 <next_function>:"
        in_function = False
        last_addr = start_addr

        for line in result.stdout.splitlines():
            line = line.strip()

            # Check for function start marker
            if f"<{function_name}>:" in line:
                in_function = True
                continue

            # Check for next function (end of current)
            if in_function and line and "<" in line and ">:" in line:
                # Found start of next function — last_addr is our end
                return last_addr + 4  # Return first instruction of next function

            # Parse instruction address
            if in_function and ":" in line:
                parts = line.split(":")
                if len(parts) >= 2:
                    try:
                        addr = int(parts[0].strip(), 16)
                        last_addr = addr
                    except ValueError:
                        pass

        # If we reach here, function extends to end of section
        # Return last instruction + 4 (typical ARM instruction size)
        logger.debug(
            "Function '%s' extends to end of section, using last_addr + 4",
            function_name,
        )
        return last_addr + 4

    except Exception as e:
        logger.warning("Failed to parse objdump output: %s", e)
        # Fallback: assume 32-byte function
        return start_addr + 32


# =============================================================================
# OpenOCD-based DWT Register Access
# =============================================================================
# Provides the same DWT functions but via OpenOCD telnet commands instead
# of pylink. This enables DWT profiling on any debug probe (ST-Link,
# CMSIS-DAP, etc.), not just J-Link.

import re

_MDW_PATTERN = re.compile(r"0x[0-9a-fA-F]+:\s+(0x[0-9a-fA-F]+|[0-9a-fA-F]+)")


def _ocd_read32(bridge, addr: int, telnet_port: int = 4444) -> int:
    """Read a 32-bit word via OpenOCD telnet ``mdw`` command.

    Args:
        bridge: OpenOCDBridge instance with ``cmd()`` method.
        addr: Memory address to read.
        telnet_port: OpenOCD telnet port.

    Returns:
        32-bit value at *addr*.
    """
    resp = bridge.cmd(f"mdw 0x{addr:08X}", telnet_port=telnet_port)
    m = _MDW_PATTERN.search(resp)
    if not m:
        raise RuntimeError(f"Failed to parse mdw response for 0x{addr:08X}: {resp!r}")
    val_str = m.group(1)
    return int(val_str, 16) if val_str.startswith("0x") else int(val_str, 16)


def _ocd_write32(bridge, addr: int, value: int, telnet_port: int = 4444) -> None:
    """Write a 32-bit word via OpenOCD telnet ``mww`` command."""
    bridge.cmd(f"mww 0x{addr:08X} 0x{value:08X}", telnet_port=telnet_port)


def enable_dwt_openocd(bridge, telnet_port: int = 4444) -> bool:
    """Enable DWT cycle counter via OpenOCD (same logic as enable_dwt but using telnet)."""
    try:
        demcr = _ocd_read32(bridge, DEMCR_ADDR, telnet_port)
        if not (demcr & DEMCR_TRCENA):
            demcr |= DEMCR_TRCENA
            _ocd_write32(bridge, DEMCR_ADDR, demcr, telnet_port)

        dwt_ctrl = _ocd_read32(bridge, DWT_CTRL_ADDR, telnet_port)
        if not (dwt_ctrl & DWT_CTRL_CYCCNTENA):
            dwt_ctrl |= DWT_CTRL_CYCCNTENA
            _ocd_write32(bridge, DWT_CTRL_ADDR, dwt_ctrl, telnet_port)

        # Verify
        demcr_check = _ocd_read32(bridge, DEMCR_ADDR, telnet_port)
        dwt_ctrl_check = _ocd_read32(bridge, DWT_CTRL_ADDR, telnet_port)
        enabled = bool(demcr_check & DEMCR_TRCENA) and bool(dwt_ctrl_check & DWT_CTRL_CYCCNTENA)
        if enabled:
            logger.info("DWT cycle counter enabled via OpenOCD")
        else:
            logger.warning("DWT enable verification failed via OpenOCD")
        return enabled
    except Exception as e:
        logger.error("Failed to enable DWT via OpenOCD: %s", e)
        raise


def read_cycle_count_openocd(bridge, telnet_port: int = 4444) -> int:
    """Read DWT_CYCCNT via OpenOCD."""
    return _ocd_read32(bridge, DWT_CYCCNT_ADDR, telnet_port)


def reset_cycle_count_openocd(bridge, telnet_port: int = 4444) -> None:
    """Reset DWT_CYCCNT to zero via OpenOCD."""
    _ocd_write32(bridge, DWT_CYCCNT_ADDR, 0, telnet_port)


def get_dwt_status_openocd(bridge, telnet_port: int = 4444) -> dict:
    """Read DWT register values via OpenOCD (same as get_dwt_status but via telnet)."""
    return {
        "DEMCR": _ocd_read32(bridge, DEMCR_ADDR, telnet_port),
        "DWT_CTRL": _ocd_read32(bridge, DWT_CTRL_ADDR, telnet_port),
        "DWT_CYCCNT": _ocd_read32(bridge, DWT_CYCCNT_ADDR, telnet_port),
    }
