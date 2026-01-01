"""
Reconnection Manager for Serial Daemon.

Handles automatic reconnection with exponential backoff when
serial port connections are lost. Includes proactive USB
disconnect detection by monitoring port availability.
"""

import os
from typing import Optional, Callable, List
from .interfaces import SerialPortInterface, ClockInterface, LoggerInterface, ConnectionState


class ReconnectionManager:
    """
    Manages serial port connection with automatic reconnection.

    Features:
    - Automatic reconnection on disconnect
    - Exponential backoff for failed attempts
    - Configurable retry limits
    - Callbacks for connection events
    """

    def __init__(
        self,
        serial_port: SerialPortInterface,
        clock: ClockInterface,
        logger: LoggerInterface,
        port_name: str,
        baud: int,
        max_retries: int = 0,  # 0 = infinite retries
        retry_delay: float = 1.0,
        max_delay: float = 30.0,
        backoff_factor: float = 2.0,
        on_connect: Optional[Callable[[], None]] = None,
        on_disconnect: Optional[Callable[[], None]] = None,
        on_reconnect: Optional[Callable[[], None]] = None,
    ):
        self._serial = serial_port
        self._clock = clock
        self._logger = logger
        self._port_name = port_name
        self._baud = baud
        self._max_retries = max_retries
        self._base_delay = retry_delay
        self._max_delay = max_delay
        self._backoff_factor = backoff_factor
        self._on_connect = on_connect
        self._on_disconnect = on_disconnect
        self._on_reconnect = on_reconnect

        self._state = ConnectionState.DISCONNECTED
        self._reconnect_count = 0
        self._current_delay = retry_delay
        self._was_connected = False

    @property
    def state(self) -> ConnectionState:
        """Current connection state."""
        return self._state

    @property
    def reconnect_count(self) -> int:
        """Number of successful reconnections."""
        return self._reconnect_count

    @property
    def current_delay(self) -> float:
        """Current retry delay (for testing)."""
        return self._current_delay

    def connect(self) -> bool:
        """
        Attempt to connect to the serial port.

        Returns True on success, False if all retries exhausted.
        """
        self._state = ConnectionState.CONNECTING
        self._logger.info(f"Connecting to {self._port_name} at {self._baud} baud")

        attempt = 0
        self._current_delay = self._base_delay

        while True:
            attempt += 1

            if self._serial.open(self._port_name, self._baud):
                self._state = ConnectionState.CONNECTED
                self._was_connected = True
                self._current_delay = self._base_delay  # Reset on success
                self._logger.info(f"Connected to {self._port_name}")

                if self._on_connect:
                    self._on_connect()

                return True

            # Connection failed
            self._logger.warning(f"Connection attempt {attempt} failed")

            # Check if we've exhausted retries
            if self._max_retries > 0 and attempt >= self._max_retries:
                self._state = ConnectionState.ERROR
                self._logger.error(f"Failed to connect after {attempt} attempts")
                return False

            # Wait before retry (except on last attempt)
            if self._max_retries == 0 or attempt < self._max_retries:
                self._clock.sleep(self._current_delay)

                # Increase delay with exponential backoff
                self._current_delay = min(
                    self._current_delay * self._backoff_factor,
                    self._max_delay
                )

    def port_exists(self) -> bool:
        """Check if the port device file exists on the filesystem."""
        return os.path.exists(self._port_name)

    def check_and_reconnect(self) -> bool:
        """
        Check if connection is alive, reconnect if needed.

        Call this periodically from the main loop.
        Returns True if connected (or reconnected), False if not connected.

        Now includes proactive USB disconnect detection by checking
        if the port device file still exists.
        """
        # First check if the port device file exists (USB disconnect detection).
        #
        # Note: even if the device file isn't present, we still attempt an open() below.
        # On real hardware this will fail fast, but it keeps the logic testable and
        # avoids special-casing platforms where "port existence" isn't meaningful.
        if not self.port_exists() and self._state == ConnectionState.CONNECTED:
            self._state = ConnectionState.RECONNECTING
            self._logger.warning(f"Port {self._port_name} disappeared (USB disconnected?)")

            # Close the serial port if it thinks it's still open
            if self._serial.is_open():
                try:
                    self._serial.close()
                except Exception:
                    pass

            if self._on_disconnect:
                self._on_disconnect()

        # Normal serial connection check
        if self._serial.is_open():
            return True

        # Connection lost but port exists
        if self._state == ConnectionState.CONNECTED:
            self._state = ConnectionState.RECONNECTING
            self._logger.warning(f"Connection lost to {self._port_name}")

            if self._on_disconnect:
                self._on_disconnect()

        # Attempt reconnection
        self._logger.info("RECONNECTING...")

        if self._serial.open(self._port_name, self._baud):
            self._reconnect_count += 1
            self._state = ConnectionState.CONNECTED
            self._current_delay = self._base_delay  # Reset backoff
            self._logger.info(f"Reconnected to {self._port_name} (reconnect #{self._reconnect_count})")

            if self._on_reconnect:
                self._on_reconnect()

            return True

        return False

    def disconnect(self) -> None:
        """Gracefully disconnect."""
        if self._serial.is_open():
            self._serial.close()
        self._state = ConnectionState.DISCONNECTED
        self._logger.info(f"Disconnected from {self._port_name}")
