"""Tests for C2000 Perfetto trace export (Phase 7)."""

from __future__ import annotations

import io
import json
import tempfile
from pathlib import Path

import pytest

from eab.analyzers.perfetto_export import (
    DLOGTrack,
    ERADSpan,
    LogEvent,
    PerfettoExporter,
)


# =========================================================================
# ERADSpan events
# =========================================================================


class TestERADSpans:
    def test_single_span(self):
        exporter = PerfettoExporter()
        exporter.add_erad_span(ERADSpan("motor_isr", 0.0, 25.5, 3060))
        trace = exporter.build_trace()

        duration_events = [
            e for e in trace["traceEvents"] if e.get("ph") == "X"
        ]
        assert len(duration_events) == 1
        e = duration_events[0]
        assert e["name"] == "motor_isr"
        assert e["ts"] == 0.0
        assert e["dur"] == 25.5
        assert e["cat"] == "erad"
        assert e["args"]["cpu_cycles"] == 3060

    def test_multiple_spans(self):
        exporter = PerfettoExporter()
        exporter.add_erad_spans([
            ERADSpan("motor_isr", 0.0, 25.5, 3060),
            ERADSpan("motor_isr", 100.0, 24.0, 2880),
            ERADSpan("adc_isr", 50.0, 10.0, 1200),
        ])
        trace = exporter.build_trace()

        duration_events = [
            e for e in trace["traceEvents"] if e.get("ph") == "X"
        ]
        assert len(duration_events) == 3

    def test_span_has_correct_tid(self):
        exporter = PerfettoExporter()
        exporter.add_erad_span(ERADSpan("motor_isr", 0.0, 25.5))
        exporter.add_erad_span(ERADSpan("adc_isr", 50.0, 10.0))
        trace = exporter.build_trace()

        duration_events = [
            e for e in trace["traceEvents"] if e.get("ph") == "X"
        ]
        # Different function names → different tids
        tids = {e["tid"] for e in duration_events}
        assert len(tids) == 2

    def test_same_function_same_tid(self):
        exporter = PerfettoExporter()
        exporter.add_erad_span(ERADSpan("motor_isr", 0.0, 25.5))
        exporter.add_erad_span(ERADSpan("motor_isr", 100.0, 24.0))
        trace = exporter.build_trace()

        duration_events = [
            e for e in trace["traceEvents"] if e.get("ph") == "X"
        ]
        tids = {e["tid"] for e in duration_events}
        assert len(tids) == 1


# =========================================================================
# DLOG counter tracks
# =========================================================================


class TestDLOGTracks:
    def test_single_track(self):
        exporter = PerfettoExporter()
        exporter.add_dlog_track(DLOGTrack("dBuff1", [1.0, 2.0, 3.0]))
        trace = exporter.build_trace()

        counter_events = [
            e for e in trace["traceEvents"] if e.get("ph") == "C"
        ]
        assert len(counter_events) == 3
        assert counter_events[0]["args"]["dBuff1"] == 1.0
        assert counter_events[1]["args"]["dBuff1"] == 2.0
        assert counter_events[2]["args"]["dBuff1"] == 3.0

    def test_track_with_interval(self):
        exporter = PerfettoExporter()
        exporter.add_dlog_track(
            DLOGTrack("dBuff1", [1.0, 2.0, 3.0], sample_interval_us=10.0)
        )
        trace = exporter.build_trace()

        counter_events = [
            e for e in trace["traceEvents"] if e.get("ph") == "C"
        ]
        assert counter_events[0]["ts"] == 0.0
        assert counter_events[1]["ts"] == 10.0
        assert counter_events[2]["ts"] == 20.0

    def test_track_without_interval_uses_index(self):
        exporter = PerfettoExporter()
        exporter.add_dlog_track(DLOGTrack("dBuff1", [1.0, 2.0, 3.0]))
        trace = exporter.build_trace()

        counter_events = [
            e for e in trace["traceEvents"] if e.get("ph") == "C"
        ]
        assert counter_events[0]["ts"] == 0.0
        assert counter_events[1]["ts"] == 1.0
        assert counter_events[2]["ts"] == 2.0

    def test_multiple_tracks(self):
        exporter = PerfettoExporter()
        exporter.add_dlog_tracks([
            DLOGTrack("dBuff1", [1.0, 2.0]),
            DLOGTrack("dBuff2", [10.0, 20.0]),
        ])
        trace = exporter.build_trace()

        counter_events = [
            e for e in trace["traceEvents"] if e.get("ph") == "C"
        ]
        assert len(counter_events) == 4

        # Different tracks → different tids
        tids = {e["tid"] for e in counter_events}
        assert len(tids) == 2

    def test_empty_track(self):
        exporter = PerfettoExporter()
        exporter.add_dlog_track(DLOGTrack("empty", []))
        trace = exporter.build_trace()

        counter_events = [
            e for e in trace["traceEvents"] if e.get("ph") == "C"
        ]
        assert len(counter_events) == 0


# =========================================================================
# Log events
# =========================================================================


class TestLogEvents:
    def test_single_log(self):
        exporter = PerfettoExporter()
        exporter.add_log_event(LogEvent(100.0, "Boot complete"))
        trace = exporter.build_trace()

        instant_events = [
            e for e in trace["traceEvents"] if e.get("ph") == "i"
        ]
        assert len(instant_events) == 1
        e = instant_events[0]
        assert e["name"] == "Boot complete"
        assert e["ts"] == 100.0
        assert e["cat"] == "log"
        assert e["args"]["channel"] == "serial"

    def test_long_message_truncated(self):
        exporter = PerfettoExporter()
        long_msg = "x" * 200
        exporter.add_log_event(LogEvent(0.0, long_msg))
        trace = exporter.build_trace()

        instant_events = [
            e for e in trace["traceEvents"] if e.get("ph") == "i"
        ]
        assert len(instant_events[0]["name"]) == 80
        # Full message preserved in args
        assert instant_events[0]["args"]["raw"] == long_msg

    def test_multiple_channels(self):
        exporter = PerfettoExporter()
        exporter.add_log_events([
            LogEvent(0.0, "Serial msg", "serial"),
            LogEvent(10.0, "Debug msg", "debug"),
        ])
        trace = exporter.build_trace()

        instant_events = [
            e for e in trace["traceEvents"] if e.get("ph") == "i"
        ]
        tids = {e["tid"] for e in instant_events}
        assert len(tids) == 2


