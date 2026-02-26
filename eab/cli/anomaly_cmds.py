"""CLI handlers for eabctl anomaly subcommands."""

from __future__ import annotations

import json
import os
import re
import sys
from typing import List, Optional

from eab.cli.helpers import _print


def _resolve_log_path(base_dir: str, log_source: Optional[str]) -> str:
    """
    Return explicit log_source if given, else <base_dir>/latest.log.
    Falls back to <base_dir>/rtt.log if latest.log is absent.
    """
    if log_source:
        return log_source
    latest = os.path.join(base_dir, "latest.log")
    if os.path.exists(latest):
        return latest
    rtt = os.path.join(base_dir, "rtt.log")
    return rtt  # caller checks existence


def _parse_sigma_threshold(threshold_str: str) -> float:
    """
    Parse threshold string like '2.5sigma' or '2.5' → float 2.5.

    Raises ValueError on invalid format.
    """
    m = re.match(r'^([\d.]+)(?:sigma)?$', threshold_str.strip())
    if not m:
        raise ValueError(
            f"Invalid threshold format: {threshold_str!r} — expected e.g. '2.5sigma'"
        )
    return float(m.group(1))


def cmd_anomaly_record(
    base_dir: str,
    duration_s: float,
    output_path: str,
    log_source: Optional[str],
    metrics: Optional[List[str]],
    device: str,
    json_mode: bool,
) -> int:
    """
    Record a golden baseline and write to output_path.

    Returns:
        0 on success, 1 on error.
    """
    from eab.anomaly.metric_extractor import MetricExtractor, METRIC_PATTERNS
    from eab.anomaly.baseline_recorder import BaselineRecorder

    log_path = _resolve_log_path(base_dir, log_source)
    if not os.path.exists(log_path):
        _print({"error": f"Log file not found: {log_path}"}, json_mode=json_mode)
        return 1

    custom = None
    if metrics:
        # Filter to requested metric names only
        custom = {k: v for k, v in METRIC_PATTERNS.items() if k in metrics}
        if not custom:
            _print({"error": f"No matching metrics for: {metrics}"}, json_mode=json_mode)
            return 1
        extractor = MetricExtractor(patterns=custom)
    else:
        extractor = MetricExtractor()

    recorder = BaselineRecorder(
        log_path=log_path,
        duration_s=duration_s,
        extractor=extractor,
    )

    if not json_mode:
        print(f"Recording baseline for {duration_s}s from {log_path}...")

    def _progress(elapsed: float) -> None:
        if not json_mode:
            pct = min(100, int(elapsed / duration_s * 100)) if duration_s > 0 else 100
            print(f"\r  {pct}% ({elapsed:.1f}s / {duration_s}s)   ", end="", flush=True)

    baseline = recorder.record(device=device, progress_cb=_progress)

    if not json_mode:
        print()  # newline after progress

    os.makedirs(os.path.dirname(os.path.abspath(output_path)), exist_ok=True)
    BaselineRecorder.save(baseline, output_path)

    result = {
        "status": "ok",
        "output": output_path,
        "device": device,
        "duration_s": duration_s,
        "metrics_recorded": len([m for m in baseline.metrics.values() if m.count > 0]),
        "total_metrics": len(baseline.metrics),
        "total_lines_scanned": baseline.total_lines_scanned,
    }
    _print(result, json_mode=json_mode)
    return 0


def cmd_anomaly_compare(
    base_dir: str,
    baseline_path: str,
    duration_s: float,
    sigma_threshold: float,
    log_source: Optional[str],
    device: str,
    json_mode: bool,
) -> int:
    """
    Compare a live recording against a baseline.

    Returns 0 if no anomalies, 1 if anomalies found.
    """
    from eab.anomaly.baseline_recorder import BaselineRecorder
    from eab.anomaly.baseline_comparator import BaselineComparator

    if not os.path.exists(baseline_path):
        _print({"error": f"Baseline not found: {baseline_path}"}, json_mode=json_mode)
        return 1

    baseline = BaselineRecorder.load(baseline_path)
    log_path = _resolve_log_path(base_dir, log_source)

    if not os.path.exists(log_path):
        _print({"error": f"Log file not found: {log_path}"}, json_mode=json_mode)
        return 1

    comparator = BaselineComparator(
        baseline=baseline,
        log_path=log_path,
        duration_s=duration_s,
        sigma_threshold=sigma_threshold,
    )
    comparator._baseline_path = baseline_path

    if not json_mode:
        print(
            f"Comparing {duration_s}s window against {baseline_path} "
            f"(σ threshold: {sigma_threshold})"
        )

    report = comparator.compare(device=device)
    _print(report.to_dict(), json_mode=json_mode)
    return 0 if report.passed else 1


def cmd_anomaly_watch(
    base_dir: str,
    metric_name: str,
    threshold_sigma: float,
    ewma_window: int,
    min_samples: int,
    duration_s: Optional[float],
    log_source: Optional[str],
    json_mode: bool,
) -> int:
    """
    Stream-watch a single metric with EWMA. Emits JSONL alerts.

    Returns 0 on clean exit (Ctrl-C or duration reached), 1 if metric not found.
    """
    from eab.anomaly.metric_extractor import METRIC_PATTERNS
    from eab.anomaly.anomaly_watcher import AnomalyWatcher

    if metric_name not in METRIC_PATTERNS:
        _print(
            {
                "error": f"Unknown metric: {metric_name!r}. "
                         f"Available: {sorted(METRIC_PATTERNS)}"
            },
            json_mode=json_mode,
        )
        return 1

    log_path = _resolve_log_path(base_dir, log_source)
    if not os.path.exists(log_path):
        _print({"error": f"Log file not found: {log_path}"}, json_mode=json_mode)
        return 1

    if not json_mode:
        print(
            f"Watching metric '{metric_name}' "
            f"(threshold={threshold_sigma}σ, window={ewma_window}, "
            f"cold-start={min_samples} samples)"
        )
        print(f"Cold-start: first {min_samples} samples collected without alerting")

    watcher = AnomalyWatcher(
        log_path=log_path,
        metric_name=metric_name,
        threshold_sigma=threshold_sigma,
        ewma_window=ewma_window,
        min_samples=min_samples,
        duration_s=duration_s,
    )

    try:
        watcher.watch()
        return 0
    except KeyboardInterrupt:
        return 0
