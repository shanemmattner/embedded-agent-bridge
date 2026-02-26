"""EAB Anomaly Detection — Phase 1 (baseline diff) and Phase 2 (EWMA streaming)."""

from eab.anomaly.metric_extractor import (
    METRIC_PATTERNS,
    MetricExtractor,
    MetricSample,
)
from eab.anomaly.baseline_recorder import (
    BaselineRecorder,
    BaselineData,
    MetricStats,
)
from eab.anomaly.baseline_comparator import (
    BaselineComparator,
    ComparisonResult,
    MetricComparison,
)
from eab.anomaly.anomaly_watcher import (
    AnomalyWatcher,
    AnomalyAlert,
    EWMAState,
)

__all__ = [
    "METRIC_PATTERNS",
    "MetricExtractor", "MetricSample",
    "BaselineRecorder", "BaselineData", "MetricStats",
    "BaselineComparator", "ComparisonResult", "MetricComparison",
    "AnomalyWatcher", "AnomalyAlert", "EWMAState",
]
