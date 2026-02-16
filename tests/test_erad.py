"""Tests for ERAD profiler (Phase 3)."""

from __future__ import annotations

import pytest

from eab.analyzers.erad import (
    configure_function_profile,
    read_profile_results,
    disable_erad,
    read_erad_status,
    configure_watchpoint,
    ProfileResult,
    # Register addresses
    GLBL_ENABLE,
    GLBL_CTM_RESET,
    EBC1_CNTL,
    EBC1_REFL,
    EBC1_REFH,
    EBC2_CNTL,
    EBC2_REFL,
    EBC2_REFH,
    SEC1_CNTL,
    SEC1_COUNT,
    SEC1_MAX_COUNT,
    SEC1_INPUT_SEL1,
    SEC1_INPUT_SEL2,
)


# =========================================================================
# Helpers
# =========================================================================


class MemoryRecorder:
    """Records memory writes and provides memory reads for testing."""

    def __init__(self):
        self.writes: list[tuple[int, bytes]] = []
        self.read_values: dict[int, bytes] = {}

    def writer(self, address: int, data: bytes) -> bool:
        self.writes.append((address, data))
        return True

    def reader(self, address: int, size: int) -> bytes | None:
        return self.read_values.get(address)

    def get_write(self, address: int) -> bytes | None:
        """Get last data written to an address."""
        for addr, data in reversed(self.writes):
            if addr == address:
                return data
        return None

    def write_count(self) -> int:
        return len(self.writes)


# =========================================================================
# Register address verification
# =========================================================================


class TestRegisterAddresses:
    """Verify register addresses match f28003x.json."""

    def test_glbl_enable(self):
        assert GLBL_ENABLE == 0x5E804

    def test_glbl_ctm_reset(self):
        assert GLBL_CTM_RESET == 0x5E806

    def test_ebc1_addresses(self):
        assert EBC1_CNTL == 0x5E820
        assert EBC1_REFL == 0x5E828
        assert EBC1_REFH == 0x5E82A

    def test_ebc2_addresses(self):
        assert EBC2_CNTL == 0x5E830
        assert EBC2_REFL == 0x5E838
        assert EBC2_REFH == 0x5E83A

    def test_sec1_addresses(self):
        assert SEC1_CNTL == 0x5E880
        assert SEC1_COUNT == 0x5E888
        assert SEC1_MAX_COUNT == 0x5E88A
        assert SEC1_INPUT_SEL1 == 0x5E894
        assert SEC1_INPUT_SEL2 == 0x5E896


# =========================================================================
# configure_function_profile
# =========================================================================


