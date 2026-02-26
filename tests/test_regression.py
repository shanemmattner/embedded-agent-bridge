"""Unit tests for eabctl regression — no hardware required."""

from __future__ import annotations

import json
import os
import subprocess
from dataclasses import asdict
from unittest.mock import patch

import pytest
import yaml

from eab.cli.regression.models import (
    StepSpec, TestSpec, StepResult, SuiteResult,
)
from eab.cli.regression.runner import (
    cmd_regression, discover_tests, parse_test, run_test, run_suite, _parse_steps,
)
from eab.cli.regression.steps import run_step, _run_eabctl
from eab.thread_inspector import ThreadInfo


# ---------------------------------------------------------------------------
# Model tests
# ---------------------------------------------------------------------------

class TestModels:
    def test_step_spec_defaults(self):
        s = StepSpec(step_type="wait")
        assert s.params == {}

    def test_test_spec_defaults(self):
        t = TestSpec(name="t", file="f.yaml")
        assert t.timeout == 60
        assert t.setup == []
        assert t.steps == []
        assert t.teardown == []

    def test_suite_result_defaults(self):
        r = SuiteResult()
        assert r.passed == 0
        assert r.failed == 0
        assert r.results == []

    def test_step_result_serializable(self):
        r = StepResult(step_type="wait", params={"pattern": "OK"},
                       passed=True, duration_ms=100)
        d = asdict(r)
        assert d["step_type"] == "wait"
        assert d["passed"] is True
        assert json.dumps(d)  # should not raise


# ---------------------------------------------------------------------------
# YAML parsing
# ---------------------------------------------------------------------------

class TestParsing:
    def _write_yaml(self, tmpdir, name, data):
        path = os.path.join(tmpdir, name)
        with open(path, "w") as f:
            yaml.dump(data, f)
        return path

    def test_parse_minimal(self, tmp_path):
        data = {"name": "Minimal", "steps": [{"sleep": {"seconds": 1}}]}
        path = self._write_yaml(str(tmp_path), "test.yaml", data)
        spec = parse_test(path)
        assert spec.name == "Minimal"
        assert len(spec.steps) == 1
        assert spec.steps[0].step_type == "sleep"
        assert spec.steps[0].params["seconds"] == 1

    def test_parse_full(self, tmp_path):
        data = {
            "name": "Full Test",
            "device": "nrf5340",
            "chip": "nrf5340",
            "timeout": 30,
            "setup": [{"flash": {"firmware": "app", "runner": "jlink"}}],
            "steps": [
                {"reset": {}},
                {"wait": {"pattern": "Ready", "timeout": 5}},
                {"send": {"text": "hello", "await_ack": True}},
            ],
            "teardown": [{"reset": None}],
        }
        path = self._write_yaml(str(tmp_path), "full.yaml", data)
        spec = parse_test(path)
        assert spec.device == "nrf5340"
        assert spec.chip == "nrf5340"
        assert spec.timeout == 30
        assert len(spec.setup) == 1
        assert len(spec.steps) == 3
        assert len(spec.teardown) == 1
        assert spec.teardown[0].params == {}  # None → {}

    def test_parse_name_fallback(self, tmp_path):
        data = {"steps": [{"sleep": {"seconds": 1}}]}
        path = self._write_yaml(str(tmp_path), "unnamed.yaml", data)
        spec = parse_test(path)
        assert spec.name == "unnamed.yaml"

    def test_parse_invalid_raises(self, tmp_path):
        path = os.path.join(str(tmp_path), "bad.yaml")
        with open(path, "w") as f:
            f.write("just a string\n")
        with pytest.raises(ValueError, match="expected mapping"):
            parse_test(path)

    def test_parse_steps_skips_non_dict(self):
        raw = [{"sleep": {"seconds": 1}}, "not_a_dict", {"wait": {"pattern": "OK"}}]
        steps = _parse_steps(raw)
        assert len(steps) == 2


# ---------------------------------------------------------------------------
# Discovery
# ---------------------------------------------------------------------------

class TestDiscovery:
    def test_discover_finds_yaml(self, tmp_path):
        (tmp_path / "a.yaml").write_text("name: a\nsteps: []")
        (tmp_path / "b.yml").write_text("name: b\nsteps: []")
        (tmp_path / "c.txt").write_text("not a test")
        found = discover_tests(str(tmp_path))
        basenames = [os.path.basename(f) for f in found]
        assert "a.yaml" in basenames
        assert "b.yml" in basenames
        assert "c.txt" not in basenames

    def test_discover_filter(self, tmp_path):
        (tmp_path / "nrf_test.yaml").write_text("name: nrf\nsteps: []")
        (tmp_path / "esp_test.yaml").write_text("name: esp\nsteps: []")
        found = discover_tests(str(tmp_path), filter_pattern="*nrf*")
        assert len(found) == 1
        assert "nrf_test.yaml" in found[0]

    def test_discover_empty_dir(self, tmp_path):
        assert discover_tests(str(tmp_path)) == []

    def test_discover_nonexistent_dir(self):
        assert discover_tests("/nonexistent/path") == []


