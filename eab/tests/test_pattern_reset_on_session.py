"""
Tests for pattern counter reset on fresh session start.

Ensures that pattern counters in PatternMatcher and StatusManager are reset
when a new session starts, preventing counts from persisting across sessions.
"""

import os
import sys
from datetime import datetime

import pytest

# Add parent directory to path for imports
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__)))))

from eab.pattern_matcher import PatternMatcher
from eab.status_manager import StatusManager
from eab.mocks import MockFileSystem, MockClock


class TestPatternMatcherResetCounts:
    """Tests for PatternMatcher.reset_counts()."""

    def test_reset_counts_clears_all_pattern_counts(self):
        """reset_counts() should reset all pattern counts to zero."""
        matcher = PatternMatcher(load_defaults=True)

        # Trigger some pattern matches
        matcher.check_line("ERROR: First error")
        matcher.check_line("ERROR: Second error")
        matcher.check_line("WATCHDOG: Task watchdog triggered")
        matcher.check_line("BOOT: rst:0x10 (SW_CPU_RESET)")

        # Verify counts are non-zero
        counts_before = matcher.get_counts()
        assert counts_before["ERROR"] >= 2
        assert counts_before["WATCHDOG"] >= 1
        assert counts_before["BOOT"] >= 1

        # Reset counts
        matcher.reset_counts()

        # Verify all counts are zero
        counts_after = matcher.get_counts()
        for pattern_name, count in counts_after.items():
            assert count == 0, f"Pattern '{pattern_name}' should be reset to 0, got {count}"

    def test_reset_counts_with_custom_patterns(self):
        """reset_counts() should work with custom patterns."""
        matcher = PatternMatcher()
        matcher.add_pattern("CUSTOM", "CUSTOM", is_regex=False)
        matcher.add_pattern("ANOTHER", "ANOTHER", is_regex=False)

        # Trigger matches
        matcher.check_line("CUSTOM error occurred")
        matcher.check_line("ANOTHER problem found")
        matcher.check_line("CUSTOM issue detected")

        # Verify counts
        counts_before = matcher.get_counts()
        assert counts_before["CUSTOM"] == 2
        assert counts_before["ANOTHER"] == 1

        # Reset
        matcher.reset_counts()

        # Verify reset
        counts_after = matcher.get_counts()
        assert counts_after["CUSTOM"] == 0
        assert counts_after["ANOTHER"] == 0

    def test_reset_counts_preserves_patterns(self):
        """reset_counts() should not remove patterns, only reset their counts."""
        matcher = PatternMatcher()
        matcher.add_pattern("ERROR", "ERROR")
        matcher.add_pattern("WARN", "WARN")

        # Check some lines
        matcher.check_line("ERROR: test")
        matcher.check_line("WARN: test")

        # Reset counts
        matcher.reset_counts()

        # Patterns should still exist
        patterns = matcher.get_patterns()
        assert "ERROR" in patterns
        assert "WARN" in patterns

        # Should still be able to match
        matches = matcher.check_line("ERROR: another test")
        assert len(matches) == 1
        assert matches[0].pattern == "ERROR"

        # Count should be 1 (not accumulated from before reset)
        counts = matcher.get_counts()
        assert counts["ERROR"] == 1

    def test_reset_counts_on_empty_matcher(self):
        """reset_counts() should work even with no patterns."""
        matcher = PatternMatcher()
        matcher.reset_counts()  # Should not raise

        counts = matcher.get_counts()
        assert counts == {}


