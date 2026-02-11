"""Tests for Cortex-M33 fault analyzer.

Tests register decoding, GDB output parsing, and the full analysis pipeline
with mocked JLinkBridge and GDB subprocess.
"""

from __future__ import annotations

from unittest.mock import MagicMock, patch

import pytest

from eab.fault_analyzer import (
    CFSR_ADDR,
    HFSR_ADDR,
    MMFAR_ADDR,
    BFAR_ADDR,
    SFSR_ADDR,
    SFAR_ADDR,
    FaultReport,
    decode_cfsr,
    decode_hfsr,
    decode_sfsr,
    generate_suggestions,
    _parse_gdb_memory_read,
    _parse_gdb_registers,
    _parse_gdb_backtrace,
    analyze_fault,
    format_report,
)


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


# =============================================================================
# GDB Output Parser Tests
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


class TestParseGDBRegisters:
    def test_standard_output(self):
        output = (
            "r0             0x20000100       536871168\n"
            "r1             0x00000000       0\n"
            "r2             0xdeadbeef       3735928559\n"
            "sp             0x20008000       0x20008000\n"
            "lr             0x0800abcd       134260173\n"
            "pc             0x08001234       0x08001234\n"
        )
        regs = _parse_gdb_registers(output)
        assert regs["r0"] == 0x20000100
        assert regs["r1"] == 0
        assert regs["r2"] == 0xDEADBEEF
        assert regs["sp"] == 0x20008000
        assert regs["lr"] == 0x0800ABCD
        assert regs["pc"] == 0x08001234

    def test_empty_output(self):
        assert _parse_gdb_registers("") == {}


class TestParseGDBBacktrace:
    def test_standard_backtrace(self):
        output = (
            "(gdb) bt\n"
            "#0  z_arm_hard_fault () at src/fault.c:42\n"
            "#1  0x08001234 in main () at src/main.c:100\n"
            "#2  0x08000100 in z_thread_entry () at kernel/thread.c:50\n"
            "(gdb) \n"
        )
        bt = _parse_gdb_backtrace(output)
        assert "#0" in bt
        assert "#1" in bt
        assert "#2" in bt
        assert "z_arm_hard_fault" in bt

    def test_empty_output(self):
        assert _parse_gdb_backtrace("") == ""


# =============================================================================
# Integration Test (Mocked)
# =============================================================================

class TestAnalyzeFaultIntegration:
    """Test full pipeline with mocked JLinkBridge and GDB subprocess."""

    def _make_gdb_output(self):
        """Build fake GDB stdout with fault register reads."""
        lines = [
            "0xe000ed28:\t0x00000200",   # CFSR: PRECISERR
            "0xe000ed2c:\t0x40000000",   # HFSR: FORCED
            "0xe000ed34:\t0x00000000",   # MMFAR
            "0xe000ed38:\t0x40001000",   # BFAR
            "0xe000ede4:\t0x00000000",   # SFSR
            "0xe000ede8:\t0x00000000",   # SFAR
            "r0             0x20000100       536871168",
            "sp             0x20008000       0x20008000",
            "pc             0x08001234       0x08001234",
            "#0  z_arm_hard_fault () at src/fault.c:42",
            "#1  0x08001234 in main () at src/main.c:100",
        ]
        return "\n".join(lines) + "\n"

    @patch("eab.fault_analyzer.run_gdb_batch")
    def test_full_pipeline(self, mock_gdb_batch, tmp_path):
        """analyze_fault() should start GDB, read regs, decode, stop."""
        # Set up mock bridge
        bridge = MagicMock()
        rtt_status = MagicMock()
        rtt_status.running = False
        bridge.rtt_status.return_value = rtt_status

        gdb_status = MagicMock()
        gdb_status.running = True
        gdb_status.last_error = None
        bridge.start_gdb_server.return_value = gdb_status

        # Set up mock GDB result
        mock_result = MagicMock()
        mock_result.success = True
        mock_result.stdout = self._make_gdb_output()
        mock_result.stderr = ""
        mock_gdb_batch.return_value = mock_result

        report = analyze_fault(bridge, device="NRF5340_XXAA_APP")

        # Verify GDB server lifecycle
        bridge.start_gdb_server.assert_called_once()
        bridge.stop_gdb_server.assert_called_once()

        # Verify decoded values
        assert report.cfsr == 0x200  # PRECISERR
        assert report.hfsr == 0x40000000  # FORCED
        assert report.bfar == 0x40001000
        assert any("PRECISERR" in f for f in report.faults)
        assert any("FORCED" in f for f in report.faults)
        assert len(report.suggestions) > 0
        assert report.backtrace != ""

    @patch("eab.fault_analyzer.run_gdb_batch")
    def test_rtt_stop_and_restart(self, mock_gdb_batch, tmp_path):
        """analyze_fault() should stop RTT before GDB and restart if requested."""
        bridge = MagicMock()
        rtt_status = MagicMock()
        rtt_status.running = True  # RTT is running
        bridge.rtt_status.return_value = rtt_status

        gdb_status = MagicMock()
        gdb_status.running = True
        gdb_status.last_error = None
        bridge.start_gdb_server.return_value = gdb_status

        mock_result = MagicMock()
        mock_result.success = True
        mock_result.stdout = self._make_gdb_output()
        mock_result.stderr = ""
        mock_gdb_batch.return_value = mock_result

        report = analyze_fault(bridge, device="NRF5340_XXAA_APP", restart_rtt=True)

        # Should stop RTT before GDB
        bridge.stop_rtt.assert_called_once()
        # Should restart RTT after analysis
        bridge.start_rtt.assert_called_once_with(device="NRF5340_XXAA_APP")

    @patch("eab.fault_analyzer.run_gdb_batch")
    def test_gdb_server_failure(self, mock_gdb_batch, tmp_path):
        """analyze_fault() should handle GDB server start failure."""
        bridge = MagicMock()
        rtt_status = MagicMock()
        rtt_status.running = False
        bridge.rtt_status.return_value = rtt_status

        gdb_status = MagicMock()
        gdb_status.running = False
        gdb_status.last_error = "JLinkGDBServer not found"
        bridge.start_gdb_server.return_value = gdb_status

        report = analyze_fault(bridge, device="NRF5340_XXAA_APP")

        assert len(report.faults) > 0
        assert "failed to start" in report.faults[0].lower()
        # GDB batch should NOT have been called
        mock_gdb_batch.assert_not_called()


# =============================================================================
# Format Report Tests
# =============================================================================

class TestFormatReport:
    def test_includes_all_sections(self):
        report = FaultReport(
            cfsr=0x200,
            hfsr=0x40000000,
            mmfar=0,
            bfar=0x40001000,
            sfsr=0,
            sfar=0,
            core_regs={"r0": 0x20000100, "pc": 0x08001234},
            backtrace="#0  main () at main.c:42",
            faults=["PRECISERR: Precise data bus error"],
            suggestions=["Check peripheral clock enables"],
        )
        text = format_report(report)

        assert "FAULT REGISTERS" in text
        assert "0x00000200" in text  # CFSR
        assert "DECODED FAULTS" in text
        assert "PRECISERR" in text
        assert "SUGGESTIONS" in text
        assert "peripheral clock" in text
        assert "CORE REGISTERS" in text
        assert "BACKTRACE" in text
        assert "main.c" in text

    def test_empty_report(self):
        report = FaultReport()
        text = format_report(report)
        assert "CORTEX-M33 FAULT ANALYSIS" in text
        assert "FAULT REGISTERS" in text
