"""Tests for ARM Cortex-M fault decoder.

Tests register decoding, GDB output parsing, PSP frame extraction,
suggestion generation, and the CortexMDecoder class.
"""

from __future__ import annotations

import pytest

from eab.fault_decoders import get_fault_decoder, FaultReport
from eab.fault_decoders.cortex_m import (
    CFSR_ADDR,
    HFSR_ADDR,
    MMFAR_ADDR,
    BFAR_ADDR,
    SFSR_ADDR,
    SFAR_ADDR,
    CortexMDecoder,
    decode_cfsr,
    decode_hfsr,
    decode_sfsr,
    generate_suggestions,
    _parse_gdb_memory_read,
    _parse_psp_frame,
)


# =============================================================================
# Registry Tests
# =============================================================================

class TestRegistry:
    def test_nrf5340_returns_cortex_m(self):
        d = get_fault_decoder("nrf5340")
        assert isinstance(d, CortexMDecoder)
        assert d.name == "ARM Cortex-M"

    def test_stm32l4_returns_cortex_m(self):
        d = get_fault_decoder("stm32l4")
        assert isinstance(d, CortexMDecoder)

    def test_unknown_chip_defaults_to_cortex_m(self):
        d = get_fault_decoder("unknown_chip_xyz")
        assert isinstance(d, CortexMDecoder)

    def test_case_insensitive(self):
        d = get_fault_decoder("NRF5340")
        assert isinstance(d, CortexMDecoder)


# =============================================================================
# CFSR Decode Tests
# =============================================================================

class TestDecodeCFSR:
    def test_iaccviol(self):
        faults = decode_cfsr(1 << 0)
        assert any("IACCVIOL" in f for f in faults)

    def test_daccviol(self):
        faults = decode_cfsr(1 << 1)
        assert any("DACCVIOL" in f for f in faults)

    def test_preciserr(self):
        faults = decode_cfsr(1 << 9)
        assert any("PRECISERR" in f for f in faults)

    def test_impreciserr(self):
        faults = decode_cfsr(1 << 10)
        assert any("IMPRECISERR" in f for f in faults)

    def test_undefinstr(self):
        faults = decode_cfsr(1 << 16)
        assert any("UNDEFINSTR" in f for f in faults)

    def test_divbyzero(self):
        faults = decode_cfsr(1 << 25)
        assert any("DIVBYZERO" in f for f in faults)

    def test_stkof(self):
        faults = decode_cfsr(1 << 20)
        assert any("STKOF" in f for f in faults)

    def test_unaligned(self):
        faults = decode_cfsr(1 << 24)
        assert any("UNALIGNED" in f for f in faults)

    def test_combo_daccviol_mmarvalid(self):
        """DACCVIOL + MMARVALID (typical MPU fault)."""
        faults = decode_cfsr((1 << 1) | (1 << 7))
        names = [f.split(":")[0] for f in faults]
        assert "DACCVIOL" in names
        assert "MMARVALID" in names

    def test_combo_preciserr_bfarvalid(self):
        """PRECISERR + BFARVALID (typical bus fault)."""
        faults = decode_cfsr((1 << 9) | (1 << 15))
        names = [f.split(":")[0] for f in faults]
        assert "PRECISERR" in names
        assert "BFARVALID" in names

    def test_zero_returns_empty(self):
        assert decode_cfsr(0) == []


# =============================================================================
# HFSR Decode Tests
# =============================================================================

class TestDecodeHFSR:
    def test_forced(self):
        faults = decode_hfsr(1 << 30)
        assert any("FORCED" in f for f in faults)

    def test_vecttbl(self):
        faults = decode_hfsr(1 << 1)
        assert any("VECTTBL" in f for f in faults)

    def test_debugevt(self):
        faults = decode_hfsr(1 << 31)
        assert any("DEBUGEVT" in f for f in faults)

    def test_zero_returns_empty(self):
        assert decode_hfsr(0) == []


# =============================================================================
# SFSR Decode Tests
# =============================================================================