class TestStatusManagerResetCounts:
    """Tests for StatusManager pattern count reset during start_session()."""

    def test_start_session_resets_pattern_counts(self, tmp_path):
        """start_session() should reset pattern_counts to empty dict."""
        import json
        
        fs = MockFileSystem()
        clock = MockClock(datetime(2025, 1, 1, 12, 0, 0))
        status_path = tmp_path / "status.json"
        status = StatusManager(
            filesystem=fs,
            clock=clock,
            status_path=str(status_path),
        )

        # Start first session and record some alerts
        status.start_session("session1", "/dev/ttyUSB0", 115200)
        status.record_alert("ERROR")
        status.record_alert("ERROR")
        status.record_alert("WATCHDOG")
        status.update()

        # Verify pattern counts are tracked
        status_data = json.loads(status_path.read_text(encoding="utf-8"))
        assert status_data["patterns"]["ERROR"] == 2
        assert status_data["patterns"]["WATCHDOG"] == 1

        # Start a new session
        status.start_session("session2", "/dev/ttyUSB0", 115200)
        status.update()

        # Verify pattern counts are reset
        status_data = json.loads(status_path.read_text(encoding="utf-8"))
        assert status_data["patterns"] == {}

    def test_start_session_resets_other_counters(self, tmp_path):
        """start_session() should reset all session-specific counters."""
        import json
        
        fs = MockFileSystem()
        clock = MockClock(datetime(2025, 1, 1, 12, 0, 0))
        status_path = tmp_path / "status.json"
        status = StatusManager(
            filesystem=fs,
            clock=clock,
            status_path=str(status_path),
        )

        # Start first session and generate activity
        status.start_session("session1", "/dev/ttyUSB0", 115200)
        status.record_line()
        status.record_line()
        status.record_bytes(100)
        status.record_command()
        status.record_alert("ERROR")
        status.update()

        # Verify counters
        status_data = json.loads(status_path.read_text(encoding="utf-8"))
        assert status_data["counters"]["lines_logged"] == 2
        assert status_data["counters"]["bytes_received"] == 100
        assert status_data["counters"]["commands_sent"] == 1
        assert status_data["counters"]["alerts_triggered"] == 1

        # Start new session
        status.start_session("session2", "/dev/ttyUSB0", 115200)
        status.update()

        # Verify all counters are reset
        status_data = json.loads(status_path.read_text(encoding="utf-8"))
        assert status_data["counters"]["lines_logged"] == 0
        assert status_data["counters"]["bytes_received"] == 0
        assert status_data["counters"]["commands_sent"] == 0
        assert status_data["counters"]["alerts_triggered"] == 0
        assert status_data["patterns"] == {}