# =========================================================================
# Metadata
# =========================================================================


class TestMetadata:
    def test_process_name(self):
        exporter = PerfettoExporter(process_name="My C2000")
        trace = exporter.build_trace()

        meta = [
            e for e in trace["traceEvents"]
            if e.get("ph") == "M" and e.get("name") == "process_name"
        ]
        assert len(meta) == 1
        assert meta[0]["args"]["name"] == "My C2000"

    def test_thread_names_created(self):
        exporter = PerfettoExporter()
        exporter.add_erad_span(ERADSpan("motor_isr", 0.0, 25.5))
        exporter.add_dlog_track(DLOGTrack("dBuff1", [1.0]))
        exporter.add_log_event(LogEvent(0.0, "msg"))
        trace = exporter.build_trace()

        thread_names = [
            e for e in trace["traceEvents"]
            if e.get("ph") == "M" and e.get("name") == "thread_name"
        ]
        assert len(thread_names) == 3

    def test_display_time_unit(self):
        exporter = PerfettoExporter()
        trace = exporter.build_trace()
        assert trace["displayTimeUnit"] == "ms"


# =========================================================================
# Combined trace
# =========================================================================


class TestCombinedTrace:
    def test_all_sources_combined(self):
        exporter = PerfettoExporter()
        exporter.add_erad_span(ERADSpan("motor_isr", 0.0, 25.5, 3060))
        exporter.add_dlog_track(DLOGTrack("dBuff1", [1.0, 2.0]))
        exporter.add_log_event(LogEvent(50.0, "ISR started"))

        trace = exporter.build_trace()

        duration = [e for e in trace["traceEvents"] if e.get("ph") == "X"]
        counter = [e for e in trace["traceEvents"] if e.get("ph") == "C"]
        instant = [e for e in trace["traceEvents"] if e.get("ph") == "i"]

        assert len(duration) == 1
        assert len(counter) == 2
        assert len(instant) == 1

    def test_empty_trace(self):
        exporter = PerfettoExporter()
        trace = exporter.build_trace()
        # Should have process_name metadata only
        assert len(trace["traceEvents"]) == 1
        assert trace["traceEvents"][0]["name"] == "process_name"

    def test_json_serializable(self):
        exporter = PerfettoExporter()
        exporter.add_erad_span(ERADSpan("motor_isr", 0.0, 25.5))
        exporter.add_dlog_track(DLOGTrack("dBuff1", [1.0]))
        exporter.add_log_event(LogEvent(0.0, "test"))
        trace = exporter.build_trace()
        # Must not raise
        json.dumps(trace)


# =========================================================================
# File output
# =========================================================================


class TestFileOutput:
    def test_write_to_file(self, tmp_path):
        exporter = PerfettoExporter()
        exporter.add_erad_span(ERADSpan("motor_isr", 0.0, 25.5, 3060))
        exporter.add_dlog_track(DLOGTrack("dBuff1", [1.0, 2.0]))
        exporter.add_log_event(LogEvent(0.0, "Boot"))

        output = tmp_path / "trace.json"
        summary = exporter.write(output)

        assert output.exists()
        assert summary["erad_spans"] == 1
        assert summary["dlog_tracks"] == 1
        assert summary["log_events"] == 1
        assert summary["output_size_bytes"] > 0

        # Verify valid JSON
        with open(output) as f:
            trace = json.load(f)
        assert "traceEvents" in trace

    def test_write_to_stream(self):
        exporter = PerfettoExporter()
        exporter.add_erad_span(ERADSpan("motor_isr", 0.0, 25.5))
        exporter.add_log_event(LogEvent(0.0, "test"))

        output = io.StringIO()
        summary = exporter.write_to_stream(output)

        assert summary["erad_spans"] == 1
        assert summary["log_events"] == 1

        output.seek(0)
        trace = json.load(output)
        assert "traceEvents" in trace


# =========================================================================
# Edge cases
# =========================================================================


class TestEdgeCases:
    def test_zero_duration_span(self):
        exporter = PerfettoExporter()
        exporter.add_erad_span(ERADSpan("quick", 100.0, 0.0, 0))
        trace = exporter.build_trace()
        events = [e for e in trace["traceEvents"] if e.get("ph") == "X"]
        assert len(events) == 1
        assert events[0]["dur"] == 0.0

    def test_negative_float_in_dlog(self):
        exporter = PerfettoExporter()
        exporter.add_dlog_track(DLOGTrack("buf", [-1.5, 0.0, 1.5]))
        trace = exporter.build_trace()
        counters = [e for e in trace["traceEvents"] if e.get("ph") == "C"]
        assert counters[0]["args"]["buf"] == -1.5

    def test_all_pid_is_one(self):
        exporter = PerfettoExporter()
        exporter.add_erad_span(ERADSpan("f", 0, 1))
        exporter.add_dlog_track(DLOGTrack("b", [1.0]))
        exporter.add_log_event(LogEvent(0, "m"))
        trace = exporter.build_trace()
        for e in trace["traceEvents"]:
            assert e["pid"] == 1