class TestDecodeSFSR:
    def test_invep(self):
        faults = decode_sfsr(1 << 0)
        assert any("INVEP" in f for f in faults)

    def test_invis(self):
        faults = decode_sfsr(1 << 1)
        assert any("INVIS" in f for f in faults)

    def test_inver(self):
        faults = decode_sfsr(1 << 2)
        assert any("INVER" in f for f in faults)

    def test_zero_returns_empty(self):
        assert decode_sfsr(0) == []


# =============================================================================
# Suggestion Generation Tests
# =============================================================================

class TestGenerateSuggestions:
    def test_stack_overflow(self):
        faults = ["STKOF: Stack overflow detected by hardware stack limit"]
        suggestions = generate_suggestions(faults, mmfar=0, bfar=0)
        assert any("stack" in s.lower() for s in suggestions)
        assert any("CONFIG_MAIN_STACK_SIZE" in s for s in suggestions)

    def test_null_pointer(self):
        faults = ["DACCVIOL: Data access violation", "MMARVALID: MMFAR holds a valid fault address"]
        suggestions = generate_suggestions(faults, mmfar=0, bfar=0)
        assert any("NULL pointer" in s for s in suggestions)

    def test_bus_error_with_address(self):
        faults = ["PRECISERR: Precise data bus error", "BFARVALID: BFAR holds a valid fault address"]
        suggestions = generate_suggestions(faults, mmfar=0, bfar=0x40000000)
        assert any("0x40000000" in s for s in suggestions)

    def test_unaligned(self):
        faults = ["UNALIGNED: Unaligned memory access"]
        suggestions = generate_suggestions(faults, mmfar=0, bfar=0)
        assert any("unaligned" in s.lower() or "packed" in s.lower() for s in suggestions)

    def test_divbyzero(self):
        faults = ["DIVBYZERO: Divide by zero"]
        suggestions = generate_suggestions(faults, mmfar=0, bfar=0)
        assert any("zero" in s.lower() for s in suggestions)

    def test_trustzone(self):
        faults = ["INVEP: Invalid entry point"]
        suggestions = generate_suggestions(faults, mmfar=0, bfar=0)
        assert any("TrustZone" in s for s in suggestions)

    def test_no_faults_gives_generic(self):
        suggestions = generate_suggestions([], mmfar=0, bfar=0)
        assert len(suggestions) >= 1

    def test_cfsr_zero_with_forced_hfsr(self):
        """When CFSR=0 but HFSR has FORCED bit, suggest checking RTT/serial."""
        faults = ["FORCED: Forced hard fault (escalated from configurable fault)"]
        suggestions = generate_suggestions(faults, mmfar=0, bfar=0, cfsr=0, hfsr=0x40000000)
        assert any("CFSR was cleared" in s for s in suggestions)
        assert any("RTT/serial" in s for s in suggestions)

    def test_cfsr_nonzero_no_cleared_hint(self):
        """When CFSR is non-zero, don't add the 'cleared' hint even with FORCED."""
        faults = ["PRECISERR: Precise data bus error", "FORCED: Forced hard fault"]
        suggestions = generate_suggestions(faults, mmfar=0, bfar=0x50FF0000, cfsr=0x200, hfsr=0x40000000)
        assert not any("CFSR was cleared" in s for s in suggestions)


# =============================================================================
# GDB Memory Read Parser Tests
# =============================================================================

class TestParseGDBMemoryRead:
    def test_standard_output(self):
        output = "0xe000ed28:\t0x00000100\n"
        val = _parse_gdb_memory_read(output, CFSR_ADDR)
        assert val == 0x100

    def test_uppercase_hex(self):
        output = "0xE000ED28:\t0x00008200\n"
        val = _parse_gdb_memory_read(output, CFSR_ADDR)
        assert val == 0x8200

    def test_with_surrounding_output(self):
        output = (
            "Reading symbols from /path/to/zephyr.elf...\n"
            "0xe000ed28:\t0x00000002\n"
            "(gdb) \n"
        )
        val = _parse_gdb_memory_read(output, CFSR_ADDR)
        assert val == 0x2

    def test_returns_none_for_missing(self):
        output = "some random gdb output\n"
        val = _parse_gdb_memory_read(output, CFSR_ADDR)
        assert val is None


