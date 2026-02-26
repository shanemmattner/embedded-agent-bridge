"""Tests for AnomalyWatcher EWMA with synthetic log injection."""

import threading
import time

import pytest
from eab.anomaly.anomaly_watcher import AnomalyWatcher, EWMAState, AnomalyAlert


def _write_lines(path, lines, interval=0.01):
    with open(path, "a") as f:
        for line in lines:
            f.write(line + "\n")
            f.flush()
            time.sleep(interval)


class TestEWMAState:
    def test_initial_mean_equals_first_value(self):
        state = EWMAState(alpha=0.1)
        mean, sigma = state.update(50.0)
        assert mean == pytest.approx(50.0)
        assert sigma == pytest.approx(0.0)

    def test_converges_to_true_mean(self):
        state = EWMAState(alpha=2 / (20 + 1))
        for _ in range(500):
            state.update(100.0)
        mean, sigma = state.update(100.0)
        assert mean == pytest.approx(100.0, abs=0.01)

    def test_variance_nonzero_after_noise(self):
        import random
        state = EWMAState(alpha=2 / (20 + 1))
        rng = random.Random(42)
        for _ in range(100):
            state.update(100.0 + rng.gauss(0, 5))
        _, sigma = state.update(100.0)
        assert sigma > 0

    def test_n_samples_increments(self):
        state = EWMAState(alpha=0.1)
        assert state.n_samples == 0
        state.update(10.0)
        assert state.n_samples == 1
        state.update(20.0)
        assert state.n_samples == 2

    def test_mean_moves_toward_new_value(self):
        state = EWMAState(alpha=0.5)
        state.update(0.0)
        # With alpha=0.5, mean should move toward new value
        mean, _ = state.update(100.0)
        assert 0.0 < mean < 100.0

    def test_variance_is_nonnegative(self):
        import random
        state = EWMAState(alpha=0.1)
        rng = random.Random(99)
        for _ in range(200):
            _, sigma = state.update(rng.uniform(-100, 100))
            assert sigma >= 0.0


class TestAnomalyWatcher:
    def test_no_alert_within_threshold(self, tmp_path):
        log_file = str(tmp_path / "log.txt")
        open(log_file, "w").close()

        # Stable values — should produce no alerts
        normal_lines = [f"[00:00:{i:02d}.000] Interval: 100 ms" for i in range(60)]

        stop = threading.Event()
        alerts = []

        def _run():
            w = AnomalyWatcher(
                log_path=log_file,
                metric_name="bt_notification_interval_ms",
                threshold_sigma=2.5,
                ewma_window=10,
                min_samples=5,
                duration_s=1.5,
                poll_interval_s=0.05,
                alert_cb=alerts.append,
            )
            w.watch()
            stop.set()

        t = threading.Thread(target=_run, daemon=True)
        t.start()
        time.sleep(0.1)  # ensure watcher has started and set its initial offset
        _write_lines(log_file, normal_lines, interval=0.02)
        stop.wait(timeout=3.0)

        assert len(alerts) == 0

    def test_alert_on_spike(self, tmp_path):
        log_file = str(tmp_path / "log.txt")
        open(log_file, "w").close()

        alerts = []

        # Warm-up with stable data, then spike
        warmup = [f"[00:00:{i:02d}.000] Interval: 100 ms" for i in range(40)]
        spike = ["[00:00:41.000] Interval: 500 ms"]

        def _run():
            w = AnomalyWatcher(
                log_path=log_file,
                metric_name="bt_notification_interval_ms",
                threshold_sigma=2.5,
                ewma_window=10,
                min_samples=10,
                duration_s=3.0,
                poll_interval_s=0.05,
                alert_cb=alerts.append,
            )
            w.watch()

        t = threading.Thread(target=_run, daemon=True)
        t.start()
        # Small delay to ensure the watcher thread has started and recorded its initial offset
        time.sleep(0.1)
        _write_lines(log_file, warmup + spike, interval=0.03)
        t.join(timeout=5.0)

        assert len(alerts) >= 1
        assert alerts[0].value == pytest.approx(500.0)
        assert alerts[0].z_score > 2.5

    def test_cold_start_suppression(self, tmp_path):
        """No alerts during cold-start period, even for spiky values."""
        log_file = str(tmp_path / "log.txt")
        open(log_file, "w").close()

        alerts = []
        # 5 spiky lines, but min_samples=20 — no alerts expected
        lines = [f"[00:00:{i:02d}.000] Interval: {1000 * (i + 1)} ms" for i in range(5)]

        def _run():
            w = AnomalyWatcher(
                log_path=log_file,
                metric_name="bt_notification_interval_ms",
                threshold_sigma=2.5,
                ewma_window=5,
                min_samples=20,   # cold-start threshold > lines written
                duration_s=1.0,
                poll_interval_s=0.05,
                alert_cb=alerts.append,
            )
            w.watch()

        t = threading.Thread(target=_run, daemon=True)
        t.start()
        time.sleep(0.1)  # ensure watcher has started
        _write_lines(log_file, lines, interval=0.03)
        t.join(timeout=3.0)

        assert len(alerts) == 0

    def test_unknown_metric_raises(self, tmp_path):
        log_file = str(tmp_path / "log.txt")
        open(log_file, "w").close()
        with pytest.raises(ValueError, match="Unknown metric"):
            AnomalyWatcher(
                log_path=log_file,
                metric_name="nonexistent_metric_xyz",
                duration_s=0.5,
            )

    def test_alert_to_dict(self):
        alert = AnomalyAlert(
            timestamp_s=1234.5,
            metric_name="bt_notification_interval_ms",
            value=500.0,
            ewma_mean=100.0,
            ewma_sigma=3.0,
            z_score=133.3,
            threshold_sigma=2.5,
            raw_line="[00:00:01.000] Interval: 500 ms",
        )
        d = alert.to_dict()
        assert d["ts"] == 1234.5
        assert d["metric"] == "bt_notification_interval_ms"
        assert d["value"] == 500.0
        assert d["z_score"] == pytest.approx(133.3)

    def test_get_state_returns_copy(self, tmp_path):
        log_file = str(tmp_path / "log.txt")
        open(log_file, "w").close()
        w = AnomalyWatcher(
            log_path=log_file,
            metric_name="bt_notification_interval_ms",
            duration_s=0.1,
        )
        state = w.get_state()
        assert state.n_samples == 0
        assert isinstance(state, EWMAState)

    def test_duration_causes_exit(self, tmp_path):
        """Watcher with duration_s should exit without KeyboardInterrupt."""
        log_file = str(tmp_path / "log.txt")
        open(log_file, "w").close()

        w = AnomalyWatcher(
            log_path=log_file,
            metric_name="bt_notification_interval_ms",
            duration_s=0.3,
            poll_interval_s=0.05,
        )
        alerts = w.watch()  # should complete in ~0.3s
        assert isinstance(alerts, list)