# ---------------------------------------------------------------------------
# Step execution (mocked subprocess)
# ---------------------------------------------------------------------------

def _mock_completed(stdout='{"ok": true}', returncode=0):
    return subprocess.CompletedProcess(
        args=[], returncode=returncode, stdout=stdout, stderr="",
    )


class TestStepExecution:
    @patch("eab.cli.regression.steps.subprocess.run")
    def test_run_wait_success(self, mock_run):
        mock_run.return_value = _mock_completed()
        step = StepSpec(step_type="wait", params={"pattern": "Ready", "timeout": 5})
        result = run_step(step)
        assert result.passed is True
        assert result.step_type == "wait"
        cmd = mock_run.call_args[0][0]
        assert "wait" in cmd
        assert "Ready" in cmd
        assert "--json" in cmd

    @patch("eab.cli.regression.steps.subprocess.run")
    def test_run_wait_failure(self, mock_run):
        mock_run.return_value = _mock_completed(
            stdout='{"error": "timeout"}', returncode=1,
        )
        step = StepSpec(step_type="wait", params={"pattern": "Never", "timeout": 1})
        result = run_step(step)
        assert result.passed is False
        assert result.error == "timeout"

    @patch("eab.cli.regression.steps.subprocess.run")
    def test_run_flash(self, mock_run):
        mock_run.return_value = _mock_completed()
        step = StepSpec(step_type="flash", params={
            "firmware": "samples/hello", "runner": "jlink",
        })
        result = run_step(step, chip="nrf5340")
        assert result.passed is True
        cmd = mock_run.call_args[0][0]
        assert "flash" in cmd
        assert "samples/hello" in cmd
        assert "--chip" in cmd
        assert "nrf5340" in cmd

    @patch("eab.cli.regression.steps.subprocess.run")
    def test_run_reset(self, mock_run):
        mock_run.return_value = _mock_completed()
        step = StepSpec(step_type="reset", params={})
        result = run_step(step, chip="nrf5340")
        assert result.passed is True

    @patch("eab.cli.regression.steps.subprocess.run")
    def test_run_send(self, mock_run):
        mock_run.return_value = _mock_completed()
        step = StepSpec(step_type="send", params={"text": "hello", "await_ack": True})
        result = run_step(step)
        assert result.passed is True
        cmd = mock_run.call_args[0][0]
        assert "--await-ack" in cmd

    def test_run_sleep(self):
        step = StepSpec(step_type="sleep", params={"seconds": 0.01})
        result = run_step(step)
        assert result.passed is True
        assert result.duration_ms >= 5  # at least ~10ms

    def test_unknown_step_type(self):
        step = StepSpec(step_type="bogus", params={})
        result = run_step(step)
        assert result.passed is False
        assert "Unknown step type" in result.error

    @patch("eab.cli.regression.steps.subprocess.run")
    def test_run_eabctl_timeout(self, mock_run):
        mock_run.side_effect = subprocess.TimeoutExpired(cmd="eabctl", timeout=5)
        rc, output = _run_eabctl(["wait", "foo"], timeout=5)
        assert rc == 1
        assert output["error"] == "timeout"

    @patch("eab.cli.regression.steps.subprocess.run")
    def test_run_eabctl_not_found(self, mock_run):
        mock_run.side_effect = FileNotFoundError()
        rc, output = _run_eabctl(["status"], timeout=5)
        assert rc == 1
        assert output["error"] == "eabctl not found"

    @patch("eab.cli.regression.steps.subprocess.run")
    def test_run_read_vars_expect_eq(self, mock_run):
        mock_run.return_value = _mock_completed(
            stdout=json.dumps({"variables": {"error_count": 0, "heap_free": 2048}}),
        )
        step = StepSpec(step_type="read_vars", params={
            "elf": "build/zephyr/zephyr.elf",
            "vars": [
                {"name": "error_count", "expect_eq": 0},
                {"name": "heap_free", "expect_gt": 1024},
            ],
        })
        result = run_step(step, device="nrf5340")
        assert result.passed is True

    @patch("eab.cli.regression.steps.subprocess.run")
    def test_run_read_vars_expect_fail(self, mock_run):
        mock_run.return_value = _mock_completed(
            stdout=json.dumps({"variables": {"error_count": 5}}),
        )
        step = StepSpec(step_type="read_vars", params={
            "elf": "build/zephyr/zephyr.elf",
            "vars": [{"name": "error_count", "expect_eq": 0}],
        })
        result = run_step(step)
        assert result.passed is False
        assert "expected 0" in result.error

    @patch("eab.cli.regression.steps.subprocess.run")
    def test_run_fault_check_clean(self, mock_run):
        mock_run.return_value = _mock_completed(
            stdout=json.dumps({"fault_detected": False}),
        )
        step = StepSpec(step_type="fault_check", params={
            "elf": "build/zephyr/zephyr.elf",
            "expect_clean": True,
        })
        result = run_step(step)
        assert result.passed is True

    @patch("eab.cli.regression.steps.subprocess.run")
    def test_run_fault_check_faulted(self, mock_run):
        mock_run.return_value = _mock_completed(
            stdout=json.dumps({"fault_detected": True}),
        )
        step = StepSpec(step_type="fault_check", params={
            "expect_clean": True,
        })
        result = run_step(step)
        assert result.passed is False
        assert "Fault detected" in result.error

    @patch("eab.cli.regression.steps.subprocess.run")
    def test_run_assert_log(self, mock_run):
        mock_run.return_value = _mock_completed()
        step = StepSpec(step_type="assert_log", params={"pattern": "Booted", "timeout": 3})
        result = run_step(step)
        assert result.passed is True
        assert result.step_type == "assert_log"

    @patch("eab.cli.regression.steps.inspect_threads")
    def test_stack_headroom_assert_pass(self, mock_inspect):
        mock_inspect.return_value = [
            ThreadInfo(name="main", stack_free=512),
            ThreadInfo(name="idle", stack_free=256),
        ]
        step = StepSpec(step_type="stack_headroom_assert", params={
            "min_free_bytes": 128,
            "elf": "build/app.elf",
            "device": "dev0",
        })
        result = run_step(step)
        assert result.passed is True

    @patch("eab.cli.regression.steps.inspect_threads")
    def test_stack_headroom_assert_fail(self, mock_inspect):
        mock_inspect.return_value = [
            ThreadInfo(name="main", stack_free=512),
            ThreadInfo(name="sensor_task", stack_free=64),
        ]
        step = StepSpec(step_type="stack_headroom_assert", params={
            "min_free_bytes": 128,
            "elf": "build/app.elf",
            "device": "dev0",
        })
        result = run_step(step)
        assert result.passed is False
        assert "sensor_task" in result.error
        assert "stack_free=64" in result.error
        assert "min_free_bytes=128" in result.error

    @patch("eab.cli.regression.steps.inspect_threads")
    def test_stack_headroom_assert_inspect_error(self, mock_inspect):
        mock_inspect.side_effect = RuntimeError("connection failed")
        step = StepSpec(step_type="stack_headroom_assert", params={
            "min_free_bytes": 128,
            "elf": "build/app.elf",
            "device": "dev0",
        })
        result = run_step(step)
        assert result.passed is False
        assert "connection failed" in result.error

    @patch("eab.cli.regression.steps.subprocess.run")
    def test_run_wait_event(self, mock_run):
        mock_run.return_value = _mock_completed()
        step = StepSpec(step_type="wait_event", params={
            "event_type": "command_result", "contains": "OK", "timeout": 5,
        })
        result = run_step(step)
        assert result.passed is True
        cmd = mock_run.call_args[0][0]
        assert "wait-event" in cmd
        assert "--event-type" in cmd


