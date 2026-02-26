"""Tests for AutoFaultAnalyzer — auto-triggered fault analysis on crash detection.

Covers:
- disabled config is a no-op
- debounce drops second call within window
- analyze_fault called on first crash
- fault_report event emitted with correct shape
- failure case emits error field
- trigger_line truncated to 200 chars
- second crash while analysis running is dropped (not debounce)
- openocd probe kwargs set correctly
"""

from __future__ import annotations

import json
import threading
import time
from typing import Optional
from unittest.mock import MagicMock, patch, call

import pytest

from eab.auto_fault_analyzer import AutoFaultAnalyzer, AutoFaultConfig
from eab.event_emitter import EventEmitter
from eab.fault_decoders.base import FaultReport
from eab.implementations import RealFileSystem, RealClock


# =============================================================================
# Test helpers
# =============================================================================

def make_emitter(tmp_path) -> EventEmitter:
    events_path = str(tmp_path / "events.jsonl")
    return EventEmitter(
        filesystem=RealFileSystem(),
        clock=RealClock(),
        events_path=events_path,
    )


def make_fault_report(
    arch: str = "cortex-m",
    faults: Optional[list] = None,
    suggestions: Optional[list] = None,
    fault_registers: Optional[dict] = None,
    core_regs: Optional[dict] = None,
    stacked_pc: Optional[int] = None,
    backtrace: str = "",
    rtt_context: Optional[list] = None,
) -> FaultReport:
    return FaultReport(
        arch=arch,
        faults=faults or ["HardFault"],
        suggestions=suggestions or [],
        fault_registers=fault_registers or {},
        core_regs=core_regs or {},
        stacked_pc=stacked_pc,
        backtrace=backtrace,
        rtt_context=rtt_context or [],
    )


def read_events(tmp_path) -> list[dict]:
    events_path = tmp_path / "events.jsonl"
    if not events_path.exists():
        return []
    lines = events_path.read_text().strip().splitlines()
    return [json.loads(line) for line in lines if line.strip()]


def make_config(**kwargs) -> AutoFaultConfig:
    defaults = dict(
        enabled=True,
        chip="nrf5340",
        device="NRF5340_XXAA_APP",
        probe_type="jlink",
        debounce_seconds=5.0,
    )
    defaults.update(kwargs)
    return AutoFaultConfig(**defaults)


# =============================================================================
# Disabled config
# =============================================================================

class TestAutoFaultAnalyzerDisabled:
    def test_disabled_config_never_triggers_analysis(self, tmp_path):
        """When enabled=False, on_crash_detected() is a no-op."""
        config = AutoFaultConfig(enabled=False)
        emitter = make_emitter(tmp_path)
        analyzer = AutoFaultAnalyzer(config=config, emitter=emitter)

        with patch("eab.auto_fault_analyzer.analyze_fault") as mock_analyze:
            analyzer.on_crash_detected("Guru Meditation Error")
            time.sleep(0.1)
            mock_analyze.assert_not_called()

        # No events written
        events = read_events(tmp_path)
        assert events == []

    def test_disabled_config_no_thread_spawned(self, tmp_path):
        """Disabled config → no background thread created."""
        config = AutoFaultConfig(enabled=False)
        emitter = make_emitter(tmp_path)
        analyzer = AutoFaultAnalyzer(config=config, emitter=emitter)

        analyzer.on_crash_detected("crash line")
        assert analyzer._analysis_thread is None

    def test_is_running_false_when_disabled_and_idle(self, tmp_path):
        """is_running() returns False when nothing has been triggered."""
        config = AutoFaultConfig(enabled=False)
        emitter = make_emitter(tmp_path)
        analyzer = AutoFaultAnalyzer(config=config, emitter=emitter)
        assert analyzer.is_running() is False


# =============================================================================
# Debounce
# =============================================================================

