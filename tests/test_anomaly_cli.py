"""Tests for CLI dispatch of eabctl anomaly subcommands."""

import json
import os
from unittest.mock import patch, MagicMock

import pytest


class TestAnomalyCliParsing:
    """Parser smoke-tests — ensure argparse accepts the new subcommand shapes."""

    def test_record_parses(self):
        from eab.cli.parser import _build_parser, _preprocess_argv
        args = _build_parser().parse_args(
            _preprocess_argv(["--device", "nrf", "anomaly", "record",
                              "--duration", "60", "--output", "/tmp/b.json"])
        )
        assert args.cmd == "anomaly"
        assert args.anomaly_action == "record"
        assert args.duration == 60.0
        assert args.output == "/tmp/b.json"

    def test_compare_parses(self):
        from eab.cli.parser import _build_parser, _preprocess_argv
        args = _build_parser().parse_args(
            _preprocess_argv(["anomaly", "compare",
                              "--baseline", "b.json", "--sigma", "2.5"])
        )
        assert args.anomaly_action == "compare"
        assert args.sigma == 2.5

    def test_watch_parses(self):
        from eab.cli.parser import _build_parser, _preprocess_argv
        args = _build_parser().parse_args(
            _preprocess_argv(["anomaly", "watch",
                              "--metric", "bt_notification_interval_ms",
                              "--threshold", "2.5sigma"])
        )
        assert args.anomaly_action == "watch"
        assert args.metric == "bt_notification_interval_ms"
        assert args.threshold == "2.5sigma"

    def test_record_defaults(self):
        from eab.cli.parser import _build_parser, _preprocess_argv
        args = _build_parser().parse_args(
            _preprocess_argv(["anomaly", "record", "--output", "/tmp/b.json"])
        )
        assert args.duration == 60.0
        assert args.metrics == []
        assert args.log_source is None

    def test_compare_defaults(self):
        from eab.cli.parser import _build_parser, _preprocess_argv
        args = _build_parser().parse_args(
            _preprocess_argv(["anomaly", "compare", "--baseline", "b.json"])
        )
        assert args.duration == 30.0
        assert args.sigma == 3.0
        assert args.log_source is None

    def test_watch_defaults(self):
        from eab.cli.parser import _build_parser, _preprocess_argv
        args = _build_parser().parse_args(
            _preprocess_argv(["anomaly", "watch",
                              "--metric", "bt_notification_interval_ms"])
        )
        assert args.ewma_window == 20
        assert args.min_samples == 30
        assert args.duration is None
        assert args.threshold == "2.5sigma"

    def test_record_with_log_source(self):
        from eab.cli.parser import _build_parser, _preprocess_argv
        args = _build_parser().parse_args(
            _preprocess_argv(["anomaly", "record", "--output", "/tmp/b.json",
                              "--log-source", "/custom/path.log"])
        )
        assert args.log_source == "/custom/path.log"

    def test_record_with_metrics_filter(self):
        from eab.cli.parser import _build_parser, _preprocess_argv
        args = _build_parser().parse_args(
            _preprocess_argv(["anomaly", "record", "--output", "/tmp/b.json",
                              "--metric", "bt_notification_interval_ms",
                              "--metric", "bt_backpressure"])
        )
        assert "bt_notification_interval_ms" in args.metrics
        assert "bt_backpressure" in args.metrics


