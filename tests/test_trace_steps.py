"""Unit tests for trace regression step executors — no hardware required."""

from __future__ import annotations

import json
import os
import subprocess
from unittest.mock import patch

import pytest

from eab.cli.regression.models import StepSpec, StepResult
from eab.cli.regression.steps import run_step


def _mock_completed(stdout='{"ok": true}', returncode=0):
    return subprocess.CompletedProcess(
        args=[], returncode=returncode, stdout=stdout, stderr="",
    )


# ---------------------------------------------------------------------------
# trace_start
# ---------------------------------------------------------------------------

class TestTraceStart:
    @patch("eab.cli.regression.steps.subprocess.run")
    def test_success(self, mock_run):
        mock_run.return_value = _mock_completed()
        step = StepSpec(step_type="trace_start", params={
            "source": "rtt", "output": "/tmp/trace.rttbin",
            "device": "NRF5340_XXAA_APP",
        })
        result = run_step(step)
        assert result.passed is True
        assert result.step_type == "trace_start"
        cmd = mock_run.call_args[0][0]
        assert "trace" in cmd
        assert "start" in cmd
        assert "--source" in cmd
        assert "rtt" in cmd
        assert "--output" in cmd

    @patch("eab.cli.regression.steps.subprocess.run")
    def test_failure(self, mock_run):
        mock_run.return_value = _mock_completed(
            stdout='{"error": "no RTT channel"}', returncode=1,
        )
        step = StepSpec(step_type="trace_start", params={"source": "rtt"})
        result = run_step(step)
        assert result.passed is False
        assert result.error == "no RTT channel"

    @patch("eab.cli.regression.steps.subprocess.run")
    def test_defaults(self, mock_run):
        mock_run.return_value = _mock_completed()
        step = StepSpec(step_type="trace_start", params={})
        result = run_step(step)
        assert result.passed is True
        cmd = mock_run.call_args[0][0]
        assert "--source" in cmd
        assert "rtt" in cmd  # default source


# ---------------------------------------------------------------------------
# trace_stop
# ---------------------------------------------------------------------------

class TestTraceStop:
    @patch("eab.cli.regression.steps.subprocess.run")
    def test_success(self, mock_run):
        mock_run.return_value = _mock_completed()
        step = StepSpec(step_type="trace_stop", params={})
        result = run_step(step)
        assert result.passed is True
        assert result.step_type == "trace_stop"
        cmd = mock_run.call_args[0][0]
        assert "trace" in cmd
        assert "stop" in cmd


# ---------------------------------------------------------------------------
# trace_export
# ---------------------------------------------------------------------------

class TestTraceExport:
    @patch("eab.cli.regression.steps.subprocess.run")
    def test_success(self, mock_run):
        mock_run.return_value = _mock_completed()
        step = StepSpec(step_type="trace_export", params={
            "input": "/tmp/trace.rttbin",
            "output": "/tmp/trace.json",
            "format": "auto",
        })
        result = run_step(step)
        assert result.passed is True
        cmd = mock_run.call_args[0][0]
        assert "trace" in cmd
        assert "export" in cmd
        assert "--input" in cmd
        assert "--format" in cmd
        assert "auto" in cmd

    @patch("eab.cli.regression.steps.subprocess.run")
    def test_failure(self, mock_run):
        mock_run.return_value = _mock_completed(
            stdout='{"error": "unknown format"}', returncode=1,
        )
        step = StepSpec(step_type="trace_export", params={
            "input": "/tmp/bad.bin", "output": "/tmp/out.json",
        })
        result = run_step(step)
        assert result.passed is False
        assert "unknown format" in result.error

    @patch("eab.cli.regression.steps.subprocess.run")
    def test_default_format(self, mock_run):
        mock_run.return_value = _mock_completed()
        step = StepSpec(step_type="trace_export", params={})
        run_step(step)
        cmd = mock_run.call_args[0][0]
        assert "--format" in cmd
        assert "auto" in cmd


# ---------------------------------------------------------------------------
# trace_validate — pass cases
# ---------------------------------------------------------------------------

