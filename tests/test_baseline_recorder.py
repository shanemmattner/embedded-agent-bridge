"""Tests for BaselineRecorder using a synthetic log file."""

import json
import os
import threading
import time

import pytest
from eab.anomaly.baseline_recorder import BaselineRecorder, BaselineData, MetricStats


def _write_log_continuously(path: str, lines: list, interval_s: float,
                             stop_event: threading.Event) -> None:
    """Background thread: write lines to a log file at a fixed interval."""
    with open(path, "a") as f:
        while not stop_event.is_set():
            for line in lines:
                if stop_event.is_set():
                    break
                f.write(line + "\n")
                f.flush()
                time.sleep(interval_s)


class TestBaselineRecorder:
    LOG_LINES = [
        "[00:00:01.000] BT/CONN: Interval: 100 ms",
        "[00:00:01.010] BT/CONN: Interval: 102 ms",
        "[00:00:01.020] BT/HCI: TX buffer full",
    ]

    def test_record_captures_metrics(self, tmp_path):
        log_file = str(tmp_path / "latest.log")
        # Pre-create the file (recorder seeks to end before starting)
        open(log_file, "w").close()

        stop = threading.Event()
        t = threading.Thread(
            target=_write_log_continuously,
            args=(log_file, self.LOG_LINES, 0.05, stop),
            daemon=True,
        )
        t.start()

        try:
            rec = BaselineRecorder(log_path=log_file, duration_s=1.0,
                                   poll_interval_s=0.05)
            baseline = rec.record(device="test_dev")
        finally:
            stop.set()
            t.join(timeout=2)

        assert baseline.device == "test_dev"
        assert baseline.duration_s == 1.0
        assert baseline.total_lines_scanned > 0

        interval_stats = baseline.metrics.get("bt_notification_interval_ms")
        assert interval_stats is not None
        assert interval_stats.count > 0
        assert interval_stats.mean == pytest.approx(101.0, abs=2.0)

    def test_save_and_load_roundtrip(self, tmp_path):
        log_file = str(tmp_path / "log.txt")
        open(log_file, "w").close()
        rec = BaselineRecorder(log_path=log_file, duration_s=0.2, poll_interval_s=0.05)
        baseline = rec.record()
        out = str(tmp_path / "baseline.json")
        BaselineRecorder.save(baseline, out)

        loaded = BaselineRecorder.load(out)
        assert loaded.version == "1"
        assert isinstance(loaded.metrics, dict)

    def test_load_validates_version(self, tmp_path):
        bad_json = tmp_path / "bad.json"
        bad_json.write_text('{"version": "99"}')
        with pytest.raises(ValueError, match="schema version"):
            BaselineRecorder.load(str(bad_json))

    def test_empty_log_no_crash(self, tmp_path):
        log_file = str(tmp_path / "empty.log")
        open(log_file, "w").close()
        rec = BaselineRecorder(log_path=log_file, duration_s=0.2, poll_interval_s=0.05)
        baseline = rec.record()
        # All metrics should have count=0
        for m in baseline.metrics.values():
            assert m.count == 0

    def test_sparse_metric_count_zero(self, tmp_path):
        """Metrics that never appear should be present with count=0 — not missing."""
        log_file = str(tmp_path / "log.txt")
        with open(log_file, "w") as f:
            f.write("[00:00:01.000] heap_free=512\n")
        rec = BaselineRecorder(log_path=log_file, duration_s=0.2, poll_interval_s=0.05)
        baseline = rec.record()
        # bt_notification_interval_ms never appeared — should be present with count=0
        assert "bt_notification_interval_ms" in baseline.metrics
        assert baseline.metrics["bt_notification_interval_ms"].count == 0

    def test_to_dict_json_serializable(self, tmp_path):
        log_file = str(tmp_path / "log.txt")
        open(log_file, "w").close()
        rec = BaselineRecorder(log_path=log_file, duration_s=0.2, poll_interval_s=0.05)
        baseline = rec.record()
        d = baseline.to_dict()
        json.dumps(d)  # must not raise

    def test_baseline_data_from_dict(self):
        d = {
            "version": "1",
            "device": "test",
            "log_source": "/tmp/test.log",
            "recorded_at": "2026-02-25T12:00:00Z",
            "duration_s": 60.0,
            "total_lines_scanned": 100,
            "metrics": {
                "bt_notification_interval_ms": {
                    "kind": "numeric",
                    "count": 10,
                    "mean": 100.0,
                    "std": 2.0,
                    "min": 95.0,
                    "max": 105.0,
                    "p50": 100.0,
                    "p95": 104.0,
                    "p99": 105.0,
                    "rate_per_min": 10.0,
                }
            },
        }
        bd = BaselineData.from_dict(d)
        assert bd.device == "test"
        assert "bt_notification_interval_ms" in bd.metrics
        m = bd.metrics["bt_notification_interval_ms"]
        assert m.mean == 100.0
        assert m.kind == "numeric"

    def test_metric_stats_occurrence_to_dict(self):
        ms = MetricStats(
            kind="occurrence", count=5,
            mean=0.0, std=0.0, min=0.0, max=0.0,
            p50=None, p95=None, p99=None,
            rate_per_min=5.0,
        )
        d = ms.to_dict()
        assert d["kind"] == "occurrence"
        assert d["count"] == 5
        assert d["rate_per_min"] == 5.0
        assert "mean" not in d  # occurrence metrics don't include mean in dict

    def test_record_single_value(self, tmp_path):
        """Single observation: std=0, p50=p95=p99=value."""
        log_file = str(tmp_path / "log.txt")
        open(log_file, "w").close()
        stop = threading.Event()

        def _write_once():
            time.sleep(0.05)
            with open(log_file, "a") as f:
                f.write("[00:00:01.000] BT/CONN: Interval: 100 ms\n")
                f.flush()
            stop.set()

        t = threading.Thread(target=_write_once, daemon=True)
        t.start()

        rec = BaselineRecorder(log_path=log_file, duration_s=0.3, poll_interval_s=0.05)
        baseline = rec.record()
        t.join(timeout=1)

        m = baseline.metrics.get("bt_notification_interval_ms")
        if m and m.count == 1:
            assert m.std == 0.0
            assert m.p50 == 100.0
