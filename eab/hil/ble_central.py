"""BleCentral — BLE central simulator backed by a second nRF5340 DK."""

from __future__ import annotations

from typing import Optional

from eab.hil.hil_device import HilDevice, HilDeviceError


class BleCentralError(RuntimeError):
    """Raised when a BleCentral operation fails."""


class BleCentral:
    """BLE central simulator backed by a second nRF5340 DK running
    the EAB central fixture firmware, controlled via RTT shell.

    Parameters
    ----------
    device:
        A fully-constructed :class:`HilDevice` pointing at the central DK.
    """

    # -------------------------------------------------------------------
    # RTT shell output prefixes emitted by the central fixture firmware.
    # All prefixes end with ':' and a space so they are unique vs Zephyr log lines.
    # -------------------------------------------------------------------
    _SCAN_RESULT_PREFIX    = "SCAN_RESULT: "
    _SCAN_TIMEOUT_PREFIX   = "SCAN_TIMEOUT"
    _CONNECT_OK_PREFIX     = "CONNECTED: "
    _CONNECT_FAIL_PREFIX   = "CONNECT_FAIL"
    _DISCONNECT_PREFIX     = "DISCONNECTED"
    _SUBSCRIBED_PREFIX     = "SUBSCRIBED: "
    _SUBSCRIBE_FAIL_PREFIX = "SUBSCRIBE_FAIL"
    _NOTIFY_DONE_PREFIX    = "NOTIFY_DONE: "
    _NOTIFY_TIMEOUT_PREFIX = "NOTIFY_TIMEOUT"
    _WRITE_OK_PREFIX       = "WRITE_OK"
    _WRITE_FAIL_PREFIX     = "WRITE_FAIL"
    _READ_RESULT_PREFIX    = "READ_RESULT: "
    _READ_FAIL_PREFIX      = "READ_FAIL"

    def __init__(self, device: HilDevice) -> None:
        self._dev = device

    # --- public property -------------------------------------------------

    @property
    def device(self) -> HilDevice:
        return self._dev

    # --- public API ------------------------------------------------------

    def flash(self, firmware: str, **kwargs) -> None:
        """Flash the central fixture firmware."""
        self._dev.flash(firmware, **kwargs)

    def reset(self, **kwargs) -> None:
        """Hardware-reset the central board and re-anchor its log offset."""
        self._dev.reset(**kwargs)

    def assert_no_fault(self, **kwargs) -> None:
        """Assert the central board has not crashed."""
        self._dev.assert_no_fault(**kwargs)

    def scan(self, target_name: str, *, timeout: int = 15) -> str:
        """Scan for a BLE peripheral by advertised name.

        Parameters
        ----------
        target_name:
            The ``CONFIG_BT_DEVICE_NAME`` string of the peripheral to find.
        timeout:
            Seconds to wait before giving up (must exceed scan window +
            peripheral advertising interval; 15 s is safe for Zephyr defaults).

        Returns
        -------
        str
            Bluetooth address of the found peripheral (``"AA:BB:CC:DD:EE:FF"``).

        Raises
        ------
        BleCentralError
            If the peripheral is not found within *timeout*.
        """
        self._dev.send(f"ble scan {target_name}")
        try:
            line = self._dev.wait(self._SCAN_RESULT_PREFIX, timeout=timeout)
        except HilDeviceError:
            raise BleCentralError(
                f"scan: '{target_name}' not found within {timeout}s"
            )
        # Firmware output: "SCAN_RESULT: EAB-Peripheral AA:BB:CC:DD:EE:FF"
        parts = line.strip().split()
        # parts[0] = "SCAN_RESULT:", parts[1] = <name>, parts[2] = <addr>
        return parts[2] if len(parts) >= 3 else ""

    def connect(self, addr: Optional[str] = None, *, timeout: int = 10) -> None:
        """Connect to the last scan result (or an explicit address).

        Parameters
        ----------
        addr:
            Optional explicit BT address. If omitted, connects to the address
            returned by the most recent successful :meth:`scan`.
        timeout:
            Seconds to wait for connection establishment + GATT service
            discovery. 10 s is a conservative minimum; 15 s recommended.

        Raises
        ------
        BleCentralError
            If connection is not established within *timeout*.
        """
        cmd = f"ble connect {addr}" if addr else "ble connect"
        self._dev.send(cmd)
        try:
            self._dev.wait(self._CONNECT_OK_PREFIX, timeout=timeout)
        except HilDeviceError:
            raise BleCentralError(f"connect failed within {timeout}s")

    def disconnect(self, *, timeout: int = 10) -> None:
        """Disconnect from the current peripheral.

        Raises
        ------
        BleCentralError
            If disconnection confirmation is not seen within *timeout*.
        """
        self._dev.send("ble disconnect")
        try:
            self._dev.wait(self._DISCONNECT_PREFIX, timeout=timeout)
        except HilDeviceError:
            raise BleCentralError(f"disconnect failed within {timeout}s")

    def subscribe(self, char_uuid: str, *, timeout: int = 10) -> None:
        """Enable CCCD notifications for a characteristic.

        Parameters
        ----------
        char_uuid:
            Short (16-bit) or full 128-bit UUID string, uppercase hex.
            e.g. ``"EAB20002"`` or ``"6E400003-B5A3-F393-E0A9-E50E24DCCA9E"``.
        timeout:
            Seconds to wait for CCCD write confirmation.

        Raises
        ------
        BleCentralError
            If the subscribe fails or times out.
        """
        self._dev.send(f"ble subscribe {char_uuid}")
        try:
            self._dev.wait(self._SUBSCRIBED_PREFIX, timeout=timeout)
        except HilDeviceError:
            raise BleCentralError(
                f"subscribe {char_uuid}: no confirmation within {timeout}s"
            )

    def assert_notify(
        self,
        char_uuid: str,
        *,
        count: int = 1,
        timeout: int = 15,
        expect_value: Optional[str] = None,
    ) -> list[str]:
        """Assert that *count* notifications arrive on *char_uuid*.

        Sends ``ble expect_notify <uuid> <count>`` to the fixture firmware, which
        buffers incoming notifications and prints ``NOTIFY_DONE:`` when it has
        accumulated *count* of them (or ``NOTIFY_TIMEOUT`` if not).

        Parameters
        ----------
        char_uuid:
            Characteristic UUID to watch.
        count:
            Number of notifications to collect before declaring success.
        timeout:
            Total seconds to wait for all notifications.
        expect_value:
            Optional hex string. If set, the last collected notification value
            must match exactly (case-insensitive). ``None`` skips value checking.

        Returns
        -------
        list[str]
            List of received notification values as uppercase hex strings,
            most recent last. Length == *count*.

        Raises
        ------
        BleCentralError
            If *count* notifications do not arrive within *timeout*, or if
            *expect_value* is set and does not match the last value.
        """
        self._dev.send(f"ble expect_notify {char_uuid} {count}")
        try:
            # Firmware prints: "NOTIFY_DONE: EAB20002 3 0102 0304 0506"
            line = self._dev.wait(self._NOTIFY_DONE_PREFIX, timeout=timeout)
        except HilDeviceError:
            raise BleCentralError(
                f"assert_notify({char_uuid}, count={count}): "
                f"did not receive {count} notifications within {timeout}s"
            )
        # Parse values from "NOTIFY_DONE: <uuid> <count> <val0> <val1> ..."
        parts = line.strip().split()
        values = parts[3:] if len(parts) > 3 else []

        if expect_value is not None:
            last = values[-1] if values else ""
            if last.upper() != expect_value.upper():
                raise BleCentralError(
                    f"assert_notify({char_uuid}): "
                    f"expected last value '{expect_value}', got '{last}'"
                )
        return values

    def write(
        self,
        char_uuid: str,
        value: "str | bytes",
        *,
        without_response: bool = True,
        timeout: int = 10,
    ) -> None:
        """Write a value to a characteristic.

        Parameters
        ----------
        char_uuid:
            Characteristic UUID (same format as :meth:`subscribe`).
        value:
            Value to write — either a hex string (``"0102"``) or raw bytes.
        without_response:
            If True (default), uses Write Without Response (BT_GATT_WRITE_NO_RSP).
            If False, uses Write With Response and waits for the ATT response.
        timeout:
            Seconds to wait for write confirmation.

        Raises
        ------
        BleCentralError
            If the write fails or confirmation is not seen within *timeout*.
        """
        if isinstance(value, (bytes, bytearray)):
            hex_val = value.hex().upper()
        else:
            hex_val = str(value).replace(" ", "").upper()
        rsp_flag = "norsp" if without_response else "rsp"
        self._dev.send(f"ble write {char_uuid} {hex_val} {rsp_flag}")
        try:
            self._dev.wait(self._WRITE_OK_PREFIX, timeout=timeout)
        except HilDeviceError:
            raise BleCentralError(
                f"write {char_uuid}={hex_val} failed within {timeout}s"
            )

    def read(self, char_uuid: str, *, timeout: int = 10) -> str:
        """Read a characteristic value.

        Returns
        -------
        str
            Characteristic value as uppercase hex string.

        Raises
        ------
        BleCentralError
            If the read fails or times out.
        """
        self._dev.send(f"ble read {char_uuid}")
        try:
            # Firmware prints: "READ_RESULT: EAB20004 0A1B2C"
            line = self._dev.wait(self._READ_RESULT_PREFIX, timeout=timeout)
        except HilDeviceError:
            raise BleCentralError(
                f"read {char_uuid}: no result within {timeout}s"
            )
        parts = line.strip().split()
        return parts[2].upper() if len(parts) >= 3 else ""