# ---------------------------------------------------------------------------
# Test runner (mocked steps)
# ---------------------------------------------------------------------------

class TestRunner:
    @patch("eab.cli.regression.runner.run_step")
    def test_run_test_all_pass(self, mock_step):
        mock_step.return_value = StepResult(
            step_type="wait", params={}, passed=True, duration_ms=10,
        )
        spec = TestSpec(
            name="ok", file="ok.yaml",
            steps=[StepSpec("wait", {"pattern": "OK"})],
        )
        result = run_test(spec)
        assert result.passed is True
        assert result.error is None

    @patch("eab.cli.regression.runner.run_step")
    def test_run_test_setup_failure_skips_steps(self, mock_step):
        mock_step.return_value = StepResult(
            step_type="flash", params={}, passed=False, duration_ms=10,
            error="flash failed",
        )
        spec = TestSpec(
            name="fail", file="fail.yaml",
            setup=[StepSpec("flash", {"firmware": "app"})],
            steps=[StepSpec("wait", {"pattern": "OK"})],
            teardown=[StepSpec("reset", {})],
        )
        result = run_test(spec)
        assert result.passed is False
        assert "Setup failed" in result.error
        # setup(1) + teardown(1) = 2 steps (test step skipped)
        assert len(result.steps) == 2

    @patch("eab.cli.regression.runner.run_step")
    def test_run_test_step_failure_stops(self, mock_step):
        call_count = [0]
        def side_effect(step, **kwargs):
            call_count[0] += 1
            if step.step_type == "wait" and step.params.get("pattern") == "fail":
                return StepResult(step_type="wait", params=step.params,
                                  passed=False, duration_ms=10, error="not found")
            return StepResult(step_type=step.step_type, params=step.params,
                              passed=True, duration_ms=10)
        mock_step.side_effect = side_effect

        spec = TestSpec(
            name="partial", file="partial.yaml",
            steps=[
                StepSpec("wait", {"pattern": "OK"}),
                StepSpec("wait", {"pattern": "fail"}),
                StepSpec("wait", {"pattern": "never"}),
            ],
        )
        result = run_test(spec)
        assert result.passed is False
        # Only first 2 steps should run (stops on failure)
        assert len(result.steps) == 2

    @patch("eab.cli.regression.runner.run_step")
    def test_teardown_always_runs(self, mock_step):
        call_count = [0]
        def side_effect(step, **kwargs):
            call_count[0] += 1
            if step.step_type == "wait":
                return StepResult(step_type="wait", params={},
                                  passed=False, duration_ms=10, error="fail")
            return StepResult(step_type=step.step_type, params={},
                              passed=True, duration_ms=10)
        mock_step.side_effect = side_effect

        spec = TestSpec(
            name="td", file="td.yaml",
            steps=[StepSpec("wait", {"pattern": "X"})],
            teardown=[StepSpec("reset", {}), StepSpec("reset", {})],
        )
        result = run_test(spec)
        assert result.passed is False
        # 1 step (failed) + 2 teardown = 3
        assert len(result.steps) == 3


