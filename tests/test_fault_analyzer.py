"""Tests for fault analysis orchestrator.

Tests the thin orchestrator (analyze_fault, format_report) and universal
GDB parsers. Architecture-specific decoder tests live in test_cortex_m_decoder.py.
"""

from __future__ import annotations

from unittest.mock import MagicMock, patch

import pytest

from eab.debug_probes.base import DebugProbe, GDBServerStatus
from eab.debug_probes.jlink import JLinkProbe
from eab.fault_analyzer import (
    analyze_fault,
    format_report,
    _parse_gdb_registers,
    _parse_gdb_backtrace,
    _wrap_legacy_bridge,
)
from eab.fault_decoders import FaultReport, get_fault_decoder


# =============================================================================
# Universal GDB Parser Tests
# =============================================================================

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
# Legacy Bridge Wrapping
# =============================================================================

class TestWrapLegacyBridge:
    def test_debug_probe_passes_through(self):
        """A DebugProbe should pass through unwrapped."""
        probe = MagicMock(spec=DebugProbe)
        result, legacy = _wrap_legacy_bridge(probe)
        assert result is probe
        assert legacy is None

    def test_jlink_bridge_gets_wrapped(self):
        """A JLinkBridge should be wrapped in JLinkProbe."""
        bridge = MagicMock()
        bridge.rtt_status = MagicMock()
        result, legacy = _wrap_legacy_bridge(bridge)
        assert isinstance(result, JLinkProbe)
        assert legacy is bridge


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
        bridge = MagicMock()
        rtt_status = MagicMock()
        rtt_status.running = False
        bridge.rtt_status.return_value = rtt_status

        gdb_status = MagicMock()
        gdb_status.running = True
        gdb_status.last_error = None
        gdb_status.port = 2331
        bridge.start_gdb_server.return_value = gdb_status

        mock_result = MagicMock()
        mock_result.success = True
        mock_result.stdout = self._make_gdb_output()
        mock_result.stderr = ""
        mock_gdb_batch.return_value = mock_result

        report = analyze_fault(bridge, device="NRF5340_XXAA_APP")

        # Verify GDB server lifecycle
        bridge.start_gdb_server.assert_called_once()
        bridge.stop_gdb_server.assert_called_once()

        # Verify decoded values via fault_registers dict
        assert report.fault_registers["CFSR"] == 0x200  # PRECISERR
        assert report.fault_registers["HFSR"] == 0x40000000  # FORCED
        assert report.fault_registers["BFAR"] == 0x40001000
        assert any("PRECISERR" in f for f in report.faults)
        assert any("FORCED" in f for f in report.faults)
        assert len(report.suggestions) > 0
        assert report.backtrace != ""
        assert report.arch == "cortex-m"

    @patch("eab.fault_analyzer.run_gdb_batch")
    def test_full_pipeline_with_debug_probe(self, mock_gdb_batch, tmp_path):
        """analyze_fault() should work with a DebugProbe (no RTT)."""
        probe = MagicMock(spec=DebugProbe)
        probe.gdb_port = 3333
        probe.start_gdb_server.return_value = GDBServerStatus(
            running=True, pid=12345, port=3333
        )

        mock_result = MagicMock()
        mock_result.success = True
        mock_result.stdout = self._make_gdb_output()
        mock_result.stderr = ""
        mock_gdb_batch.return_value = mock_result

        report = analyze_fault(probe, device="MCXN947", chip="mcxn947")

        probe.start_gdb_server.assert_called_once()
        probe.stop_gdb_server.assert_called_once()
        assert report.arch == "cortex-m"
        # GDB batch should target the probe's port
        call_kwargs = mock_gdb_batch.call_args[1]
        assert call_kwargs["target"] == "localhost:3333"

    @patch("eab.fault_analyzer.run_gdb_batch")
    def test_rtt_stop_and_restart(self, mock_gdb_batch, tmp_path):
        """analyze_fault() should stop RTT before GDB and restart if requested."""
        bridge = MagicMock()
        rtt_status = MagicMock()
        rtt_status.running = True
        bridge.rtt_status.return_value = rtt_status

        gdb_status = MagicMock()
        gdb_status.running = True
        gdb_status.last_error = None
        gdb_status.port = 2331
        bridge.start_gdb_server.return_value = gdb_status

        mock_result = MagicMock()
        mock_result.success = True
        mock_result.stdout = self._make_gdb_output()
        mock_result.stderr = ""
        mock_gdb_batch.return_value = mock_result

        report = analyze_fault(bridge, device="NRF5340_XXAA_APP", restart_rtt=True)

        bridge.stop_rtt.assert_called_once()
        bridge.start_rtt.assert_called_once_with(device="NRF5340_XXAA_APP")

    @patch("eab.fault_analyzer.run_gdb_batch")
    def test_no_rtt_for_openocd_probe(self, mock_gdb_batch, tmp_path):
        """analyze_fault() with DebugProbe should NOT touch RTT."""
        probe = MagicMock(spec=DebugProbe)
        probe.gdb_port = 3333
        probe.start_gdb_server.return_value = GDBServerStatus(
            running=True, pid=12345, port=3333
        )

        mock_result = MagicMock()
        mock_result.success = True
        mock_result.stdout = self._make_gdb_output()
        mock_result.stderr = ""
        mock_gdb_batch.return_value = mock_result

        report = analyze_fault(probe, device="MCXN947", chip="mcxn947")

        # DebugProbe has no rtt_status — should never be called
        assert not hasattr(probe, "rtt_status") or not probe.rtt_status.called

    @patch("eab.fault_analyzer.run_gdb_batch")
    def test_cfsr_zero_with_psp_frame(self, mock_gdb_batch, tmp_path):
        """CFSR=0 + FORCED: should produce cleared hint and parse stacked PC."""
        bridge = MagicMock()
        rtt_status = MagicMock()
        rtt_status.running = False
        bridge.rtt_status.return_value = rtt_status

        gdb_status = MagicMock()
        gdb_status.running = True
        gdb_status.last_error = None
        gdb_status.port = 2331
        bridge.start_gdb_server.return_value = gdb_status

        lines = [
            "0xe000ed28:\t0x00000000",   # CFSR: 0 (cleared by Zephyr)
            "0xe000ed2c:\t0x40000000",   # HFSR: FORCED
            "0xe000ed34:\t0x00000000",
            "0xe000ed38:\t0x00000000",
            "0xe000ede4:\t0x00000000",
            "0xe000ede8:\t0x00000000",
            "r0             0x20000100       536871168",
            "sp             0x20008000       0x20008000",
            "pc             0x08000500       0x08000500",
            "0x20007fc0:\t0x00000000\t0x00000000\t0x00000000\t0x00000000",
            "0x20007fd0:\t0x00000000\t0x0800abcd\t0x08001234\t0x21000000",
            "#0  z_arm_hard_fault () at src/fault.c:42",
        ]
        mock_result = MagicMock()
        mock_result.success = True
        mock_result.stdout = "\n".join(lines) + "\n"
        mock_result.stderr = ""
        mock_gdb_batch.return_value = mock_result

        report = analyze_fault(bridge, device="NRF5340_XXAA_APP")

        assert report.fault_registers["CFSR"] == 0
        assert report.fault_registers["HFSR"] == 0x40000000
        assert report.stacked_pc == 0x08001234
        assert any("CFSR was cleared" in s for s in report.suggestions)

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
        gdb_status.port = 2331
        bridge.start_gdb_server.return_value = gdb_status

        report = analyze_fault(bridge, device="NRF5340_XXAA_APP")

        assert len(report.faults) > 0
        assert "failed to start" in report.faults[0].lower()
        mock_gdb_batch.assert_not_called()

    @patch("eab.fault_analyzer.run_gdb_batch")
    def test_custom_decoder_override(self, mock_gdb_batch):
        """analyze_fault() should use a provided decoder instead of chip lookup."""
        bridge = MagicMock()
        rtt_status = MagicMock()
        rtt_status.running = False
        bridge.rtt_status.return_value = rtt_status

        gdb_status = MagicMock()
        gdb_status.running = True
        gdb_status.last_error = None
        gdb_status.port = 2331
        bridge.start_gdb_server.return_value = gdb_status

        mock_result = MagicMock()
        mock_result.success = True
        mock_result.stdout = self._make_gdb_output()
        mock_result.stderr = ""
        mock_gdb_batch.return_value = mock_result

        decoder = get_fault_decoder("nrf5340")
        report = analyze_fault(bridge, device="NRF5340_XXAA_APP", decoder=decoder)

        assert report.arch == "cortex-m"
        assert "CFSR" in report.fault_registers


# =============================================================================
# Format Report Tests
# =============================================================================

class TestFormatReport:
    def test_includes_all_sections(self):
        report = FaultReport(
            arch="cortex-m",
            fault_registers={
                "CFSR": 0x200,
                "HFSR": 0x40000000,
                "MMFAR": 0,
                "BFAR": 0x40001000,
                "SFSR": 0,
                "SFAR": 0,
            },
            core_regs={"r0": 0x20000100, "pc": 0x08001234},
            backtrace="#0  main () at main.c:42",
            faults=["PRECISERR: Precise data bus error"],
            suggestions=["Check peripheral clock enables"],
        )
        text = format_report(report)

        assert "CORTEX-M ANALYSIS" in text
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
        assert "FAULT ANALYSIS" in text

    def test_stacked_pc_shown(self):
        report = FaultReport(
            arch="cortex-m",
            fault_registers={"CFSR": 0},
            stacked_pc=0x08004000,
        )
        text = format_report(report)
        assert "0x08004000" in text
        assert "Stacked PC" in text
