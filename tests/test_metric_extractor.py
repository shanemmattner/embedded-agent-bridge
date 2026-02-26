"""Tests for MetricExtractor and METRIC_PATTERNS."""

import pytest
from eab.anomaly.metric_extractor import MetricExtractor, METRIC_PATTERNS, MetricSample

SYNTHETIC_LINES = [
    "[00:00:10.123] BT/CONN: Interval: 100 ms",
    "[00:00:10.456] BT/CONN: Interval: 99 ms",
    "[00:00:11.000] BT/ATT: notify_count=42",
    "[00:00:11.500] kernel: heap_free=8192",
    "[00:00:12.000] BT/HCI: TX buffer full",
    "[00:00:12.001] BT/HCI: TX buffer full",
    "[00:00:13.000] BT/ATT: MTU exchanged: 247",
    "[00:00:14.000] ERR: something failed",
    "[00:00:15.000] some unrelated line",
]


class TestMetricExtractor:
    def test_numeric_extraction(self):
        ext = MetricExtractor()
        samples = ext.extract_lines(SYNTHETIC_LINES)
        interval_vals = [s.value for s in samples if s.metric_name == "bt_notification_interval_ms"]
        assert interval_vals == [100.0, 99.0]

    def test_occurrence_extraction(self):
        ext = MetricExtractor()
        samples = ext.extract_lines(SYNTHETIC_LINES)
        bp = [s for s in samples if s.metric_name == "bt_backpressure"]
        assert len(bp) == 2
        assert all(s.value == 1.0 for s in bp)

    def test_no_match_returns_empty(self):
        ext = MetricExtractor()
        assert ext.extract_line("no patterns here at all") == []

    def test_custom_patterns_override(self):
        custom = {"my_counter": ("numeric", r"counter=(\d+)")}
        ext = MetricExtractor(custom_patterns=custom)
        samples = ext.extract_line("counter=99")
        assert len(samples) == 1
        assert samples[0].metric_name == "my_counter"
        assert samples[0].value == 99.0

    def test_rtt_timestamp_extraction(self):
        ext = MetricExtractor()
        # [01:02:03.456] → 1*3600 + 2*60 + 3.456 = 3723.456
        samples = ext.extract_line("[01:02:03.456] anything")
        ts_vals = [s.value for s in samples if s.metric_name == "rtt_timestamp_s"]
        assert ts_vals == pytest.approx([3723.456], abs=0.001)

    def test_float_value(self):
        ext = MetricExtractor()
        samples = ext.extract_line("[00:00:01.000] irq_latency: 12.5 us")
        irq_vals = [s.value for s in samples if s.metric_name == "zephyr_irq_latency_us"]
        assert irq_vals == pytest.approx([12.5])

    def test_metric_names_returns_all(self):
        ext = MetricExtractor()
        names = ext.metric_names()
        assert "bt_notification_interval_ms" in names
        assert "bt_backpressure" in names
        assert len(names) == len(METRIC_PATTERNS)

    def test_extract_text(self):
        ext = MetricExtractor()
        text = "\n".join(SYNTHETIC_LINES)
        samples = ext.extract_text(text)
        assert len(samples) > 0

    def test_metric_sample_fields(self):
        ext = MetricExtractor()
        samples = ext.extract_line("[00:00:10.123] BT/CONN: Interval: 100 ms", line_index=5)
        interval = [s for s in samples if s.metric_name == "bt_notification_interval_ms"]
        assert len(interval) == 1
        assert interval[0].line_index == 5
        assert "100" in interval[0].raw_line

    def test_custom_patterns_only(self):
        """Using patterns= kwarg replaces defaults entirely."""
        custom = {"my_metric": ("numeric", r"val=(\d+)")}
        ext = MetricExtractor(patterns=custom)
        assert ext.metric_names() == ["my_metric"]
        samples = ext.extract_line("val=42")
        assert samples[0].value == 42.0

    def test_occurrence_value_is_one(self):
        ext = MetricExtractor()
        samples = ext.extract_line("Disconnected from peer")
        disc = [s for s in samples if s.metric_name == "bt_disconnect"]
        assert len(disc) == 1
        assert disc[0].value == 1.0

    def test_error_log_detection(self):
        ext = MetricExtractor()
        samples = ext.extract_line("[00:00:01.000] ERR: fault occurred")
        errors = [s for s in samples if s.metric_name == "log_error"]
        assert len(errors) >= 1

    def test_warning_log_detection(self):
        ext = MetricExtractor()
        samples = ext.extract_line("[00:00:01.000] WRN: something unusual")
        warnings = [s for s in samples if s.metric_name == "log_warning"]
        assert len(warnings) >= 1