# ---------------------------------------------------------------------------
# Suite runner
# ---------------------------------------------------------------------------

class TestSuiteRunner:
    def test_suite_with_tests(self, tmp_path):
        data = {"name": "Sleep Test", "steps": [{"sleep": {"seconds": 0.01}}]}
        path = tmp_path / "test_sleep.yaml"
        path.write_text(yaml.dump(data))

        result = run_suite(suite_dir=str(tmp_path))
        assert result.passed == 1
        assert result.failed == 0
        assert len(result.results) == 1
        assert result.results[0].passed is True

    def test_suite_single_file(self, tmp_path):
        data = {"name": "Single", "steps": [{"sleep": {"seconds": 0.01}}]}
        path = tmp_path / "single.yaml"
        path.write_text(yaml.dump(data))

        result = run_suite(test_file=str(path))
        assert result.passed == 1

    def test_suite_parse_error(self, tmp_path):
        path = tmp_path / "bad.yaml"
        path.write_text("just a string\n")
        result = run_suite(suite_dir=str(tmp_path))
        assert result.failed == 1
        assert "Parse error" in result.results[0].error

    def test_suite_empty(self):
        result = run_suite()
        assert result.passed == 0
        assert result.failed == 0


# ---------------------------------------------------------------------------
# cmd_regression entry point
# ---------------------------------------------------------------------------

class TestCmdRegression:
    def test_no_args_returns_2(self, capsys):
        rc = cmd_regression(json_mode=True)
        assert rc == 2
        out = json.loads(capsys.readouterr().out)
        assert "error" in out

    def test_suite_run(self, tmp_path, capsys):
        data = {"name": "E2E", "steps": [{"sleep": {"seconds": 0.01}}]}
        (tmp_path / "e2e.yaml").write_text(yaml.dump(data))
        rc = cmd_regression(suite=str(tmp_path), json_mode=True)
        assert rc == 0
        out = json.loads(capsys.readouterr().out)
        assert out["passed"] == 1
        assert out["failed"] == 0

    @patch("eab.cli.regression.runner.run_step")
    def test_suite_failure_returns_1(self, mock_step, tmp_path, capsys):
        mock_step.return_value = StepResult(
            step_type="wait", params={}, passed=False, duration_ms=0, error="nope",
        )
        data = {"name": "Fail", "steps": [{"wait": {"pattern": "X"}}]}
        (tmp_path / "fail.yaml").write_text(yaml.dump(data))
        rc = cmd_regression(suite=str(tmp_path), json_mode=True)
        assert rc == 1
        out = json.loads(capsys.readouterr().out)
        assert out["failed"] == 1