class TestConfigureFunctionProfile:
    def test_writes_correct_sequence(self):
        mem = MemoryRecorder()
        result = configure_function_profile(mem.writer, 0x8000, 0x8100)
        assert result is True
        assert mem.write_count() == 12

    def test_disables_erad_first(self):
        mem = MemoryRecorder()
        configure_function_profile(mem.writer, 0x8000, 0x8100)
        # First write should disable ERAD
        assert mem.writes[0] == (GLBL_ENABLE, b"\x00\x00")

    def test_resets_counters(self):
        mem = MemoryRecorder()
        configure_function_profile(mem.writer, 0x8000, 0x8100)
        assert mem.writes[1] == (GLBL_CTM_RESET, b"\x0F\x00")

    def test_ebc1_entry_address(self):
        mem = MemoryRecorder()
        configure_function_profile(mem.writer, 0x8000, 0x8100)
        # EBC1_REFL should be function start address
        ebc1_refl_data = mem.get_write(EBC1_REFL)
        assert ebc1_refl_data == (0x8000).to_bytes(4, "little")

    def test_ebc1_exact_match_mask(self):
        mem = MemoryRecorder()
        configure_function_profile(mem.writer, 0x8000, 0x8100)
        assert mem.get_write(EBC1_REFH) == b"\xFF\xFF\xFF\xFF"

    def test_ebc1_vpc_enable(self):
        mem = MemoryRecorder()
        configure_function_profile(mem.writer, 0x8000, 0x8100)
        ebc1_cntl = int.from_bytes(mem.get_write(EBC1_CNTL), "little")
        assert ebc1_cntl & 0x000F == 4  # BUS_SEL = VPC
        assert ebc1_cntl & 0x8000 == 0x8000  # ENABLE

    def test_ebc2_exit_address(self):
        mem = MemoryRecorder()
        configure_function_profile(mem.writer, 0x8000, 0x8100)
        ebc2_refl_data = mem.get_write(EBC2_REFL)
        assert ebc2_refl_data == (0x8100).to_bytes(4, "little")

    def test_sec1_start_stop_mode(self):
        mem = MemoryRecorder()
        configure_function_profile(mem.writer, 0x8000, 0x8100)
        sec1_cntl = int.from_bytes(mem.get_write(SEC1_CNTL), "little")
        assert sec1_cntl & 0x0003 == 2  # MODE = start_stop
        assert sec1_cntl & 0x0004 == 4  # EDGE_LEVEL = level
        assert sec1_cntl & 0x8000 == 0x8000  # ENABLE

    def test_sec1_input_selects(self):
        mem = MemoryRecorder()
        configure_function_profile(mem.writer, 0x8000, 0x8100)
        sel1 = int.from_bytes(mem.get_write(SEC1_INPUT_SEL1), "little")
        sel2 = int.from_bytes(mem.get_write(SEC1_INPUT_SEL2), "little")
        assert sel1 == 1  # EBC1 event
        assert sel2 == 2  # EBC2 event

    def test_enables_erad_last(self):
        mem = MemoryRecorder()
        configure_function_profile(mem.writer, 0x8000, 0x8100)
        # Last write should enable ERAD
        last_addr, last_data = mem.writes[-1]
        assert last_addr == GLBL_ENABLE
        assert int.from_bytes(last_data, "little") == 0x000F

    def test_returns_false_on_write_failure(self):
        call_count = 0

        def failing_writer(addr, data):
            nonlocal call_count
            call_count += 1
            if call_count >= 3:
                return False
            return True

        result = configure_function_profile(failing_writer, 0x8000, 0x8100)
        assert result is False


# =========================================================================
# read_profile_results
# =========================================================================


class TestReadProfileResults:
    def test_basic_read(self):
        mem = MemoryRecorder()
        mem.read_values[SEC1_COUNT] = (1200).to_bytes(4, "little")
        mem.read_values[SEC1_MAX_COUNT] = (2400).to_bytes(4, "little")

        result = read_profile_results(mem.reader, cpu_freq_hz=120_000_000)
        assert result.cycles == 1200
        assert result.max_cycles == 2400

    def test_time_conversion_120mhz(self):
        mem = MemoryRecorder()
        mem.read_values[SEC1_COUNT] = (120).to_bytes(4, "little")  # 120 cycles
        mem.read_values[SEC1_MAX_COUNT] = (240).to_bytes(4, "little")

        result = read_profile_results(mem.reader, cpu_freq_hz=120_000_000)
        assert result.time_us == pytest.approx(1.0)  # 120 cycles / 120MHz = 1us
        assert result.max_time_us == pytest.approx(2.0)

    def test_time_conversion_200mhz(self):
        mem = MemoryRecorder()
        mem.read_values[SEC1_COUNT] = (200).to_bytes(4, "little")
        mem.read_values[SEC1_MAX_COUNT] = (400).to_bytes(4, "little")

        result = read_profile_results(mem.reader, cpu_freq_hz=200_000_000)
        assert result.time_us == pytest.approx(1.0)
        assert result.max_time_us == pytest.approx(2.0)

    def test_zero_cycles(self):
        mem = MemoryRecorder()
        mem.read_values[SEC1_COUNT] = (0).to_bytes(4, "little")
        mem.read_values[SEC1_MAX_COUNT] = (0).to_bytes(4, "little")

        result = read_profile_results(mem.reader)
        assert result.cycles == 0
        assert result.time_us == 0.0

    def test_large_cycles(self):
        mem = MemoryRecorder()
        cycles = 120_000_000  # 1 second at 120MHz
        mem.read_values[SEC1_COUNT] = cycles.to_bytes(4, "little")
        mem.read_values[SEC1_MAX_COUNT] = cycles.to_bytes(4, "little")

        result = read_profile_results(mem.reader, cpu_freq_hz=120_000_000)
        assert result.time_us == pytest.approx(1_000_000.0)  # 1 second

    def test_missing_reads(self):
        mem = MemoryRecorder()
        # No read values set — reader returns None
        result = read_profile_results(mem.reader)
        assert result.cycles == 0
        assert result.max_cycles == 0

    def test_function_metadata(self):
        mem = MemoryRecorder()
        mem.read_values[SEC1_COUNT] = (100).to_bytes(4, "little")
        mem.read_values[SEC1_MAX_COUNT] = (200).to_bytes(4, "little")

        result = read_profile_results(
            mem.reader,
            function_name="motor_isr",
            start_addr=0x8000,
            end_addr=0x8100,
        )
        assert result.function_name == "motor_isr"
        assert result.start_addr == 0x8000
        assert result.end_addr == 0x8100

    def test_to_json(self):
        result = ProfileResult(
            cycles=1200,
            max_cycles=2400,
            time_us=10.0,
            max_time_us=20.0,
            cpu_freq_hz=120_000_000,
            function_name="motor_isr",
            start_addr=0x8000,
            end_addr=0x8100,
        )
        j = result.to_json()
        assert j["cycles"] == 1200
        assert j["function"] == "motor_isr"
        assert j["start_addr"] == "0x00008000"
        assert j["cpu_freq_hz"] == 120_000_000