class TestAutoFaultAnalyzerDebounce:
    def test_rapid_crash_lines_trigger_only_once(self, tmp_path):
        """Multiple crash lines within debounce window → single analysis."""
        config = make_config(debounce_seconds=60.0)
        emitter = make_emitter(tmp_path)
        analyzer = AutoFaultAnalyzer(config=config, emitter=emitter)

        with patch("eab.auto_fault_analyzer.analyze_fault") as mock_analyze, \
             patch("eab.auto_fault_analyzer.get_debug_probe"):
            mock_analyze.return_value = make_fault_report()

            for _ in range(10):
                analyzer.on_crash_detected("E: ***** ZEPHYR FATAL ERROR")
                time.sleep(0.005)

            # Wait for thread to finish
            if analyzer._analysis_thread:
                analyzer._analysis_thread.join(timeout=5)

            assert mock_analyze.call_count == 1

    def test_second_crash_after_debounce_triggers_new_analysis(self, tmp_path):
        """After debounce window expires, a new crash triggers another analysis."""
        config = make_config(debounce_seconds=0.05)
        emitter = make_emitter(tmp_path)
        analyzer = AutoFaultAnalyzer(config=config, emitter=emitter)

        with patch("eab.auto_fault_analyzer.analyze_fault") as mock_analyze, \
             patch("eab.auto_fault_analyzer.get_debug_probe"):
            mock_analyze.return_value = make_fault_report()

            # First trigger
            analyzer.on_crash_detected("crash line 1")
            if analyzer._analysis_thread:
                analyzer._analysis_thread.join(timeout=5)

            time.sleep(0.1)  # past debounce window

            # Second trigger
            analyzer.on_crash_detected("crash line 2")
            if analyzer._analysis_thread:
                analyzer._analysis_thread.join(timeout=5)

            assert mock_analyze.call_count == 2

    def test_first_crash_triggers_analysis(self, tmp_path):
        """First crash line always triggers analysis when enabled."""
        config = make_config(debounce_seconds=5.0)
        emitter = make_emitter(tmp_path)
        analyzer = AutoFaultAnalyzer(config=config, emitter=emitter)

        with patch("eab.auto_fault_analyzer.analyze_fault") as mock_analyze, \
             patch("eab.auto_fault_analyzer.get_debug_probe"):
            mock_analyze.return_value = make_fault_report()

            analyzer.on_crash_detected("first crash")
            if analyzer._analysis_thread:
                analyzer._analysis_thread.join(timeout=5)

            assert mock_analyze.call_count == 1


# =============================================================================
# Event emission — success case
# =============================================================================

