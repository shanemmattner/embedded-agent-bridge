"""BleakCentral — BLE central using the host's Bluetooth via bleak.

Drop-in replacement for :class:`~eab.hil.ble_central.BleCentral` when you
don't have a second nRF DK.  Uses the Mac (or Linux) built-in Bluetooth
adapter instead of an RTT-shell-controlled nRF central.

The async implementation lives in :class:`BleakCentral`; a synchronous
wrapper :class:`BleakCentralSync` is provided for easy use in pytest
(no ``pytest-asyncio`` needed).
"""

from __future__ import annotations

import asyncio
import logging
import threading
from typing import Optional

from bleak import BleakClient, BleakScanner
from bleak.backends.characteristic import BleakGATTCharacteristic

logger = logging.getLogger(__name__)


class BleakCentralError(RuntimeError):
    """Raised when a BleakCentral operation fails."""


# ======================================================================
# Async implementation
# ======================================================================


class BleakCentral:
    """BLE central using Mac's built-in Bluetooth via bleak library.

    Drop-in replacement for BleCentral when you don't have a second nRF DK.
    Uses the host machine's Bluetooth adapter instead.
    """

    def __init__(self, event_callback=None) -> None:
        self._client: Optional[BleakClient] = None
        self._address: Optional[str] = None
        self._notifications: dict[str, list[bytes]] = {}
        self._notify_events: dict[str, asyncio.Event] = {}
        self._lock = asyncio.Lock()
        self._event_cb = event_callback

    def _emit(self, event_type: str, detail: str = "") -> None:
        """Fire event callback if registered."""
        if self._event_cb:
            import time
            self._event_cb({"type": event_type, "detail": detail, "ts": time.time()})

    # --- scanning -------------------------------------------------

    async def scan(self, target_name: str, *, timeout: int = 15) -> str:
        """Scan for peripheral by name, return BLE address (or macOS UUID).

        Parameters
        ----------
        target_name:
            Advertised device name to search for (e.g. ``"EAB-Test"``).
        timeout:
            Seconds to scan before giving up.

        Returns
        -------
        str
            BLE address string.  On macOS this is a CoreBluetooth UUID,
            not a true MAC address (Apple privacy restriction).

        Raises
        ------
        BleakCentralError
            If the device is not found within *timeout*.
        """
        logger.info("Scanning for '%s' (timeout=%ds)...", target_name, timeout)
        device = await BleakScanner.find_device_by_name(
            target_name, timeout=timeout,
        )
        if device is None:
            raise BleakCentralError(
                f"scan: '{target_name}' not found within {timeout}s"
            )
        self._address = str(device.address)
        logger.info("Found '%s' at %s", target_name, self._address)
        self._emit("scan_found", f"{target_name} at {self._address}")
        return self._address

    # --- connection -----------------------------------------------

    async def connect(self, addr: Optional[str] = None, *, timeout: int = 10) -> None:
        """Connect to peripheral.

        Parameters
        ----------
        addr:
            BLE address / macOS UUID.  If *None*, uses the address from
            the most recent :meth:`scan`.
        timeout:
            Connection timeout in seconds.

        Raises
        ------
        BleakCentralError
            If connection fails.
        """
        target = addr or self._address
        if not target:
            raise BleakCentralError(
                "connect: no address — call scan() first or pass addr="
            )

        logger.info("Connecting to %s (timeout=%ds)...", target, timeout)

        # Disconnect any previous session
        if self._client and self._client.is_connected:
            try:
                await self._client.disconnect()
            except Exception:
                pass

        self._client = BleakClient(target, timeout=timeout)
        try:
            await self._client.connect()
        except Exception as exc:
            raise BleakCentralError(f"connect failed: {exc}") from exc

        logger.info("Connected to %s", target)
        self._emit("connected", str(target))

    async def disconnect(self, *, timeout: int = 10) -> None:
        """Disconnect from peripheral.

        Raises
        ------
        BleakCentralError
            If disconnect fails.
        """
        if self._client is None:
            return
        try:
            # Stop all active notifications before disconnecting
            for uuid_key in list(self._notifications.keys()):
                try:
                    await self._client.stop_notify(uuid_key)
                except Exception:
                    pass
            self._notifications.clear()
            self._notify_events.clear()

            logger.info("Disconnecting...")
            await self._client.disconnect()
            logger.info("Disconnected")
            self._emit("disconnected", "")
        except Exception as exc:
            raise BleakCentralError(f"disconnect failed: {exc}") from exc

    # --- GATT operations ------------------------------------------

    async def subscribe(self, char_uuid: str, *, timeout: int = 10) -> None:
        """Enable notifications for a characteristic.

        Parameters
        ----------
        char_uuid:
            Full 128-bit UUID string of the characteristic.
        timeout:
            Not used by bleak (kept for API compatibility).

        Raises
        ------
        BleakCentralError
            If subscription fails.
        """
        self._ensure_connected()
        uuid_lower = char_uuid.lower()

        # Prepare notification storage
        self._notifications[uuid_lower] = []
        self._notify_events[uuid_lower] = asyncio.Event()

        def _handler(char: BleakGATTCharacteristic, data: bytearray) -> None:
            key = char.uuid.lower()
            if key not in self._notifications:
                self._notifications[key] = []
            self._notifications[key].append(bytes(data))
            logger.debug("Notification on %s: %s", key, data.hex())
            self._emit("notification", f"{key}: {data.hex()}")
            # Signal any waiters
            evt = self._notify_events.get(key)
            if evt:
                evt.set()

        try:
            await self._client.start_notify(char_uuid, _handler)  # type: ignore[union-attr]
            logger.info("Subscribed to %s", char_uuid)
            self._emit("subscribed", char_uuid)
        except Exception as exc:
            raise BleakCentralError(
                f"subscribe {char_uuid} failed: {exc}"
            ) from exc

    async def assert_notify(
        self,
        char_uuid: str,
        *,
        count: int = 1,
        timeout: int = 15,
    ) -> list[str]:
        """Wait for *count* notifications, return values as hex strings.

        Parameters
        ----------
        char_uuid:
            UUID of the subscribed characteristic.
        count:
            Number of notifications to collect.
        timeout:
            Total seconds to wait.

        Returns
        -------
        list[str]
            Notification payloads as uppercase hex strings.

        Raises
        ------
        BleakCentralError
            If *count* notifications do not arrive within *timeout*.
        """
        self._ensure_connected()
        uuid_lower = char_uuid.lower()

        if uuid_lower not in self._notifications:
            self._notifications[uuid_lower] = []
        if uuid_lower not in self._notify_events:
            self._notify_events[uuid_lower] = asyncio.Event()

        # Clear previous notifications for a fresh count
        self._notifications[uuid_lower] = []
        self._notify_events[uuid_lower].clear()

        deadline = asyncio.get_event_loop().time() + timeout
        while len(self._notifications[uuid_lower]) < count:
            remaining = deadline - asyncio.get_event_loop().time()
            if remaining <= 0:
                got = len(self._notifications[uuid_lower])
                raise BleakCentralError(
                    f"assert_notify({char_uuid}, count={count}): "
                    f"only received {got}/{count} within {timeout}s"
                )
            self._notify_events[uuid_lower].clear()
            try:
                await asyncio.wait_for(
                    self._notify_events[uuid_lower].wait(),
                    timeout=remaining,
                )
            except asyncio.TimeoutError:
                got = len(self._notifications[uuid_lower])
                raise BleakCentralError(
                    f"assert_notify({char_uuid}, count={count}): "
                    f"only received {got}/{count} within {timeout}s"
                )

        values = [
            v.hex().upper()
            for v in self._notifications[uuid_lower][:count]
        ]
        logger.info("Received %d notifications on %s", count, char_uuid)
        return values

    async def write(
        self,
        char_uuid: str,
        value: str | bytes,
        *,
        without_response: bool = True,
    ) -> None:
        """Write value to characteristic.

        Parameters
        ----------
        char_uuid:
            UUID of the characteristic.
        value:
            Hex string (e.g. ``"01"``) or raw bytes.
        without_response:
            If *True*, use Write Without Response.
        """
        self._ensure_connected()

        if isinstance(value, str):
            data = bytes.fromhex(value)
        else:
            data = bytes(value)

        logger.info("Writing %s to %s (response=%s)",
                     data.hex(), char_uuid, not without_response)
        try:
            await self._client.write_gatt_char(  # type: ignore[union-attr]
                char_uuid, data, response=not without_response,
            )
            self._emit("write", f"{char_uuid}: {data.hex()}")
        except Exception as exc:
            raise BleakCentralError(
                f"write {char_uuid} failed: {exc}"
            ) from exc

    async def read(self, char_uuid: str) -> str:
        """Read characteristic value, return as uppercase hex string.

        Parameters
        ----------
        char_uuid:
            UUID of the characteristic to read.

        Returns
        -------
        str
            Value as uppercase hex string.
        """
        self._ensure_connected()

        try:
            data = await self._client.read_gatt_char(char_uuid)  # type: ignore[union-attr]
        except Exception as exc:
            raise BleakCentralError(
                f"read {char_uuid} failed: {exc}"
            ) from exc

        hex_val = bytes(data).hex().upper()
        logger.info("Read %s from %s", hex_val, char_uuid)
        self._emit("read", f"{char_uuid}: {hex_val}")
        return hex_val

    # --- properties ------------------------------------------------

    @property
    def is_connected(self) -> bool:
        """Check if currently connected."""
        return self._client is not None and self._client.is_connected

    @property
    def services(self) -> dict:
        """Return discovered services and characteristics.

        Returns
        -------
        dict
            ``{service_uuid: [char_uuid, ...], ...}``
        """
        if self._client is None or not self._client.is_connected:
            return {}

        result: dict[str, list[str]] = {}
        for svc in self._client.services:
            chars = [str(c.uuid) for c in svc.characteristics]
            result[str(svc.uuid)] = chars
        return result

    # --- cleanup ---------------------------------------------------

    async def aclose(self) -> None:
        """Disconnect and clean up resources."""
        if self._client and self._client.is_connected:
            try:
                await self._client.disconnect()
            except Exception:
                pass
        self._client = None
        self._notifications.clear()
        self._notify_events.clear()

    # --- internal --------------------------------------------------

    def _ensure_connected(self) -> None:
        if self._client is None or not self._client.is_connected:
            raise BleakCentralError("Not connected — call connect() first")


