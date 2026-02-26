"""Metric extractor: pattern matching over RTT log lines."""

from __future__ import annotations

import re
from dataclasses import dataclass
from typing import Dict, List, Optional

# Each entry is either:
#   ("numeric", pattern)     — extract the first capture group as float
#   ("occurrence", pattern)  — count occurrences (no numeric capture needed)
#
# Patterns are matched against raw RTT log lines (with optional timestamp prefix).

METRIC_PATTERNS: Dict[str, tuple] = {
    # BLE / connectivity
    "bt_notification_interval_ms": ("numeric",    r"[Ii]nterval[:\s]+(\d+(?:\.\d+)?)\s*ms"),
    "bt_notify_count":             ("numeric",    r"notify_count=(\d+)"),
    "bt_conn_interval_ms":         ("numeric",    r"[Cc]onn[ection]?\s+[Ii]nterval[:\s]+(\d+(?:\.\d+)?)"),
    "bt_mtu":                      ("numeric",    r"MTU\s+exchanged[:\s]+(\d+)"),
    "bt_rssi":                     ("numeric",    r"RSSI[:\s]+([-\d]+)"),
    "bt_backpressure":             ("occurrence", r"TX\s+buffer\s+full"),
    "bt_disconnect":               ("occurrence", r"[Dd]isconnected"),

    # Zephyr system health
    "zephyr_heap_free_bytes":      ("numeric",    r"heap_free=(\d+)"),
    "zephyr_heap_alloc_bytes":     ("numeric",    r"heap_alloc=(\d+)"),
    "zephyr_stack_unused_bytes":   ("numeric",    r"unused\s+stack[:\s]+(\d+)"),
    "zephyr_irq_latency_us":       ("numeric",    r"irq_latency[:\s]+(\d+(?:\.\d+)?)\s*us"),
    "zephyr_workq_latency_ms":     ("numeric",    r"workq_latency[:\s]+(\d+(?:\.\d+)?)\s*ms"),

    # Error / warning rate
    "log_error":                   ("occurrence", r"\bERR\b|\bERROR\b"),
    "log_warning":                 ("occurrence", r"\bWRN\b|\bWARN\b"),

    # RTT timestamp (extracts fractional seconds from [HH:MM:SS.mmm] prefix)
    "rtt_timestamp_s":             ("numeric",    r"^\[(\d+):(\d+):(\d+\.\d+)\]"),
}


@dataclass
class MetricSample:
    """A single extracted metric observation."""
    metric_name: str
    value: float          # numeric value, or 1.0 for occurrence patterns
    raw_line: str
    line_index: int       # 0-based line number in the source


class MetricExtractor:
    """
    Extract named numeric metrics and occurrence counts from RTT log lines.

    Args:
        patterns: Dict mapping metric_name -> (kind, regex_str).
                  Defaults to METRIC_PATTERNS.
        custom_patterns: Extra patterns merged with (or overriding) defaults.

    Usage:
        extractor = MetricExtractor()
        for line in log_lines:
            samples = extractor.extract_line(line, line_index=i)
        # or batch:
        all_samples = extractor.extract_text(full_log_text)
    """

    def __init__(
        self,
        patterns: Optional[Dict[str, tuple]] = None,
        custom_patterns: Optional[Dict[str, tuple]] = None,
    ) -> None:
        base = patterns if patterns is not None else METRIC_PATTERNS
        merged = {**base, **(custom_patterns or {})}
        self._compiled: Dict[str, tuple] = {
            name: (kind, re.compile(pat))
            for name, (kind, pat) in merged.items()
        }

    def extract_line(self, line: str, line_index: int = 0) -> List[MetricSample]:
        """
        Match all patterns against a single log line.

        Returns a list of MetricSample (empty if no patterns match).
        """
        results: List[MetricSample] = []
        for name, (kind, compiled) in self._compiled.items():
            m = compiled.search(line)
            if not m:
                continue
            if kind == "occurrence":
                value = 1.0
            elif name == "rtt_timestamp_s":
                # Special case: HH:MM:SS.mmm → float seconds
                h = float(m.group(1))
                mn = float(m.group(2))
                s = float(m.group(3))
                value = h * 3600 + mn * 60 + s
            else:
                try:
                    value = float(m.group(1))
                except (IndexError, ValueError):
                    continue
            results.append(MetricSample(
                metric_name=name,
                value=value,
                raw_line=line,
                line_index=line_index,
            ))
        return results

    def extract_lines(self, lines: List[str]) -> List[MetricSample]:
        """Batch extraction over a list of lines."""
        out: List[MetricSample] = []
        for i, line in enumerate(lines):
            out.extend(self.extract_line(line, line_index=i))
        return out

    def extract_text(self, text: str) -> List[MetricSample]:
        """Convenience: split text on newlines and extract."""
        return self.extract_lines(text.splitlines())

    def metric_names(self) -> List[str]:
        """Return list of all tracked metric names."""
        return list(self._compiled.keys())