class TestTraceValidatePass:
    def test_metadata_events_excluded(self, tmp_path):
        """Metadata events (ph=M) should be excluded from required_fields checks."""
        trace = {
            "traceEvents": [
                {"name": "process_name", "ph": "M", "pid": 1, "tid": 0,
                 "cat": "__metadata", "args": {"name": "RTT"}},
                {"name": "ev1", "ts": 100, "ph": "X", "pid": 0, "tid": 1},
            ],
            "displayTimeUnit": "ns",
        }
        path = tmp_path / "trace.json"
        path.write_text(json.dumps(trace))

        step = StepSpec(step_type="trace_validate", params={
            "input": str(path),
            "min_events": 1,
            "required_fields": ["name", "ts", "ph"],
            "schema": "perfetto",
        })
        result = run_step(step)
        assert result.passed is True
        assert result.output["data_events"] == 1
        assert result.output["metadata_events"] == 1

    def test_basic_pass(self, tmp_path):
        trace = {
            "traceEvents": [
                {"name": "ev1", "ts": 100, "ph": "X", "pid": 0, "tid": 1},
                {"name": "ev2", "ts": 200, "ph": "X", "pid": 0, "tid": 1},
            ],
            "displayTimeUnit": "ns",
        }
        path = tmp_path / "trace.json"
        path.write_text(json.dumps(trace))

        step = StepSpec(step_type="trace_validate", params={
            "input": str(path),
            "min_events": 2,
            "required_fields": ["name", "ts", "ph"],
            "schema": "perfetto",
        })
        result = run_step(step)
        assert result.passed is True
        assert result.output["data_events"] == 2

    def test_golden_reference(self):
        """Validate the actual golden reference fixture."""
        fixture = os.path.join(
            os.path.dirname(__file__), "fixtures", "golden_trace.json",
        )
        step = StepSpec(step_type="trace_validate", params={
            "input": fixture,
            "min_events": 10,
            "required_fields": ["name", "ts", "ph"],
            "schema": "perfetto",
        })
        result = run_step(step)
        assert result.passed is True
        assert result.output["data_events"] == 20

    def test_event_name_patterns(self, tmp_path):
        trace = {
            "traceEvents": [
                {"name": "thread_switched", "ts": 100, "ph": "X"},
                {"name": "isr_enter", "ts": 200, "ph": "B"},
            ],
            "displayTimeUnit": "ns",
        }
        path = tmp_path / "trace.json"
        path.write_text(json.dumps(trace))

        step = StepSpec(step_type="trace_validate", params={
            "input": str(path),
            "event_names": ["thread_.*", "isr_.*"],
        })
        result = run_step(step)
        assert result.passed is True

    def test_timing_validation(self, tmp_path):
        trace = {
            "traceEvents": [
                {"name": "a", "ts": 1000, "ph": "X"},
                {"name": "b", "ts": 1500, "ph": "X"},
                {"name": "c", "ts": 2000, "ph": "X"},
            ],
            "displayTimeUnit": "ns",
        }
        path = tmp_path / "trace.json"
        path.write_text(json.dumps(trace))

        step = StepSpec(step_type="trace_validate", params={
            "input": str(path),
            "timing": {"min_duration_us": 500, "max_gap_us": 600},
        })
        result = run_step(step)
        assert result.passed is True


# ---------------------------------------------------------------------------
# trace_validate — failure cases
# ---------------------------------------------------------------------------

