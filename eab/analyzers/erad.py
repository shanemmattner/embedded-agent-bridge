"""ERAD (Enhanced Realtime Analysis and Diagnostics) profiler for C2000.

ERAD is the C2000 equivalent of ARM DWT — it uses Enhanced Bus Comparators (EBC)
to match program counter addresses and System Event Counters (SEC) to count CPU
cycles between matches. This enables non-intrusive function execution time
measurement without halting the CPU.

All register addresses are loaded from the f28003x.json register map.
Configuration is done entirely via memory writes through the XDS110 probe
or DSS transport.
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Callable, Optional

from ..register_maps import load_register_map

# Type aliases for memory access callables
MemoryReader = Callable[[int, int], Optional[bytes]]
MemoryWriter = Callable[[int, bytes], Optional[bool]]


@dataclass
class ProfileResult:
    """Result from ERAD function profiling."""

    cycles: int
    max_cycles: int
    time_us: float
    max_time_us: float
    cpu_freq_hz: int
    function_name: str = ""
    start_addr: int = 0
    end_addr: int = 0

    def to_json(self) -> dict:
        """Convert to JSON-serializable dict."""
        result = {
            "cycles": self.cycles,
            "max_cycles": self.max_cycles,
            "time_us": round(self.time_us, 3),
            "max_time_us": round(self.max_time_us, 3),
            "cpu_freq_hz": self.cpu_freq_hz,
        }
        if self.function_name:
            result["function"] = self.function_name
        if self.start_addr:
            result["start_addr"] = f"0x{self.start_addr:08X}"
        if self.end_addr:
            result["end_addr"] = f"0x{self.end_addr:08X}"
        return result


# =========================================================================
# ERAD register addresses (from f28003x.json, cached as constants for speed)
# =========================================================================

# Load once at module level
_REGMAP = load_register_map("f28003x")
_ERAD = _REGMAP.get_group("erad")

# Global control
GLBL_ENABLE = _ERAD.registers["GLBL_ENABLE"].address       # 0x5E804
GLBL_CTM_RESET = _ERAD.registers["GLBL_CTM_RESET"].address # 0x5E806

# Bus Comparator 1 (function entry)
EBC1_CNTL = _ERAD.registers["EBC1_CNTL"].address           # 0x5E820
EBC1_REFL = _ERAD.registers["EBC1_REFL"].address           # 0x5E828
EBC1_REFH = _ERAD.registers["EBC1_REFH"].address           # 0x5E82A

# Bus Comparator 2 (function exit)
EBC2_CNTL = _ERAD.registers["EBC2_CNTL"].address           # 0x5E830
EBC2_REFL = _ERAD.registers["EBC2_REFL"].address           # 0x5E838
EBC2_REFH = _ERAD.registers["EBC2_REFH"].address           # 0x5E83A

# System Event Counter 1 (cycle counter)
SEC1_CNTL = _ERAD.registers["SEC1_CNTL"].address           # 0x5E880
SEC1_COUNT = _ERAD.registers["SEC1_COUNT"].address          # 0x5E888
SEC1_MAX_COUNT = _ERAD.registers["SEC1_MAX_COUNT"].address  # 0x5E88A
SEC1_INPUT_SEL1 = _ERAD.registers["SEC1_INPUT_SEL1"].address # 0x5E894
SEC1_INPUT_SEL2 = _ERAD.registers["SEC1_INPUT_SEL2"].address # 0x5E896

# EBC control values
_EBC_VPC_ENABLE = 0x8004  # BUS_SEL=4 (VPC) | ENABLE (bit 15)

# SEC control values
_SEC_START_STOP_LEVEL_ENABLE = 0x8006  # MODE=2 (start_stop) | EDGE_LEVEL=1 (level) | ENABLE (bit 15)

# EBC event IDs for SEC input select
_EBC1_EVENT = 0x0001
_EBC2_EVENT = 0x0002


def configure_function_profile(
    memory_writer: MemoryWriter,
    start_addr: int,
    end_addr: int,
) -> bool:
    """Configure ERAD to profile function execution time.

    Sets up EBC1 to match function entry address (VPC bus),
    EBC2 to match function exit address, and SEC1 in start-stop
    mode to count CPU cycles between the two events.

    Args:
        memory_writer: Callable(address, data) -> bool | None.
        start_addr: Function entry address (from MAP file).
        end_addr: Function exit address (start_addr + function size).

    Returns:
        True if all writes succeeded.
    """
    writes = [
        # 1. Disable ERAD globally
        (GLBL_ENABLE, b"\x00\x00"),
        # 2. Reset all counters
        (GLBL_CTM_RESET, b"\x0F\x00"),
        # 3-5. Configure EBC1 for function entry (VPC bus match)
        (EBC1_REFL, start_addr.to_bytes(4, "little")),
        (EBC1_REFH, b"\xFF\xFF\xFF\xFF"),  # Exact match (no mask)
        (EBC1_CNTL, _EBC_VPC_ENABLE.to_bytes(2, "little")),
        # 6-8. Configure EBC2 for function exit
        (EBC2_REFL, end_addr.to_bytes(4, "little")),
        (EBC2_REFH, b"\xFF\xFF\xFF\xFF"),
        (EBC2_CNTL, _EBC_VPC_ENABLE.to_bytes(2, "little")),
        # 9-11. Configure SEC1 in start-stop mode
        (SEC1_INPUT_SEL1, _EBC1_EVENT.to_bytes(2, "little")),
        (SEC1_INPUT_SEL2, _EBC2_EVENT.to_bytes(2, "little")),
        (SEC1_CNTL, _SEC_START_STOP_LEVEL_ENABLE.to_bytes(2, "little")),
        # 12. Enable ERAD globally
        (GLBL_ENABLE, (0x000F).to_bytes(2, "little")),
    ]

    for addr, data in writes:
        result = memory_writer(addr, data)
        if result is False:  # Explicit False means failure (None is ok)
            return False

    return True


def read_profile_results(
    memory_reader: MemoryReader,
    cpu_freq_hz: int = 120_000_000,
    function_name: str = "",
    start_addr: int = 0,
    end_addr: int = 0,
) -> ProfileResult:
    """Read ERAD profiling results from SEC1 counter.

    Args:
        memory_reader: Callable(address, size) -> bytes | None.
        cpu_freq_hz: CPU frequency for cycle-to-time conversion.
        function_name: Optional function name for the report.
        start_addr: Function start address.
        end_addr: Function end address.

    Returns:
        ProfileResult with cycle counts and timing.
    """
    # Read SEC1_COUNT (4 bytes) — last measurement
    count_data = memory_reader(SEC1_COUNT, 4)
    cycles = int.from_bytes(count_data, "little") if count_data else 0

    # Read SEC1_MAX_COUNT (4 bytes) — worst-case
    max_data = memory_reader(SEC1_MAX_COUNT, 4)
    max_cycles = int.from_bytes(max_data, "little") if max_data else 0

    # Convert cycles to microseconds
    if cpu_freq_hz > 0:
        time_us = cycles / cpu_freq_hz * 1_000_000
        max_time_us = max_cycles / cpu_freq_hz * 1_000_000
    else:
        time_us = 0.0
        max_time_us = 0.0

    return ProfileResult(
        cycles=cycles,
        max_cycles=max_cycles,
        time_us=time_us,
        max_time_us=max_time_us,
        cpu_freq_hz=cpu_freq_hz,
        function_name=function_name,
        start_addr=start_addr,
        end_addr=end_addr,
    )


def disable_erad(memory_writer: MemoryWriter) -> bool:
    """Disable ERAD globally.

    Args:
        memory_writer: Callable(address, data) -> bool | None.

    Returns:
        True if write succeeded.
    """
    result = memory_writer(GLBL_ENABLE, b"\x00\x00")
    return result is not False


def read_erad_status(memory_reader: MemoryReader) -> dict:
    """Read ERAD global status registers.

    Returns:
        Dict with event_stat, halt_stat, and enable values.
    """
    def _read16(addr: int) -> int:
        data = memory_reader(addr, 2)
        return int.from_bytes(data, "little") if data else 0

    event_stat_addr = _ERAD.registers["GLBL_EVENT_STAT"].address
    halt_stat_addr = _ERAD.registers["GLBL_HALT_STAT"].address

    return {
        "event_stat": _read16(event_stat_addr),
        "halt_stat": _read16(halt_stat_addr),
        "enabled": _read16(GLBL_ENABLE),
        "event_stat_hex": f"0x{_read16(event_stat_addr):04X}",
        "halt_stat_hex": f"0x{_read16(halt_stat_addr):04X}",
        "enabled_hex": f"0x{_read16(GLBL_ENABLE):04X}",
    }


def configure_watchpoint(
    memory_writer: MemoryWriter,
    address: int,
    bus: str = "DWAB",
    halt: bool = True,
    ebc_num: int = 1,
) -> bool:
    """Configure an ERAD bus comparator as a data watchpoint.

    Args:
        memory_writer: Callable(address, data) -> bool | None.
        address: Memory address to watch.
        bus: Bus to monitor — "DWAB" (data write), "DRAB" (data read),
             "VPC" (program counter), "PAB" (program address).
        halt: If True, halt CPU on match.
        ebc_num: Which EBC to use (1 or 2).

    Returns:
        True if all writes succeeded.
    """
    bus_codes = {"DWAB": 0, "DRAB": 1, "DWDB": 2, "DRDB": 3, "VPC": 4, "PAB": 5}
    bus_sel = bus_codes.get(bus.upper(), 0)

    cntl = bus_sel | (1 << 15)  # BUS_SEL + ENABLE
    if halt:
        cntl |= (1 << 4)  # HALT bit

    if ebc_num == 1:
        refl, refh, cntl_addr = EBC1_REFL, EBC1_REFH, EBC1_CNTL
    else:
        refl, refh, cntl_addr = EBC2_REFL, EBC2_REFH, EBC2_CNTL

    writes = [
        (GLBL_ENABLE, b"\x00\x00"),  # Disable first
        (refl, address.to_bytes(4, "little")),
        (refh, b"\xFF\xFF\xFF\xFF"),
        (cntl_addr, cntl.to_bytes(2, "little")),
        (GLBL_ENABLE, (0x000F).to_bytes(2, "little")),  # Re-enable
    ]

    for addr, data in writes:
        result = memory_writer(addr, data)
        if result is False:
            return False

    return True