class TestAutoFaultAnalyzerEventEmissionSuccess:
    def test_success_emits_fault_report_with_correct_shape(self, tmp_path):
        """Successful analysis → fault_report event with all required fields."""
        config = make_config(
            chip="nrf5340",
            device="NRF5340_XXAA_APP",
            probe_type="jlink",
            debounce_seconds=0.0,
        )
        emitter = make_emitter(tmp_path)
        analyzer = AutoFaultAnalyzer(config=config, emitter=emitter)

        fake_report = make_fault_report(
            arch="cortex-m",
            fault_registers={"CFSR": 0x20000, "HFSR": 0x40000000},
            stacked_pc=0x0800ABCD,
            faults=["BusFault: Imprecise data bus error"],
            suggestions=["Check DMA config"],
            core_regs={"pc": 0x0800ABCD, "r0": 0},
            backtrace="#0  z_arm_hard_fault",
            rtt_context=["[10:30:11] Starting"],
        )

        with patch("eab.auto_fault_analyzer.analyze_fault", return_value=fake_report), \
             patch("eab.auto_fault_analyzer.get_debug_probe"):
            analyzer.on_crash_detected("E: ***** ZEPHYR FATAL ERROR")
            if analyzer._analysis_thread:
                analyzer._analysis_thread.join(timeout=5)

        events = read_events(tmp_path)
        assert len(events) == 1
        ev = events[0]

        # Assert outer envelope
        assert ev["type"] == "fault_report"
        assert ev["level"] == "error"
        assert ev["schema_version"] == 1
        assert "sequence" in ev
        assert "timestamp" in ev

        # Assert data fields
        d = ev["data"]
        assert d["trigger_line"] == "E: ***** ZEPHYR FATAL ERROR"
        assert d["chip"] == "nrf5340"
        assert d["device"] == "NRF5340_XXAA_APP"
        assert d["probe_type"] == "jlink"
        assert d["arch"] == "cortex-m"
        assert d["fault_registers"]["CFSR"] == "0x00020000"
        assert d["fault_registers"]["HFSR"] == "0x40000000"
        assert d["stacked_pc"] == "0x0800ABCD"
        assert d["faults"] == ["BusFault: Imprecise data bus error"]
        assert d["suggestions"] == ["Check DMA config"]
        assert d["backtrace"] == "#0  z_arm_hard_fault"
        assert d["rtt_context"] == ["[10:30:11] Starting"]
        assert isinstance(d["analysis_duration_s"], float)
        assert d["error"] is None

    def test_core_regs_formatted_as_hex_strings(self, tmp_path):
        """core_regs values are formatted as 0x-prefixed hex strings."""
        config = make_config(debounce_seconds=0.0)
        emitter = make_emitter(tmp_path)
        analyzer = AutoFaultAnalyzer(config=config, emitter=emitter)

        fake_report = make_fault_report(
            core_regs={"r0": 0, "pc": 0x08001234, "sp": 0x20007FFF},
        )

        with patch("eab.auto_fault_analyzer.analyze_fault", return_value=fake_report), \
             patch("eab.auto_fault_analyzer.get_debug_probe"):
            analyzer.on_crash_detected("crash")
            if analyzer._analysis_thread:
                analyzer._analysis_thread.join(timeout=5)

        d = read_events(tmp_path)[0]["data"]
        assert d["core_regs"]["r0"] == "0x00000000"
        assert d["core_regs"]["pc"] == "0x08001234"
        assert d["core_regs"]["sp"] == "0x20007FFF"

    def test_null_stacked_pc_emitted_as_null(self, tmp_path):
        """stacked_pc=None → "stacked_pc": null in event data."""
        config = make_config(debounce_seconds=0.0)
        emitter = make_emitter(tmp_path)
        analyzer = AutoFaultAnalyzer(config=config, emitter=emitter)

        fake_report = make_fault_report(stacked_pc=None)

        with patch("eab.auto_fault_analyzer.analyze_fault", return_value=fake_report), \
             patch("eab.auto_fault_analyzer.get_debug_probe"):
            analyzer.on_crash_detected("crash")
            if analyzer._analysis_thread:
                analyzer._analysis_thread.join(timeout=5)

        d = read_events(tmp_path)[0]["data"]
        assert d["stacked_pc"] is None


# =============================================================================
# Event emission — failure case
# =============================================================================

class TestAutoFaultAnalyzerEventEmissionFailure:
    def test_gdb_failure_emits_fault_report_with_error_field(self, tmp_path):
        """Failed analysis → fault_report event with error field populated."""
        config = make_config(debounce_seconds=0.0)
        emitter = make_emitter(tmp_path)
        analyzer = AutoFaultAnalyzer(config=config, emitter=emitter)

        with patch(
            "eab.auto_fault_analyzer.analyze_fault",
            side_effect=RuntimeError("GDB server failed to start: J-Link not found"),
        ), patch("eab.auto_fault_analyzer.get_debug_probe"):
            analyzer.on_crash_detected("Guru Meditation Error")
            if analyzer._analysis_thread:
                analyzer._analysis_thread.join(timeout=5)

        events = read_events(tmp_path)
        assert len(events) == 1
        d = events[0]["data"]
        assert d["error"] == "GDB server failed to start: J-Link not found"
        # Error case has minimal fields — no fault_registers, faults, etc.
        assert "fault_registers" not in d
        assert "faults" not in d
        # But always has these
        assert d["trigger_line"] == "Guru Meditation Error"
        assert d["chip"] == "nrf5340"
        assert d["device"] == "NRF5340_XXAA_APP"
        assert d["probe_type"] == "jlink"
        assert isinstance(d["analysis_duration_s"], float)

    def test_failure_event_outer_envelope_correct(self, tmp_path):
        """Failure case still emits fault_report type with error level."""
        config = make_config(debounce_seconds=0.0)
        emitter = make_emitter(tmp_path)
        analyzer = AutoFaultAnalyzer(config=config, emitter=emitter)

        with patch(
            "eab.auto_fault_analyzer.analyze_fault",
            side_effect=ValueError("probe error"),
        ), patch("eab.auto_fault_analyzer.get_debug_probe"):
            analyzer.on_crash_detected("crash")
            if analyzer._analysis_thread:
                analyzer._analysis_thread.join(timeout=5)

        ev = read_events(tmp_path)[0]
        assert ev["type"] == "fault_report"
        assert ev["level"] == "error"
        assert ev["schema_version"] == 1