class TestTraceValidateFail:
    def test_file_not_found(self):
        step = StepSpec(step_type="trace_validate", params={
            "input": "/nonexistent/trace.json",
        })
        result = run_step(step)
        assert result.passed is False
        assert "not found" in result.error

    def test_invalid_json(self, tmp_path):
        path = tmp_path / "bad.json"
        path.write_text("not json {{{")
        step = StepSpec(step_type="trace_validate", params={
            "input": str(path),
        })
        result = run_step(step)
        assert result.passed is False
        assert "Invalid JSON" in result.error

    def test_min_events_fail(self, tmp_path):
        trace = {
            "traceEvents": [{"name": "a", "ts": 100, "ph": "X"}],
            "displayTimeUnit": "ns",
        }
        path = tmp_path / "trace.json"
        path.write_text(json.dumps(trace))

        step = StepSpec(step_type="trace_validate", params={
            "input": str(path),
            "min_events": 10,
        })
        result = run_step(step)
        assert result.passed is False
        assert "Too few events" in result.error

    def test_max_events_fail(self, tmp_path):
        trace = {
            "traceEvents": [
                {"name": f"ev{i}", "ts": i * 100, "ph": "X"}
                for i in range(20)
            ],
            "displayTimeUnit": "ns",
        }
        path = tmp_path / "trace.json"
        path.write_text(json.dumps(trace))

        step = StepSpec(step_type="trace_validate", params={
            "input": str(path),
            "max_events": 5,
        })
        result = run_step(step)
        assert result.passed is False
        assert "Too many events" in result.error

    def test_missing_fields(self, tmp_path):
        trace = {
            "traceEvents": [{"name": "a", "ts": 100, "ph": "X"}],  # missing pid
            "displayTimeUnit": "ns",
        }
        path = tmp_path / "trace.json"
        path.write_text(json.dumps(trace))

        step = StepSpec(step_type="trace_validate", params={
            "input": str(path),
            "required_fields": ["name", "ts", "ph", "pid"],
        })
        result = run_step(step)
        assert result.passed is False
        assert "missing fields" in result.error
        assert "Data event" in result.error

    def test_schema_missing_trace_events(self, tmp_path):
        path = tmp_path / "trace.json"
        path.write_text(json.dumps({"events": [], "displayTimeUnit": "ns"}))

        step = StepSpec(step_type="trace_validate", params={
            "input": str(path),
            "schema": "perfetto",
        })
        result = run_step(step)
        assert result.passed is False
        assert "traceEvents" in result.error

    def test_schema_missing_display_time_unit(self, tmp_path):
        path = tmp_path / "trace.json"
        path.write_text(json.dumps({"traceEvents": []}))

        step = StepSpec(step_type="trace_validate", params={
            "input": str(path),
            "schema": "perfetto",
        })
        result = run_step(step)
        assert result.passed is False
        assert "displayTimeUnit" in result.error

    def test_event_name_pattern_no_match(self, tmp_path):
        trace = {
            "traceEvents": [{"name": "foo", "ts": 100, "ph": "X"}],
            "displayTimeUnit": "ns",
        }
        path = tmp_path / "trace.json"
        path.write_text(json.dumps(trace))

        step = StepSpec(step_type="trace_validate", params={
            "input": str(path),
            "event_names": ["nonexistent_.*"],
        })
        result = run_step(step)
        assert result.passed is False
        assert "No event matching" in result.error

    def test_timing_min_duration_fail(self, tmp_path):
        trace = {
            "traceEvents": [
                {"name": "a", "ts": 1000, "ph": "X"},
                {"name": "b", "ts": 1050, "ph": "X"},
            ],
            "displayTimeUnit": "ns",
        }
        path = tmp_path / "trace.json"
        path.write_text(json.dumps(trace))

        step = StepSpec(step_type="trace_validate", params={
            "input": str(path),
            "timing": {"min_duration_us": 1000},
        })
        result = run_step(step)
        assert result.passed is False
        assert "duration" in result.error

    def test_timing_max_gap_fail(self, tmp_path):
        trace = {
            "traceEvents": [
                {"name": "a", "ts": 1000, "ph": "X"},
                {"name": "b", "ts": 50000, "ph": "X"},
            ],
            "displayTimeUnit": "ns",
        }
        path = tmp_path / "trace.json"
        path.write_text(json.dumps(trace))

        step = StepSpec(step_type="trace_validate", params={
            "input": str(path),
            "timing": {"max_gap_us": 100},
        })
        result = run_step(step)
        assert result.passed is False
        assert "Gap" in result.error
