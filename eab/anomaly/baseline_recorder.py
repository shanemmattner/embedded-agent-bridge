"""Baseline recorder: tail a device log file and compute metric statistics."""

from __future__ import annotations

import json
import os
import statistics
import time
from collections import defaultdict
from dataclasses import dataclass, field
from datetime import datetime, timezone
from typing import Callable, Dict, List, Optional

from eab.anomaly.metric_extractor import MetricExtractor


def _get_file_size(path: str) -> int:
    """Return current file size in bytes, or 0 if file does not exist."""
    try:
        return os.path.getsize(path)
    except OSError:
        return 0


def _read_new_lines(path: str, offset: int) -> tuple:
    """
    Read new lines from a file starting at offset.

    Handles log rotation: if the file is smaller than offset (rotated),
    starts from the beginning.

    Returns:
        (list[str], new_offset_int)
    """
    try:
        stat = os.stat(path)
        current_size = stat.st_size
    except OSError:
        return [], offset

    # Handle log rotation: file shrunk → start over
    if current_size < offset:
        offset = 0

    if current_size == offset:
        return [], offset

    try:
        with open(path, "rb") as f:
            f.seek(offset)
            raw = f.read()
        new_offset = offset + len(raw)
        text = raw.decode("utf-8", errors="replace")
        lines = text.splitlines()
        return lines, new_offset
    except OSError:
        return [], offset


@dataclass
class MetricStats:
    """Statistics for a single metric over a recording window."""
    kind: str                           # "numeric" or "occurrence"
    count: int
    mean: float                         # 0.0 for occurrence (use rate_per_min)
    std: float
    min: float
    max: float
    p50: Optional[float]
    p95: Optional[float]
    p99: Optional[float]
    rate_per_min: float

    def to_dict(self) -> dict:
        d = {
            "kind": self.kind,
            "count": self.count,
            "rate_per_min": self.rate_per_min,
        }
        if self.kind == "numeric":
            d.update({
                "mean": self.mean,
                "std": self.std,
                "min": self.min,
                "max": self.max,
            })
            if self.p50 is not None:
                d["p50"] = self.p50
            if self.p95 is not None:
                d["p95"] = self.p95
            if self.p99 is not None:
                d["p99"] = self.p99
        return d

    @classmethod
    def from_dict(cls, d: dict) -> "MetricStats":
        return cls(
            kind=d.get("kind", "numeric"),
            count=d.get("count", 0),
            mean=d.get("mean", 0.0),
            std=d.get("std", 0.0),
            min=d.get("min", 0.0),
            max=d.get("max", 0.0),
            p50=d.get("p50"),
            p95=d.get("p95"),
            p99=d.get("p99"),
            rate_per_min=d.get("rate_per_min", 0.0),
        )


@dataclass
class BaselineData:
    """A recorded baseline with metric statistics."""
    version: str = "1"
    device: str = ""
    log_source: str = ""
    recorded_at: str = ""               # ISO-8601 UTC
    duration_s: float = 0.0
    total_lines_scanned: int = 0
    metrics: Dict[str, MetricStats] = field(default_factory=dict)

    def to_dict(self) -> dict:
        return {
            "version": self.version,
            "device": self.device,
            "log_source": self.log_source,
            "recorded_at": self.recorded_at,
            "duration_s": self.duration_s,
            "total_lines_scanned": self.total_lines_scanned,
            "metrics": {
                name: stats.to_dict()
                for name, stats in self.metrics.items()
            },
        }

    @classmethod
    def from_dict(cls, d: dict) -> "BaselineData":
        metrics = {
            name: MetricStats.from_dict(v)
            for name, v in d.get("metrics", {}).items()
        }
        return cls(
            version=d.get("version", "1"),
            device=d.get("device", ""),
            log_source=d.get("log_source", ""),
            recorded_at=d.get("recorded_at", ""),
            duration_s=d.get("duration_s", 0.0),
            total_lines_scanned=d.get("total_lines_scanned", 0),
            metrics=metrics,
        )