# =============================================================================
# Trigger line truncation
# =============================================================================

class TestAutoFaultAnalyzerTriggerLineTruncation:
    def test_trigger_line_truncated_to_200_chars(self, tmp_path):
        """trigger_line is capped at 200 characters in the event."""
        long_line = "X" * 500
        config = make_config(debounce_seconds=0.0)
        emitter = make_emitter(tmp_path)
        analyzer = AutoFaultAnalyzer(config=config, emitter=emitter)

        with patch("eab.auto_fault_analyzer.analyze_fault", return_value=make_fault_report()), \
             patch("eab.auto_fault_analyzer.get_debug_probe"):
            analyzer.on_crash_detected(long_line)
            if analyzer._analysis_thread:
                analyzer._analysis_thread.join(timeout=5)

        d = read_events(tmp_path)[0]["data"]
        assert len(d["trigger_line"]) == 200
        assert d["trigger_line"] == "X" * 200

    def test_short_trigger_line_not_padded(self, tmp_path):
        """Short trigger lines are not padded to 200 chars."""
        config = make_config(debounce_seconds=0.0)
        emitter = make_emitter(tmp_path)
        analyzer = AutoFaultAnalyzer(config=config, emitter=emitter)

        short_line = "crash!"
        with patch("eab.auto_fault_analyzer.analyze_fault", return_value=make_fault_report()), \
             patch("eab.auto_fault_analyzer.get_debug_probe"):
            analyzer.on_crash_detected(short_line)
            if analyzer._analysis_thread:
                analyzer._analysis_thread.join(timeout=5)

        d = read_events(tmp_path)[0]["data"]
        assert d["trigger_line"] == "crash!"


# =============================================================================
# Concurrency: analysis already in progress
# =============================================================================

class TestAutoFaultAnalyzerConcurrency:
    def test_second_crash_while_analysis_running_is_dropped(self, tmp_path):
        """If analysis is in-progress, a second crash is dropped (not queued)."""
        barrier_start = threading.Barrier(2)
        barrier_release = threading.Barrier(2)

        def slow_analyze(*args, **kwargs):
            barrier_start.wait(timeout=5)  # signal: analysis thread started
            barrier_release.wait(timeout=5)  # wait for test to release
            return make_fault_report()

        config = make_config(debounce_seconds=0.0)
        emitter = make_emitter(tmp_path)
        analyzer = AutoFaultAnalyzer(config=config, emitter=emitter)

        with patch("eab.auto_fault_analyzer.analyze_fault", side_effect=slow_analyze) as mock_analyze, \
             patch("eab.auto_fault_analyzer.get_debug_probe"):
            analyzer.on_crash_detected("crash 1")
            barrier_start.wait(timeout=5)  # wait for thread to start

            # Second crash while analysis is running → should be dropped
            analyzer.on_crash_detected("crash 2")
            barrier_release.wait(timeout=5)  # release analysis thread

            if analyzer._analysis_thread:
                analyzer._analysis_thread.join(timeout=5)

        # Only one analysis ran
        assert mock_analyze.call_count == 1
        events = read_events(tmp_path)
        assert len(events) == 1


# =============================================================================
# OpenOCD probe
# =============================================================================