# =============================================================================
# PSP Frame Parser Tests
# =============================================================================

class TestParsePSPFrame:
    def test_standard_psp_output(self):
        """Parse typical GDB x/8wx $psp output."""
        output = (
            "0x20007fc0:\t0x00000001\t0x00000002\t0x00000003\t0x00000004\n"
            "0x20007fd0:\t0x0000000c\t0x0800abcd\t0x08001234\t0x21000000\n"
        )
        pc = _parse_psp_frame(output)
        assert pc == 0x08001234

    def test_not_enough_words(self):
        """Return None if fewer than 7 words parsed."""
        output = "0x20007fc0:\t0x00000001\t0x00000002\n"
        pc = _parse_psp_frame(output)
        assert pc is None

    def test_empty_output(self):
        assert _parse_psp_frame("") is None

    def test_mixed_with_other_gdb_output(self):
        """PSP frame lines amid other GDB output."""
        output = (
            "0xe000ed28:\t0x00000000\n"
            "r0             0x20000100       536871168\n"
            "0x20007fc0:\t0xAAAAAAAA\t0xBBBBBBBB\t0xCCCCCCCC\t0xDDDDDDDD\n"
            "0x20007fd0:\t0xEEEEEEEE\t0x0800FFFF\t0x08004000\t0x61000000\n"
            "#0  z_arm_hard_fault ()\n"
        )
        pc = _parse_psp_frame(output)
        assert pc == 0x08004000


# =============================================================================
# CortexMDecoder Tests
# =============================================================================

class TestCortexMDecoder:
    def test_name(self):
        d = CortexMDecoder()
        assert d.name == "ARM Cortex-M"

    def test_gdb_commands_returns_register_reads(self):
        d = CortexMDecoder()
        cmds = d.gdb_commands()
        # Should have 6 register reads + 1 PSP frame read
        assert len(cmds) == 7
        assert any("0xE000ED28" in c for c in cmds)  # CFSR
        assert any("$psp" in c for c in cmds)

    def test_parse_and_decode_preciserr(self):
        """Full parse_and_decode with PRECISERR + FORCED."""
        gdb_output = (
            "0xe000ed28:\t0x00000200\n"   # CFSR: PRECISERR
            "0xe000ed2c:\t0x40000000\n"   # HFSR: FORCED
            "0xe000ed34:\t0x00000000\n"   # MMFAR
            "0xe000ed38:\t0x40001000\n"   # BFAR
            "0xe000ede4:\t0x00000000\n"   # SFSR
            "0xe000ede8:\t0x00000000\n"   # SFAR
        )
        d = CortexMDecoder()
        report = d.parse_and_decode(gdb_output)

        assert report.arch == "cortex-m"
        assert report.fault_registers["CFSR"] == 0x200
        assert report.fault_registers["HFSR"] == 0x40000000
        assert report.fault_registers["BFAR"] == 0x40001000
        assert any("PRECISERR" in f for f in report.faults)
        assert any("FORCED" in f for f in report.faults)
        assert any("0x40001000" in s for s in report.suggestions)

    def test_parse_and_decode_with_psp_frame(self):
        """parse_and_decode extracts stacked PC from PSP frame."""
        gdb_output = (
            "0xe000ed28:\t0x00000000\n"
            "0xe000ed2c:\t0x40000000\n"
            "0xe000ed34:\t0x00000000\n"
            "0xe000ed38:\t0x00000000\n"
            "0xe000ede4:\t0x00000000\n"
            "0xe000ede8:\t0x00000000\n"
            "0x20007fc0:\t0x00000000\t0x00000000\t0x00000000\t0x00000000\n"
            "0x20007fd0:\t0x00000000\t0x0800abcd\t0x08001234\t0x21000000\n"
        )
        d = CortexMDecoder()
        report = d.parse_and_decode(gdb_output)
        assert report.stacked_pc == 0x08001234

    def test_parse_and_decode_empty_output(self):
        """Empty GDB output produces zeroed report with no faults."""
        d = CortexMDecoder()
        report = d.parse_and_decode("")
        assert report.arch == "cortex-m"
        assert all(v == 0 for v in report.fault_registers.values())
        assert report.faults == []
