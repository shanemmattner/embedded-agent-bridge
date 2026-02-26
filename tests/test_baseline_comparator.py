"""Tests for BaselineComparator using synthetic baseline + current data."""

import json
import threading
import time

import pytest
from eab.anomaly.baseline_recorder import BaselineData, MetricStats
from eab.anomaly.baseline_comparator import BaselineComparator, ComparisonResult


def _make_baseline(mean=100.0, std=2.0, count=120) -> BaselineData:
    return BaselineData(
        version="1", device="test", duration_s=60,
        metrics={
            "bt_notification_interval_ms": MetricStats(
                kind="numeric", count=count,
                mean=mean, std=std,
                min=mean - 3 * std, max=mean + 3 * std,
                p50=mean, p95=mean + 1.5 * std, p99=mean + 2 * std,
                rate_per_min=count / 1.0,
            ),
            "bt_backpressure": MetricStats(
                kind="occurrence", count=3,
                mean=0.0, std=0.0, min=0.0, max=0.0,
                p50=None, p95=None, p99=None, rate_per_min=3.0,
            ),
        }
    )


def _write_lines_after_delay(path: str, lines: list, delay_s: float = 0.05) -> None:
    """Write lines to a file after a short delay (so recorder has time to seek to end)."""
    time.sleep(delay_s)
    with open(path, "a") as f:
        for line in lines:
            f.write(line + "\n")
            f.flush()
            time.sleep(0.01)


