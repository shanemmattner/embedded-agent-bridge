"""Baseline comparator: compare a live recording window against a saved baseline."""

from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime, timezone
from typing import Callable, Dict, Optional

from eab.anomaly.baseline_recorder import BaselineData, BaselineRecorder, MetricStats
from eab.anomaly.metric_extractor import MetricExtractor

_MIN_STD = 0.001  # floor to prevent division by zero


@dataclass
class MetricComparison:
    """Comparison result for a single metric."""
    kind: str
    # numeric fields
    baseline_mean: Optional[float]
    baseline_std: Optional[float]
    current_mean: Optional[float]
    current_std: Optional[float]
    z_score: Optional[float]
    # occurrence fields
    baseline_rate_per_min: Optional[float]
    current_rate_per_min: Optional[float]
    rate_ratio: Optional[float]
    # shared
    baseline_count: int
    current_count: int
    anomalous: bool
    direction: Optional[str]            # "high", "low", or None

    def to_dict(self) -> dict:
        d: dict = {
            "kind": self.kind,
            "baseline_count": self.baseline_count,
            "current_count": self.current_count,
            "anomalous": self.anomalous,
        }
        if self.kind == "numeric":
            d["baseline_mean"] = self.baseline_mean
            d["baseline_std"] = self.baseline_std
            d["current_mean"] = self.current_mean
            d["current_std"] = self.current_std
            d["z_score"] = self.z_score
            d["direction"] = self.direction
        else:
            d["baseline_rate_per_min"] = self.baseline_rate_per_min
            d["current_rate_per_min"] = self.current_rate_per_min
            d["rate_ratio"] = self.rate_ratio
        return d


@dataclass
class ComparisonResult:
    """Full comparison report — call .to_dict() for JSON output."""
    device: str
    baseline_path: str
    baseline_recorded_at: str
    compared_at: str
    duration_s: float
    anomaly_count: int
    passed: bool                        # True if no anomalies found
    metrics: Dict[str, MetricComparison]

    def to_dict(self) -> dict:
        return {
            "device": self.device,
            "baseline_path": self.baseline_path,
            "baseline_recorded_at": self.baseline_recorded_at,
            "compared_at": self.compared_at,
            "duration_s": self.duration_s,
            "anomaly_count": self.anomaly_count,
            "passed": self.passed,
            "metrics": {
                name: m.to_dict()
                for name, m in self.metrics.items()
            },
        }


class BaselineComparator:
    """
    Compare a live recording window against a saved baseline.

    Args:
        baseline: BaselineData loaded via BaselineRecorder.load().
        log_path: Path to the device log file to record against.
        duration_s: Duration of the comparison window (seconds).
        sigma_threshold: Alert if |z_score| > this (default 3.0).
        rate_threshold: Alert if rate_ratio > this for occurrence metrics (default 3.0).
        extractor: MetricExtractor to use (defaults to MetricExtractor()).
        flag_new_occurrences: Flag as anomalous if a metric appears in current but
                              had baseline_count=0 (default True).
        flag_disappeared: Flag as anomalous if baseline_count > 0 but current_count=0
                          (default False).
    """

    def __init__(
        self,
        baseline: BaselineData,
        log_path: str,
        duration_s: float,
        sigma_threshold: float = 3.0,
        rate_threshold: float = 3.0,
        extractor: Optional[MetricExtractor] = None,
        flag_new_occurrences: bool = True,
        flag_disappeared: bool = False,
    ) -> None:
        self.baseline = baseline
        self.log_path = log_path
        self.duration_s = duration_s
        self.sigma_threshold = sigma_threshold
        self.rate_threshold = rate_threshold
        self.extractor = extractor or MetricExtractor()
        self.flag_new_occurrences = flag_new_occurrences
        self.flag_disappeared = flag_disappeared
        self._baseline_path = ""  # set optionally

    def compare(
        self,
        device: str = "",
        progress_cb: Optional[Callable[[float], None]] = None,
    ) -> ComparisonResult:
        """
        Record a fresh window, compare against baseline, return ComparisonResult.

        Uses BaselineRecorder internally with the same log_path / duration_s.
        Missing metrics in either baseline or current window are reported as
        anomalous=False with count=0 (not an error — sparse metrics are expected).
        """
        recorder = BaselineRecorder(
            log_path=self.log_path,
            duration_s=self.duration_s,
            extractor=self.extractor,
        )
        current = recorder.record(device=device, progress_cb=progress_cb)
        compared_at = datetime.now(timezone.utc).isoformat()

        metric_results: Dict[str, MetricComparison] = {}

        # Iterate over all metrics known to the extractor
        for name in self.extractor.metric_names():
            kind = self.extractor._compiled[name][0]
            b_stats: Optional[MetricStats] = self.baseline.metrics.get(name)
            c_stats: Optional[MetricStats] = current.metrics.get(name)

            b_count = b_stats.count if b_stats else 0
            c_count = c_stats.count if c_stats else 0

            if kind == "numeric":
                b_mean = b_stats.mean if b_stats else 0.0
                b_std = b_stats.std if b_stats else 0.0
                c_mean = c_stats.mean if c_stats else 0.0
                c_std = c_stats.std if c_stats else 0.0

                if b_count == 0 or c_count == 0:
                    # Missing data in one window — not anomalous by default
                    anomalous = False
                    z_score = None
                    direction = None
                else:
                    z_score = (c_mean - b_mean) / max(b_std, _MIN_STD)
                    anomalous = abs(z_score) > self.sigma_threshold
                    if anomalous:
                        direction = "high" if z_score > 0 else "low"
                    else:
                        direction = None

                metric_results[name] = MetricComparison(
                    kind="numeric",
                    baseline_mean=b_mean,
                    baseline_std=b_std,
                    current_mean=c_mean,
                    current_std=c_std,
                    z_score=z_score,
                    baseline_rate_per_min=None,
                    current_rate_per_min=None,
                    rate_ratio=None,
                    baseline_count=b_count,
                    current_count=c_count,
                    anomalous=anomalous,
                    direction=direction,
                )

            else:  # occurrence
                b_rate = b_stats.rate_per_min if b_stats else 0.0
                c_rate = c_stats.rate_per_min if c_stats else 0.0

                if b_count == 0 and c_count == 0:
                    anomalous = False
                    rate_ratio = None
                elif b_count == 0 and c_count > 0:
                    # New occurrence — flag based on flag_new_occurrences
                    anomalous = self.flag_new_occurrences
                    rate_ratio = None
                elif b_count > 0 and c_count == 0:
                    # Disappeared — flag based on flag_disappeared
                    anomalous = self.flag_disappeared
                    rate_ratio = 0.0
                else:
                    rate_ratio = c_rate / max(b_rate, _MIN_STD)
                    anomalous = rate_ratio > self.rate_threshold

                metric_results[name] = MetricComparison(
                    kind="occurrence",
                    baseline_mean=None,
                    baseline_std=None,
                    current_mean=None,
                    current_std=None,
                    z_score=None,
                    baseline_rate_per_min=b_rate,
                    current_rate_per_min=c_rate,
                    rate_ratio=rate_ratio,
                    baseline_count=b_count,
                    current_count=c_count,
                    anomalous=anomalous,
                    direction=None,
                )

        anomaly_count = sum(1 for m in metric_results.values() if m.anomalous)

        return ComparisonResult(
            device=device,
            baseline_path=self._baseline_path,
            baseline_recorded_at=self.baseline.recorded_at,
            compared_at=compared_at,
            duration_s=self.duration_s,
            anomaly_count=anomaly_count,
            passed=(anomaly_count == 0),
            metrics=metric_results,
        )
