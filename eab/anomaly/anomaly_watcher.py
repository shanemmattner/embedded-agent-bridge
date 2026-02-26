"""Anomaly watcher: streaming EWMA-based anomaly detection on device log metrics."""

from __future__ import annotations

import json
import math
import time
from dataclasses import dataclass
from typing import Callable, Dict, List, Optional

from eab.anomaly.baseline_recorder import _read_new_lines, _get_file_size
from eab.anomaly.metric_extractor import METRIC_PATTERNS, MetricExtractor

_MIN_SIGMA = 0.001  # floor for sigma to prevent numerical explosion


@dataclass
class EWMAState:
    """Per-metric EWMA running state."""
    mean: float = 0.0
    variance: float = 0.0
    n_samples: int = 0
    alpha: float = 0.0              # set at construction from window param

    def update(self, x: float):
        """
        Update state with new observation x.

        Returns:
            (updated_mean, updated_sigma) after incorporating x.
        """
        if self.n_samples == 0:
            self.mean = x
            self.variance = 0.0
        else:
            prev_mean = self.mean
            self.mean = self.alpha * x + (1 - self.alpha) * self.mean
            self.variance = (1 - self.alpha) * (
                self.variance + self.alpha * (x - prev_mean) ** 2
            )
        self.n_samples += 1
        return self.mean, math.sqrt(self.variance)


@dataclass
class AnomalyAlert:
    """Emitted when a sample exceeds the sigma threshold."""
    timestamp_s: float              # monotonic time
    metric_name: str
    value: float
    ewma_mean: float
    ewma_sigma: float
    z_score: float                  # = (value - ewma_mean) / max(ewma_sigma, _MIN_SIGMA)
    threshold_sigma: float
    raw_line: str

    def to_dict(self) -> dict:
        return {
            "ts": self.timestamp_s,
            "metric": self.metric_name,
            "value": self.value,
            "ewma_mean": self.ewma_mean,
            "ewma_sigma": self.ewma_sigma,
            "z_score": self.z_score,
            "threshold": self.threshold_sigma,
            "raw_line": self.raw_line,
        }


class AnomalyWatcher:
    """
    Stream-watch a single metric in a device log, alert on EWMA sigma violations.

    Args:
        log_path: Device log file path.
        metric_name: Key from METRIC_PATTERNS to watch.
        threshold_sigma: Alert when |z| > threshold_sigma (default 2.5).
        ewma_window: EWMA window size N; α = 2/(N+1) (default 20).
        min_samples: Cold-start samples before alerts fire (default 30).
        duration_s: Stop after N seconds (None = run until Ctrl-C).
        poll_interval_s: Log-tail poll rate (default 0.1).
        custom_patterns: Extra patterns for MetricExtractor.
        alert_cb: Optional callback(AnomalyAlert) instead of stdout JSON.

    Usage:
        watcher = AnomalyWatcher(
            log_path="/tmp/eab-devices/nrf/latest.log",
            metric_name="bt_notification_interval_ms",
            threshold_sigma=2.5,
        )
        watcher.watch()     # blocks; prints JSONL alerts to stdout
    """

    def __init__(
        self,
        log_path: str,
        metric_name: str,
        threshold_sigma: float = 2.5,
        ewma_window: int = 20,
        min_samples: int = 30,
        duration_s: Optional[float] = None,
        poll_interval_s: float = 0.1,
        custom_patterns: Optional[Dict[str, tuple]] = None,
        alert_cb: Optional[Callable[["AnomalyAlert"], None]] = None,
    ) -> None:
        # Validate metric name
        all_patterns = {**METRIC_PATTERNS, **(custom_patterns or {})}
        if metric_name not in all_patterns:
            raise ValueError(
                f"Unknown metric: {metric_name!r}. "
                f"Available: {sorted(all_patterns)}"
            )

        self.log_path = log_path
        self.metric_name = metric_name
        self.threshold_sigma = threshold_sigma
        self.ewma_window = ewma_window
        self.min_samples = min_samples
        self.duration_s = duration_s
        self.poll_interval_s = poll_interval_s
        self.alert_cb = alert_cb

        # Only extract the watched metric for efficiency
        self.extractor = MetricExtractor(
            patterns={metric_name: all_patterns[metric_name]},
        )

        alpha = 2.0 / (ewma_window + 1)
        self._ewma_state = EWMAState(alpha=alpha)

    def watch(self) -> List[AnomalyAlert]:
        """
        Start tailing and watching. Blocks until duration_s or KeyboardInterrupt.

        Each alert is:
        1. Passed to alert_cb if set, OR
        2. Printed as a JSON line to stdout.

        Returns the list of all alerts emitted (useful for testing).
        """
        alerts: List[AnomalyAlert] = []
        offset = _get_file_size(self.log_path)

        t_start = time.monotonic()
        t_end = t_start + self.duration_s if self.duration_s is not None else None

        try:
            while True:
                now = time.monotonic()
                if t_end is not None and now >= t_end:
                    break

                time.sleep(self.poll_interval_s)
                new_lines, offset = _read_new_lines(self.log_path, offset)

                for line in new_lines:
                    for sample in self.extractor.extract_line(line):
                        if sample.metric_name != self.metric_name:
                            continue

                        x = sample.value

                        # Compute z-score BEFORE updating state so we measure
                        # deviation from the current running baseline, not the
                        # post-update (spike-polluted) values.
                        prev_mean = self._ewma_state.mean
                        prev_sigma = math.sqrt(self._ewma_state.variance)

                        ewma_mean, ewma_sigma = self._ewma_state.update(x)

                        # Cold-start suppression
                        if self._ewma_state.n_samples < self.min_samples:
                            continue

                        sigma_floor = max(prev_sigma, _MIN_SIGMA)
                        z_score = (x - prev_mean) / sigma_floor

                        if abs(z_score) > self.threshold_sigma:
                            alert = AnomalyAlert(
                                timestamp_s=time.monotonic(),
                                metric_name=self.metric_name,
                                value=x,
                                ewma_mean=prev_mean,   # baseline mean before update
                                ewma_sigma=prev_sigma, # baseline sigma before update
                                z_score=z_score,
                                threshold_sigma=self.threshold_sigma,
                                raw_line=line.rstrip(),
                            )
                            alerts.append(alert)
                            if self.alert_cb is not None:
                                self.alert_cb(alert)
                            else:
                                print(json.dumps(alert.to_dict()))

        except KeyboardInterrupt:
            pass

        return alerts

    def get_state(self) -> EWMAState:
        """Return a copy of the current EWMA state for the watched metric."""
        s = self._ewma_state
        return EWMAState(
            mean=s.mean,
            variance=s.variance,
            n_samples=s.n_samples,
            alpha=s.alpha,
        )