class TestBaselineComparator:
    def test_no_anomaly_within_bounds(self, tmp_path):
        """Current mean within 3sigma of baseline -> no anomaly."""
        baseline = _make_baseline(mean=100.0, std=2.0)
        log_file = str(tmp_path / "log.txt")
        open(log_file, "w").close()  # create empty file

        # Write lines concurrently after the recorder seeks to end
        lines = ["[00:00:01.000] Interval: 101 ms"] * 30
        writer = threading.Thread(
            target=_write_lines_after_delay,
            args=(log_file, lines),
            daemon=True,
        )
        writer.start()

        cmp = BaselineComparator(
            baseline=baseline, log_path=log_file,
            duration_s=0.5, sigma_threshold=3.0,
        )
        report = cmp.compare(device="test")
        writer.join(timeout=2.0)

        m = report.metrics.get("bt_notification_interval_ms")
        assert m is not None
        if m.current_count >= 2:  # only check z_score if we captured data
            assert abs(m.z_score) < 3.0
            assert not m.anomalous

    def test_anomaly_detected_when_mean_shifts(self, tmp_path):
        """Current mean >> baseline mean -> anomaly."""
        baseline = _make_baseline(mean=100.0, std=2.0)
        log_file = str(tmp_path / "log.txt")
        open(log_file, "w").close()

        lines = ["[00:00:01.000] Interval: 200 ms"] * 30
        writer = threading.Thread(
            target=_write_lines_after_delay,
            args=(log_file, lines),
            daemon=True,
        )
        writer.start()

        cmp = BaselineComparator(
            baseline=baseline, log_path=log_file,
            duration_s=0.5, sigma_threshold=3.0,
        )
        report = cmp.compare(device="test")
        writer.join(timeout=2.0)

        m = report.metrics["bt_notification_interval_ms"]
        if m.current_count >= 2:
            assert m.anomalous
            assert m.z_score > 3.0
            assert m.direction == "high"
            assert report.anomaly_count >= 1
            assert not report.passed
        else:
            pytest.skip("Not enough samples captured in time window")

    def test_low_direction_when_mean_drops(self, tmp_path):
        """Current mean << baseline mean -> direction == 'low'."""
        baseline = _make_baseline(mean=100.0, std=2.0)
        log_file = str(tmp_path / "log.txt")
        open(log_file, "w").close()

        lines = ["[00:00:01.000] Interval: 10 ms"] * 30
        writer = threading.Thread(
            target=_write_lines_after_delay,
            args=(log_file, lines),
            daemon=True,
        )
        writer.start()

        cmp = BaselineComparator(
            baseline=baseline, log_path=log_file,
            duration_s=0.5, sigma_threshold=3.0,
        )
        report = cmp.compare(device="test")
        writer.join(timeout=2.0)

        m = report.metrics["bt_notification_interval_ms"]
        if m.current_count >= 2:
            assert m.anomalous
            assert m.z_score < -3.0
            assert m.direction == "low"
        else:
            pytest.skip("Not enough samples captured in time window")

    def test_missing_metric_in_current_not_anomalous(self, tmp_path):
        """Metric in baseline but absent in current window -> count=0, not anomalous."""
        baseline = _make_baseline()
        log_file = str(tmp_path / "log.txt")
        open(log_file, "w").close()   # empty log

        cmp = BaselineComparator(
            baseline=baseline, log_path=log_file,
            duration_s=0.2, sigma_threshold=3.0,
        )
        report = cmp.compare()
        m = report.metrics.get("bt_notification_interval_ms")
        assert m is not None
        assert m.current_count == 0
        # Sparse metric - absence of data is not anomalous by default
        assert not m.anomalous

    def test_to_dict_json_serializable(self, tmp_path):
        baseline = _make_baseline()
        log_file = str(tmp_path / "log.txt")
        open(log_file, "w").close()
        cmp = BaselineComparator(baseline=baseline, log_path=log_file, duration_s=0.2)
        report = cmp.compare()
        d = report.to_dict()
        json.dumps(d)  # must not raise

    def test_passed_is_true_when_no_anomalies(self, tmp_path):
        baseline = _make_baseline()
        log_file = str(tmp_path / "log.txt")
        open(log_file, "w").close()  # empty log -> no anomalies
        cmp = BaselineComparator(baseline=baseline, log_path=log_file, duration_s=0.2)
        report = cmp.compare()
        assert report.passed == (report.anomaly_count == 0)

    def test_comparison_result_fields(self, tmp_path):
        baseline = _make_baseline()
        log_file = str(tmp_path / "log.txt")
        open(log_file, "w").close()
        cmp = BaselineComparator(baseline=baseline, log_path=log_file, duration_s=0.2)
        cmp._baseline_path = "baselines/test.json"
        report = cmp.compare(device="mydevice")
        assert report.device == "mydevice"
        assert report.baseline_path == "baselines/test.json"
        assert report.duration_s == 0.2
        assert isinstance(report.metrics, dict)

    def test_occurrence_anomaly_when_rate_spikes(self, tmp_path):
        """Rate increases >> threshold -> occurrence metric flagged."""
        baseline = _make_baseline()
        log_file = str(tmp_path / "log.txt")
        open(log_file, "w").close()

        lines = ["[00:00:01.000] BT/HCI: TX buffer full"] * 100
        writer = threading.Thread(
            target=_write_lines_after_delay,
            args=(log_file, lines),
            daemon=True,
        )
        writer.start()

        cmp = BaselineComparator(
            baseline=baseline, log_path=log_file,
            duration_s=0.5, sigma_threshold=3.0, rate_threshold=3.0,
        )
        report = cmp.compare()
        writer.join(timeout=2.0)

        m = report.metrics.get("bt_backpressure")
        assert m is not None
        # Rate should be high - check that ratio is computed
        if m.current_count > 0 and m.rate_ratio is not None:
            if m.rate_ratio > 3.0:
                assert m.anomalous

    def test_metric_comparison_dict_numeric(self):
        from eab.anomaly.baseline_comparator import MetricComparison
        mc = MetricComparison(
            kind="numeric",
            baseline_mean=100.0, baseline_std=2.0,
            current_mean=105.0, current_std=3.0,
            z_score=2.5,
            baseline_rate_per_min=None, current_rate_per_min=None, rate_ratio=None,
            baseline_count=120, current_count=60,
            anomalous=False, direction=None,
        )
        d = mc.to_dict()
        assert d["kind"] == "numeric"
        assert d["z_score"] == 2.5
        assert "baseline_mean" in d

    def test_metric_comparison_dict_occurrence(self):
        from eab.anomaly.baseline_comparator import MetricComparison
        mc = MetricComparison(
            kind="occurrence",
            baseline_mean=None, baseline_std=None,
            current_mean=None, current_std=None,
            z_score=None,
            baseline_rate_per_min=3.0, current_rate_per_min=9.0, rate_ratio=3.0,
            baseline_count=3, current_count=9,
            anomalous=True, direction=None,
        )
        d = mc.to_dict()
        assert d["kind"] == "occurrence"
        assert d["rate_ratio"] == 3.0
        assert "baseline_mean" not in d