class TestAutoFaultAnalyzerOpenOCD:
    def test_openocd_probe_kwargs_are_set_correctly(self, tmp_path):
        """OpenOCD probe type triggers ZephyrProfile config lookup."""
        config = make_config(
            probe_type="openocd",
            chip="stm32l4",
            debounce_seconds=0.0,
        )
        emitter = make_emitter(tmp_path)
        analyzer = AutoFaultAnalyzer(config=config, emitter=emitter)

        mock_ocd_cfg = MagicMock()
        mock_ocd_cfg.interface_cfg = "interface/stlink.cfg"
        mock_ocd_cfg.target_cfg = "target/stm32l4x.cfg"
        mock_ocd_cfg.transport = "hla_swd"
        mock_ocd_cfg.extra_commands = []
        mock_ocd_cfg.halt_command = "reset halt"

        mock_profile = MagicMock()
        mock_profile.get_openocd_config.return_value = mock_ocd_cfg

        with patch("eab.auto_fault_analyzer.get_debug_probe") as mock_get_probe, \
             patch("eab.auto_fault_analyzer.analyze_fault", return_value=make_fault_report()), \
             patch("eab.chips.zephyr.ZephyrProfile", return_value=mock_profile) as mock_zp_cls:
            analyzer.on_crash_detected("crash")
            if analyzer._analysis_thread:
                analyzer._analysis_thread.join(timeout=5)

        # ZephyrProfile was called with the chip variant
        mock_zp_cls.assert_called_once_with(variant="stm32l4")

        # get_debug_probe was called with openocd and the expected kwargs
        mock_get_probe.assert_called_once()
        call_args = mock_get_probe.call_args
        assert call_args[0][0] == "openocd"
        call_kwargs = call_args[1]
        assert call_kwargs["interface_cfg"] == "interface/stlink.cfg"
        assert call_kwargs["target_cfg"] == "target/stm32l4x.cfg"

    def test_openocd_with_probe_selector(self, tmp_path):
        """OpenOCD + probe_selector → adapter_serial kwarg is passed."""
        config = make_config(
            probe_type="openocd",
            chip="stm32l4",
            probe_selector="0800000000123456",
            debounce_seconds=0.0,
        )
        emitter = make_emitter(tmp_path)
        analyzer = AutoFaultAnalyzer(config=config, emitter=emitter)

        mock_ocd_cfg = MagicMock()
        mock_ocd_cfg.interface_cfg = "interface/stlink.cfg"
        mock_ocd_cfg.target_cfg = "target/stm32l4x.cfg"
        mock_ocd_cfg.transport = None
        mock_ocd_cfg.extra_commands = []
        mock_ocd_cfg.halt_command = "reset halt"

        mock_profile = MagicMock()
        mock_profile.get_openocd_config.return_value = mock_ocd_cfg

        with patch("eab.auto_fault_analyzer.get_debug_probe") as mock_get_probe, \
             patch("eab.auto_fault_analyzer.analyze_fault", return_value=make_fault_report()), \
             patch("eab.chips.zephyr.ZephyrProfile", return_value=mock_profile):
            analyzer.on_crash_detected("crash")
            if analyzer._analysis_thread:
                analyzer._analysis_thread.join(timeout=5)

        call_kwargs = mock_get_probe.call_args[1]
        assert call_kwargs["adapter_serial"] == "0800000000123456"


# =============================================================================
# Config property
# =============================================================================

class TestAutoFaultConfig:
    def test_config_property(self, tmp_path):
        """config property returns the AutoFaultConfig instance."""
        cfg = AutoFaultConfig(enabled=True, chip="esp32")
        analyzer = AutoFaultAnalyzer(config=cfg, emitter=make_emitter(tmp_path))
        assert analyzer.config is cfg

    def test_default_config_disabled(self):
        """Default AutoFaultConfig has enabled=False."""
        cfg = AutoFaultConfig()
        assert cfg.enabled is False

    def test_default_debounce_is_5_seconds(self):
        """Default debounce is 5.0 seconds."""
        cfg = AutoFaultConfig()
        assert cfg.debounce_seconds == 5.0