class TestDaemonPatternResetIntegration:
    """Integration tests for daemon resetting pattern counts on session start."""

    def test_daemon_resets_pattern_counts_on_start(self, tmp_path, monkeypatch):
        """Daemon should call reset_counts() on PatternMatcher when starting a session."""
        import eab.daemon as daemon_mod
        from eab.mocks import MockSerialPort, MockClock, MockLogger
        import eab.port_lock

        # Isolate singleton and locks
        monkeypatch.setenv("EAB_RUN_DIR", str(tmp_path))
        monkeypatch.setattr(eab.port_lock.PortLock, "LOCK_DIR", str(tmp_path / "locks"))

        # Avoid external tooling
        monkeypatch.setattr(daemon_mod, "find_port_users", lambda _port: [])
        monkeypatch.setattr(daemon_mod, "list_all_locks", lambda: [])

        base_dir = tmp_path / "session"
        port_path = tmp_path / "fake_serial_port"
        port_path.write_text("", encoding="utf-8")

        serial = MockSerialPort()
        clock = MockClock()
        logger = MockLogger()

        daemon = daemon_mod.SerialDaemon(
            port=str(port_path),
            baud=115200,
            base_dir=str(base_dir),
            auto_detect=False,
            serial_port=serial,
            clock=clock,
            logger=logger,
        )

        # Simulate some pattern matches before starting
        daemon._pattern_matcher.check_line("ERROR: Pre-start error")
        daemon._pattern_matcher.check_line("BOOT: rst:0x10")

        # Verify counts before start
        counts_before = daemon._pattern_matcher.get_counts()
        assert counts_before["ERROR"] >= 1
        assert counts_before["BOOT"] >= 1

        # Start daemon (should reset counts)
        assert daemon.start(force=True) is True

        # Verify counts are reset after start
        counts_after = daemon._pattern_matcher.get_counts()
        for pattern_name, count in counts_after.items():
            assert count == 0, f"Pattern '{pattern_name}' should be reset to 0 after daemon start, got {count}"

    def test_daemon_pattern_counts_fresh_after_restart(self, tmp_path, monkeypatch):
        """Pattern counts should be fresh when daemon is stopped and restarted."""
        import eab.daemon as daemon_mod
        from eab.mocks import MockSerialPort, MockClock, MockLogger
        import eab.port_lock

        # Isolate singleton and locks
        monkeypatch.setenv("EAB_RUN_DIR", str(tmp_path))
        monkeypatch.setattr(eab.port_lock.PortLock, "LOCK_DIR", str(tmp_path / "locks"))

        # Avoid external tooling
        monkeypatch.setattr(daemon_mod, "find_port_users", lambda _port: [])
        monkeypatch.setattr(daemon_mod, "list_all_locks", lambda: [])

        base_dir = tmp_path / "session"
        port_path = tmp_path / "fake_serial_port"
        port_path.write_text("", encoding="utf-8")

        # First daemon instance
        serial1 = MockSerialPort()
        clock1 = MockClock()
        logger1 = MockLogger()

        daemon1 = daemon_mod.SerialDaemon(
            port=str(port_path),
            baud=115200,
            base_dir=str(base_dir),
            auto_detect=False,
            serial_port=serial1,
            clock=clock1,
            logger=logger1,
        )

        # Start first daemon and generate some pattern matches
        assert daemon1.start(force=True) is True
        daemon1._process_line("ERROR: First daemon error")
        daemon1._process_line("WATCHDOG: Task watchdog triggered")
        daemon1._process_line("ERROR: Another error")

        # Verify counts
        counts1 = daemon1._pattern_matcher.get_counts()
        assert counts1["ERROR"] >= 2
        assert counts1["WATCHDOG"] >= 1

        # Stop first daemon
        daemon1.stop()

        # Second daemon instance (simulating restart)
        serial2 = MockSerialPort()
        clock2 = MockClock()
        logger2 = MockLogger()

        daemon2 = daemon_mod.SerialDaemon(
            port=str(port_path),
            baud=115200,
            base_dir=str(base_dir),
            auto_detect=False,
            serial_port=serial2,
            clock=clock2,
            logger=logger2,
        )

        # Start second daemon
        assert daemon2.start(force=True) is True

        # Verify counts are fresh (all zero)
        counts2 = daemon2._pattern_matcher.get_counts()
        for pattern_name, count in counts2.items():
            assert count == 0, f"Pattern '{pattern_name}' should be 0 in fresh session, got {count}"

        # Process new lines
        daemon2._process_line("ERROR: Second daemon error")

        # Verify only new counts
        counts3 = daemon2._pattern_matcher.get_counts()
        assert counts3["ERROR"] >= 1  # Only the new error
        assert counts3["WATCHDOG"] == 0  # Should not have old watchdog count

        daemon2.stop()

    def test_status_json_patterns_empty_after_daemon_start(self, tmp_path, monkeypatch):
        """status.json patterns field should be empty after daemon start."""
        import eab.daemon as daemon_mod
        from eab.mocks import MockSerialPort, MockClock, MockLogger
        import eab.port_lock
        import json

        # Isolate singleton and locks
        monkeypatch.setenv("EAB_RUN_DIR", str(tmp_path))
        monkeypatch.setattr(eab.port_lock.PortLock, "LOCK_DIR", str(tmp_path / "locks"))

        # Avoid external tooling
        monkeypatch.setattr(daemon_mod, "find_port_users", lambda _port: [])
        monkeypatch.setattr(daemon_mod, "list_all_locks", lambda: [])

        base_dir = tmp_path / "session"
        port_path = tmp_path / "fake_serial_port"
        port_path.write_text("", encoding="utf-8")

        serial = MockSerialPort()
        clock = MockClock()
        logger = MockLogger()

        daemon = daemon_mod.SerialDaemon(
            port=str(port_path),
            baud=115200,
            base_dir=str(base_dir),
            auto_detect=False,
            serial_port=serial,
            clock=clock,
            logger=logger,
        )

        # Start daemon
        assert daemon.start(force=True) is True

        # Check status.json
        status_path = base_dir / "status.json"
        assert status_path.exists()

        status_data = json.loads(status_path.read_text(encoding="utf-8"))
        assert status_data["patterns"] == {}, "Patterns should be empty dict at session start"

        # Process some lines with patterns
        daemon._process_line("ERROR: Test error")
        daemon._process_line("BOOT: rst:0x10")
        daemon._status_manager.update()

        # Check status.json again
        status_data = json.loads(status_path.read_text(encoding="utf-8"))
        assert status_data["patterns"]["ERROR"] >= 1
        assert status_data["patterns"]["BOOT"] >= 1

        daemon.stop()