class TestAnomalyCliDispatch:
    def test_record_missing_log_returns_1(self, tmp_path):
        from eab.cli.anomaly_cmds import cmd_anomaly_record
        rc = cmd_anomaly_record(
            base_dir=str(tmp_path),     # no latest.log created
            duration_s=5.0,
            output_path=str(tmp_path / "out.json"),
            log_source=None,
            metrics=None,
            device="test",
            json_mode=True,
        )
        assert rc == 1

    def test_compare_missing_baseline_returns_1(self, tmp_path):
        from eab.cli.anomaly_cmds import cmd_anomaly_compare
        rc = cmd_anomaly_compare(
            base_dir=str(tmp_path),
            baseline_path=str(tmp_path / "nonexistent.json"),
            duration_s=5.0,
            sigma_threshold=3.0,
            log_source=None,
            device="test",
            json_mode=True,
        )
        assert rc == 1

    def test_compare_missing_log_returns_1(self, tmp_path):
        from eab.cli.anomaly_cmds import cmd_anomaly_compare
        from eab.anomaly.baseline_recorder import BaselineRecorder, BaselineData

        # Create a valid baseline file
        baseline = BaselineData(version="1")
        baseline_path = str(tmp_path / "baseline.json")
        BaselineRecorder.save(baseline, baseline_path)

        rc = cmd_anomaly_compare(
            base_dir=str(tmp_path),   # no latest.log
            baseline_path=baseline_path,
            duration_s=0.1,
            sigma_threshold=3.0,
            log_source=None,
            device="test",
            json_mode=True,
        )
        assert rc == 1

    def test_watch_unknown_metric_returns_1(self, tmp_path):
        from eab.cli.anomaly_cmds import cmd_anomaly_watch
        log = tmp_path / "latest.log"
        log.write_text("")
        rc = cmd_anomaly_watch(
            base_dir=str(tmp_path),
            metric_name="definitely_not_a_metric_xxxx",
            threshold_sigma=2.5,
            ewma_window=20,
            min_samples=30,
            duration_s=1.0,
            log_source=None,
            json_mode=True,
        )
        assert rc == 1

    def test_parse_sigma_threshold(self):
        from eab.cli.anomaly_cmds import _parse_sigma_threshold
        assert _parse_sigma_threshold("2.5sigma") == pytest.approx(2.5)
        assert _parse_sigma_threshold("3sigma") == pytest.approx(3.0)
        assert _parse_sigma_threshold("3.0") == pytest.approx(3.0)
        with pytest.raises(ValueError):
            _parse_sigma_threshold("notanumber")

    def test_resolve_log_path_explicit(self, tmp_path):
        from eab.cli.anomaly_cmds import _resolve_log_path
        result = _resolve_log_path(str(tmp_path), "/explicit/path.log")
        assert result == "/explicit/path.log"

    def test_resolve_log_path_latest(self, tmp_path):
        from eab.cli.anomaly_cmds import _resolve_log_path
        latest = tmp_path / "latest.log"
        latest.write_text("")
        result = _resolve_log_path(str(tmp_path), None)
        assert result == str(latest)

    def test_resolve_log_path_rtt_fallback(self, tmp_path):
        """Falls back to rtt.log when latest.log doesn't exist."""
        from eab.cli.anomaly_cmds import _resolve_log_path
        result = _resolve_log_path(str(tmp_path), None)
        # Should return rtt.log path (even if it doesn't exist — caller checks)
        assert result.endswith("rtt.log")

    def test_record_success(self, tmp_path):
        """record command succeeds with an existing empty log file."""
        from eab.cli.anomaly_cmds import cmd_anomaly_record

        log = tmp_path / "latest.log"
        log.write_text("")
        out = str(tmp_path / "baseline.json")

        rc = cmd_anomaly_record(
            base_dir=str(tmp_path),
            duration_s=0.2,
            output_path=out,
            log_source=None,
            metrics=None,
            device="testdev",
            json_mode=True,
        )
        assert rc == 0
        assert os.path.exists(out)

    def test_watch_exits_cleanly_with_duration(self, tmp_path):
        """watch command exits cleanly when duration is reached."""
        from eab.cli.anomaly_cmds import cmd_anomaly_watch

        log = tmp_path / "latest.log"
        log.write_text("")

        rc = cmd_anomaly_watch(
            base_dir=str(tmp_path),
            metric_name="bt_notification_interval_ms",
            threshold_sigma=2.5,
            ewma_window=20,
            min_samples=30,
            duration_s=0.2,
            log_source=None,
            json_mode=True,
        )
        assert rc == 0


class TestAnomalyRegressionStep:
    """Test the regression step integration."""

    def test_anomaly_watch_step_no_baseline(self):
        """Step without 'baseline' param returns error."""
        from eab.cli.regression.steps import _run_anomaly_watch
        from eab.cli.regression.models import StepSpec

        step = StepSpec(step_type="anomaly_watch", params={})
        result = _run_anomaly_watch(step, device=None, chip=None, timeout=60)
        assert not result.passed
        assert result.error is not None
        assert "baseline" in result.error.lower()

    def test_anomaly_watch_step_registered(self):
        """anomaly_watch step type is registered in _STEP_DISPATCH."""
        from eab.cli.regression.steps import _STEP_DISPATCH
        assert "anomaly_watch" in _STEP_DISPATCH

    def test_anomaly_watch_step_type_in_result(self):
        """Step result has correct step_type."""
        from eab.cli.regression.steps import _run_anomaly_watch
        from eab.cli.regression.models import StepSpec

        step = StepSpec(step_type="anomaly_watch", params={})
        result = _run_anomaly_watch(step, device=None, chip=None, timeout=60)
        assert result.step_type == "anomaly_watch"
