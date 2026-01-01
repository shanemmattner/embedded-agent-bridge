"""
Tests for status.json manager.

The status manager writes connection state and statistics to a JSON file
that agents can read to understand daemon state.
"""

import pytest
from datetime import datetime
import json
import sys
import os

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__)))))

from eab.mocks import MockFileSystem, MockClock
from eab.interfaces import ConnectionState


class TestStatusManager:
    """Tests for StatusManager class."""

    def test_creates_status_file(self):
        """Should create status.json file."""
        from eab.status_manager import StatusManager

        fs = MockFileSystem()
        clock = MockClock(datetime(2025, 12, 11, 1, 30, 0))

        manager = StatusManager(
            filesystem=fs,
            clock=clock,
            status_path="/var/run/eab/serial/status.json"
        )

        manager.start_session("session_123", "/dev/ttyUSB0", 115200)

        assert fs.file_exists("/var/run/eab/serial/status.json")

    def test_status_json_structure(self):
        """Status JSON should have expected structure."""
        from eab.status_manager import StatusManager

        fs = MockFileSystem()
        clock = MockClock(datetime(2025, 12, 11, 1, 30, 0))

        manager = StatusManager(
            filesystem=fs,
            clock=clock,
            status_path="/var/run/eab/serial/status.json"
        )

        manager.start_session("session_123", "/dev/ttyUSB0", 115200)

        content = fs.read_file("/var/run/eab/serial/status.json")
        status = json.loads(content)

        assert "session" in status
        assert "connection" in status
        assert "counters" in status
        assert "patterns" in status
        assert "stream" in status
        assert "last_updated" in status

    def test_session_info(self):
        """Session info should include id, started, uptime."""
        from eab.status_manager import StatusManager

        fs = MockFileSystem()
        clock = MockClock(datetime(2025, 12, 11, 1, 30, 0))

        manager = StatusManager(
            filesystem=fs,
            clock=clock,
            status_path="/var/run/eab/serial/status.json"
        )

        manager.start_session("serial_2025-12-11_01-30-00", "/dev/ttyUSB0", 115200)

        content = fs.read_file("/var/run/eab/serial/status.json")
        status = json.loads(content)

        assert status["session"]["id"] == "serial_2025-12-11_01-30-00"
        assert "2025-12-11" in status["session"]["started"]
        assert status["session"]["uptime_seconds"] == 0

    def test_uptime_updates(self):
        """Uptime should increase with time."""
        from eab.status_manager import StatusManager

        fs = MockFileSystem()
        clock = MockClock(datetime(2025, 12, 11, 1, 30, 0))

        manager = StatusManager(
            filesystem=fs,
            clock=clock,
            status_path="/var/run/eab/serial/status.json"
        )

        manager.start_session("session_123", "/dev/ttyUSB0", 115200)

        clock.advance(3600)  # 1 hour
        manager.update()

        content = fs.read_file("/var/run/eab/serial/status.json")
        status = json.loads(content)

        assert status["session"]["uptime_seconds"] == 3600

    def test_connection_info(self):
        """Connection info should include port, baud, status."""
        from eab.status_manager import StatusManager

        fs = MockFileSystem()
        clock = MockClock(datetime(2025, 12, 11, 1, 30, 0))

        manager = StatusManager(
            filesystem=fs,
            clock=clock,
            status_path="/var/run/eab/serial/status.json"
        )

        manager.start_session("session_123", "/dev/ttyUSB0", 115200)
        manager.set_connection_state(ConnectionState.CONNECTED)

        content = fs.read_file("/var/run/eab/serial/status.json")
        status = json.loads(content)

        assert status["connection"]["port"] == "/dev/ttyUSB0"
        assert status["connection"]["baud"] == 115200
        assert status["connection"]["status"] == "connected"

    def test_reconnect_count(self):
        """Should track reconnection count."""
        from eab.status_manager import StatusManager

        fs = MockFileSystem()
        clock = MockClock(datetime(2025, 12, 11, 1, 30, 0))

        manager = StatusManager(
            filesystem=fs,
            clock=clock,
            status_path="/var/run/eab/serial/status.json"
        )

        manager.start_session("session_123", "/dev/ttyUSB0", 115200)
        manager.record_reconnect()
        manager.record_reconnect()

        content = fs.read_file("/var/run/eab/serial/status.json")
        status = json.loads(content)

        assert status["connection"]["reconnects"] == 2

    def test_counters(self):
        """Should track lines, bytes, commands, alerts."""
        from eab.status_manager import StatusManager

        fs = MockFileSystem()
        clock = MockClock(datetime(2025, 12, 11, 1, 30, 0))

        manager = StatusManager(
            filesystem=fs,
            clock=clock,
            status_path="/var/run/eab/serial/status.json"
        )

        manager.start_session("session_123", "/dev/ttyUSB0", 115200)

        for _ in range(100):
            manager.record_line()
        manager.record_bytes(5000)
        manager.record_command()
        manager.record_command()
        manager.record_alert("ERROR")
        manager.record_alert("TIMEOUT")
        manager.record_alert("ERROR")
        manager.update()  # Flush to file

        content = fs.read_file("/var/run/eab/serial/status.json")
        status = json.loads(content)

        assert status["counters"]["lines_logged"] == 100
        assert status["counters"]["bytes_received"] == 5000
        assert status["counters"]["commands_sent"] == 2
        assert status["counters"]["alerts_triggered"] == 3

    def test_pattern_counts(self):
        """Should track per-pattern alert counts."""
        from eab.status_manager import StatusManager

        fs = MockFileSystem()
        clock = MockClock(datetime(2025, 12, 11, 1, 30, 0))

        manager = StatusManager(
            filesystem=fs,
            clock=clock,
            status_path="/var/run/eab/serial/status.json"
        )

        manager.start_session("session_123", "/dev/ttyUSB0", 115200)

        manager.record_alert("ERROR")
        manager.record_alert("ERROR")
        manager.record_alert("TIMEOUT")
        manager.update()  # Flush to file

        content = fs.read_file("/var/run/eab/serial/status.json")
        status = json.loads(content)

        assert status["patterns"]["ERROR"] == 2
        assert status["patterns"]["TIMEOUT"] == 1

    def test_last_updated_timestamp(self):
        """Should update last_updated on every write."""
        from eab.status_manager import StatusManager

        fs = MockFileSystem()
        clock = MockClock(datetime(2025, 12, 11, 1, 30, 0))

        manager = StatusManager(
            filesystem=fs,
            clock=clock,
            status_path="/var/run/eab/serial/status.json"
        )

        manager.start_session("session_123", "/dev/ttyUSB0", 115200)

        clock.advance(60)
        manager.update()

        content = fs.read_file("/var/run/eab/serial/status.json")
        status = json.loads(content)

        assert "01:31:00" in status["last_updated"]

    def test_valid_json(self):
        """Status file should always be valid JSON."""
        from eab.status_manager import StatusManager

        fs = MockFileSystem()
        clock = MockClock(datetime(2025, 12, 11, 1, 30, 0))

        manager = StatusManager(
            filesystem=fs,
            clock=clock,
            status_path="/var/run/eab/serial/status.json"
        )

        manager.start_session("session_123", "/dev/ttyUSB0", 115200)

        # Do many updates
        for i in range(100):
            manager.record_line()
            manager.record_bytes(100)
            if i % 10 == 0:
                manager.record_alert("ERROR")
            manager.update()

        # Should still be valid JSON
        content = fs.read_file("/var/run/eab/serial/status.json")
        status = json.loads(content)  # Should not raise
        assert status is not None