# ======================================================================
# Synchronous wrapper
# ======================================================================


class BleakCentralSync:
    """Synchronous wrapper around :class:`BleakCentral` for pytest.

    Runs its own asyncio event loop on a background thread so callers
    can use plain synchronous calls without ``pytest-asyncio``.  The
    public API mirrors :class:`~eab.hil.ble_central.BleCentral`.
    """

    def __init__(self) -> None:
        self._loop = asyncio.new_event_loop()
        self._thread = threading.Thread(
            target=self._loop.run_forever, daemon=True, name="bleak-loop",
        )
        self._thread.start()
        self._central = BleakCentral()

    # --- helpers ---------------------------------------------------

    def _run(self, coro):  # noqa: ANN001, ANN202
        """Submit *coro* to the background loop and block until done."""
        future = asyncio.run_coroutine_threadsafe(coro, self._loop)
        return future.result()

    # --- public API (same signatures as BleCentral) ----------------

    def scan(self, target_name: str, *, timeout: int = 15) -> str:
        """Scan for peripheral by name, return BLE address."""
        return self._run(self._central.scan(target_name, timeout=timeout))

    def connect(self, addr: Optional[str] = None, *, timeout: int = 10) -> None:
        """Connect to peripheral."""
        self._run(self._central.connect(addr, timeout=timeout))

    def disconnect(self, *, timeout: int = 10) -> None:
        """Disconnect from peripheral."""
        self._run(self._central.disconnect(timeout=timeout))

    def subscribe(self, char_uuid: str, *, timeout: int = 10) -> None:
        """Enable notifications for a characteristic."""
        self._run(self._central.subscribe(char_uuid, timeout=timeout))

    def assert_notify(
        self,
        char_uuid: str,
        *,
        count: int = 1,
        timeout: int = 15,
    ) -> list[str]:
        """Wait for *count* notifications, return values as hex strings."""
        return self._run(
            self._central.assert_notify(char_uuid, count=count, timeout=timeout)
        )

    def write(
        self,
        char_uuid: str,
        value: str | bytes,
        *,
        without_response: bool = True,
    ) -> None:
        """Write value to characteristic."""
        self._run(
            self._central.write(char_uuid, value, without_response=without_response)
        )

    def read(self, char_uuid: str) -> str:
        """Read characteristic value, return as uppercase hex string."""
        return self._run(self._central.read(char_uuid))

    @property
    def is_connected(self) -> bool:
        """Check if currently connected."""
        return self._central.is_connected

    @property
    def services(self) -> dict:
        """Return discovered services and characteristics."""
        return self._central.services

    def cleanup(self) -> None:
        """Disconnect and shut down the background event loop."""
        try:
            self._run(self._central.aclose())
        except Exception:
            pass
        self._loop.call_soon_threadsafe(self._loop.stop)
        self._thread.join(timeout=5)