# =========================================================================
# disable_erad
# =========================================================================


class TestDisableErad:
    def test_writes_zero(self):
        mem = MemoryRecorder()
        result = disable_erad(mem.writer)
        assert result is True
        assert mem.writes == [(GLBL_ENABLE, b"\x00\x00")]

    def test_returns_false_on_failure(self):
        def fail_writer(addr, data):
            return False

        assert disable_erad(fail_writer) is False


# =========================================================================
# read_erad_status
# =========================================================================


class TestReadEradStatus:
    def test_reads_status(self):
        mem = MemoryRecorder()
        mem.read_values[0x5E800] = (0x0003).to_bytes(2, "little")  # GLBL_EVENT_STAT
        mem.read_values[0x5E802] = (0x0000).to_bytes(2, "little")  # GLBL_HALT_STAT
        mem.read_values[GLBL_ENABLE] = (0x000F).to_bytes(2, "little")

        status = read_erad_status(mem.reader)
        assert status["event_stat"] == 3
        assert status["halt_stat"] == 0
        assert status["enabled"] == 0x000F

    def test_missing_reads(self):
        mem = MemoryRecorder()
        status = read_erad_status(mem.reader)
        assert status["event_stat"] == 0
        assert status["enabled"] == 0


# =========================================================================
# configure_watchpoint
# =========================================================================


class TestConfigureWatchpoint:
    def test_data_write_watchpoint(self):
        mem = MemoryRecorder()
        result = configure_watchpoint(mem.writer, 0xC002, bus="DWAB", halt=True)
        assert result is True
        cntl = int.from_bytes(mem.get_write(EBC1_CNTL), "little")
        assert cntl & 0x000F == 0  # DWAB
        assert cntl & 0x0010 == 0x0010  # HALT
        assert cntl & 0x8000 == 0x8000  # ENABLE

    def test_vpc_watchpoint(self):
        mem = MemoryRecorder()
        configure_watchpoint(mem.writer, 0x8000, bus="VPC", halt=False)
        cntl = int.from_bytes(mem.get_write(EBC1_CNTL), "little")
        assert cntl & 0x000F == 4  # VPC
        assert cntl & 0x0010 == 0  # No HALT

    def test_ebc2_watchpoint(self):
        mem = MemoryRecorder()
        configure_watchpoint(mem.writer, 0xD000, bus="DRAB", ebc_num=2)
        refl = mem.get_write(EBC2_REFL)
        assert refl == (0xD000).to_bytes(4, "little")

    def test_address_written(self):
        mem = MemoryRecorder()
        configure_watchpoint(mem.writer, 0xC002)
        refl = mem.get_write(EBC1_REFL)
        assert refl == (0xC002).to_bytes(4, "little")
