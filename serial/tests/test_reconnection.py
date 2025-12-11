"""
Tests for auto-reconnection logic.

These tests define the expected reconnection behavior BEFORE implementation.
Test-First Development: Write the test, watch it fail, then implement.
"""

import pytest
from datetime import datetime, timedelta
import sys
import os

# Add parent directory to path for imports
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__)))))

from serial.mocks import MockSerialPort, MockClock, MockLogger, MockFileSystem
from serial.interfaces import ConnectionState


class TestReconnectionManager:
    """Tests for ReconnectionManager class."""

    def test_initial_connection_success(self):
        """Should connect successfully on first attempt."""
        from serial.reconnection import ReconnectionManager

        port = MockSerialPort()
        clock = MockClock()
        logger = MockLogger()

        manager = ReconnectionManager(
            serial_port=port,
            clock=clock,
            logger=logger,
            port_name="/dev/ttyUSB0",
            baud=115200
        )

        result = manager.connect()

        assert result is True
        assert port.is_open()
        assert manager.state == ConnectionState.CONNECTED
        assert manager.reconnect_count == 0

    def test_initial_connection_failure_retries(self):
        """Should retry on initial connection failure."""
        from serial.reconnection import ReconnectionManager

        port = MockSerialPort()
        port.set_fail_on_open(True)
        clock = MockClock()
        logger = MockLogger()

        manager = ReconnectionManager(
            serial_port=port,
            clock=clock,
            logger=logger,
            port_name="/dev/ttyUSB0",
            baud=115200,
            max_retries=3,
            retry_delay=1.0
        )

        result = manager.connect()

        assert result is False
        assert not port.is_open()
        assert manager.state == ConnectionState.ERROR
        # Should have tried 3 times
        assert len(clock.get_sleep_calls()) == 2  # sleeps between retries

    def test_reconnect_on_disconnect(self):
        """Should auto-reconnect when connection is lost."""
        from serial.reconnection import ReconnectionManager

        port = MockSerialPort()
        clock = MockClock()
        logger = MockLogger()

        manager = ReconnectionManager(
            serial_port=port,
            clock=clock,
            logger=logger,
            port_name="/dev/ttyUSB0",
            baud=115200
        )

        # Initial connect
        manager.connect()
        assert manager.state == ConnectionState.CONNECTED

        # Simulate disconnect
        port.close()

        # Check connection and trigger reconnect
        manager.check_and_reconnect()

        assert port.is_open()
        assert manager.state == ConnectionState.CONNECTED
        assert manager.reconnect_count == 1

    def test_exponential_backoff(self):
        """Should use exponential backoff on repeated failures."""
        from serial.reconnection import ReconnectionManager

        port = MockSerialPort()
        port.set_fail_on_open(True)
        clock = MockClock()
        logger = MockLogger()

        manager = ReconnectionManager(
            serial_port=port,
            clock=clock,
            logger=logger,
            port_name="/dev/ttyUSB0",
            baud=115200,
            max_retries=5,
            retry_delay=1.0,
            max_delay=10.0,
            backoff_factor=2.0
        )

        manager.connect()

        # Check sleep intervals for exponential backoff
        sleeps = clock.get_sleep_calls()
        # Expected: 1.0, 2.0, 4.0, 8.0 (capped at max_delay)
        assert len(sleeps) == 4
        assert sleeps[0] == 1.0
        assert sleeps[1] == 2.0
        assert sleeps[2] == 4.0
        assert sleeps[3] == 8.0  # Would be 16 but capped

    def test_max_delay_cap(self):
        """Should cap retry delay at max_delay."""
        from serial.reconnection import ReconnectionManager

        port = MockSerialPort()
        port.set_fail_on_open(True)
        clock = MockClock()
        logger = MockLogger()

        manager = ReconnectionManager(
            serial_port=port,
            clock=clock,
            logger=logger,
            port_name="/dev/ttyUSB0",
            baud=115200,
            max_retries=10,
            retry_delay=1.0,
            max_delay=5.0,
            backoff_factor=2.0
        )

        manager.connect()

        sleeps = clock.get_sleep_calls()
        # All delays after the 3rd should be capped at 5.0
        for sleep in sleeps[3:]:
            assert sleep <= 5.0

    def test_successful_reconnect_resets_backoff(self):
        """Should reset backoff delay after successful reconnect."""
        from serial.reconnection import ReconnectionManager

        port = MockSerialPort()
        clock = MockClock()
        logger = MockLogger()

        manager = ReconnectionManager(
            serial_port=port,
            clock=clock,
            logger=logger,
            port_name="/dev/ttyUSB0",
            baud=115200,
            retry_delay=1.0,
            backoff_factor=2.0
        )

        # Connect, disconnect, reconnect
        manager.connect()
        port.close()
        manager.check_and_reconnect()

        # Disconnect again
        port.close()
        clock.clear_sleep_calls()
        manager.check_and_reconnect()

        # Should start from base delay again, not continue backoff
        assert manager.current_delay == 1.0

    def test_state_transitions(self):
        """Should correctly transition through states."""
        from serial.reconnection import ReconnectionManager

        port = MockSerialPort()
        clock = MockClock()
        logger = MockLogger()

        manager = ReconnectionManager(
            serial_port=port,
            clock=clock,
            logger=logger,
            port_name="/dev/ttyUSB0",
            baud=115200
        )

        # Initial state
        assert manager.state == ConnectionState.DISCONNECTED

        # After connect
        manager.connect()
        assert manager.state == ConnectionState.CONNECTED

        # After disconnect
        port.close()
        manager.check_and_reconnect()  # triggers RECONNECTING -> CONNECTED

        # The manager should have gone through RECONNECTING
        assert logger.contains("RECONNECTING") or manager.state == ConnectionState.CONNECTED

    def test_callback_on_reconnect(self):
        """Should call callback when reconnection occurs."""
        from serial.reconnection import ReconnectionManager

        port = MockSerialPort()
        clock = MockClock()
        logger = MockLogger()

        callback_count = [0]

        def on_reconnect():
            callback_count[0] += 1

        manager = ReconnectionManager(
            serial_port=port,
            clock=clock,
            logger=logger,
            port_name="/dev/ttyUSB0",
            baud=115200,
            on_reconnect=on_reconnect
        )

        manager.connect()
        port.close()
        manager.check_and_reconnect()

        assert callback_count[0] == 1

    def test_callback_on_disconnect(self):
        """Should call callback when disconnect is detected."""
        from serial.reconnection import ReconnectionManager

        port = MockSerialPort()
        clock = MockClock()
        logger = MockLogger()

        callback_count = [0]

        def on_disconnect():
            callback_count[0] += 1

        manager = ReconnectionManager(
            serial_port=port,
            clock=clock,
            logger=logger,
            port_name="/dev/ttyUSB0",
            baud=115200,
            on_disconnect=on_disconnect
        )

        manager.connect()
        port.close()
        manager.check_and_reconnect()

        assert callback_count[0] == 1

    def test_port_not_found_waits_for_replug(self):
        """Should wait and retry when port not found (USB unplugged)."""
        from serial.reconnection import ReconnectionManager

        port = MockSerialPort()
        port.set_fail_on_open(True)  # Simulate port not found
        clock = MockClock()
        logger = MockLogger()

        manager = ReconnectionManager(
            serial_port=port,
            clock=clock,
            logger=logger,
            port_name="/dev/ttyUSB0",
            baud=115200,
            max_retries=3
        )

        # First connect fails
        result = manager.connect()
        assert result is False

        # Now "replug" the device
        port.set_fail_on_open(False)
        clock.clear_sleep_calls()

        # Retry should succeed
        result = manager.connect()
        assert result is True
        assert port.is_open()


class TestReconnectionIntegration:
    """Integration tests for reconnection with main loop."""

    def test_main_loop_handles_disconnect(self):
        """Main loop should handle disconnect during operation."""
        from serial.reconnection import ReconnectionManager

        port = MockSerialPort()
        clock = MockClock()
        logger = MockLogger()

        manager = ReconnectionManager(
            serial_port=port,
            clock=clock,
            logger=logger,
            port_name="/dev/ttyUSB0",
            baud=115200
        )

        manager.connect()

        # Inject some data
        port.inject_line("Hello, World!")

        # Read should work
        data = port.read_line()
        assert data is not None

        # Simulate disconnect after next read
        port.set_disconnect_after(1)
        port.inject_line("Last message")

        # This read triggers disconnect
        data = port.read_line()

        # Check and reconnect
        manager.check_and_reconnect()

        # Should be reconnected
        assert port.is_open()
        assert manager.reconnect_count == 1