class BaselineRecorder:
    """
    Tail a device log file for a fixed duration and compute metric statistics.

    Args:
        log_path: Path to the log file (e.g. /tmp/eab-devices/X/latest.log).
                  The recorder seeks to the current file end before starting,
                  so only lines written during the recording window are included.
        duration_s: How long to record (seconds).
        extractor: MetricExtractor instance. Defaults to MetricExtractor().
        poll_interval_s: How often to read new log lines (default 0.1 s).

    Usage:
        rec = BaselineRecorder(log_path="/tmp/eab-devices/nrf/latest.log",
                               duration_s=60)
        baseline = rec.record()          # blocks for duration_s seconds
        rec.save(baseline, "baselines/foo.json")
    """

    def __init__(
        self,
        log_path: str,
        duration_s: float,
        extractor: Optional[MetricExtractor] = None,
        poll_interval_s: float = 0.1,
    ) -> None:
        self.log_path = log_path
        self.duration_s = duration_s
        self.extractor = extractor or MetricExtractor()
        self.poll_interval_s = poll_interval_s

    def record(
        self,
        device: str = "",
        progress_cb: Optional[Callable[[float], None]] = None,
    ) -> BaselineData:
        """
        Block for self.duration_s seconds, tail the log, extract metrics.

        Args:
            device: Device name stored in baseline metadata.
            progress_cb: Optional callback(elapsed_s) called each poll cycle.

        Returns:
            BaselineData — call .to_dict() to get the JSON-serializable form.
        """
        # Seek to end of log file before recording
        start_offset = _get_file_size(self.log_path)

        bucket: Dict[str, List[float]] = defaultdict(list)   # metric → [values]
        occ_counts: Dict[str, int] = defaultdict(int)         # occurrence metrics
        total_lines = 0

        t_start = time.monotonic()
        t_end = t_start + self.duration_s

        while time.monotonic() < t_end:
            time.sleep(self.poll_interval_s)
            new_lines, start_offset = _read_new_lines(self.log_path, start_offset)
            total_lines += len(new_lines)
            for line in new_lines:
                for sample in self.extractor.extract_line(line):
                    kind = self.extractor._compiled[sample.metric_name][0]
                    if kind == "occurrence":
                        occ_counts[sample.metric_name] += 1
                    else:
                        bucket[sample.metric_name].append(sample.value)
            if progress_cb:
                progress_cb(time.monotonic() - t_start)

        # Build MetricStats
        metrics: Dict[str, MetricStats] = {}
        for name in self.extractor.metric_names():
            kind = self.extractor._compiled[name][0]
            if kind == "occurrence":
                cnt = occ_counts.get(name, 0)
                metrics[name] = MetricStats(
                    kind="occurrence", count=cnt,
                    mean=0.0, std=0.0, min=0.0, max=0.0,
                    p50=None, p95=None, p99=None,
                    rate_per_min=cnt / (self.duration_s / 60.0) if self.duration_s > 0 else 0.0,
                )
            else:
                vals = bucket.get(name, [])
                cnt = len(vals)
                if cnt == 0:
                    metrics[name] = MetricStats(
                        kind="numeric", count=0,
                        mean=0.0, std=0.0, min=0.0, max=0.0,
                        p50=None, p95=None, p99=None, rate_per_min=0.0,
                    )
                elif cnt == 1:
                    metrics[name] = MetricStats(
                        kind="numeric", count=1,
                        mean=vals[0], std=0.0, min=vals[0], max=vals[0],
                        p50=vals[0], p95=vals[0], p99=vals[0],
                        rate_per_min=1.0 / (self.duration_s / 60.0) if self.duration_s > 0 else 0.0,
                    )
                else:
                    mean = statistics.mean(vals)
                    std = statistics.stdev(vals)   # Bessel-corrected
                    # Use statistics.quantiles (Python 3.8+)
                    qs = statistics.quantiles(vals, n=100, method="inclusive")
                    metrics[name] = MetricStats(
                        kind="numeric", count=cnt,
                        mean=mean, std=std,
                        min=min(vals), max=max(vals),
                        p50=qs[49], p95=qs[94], p99=qs[98],
                        rate_per_min=cnt / (self.duration_s / 60.0) if self.duration_s > 0 else 0.0,
                    )

        return BaselineData(
            version="1",
            device=device,
            log_source=self.log_path,
            recorded_at=datetime.now(timezone.utc).isoformat(),
            duration_s=self.duration_s,
            total_lines_scanned=total_lines,
            metrics=metrics,
        )

    @staticmethod
    def save(baseline: BaselineData, output_path: str) -> None:
        """
        Write baseline to a JSON file (creates parent dirs if needed).
        """
        os.makedirs(os.path.dirname(os.path.abspath(output_path)), exist_ok=True)
        with open(output_path, "w", encoding="utf-8") as f:
            json.dump(baseline.to_dict(), f, indent=2)

    @staticmethod
    def load(path: str) -> BaselineData:
        """
        Load and validate a baseline JSON file.

        Raises:
            FileNotFoundError: path does not exist.
            ValueError: JSON structure does not match expected schema version.
        """
        if not os.path.exists(path):
            raise FileNotFoundError(f"Baseline file not found: {path}")
        with open(path, "r", encoding="utf-8") as f:
            d = json.load(f)
        version = d.get("version", "")
        if version != "1":
            raise ValueError(
                f"Unsupported baseline schema version: {version!r}. "
                f"Expected '1'."
            )
        return BaselineData.from_dict(d)
