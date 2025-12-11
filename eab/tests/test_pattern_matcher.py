"""
Tests for pattern detection and alerts.

These tests define the expected pattern matching behavior BEFORE implementation.
"""

import pytest
from datetime import datetime
import sys
import os

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__)))))

from eab.mocks import MockFileSystem, MockClock


class TestPatternMatcher:
    """Tests for PatternMatcher class."""

    def test_add_string_pattern(self):
        """Should add a simple string pattern."""
        from eab.pattern_matcher import PatternMatcher

        matcher = PatternMatcher()
        matcher.add_pattern("ERROR", "ERROR")

        assert "ERROR" in matcher.get_patterns()

    def test_add_regex_pattern(self):
        """Should add a regex pattern."""
        from eab.pattern_matcher import PatternMatcher

        matcher = PatternMatcher()
        matcher.add_pattern("timeout", r"timeout|timed?\s*out", is_regex=True)

        matches = matcher.check_line("Connection timed out")
        assert len(matches) == 1
        assert matches[0].pattern == "timeout"

    def test_case_insensitive_by_default(self):
        """Should match case-insensitively by default."""
        from eab.pattern_matcher import PatternMatcher

        matcher = PatternMatcher()
        matcher.add_pattern("ERROR", "ERROR")

        matches = matcher.check_line("error: something went wrong")
        assert len(matches) == 1

        matches = matcher.check_line("Error: mixed case")
        assert len(matches) == 1

    def test_multiple_patterns_same_line(self):
        """Should detect multiple patterns in same line."""
        from eab.pattern_matcher import PatternMatcher

        matcher = PatternMatcher()
        matcher.add_pattern("ERROR", "ERROR")
        matcher.add_pattern("TIMEOUT", "TIMEOUT")

        matches = matcher.check_line("ERROR: Connection TIMEOUT")
        assert len(matches) == 2

    def test_pattern_counts(self):
        """Should track count per pattern."""
        from eab.pattern_matcher import PatternMatcher

        matcher = PatternMatcher()
        matcher.add_pattern("ERROR", "ERROR")
        matcher.add_pattern("WARN", "WARN")

        matcher.check_line("ERROR: First error")
        matcher.check_line("ERROR: Second error")
        matcher.check_line("WARN: A warning")
        matcher.check_line("ERROR: Third error")

        counts = matcher.get_counts()
        assert counts["ERROR"] == 3
        assert counts["WARN"] == 1

    def test_remove_pattern(self):
        """Should remove a pattern."""
        from eab.pattern_matcher import PatternMatcher

        matcher = PatternMatcher()
        matcher.add_pattern("ERROR", "ERROR")
        matcher.add_pattern("WARN", "WARN")

        matcher.remove_pattern("ERROR")

        matches = matcher.check_line("ERROR and WARN")
        assert len(matches) == 1
        assert matches[0].pattern == "WARN"

    def test_no_match_returns_empty(self):
        """Should return empty list when no patterns match."""
        from eab.pattern_matcher import PatternMatcher

        matcher = PatternMatcher()
        matcher.add_pattern("ERROR", "ERROR")

        matches = matcher.check_line("Everything is fine")
        assert len(matches) == 0

    def test_match_includes_timestamp(self):
        """Match results should include timestamp."""
        from eab.pattern_matcher import PatternMatcher

        clock = MockClock(datetime(2025, 12, 11, 1, 30, 0))
        matcher = PatternMatcher(clock=clock)
        matcher.add_pattern("ERROR", "ERROR")

        matches = matcher.check_line("ERROR: Something bad")
        assert matches[0].timestamp == datetime(2025, 12, 11, 1, 30, 0)

    def test_match_includes_line(self):
        """Match results should include the original line."""
        from eab.pattern_matcher import PatternMatcher

        matcher = PatternMatcher()
        matcher.add_pattern("ERROR", "ERROR")

        line = "E (12345) BLE: ERROR during connection"
        matches = matcher.check_line(line)
        assert matches[0].line == line


class TestBuiltInPatterns:
    """Tests for built-in alert patterns."""

    def test_default_patterns_loaded(self):
        """Should load default patterns on creation."""
        from eab.pattern_matcher import PatternMatcher

        matcher = PatternMatcher(load_defaults=True)
        patterns = matcher.get_patterns()

        assert "ERROR" in patterns
        assert "FAIL" in patterns
        assert "DISCONNECT" in patterns
        assert "TIMEOUT" in patterns
        assert "CRASH" in patterns
        assert "panic" in patterns
        assert "assert" in patterns

    def test_esp32_error_format(self):
        """Should detect ESP32 error format: E (timestamp) TAG: message."""
        from eab.pattern_matcher import PatternMatcher

        matcher = PatternMatcher(load_defaults=True)

        matches = matcher.check_line("E (45890) BLE: Connection failed")
        assert len(matches) >= 1

    def test_esp32_assert_failure(self):
        """Should detect ESP32 assert failures."""
        from eab.pattern_matcher import PatternMatcher

        matcher = PatternMatcher(load_defaults=True)

        matches = matcher.check_line("assert failed: xQueueSemaphoreTake queue.c:1545")
        assert len(matches) >= 1

    def test_esp32_panic(self):
        """Should detect ESP32 panic messages."""
        from eab.pattern_matcher import PatternMatcher

        matcher = PatternMatcher(load_defaults=True)

        matches = matcher.check_line("Guru Meditation Error: Core  0 panic'ed (LoadProhibited)")
        assert len(matches) >= 1


class TestAlertLogger:
    """Tests for AlertLogger that writes alerts to separate file."""

    def test_writes_alert_to_file(self):
        """Should write alert to alerts file."""
        from eab.pattern_matcher import PatternMatcher, AlertLogger

        fs = MockFileSystem()
        clock = MockClock(datetime(2025, 12, 11, 1, 30, 0))

        matcher = PatternMatcher(clock=clock, load_defaults=True)
        alert_logger = AlertLogger(
            filesystem=fs,
            clock=clock,
            alerts_path="/var/run/eab/serial/alerts.log"
        )

        matches = matcher.check_line("ERROR: Connection failed")
        for match in matches:
            alert_logger.log_alert(match)

        content = fs.read_file("/var/run/eab/serial/alerts.log")
        assert "ERROR" in content
        assert "Connection failed" in content

    def test_alert_format(self):
        """Alert format should be: [timestamp] [PATTERN] line."""
        from eab.pattern_matcher import PatternMatcher, AlertLogger

        fs = MockFileSystem()
        clock = MockClock(datetime(2025, 12, 11, 1, 30, 45, 123000))

        matcher = PatternMatcher(clock=clock)
        matcher.add_pattern("ERROR", "ERROR")

        alert_logger = AlertLogger(
            filesystem=fs,
            clock=clock,
            alerts_path="/var/run/eab/serial/alerts.log"
        )

        matches = matcher.check_line("ERROR: Test error")
        alert_logger.log_alert(matches[0])

        content = fs.read_file("/var/run/eab/serial/alerts.log")
        assert "[01:30:45.123]" in content
        assert "[ERROR]" in content
        assert "ERROR: Test error" in content

    def test_multiple_alerts_appended(self):
        """Multiple alerts should be appended to file."""
        from eab.pattern_matcher import PatternMatcher, AlertLogger

        fs = MockFileSystem()
        clock = MockClock(datetime(2025, 12, 11, 1, 30, 0))

        matcher = PatternMatcher(clock=clock, load_defaults=True)
        alert_logger = AlertLogger(
            filesystem=fs,
            clock=clock,
            alerts_path="/var/run/eab/serial/alerts.log"
        )

        for i, line in enumerate([
            "ERROR: First error",
            "TIMEOUT: Connection timeout",
            "CRASH: System crash"
        ]):
            clock.advance(1)
            matches = matcher.check_line(line)
            for match in matches:
                alert_logger.log_alert(match)

        content = fs.read_file("/var/run/eab/serial/alerts.log")
        assert "First error" in content
        assert "Connection timeout" in content
        assert "System crash" in content

    def test_alert_count(self):
        """Should track total number of alerts."""
        from eab.pattern_matcher import PatternMatcher, AlertLogger

        fs = MockFileSystem()
        clock = MockClock(datetime(2025, 12, 11, 1, 30, 0))

        matcher = PatternMatcher(clock=clock, load_defaults=True)
        alert_logger = AlertLogger(
            filesystem=fs,
            clock=clock,
            alerts_path="/var/run/eab/serial/alerts.log"
        )

        for line in ["ERROR: 1", "ERROR: 2", "TIMEOUT: 1"]:
            matches = matcher.check_line(line)
            for match in matches:
                alert_logger.log_alert(match)

        assert alert_logger.alert_count == 3
