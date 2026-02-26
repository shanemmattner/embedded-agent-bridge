"""End-to-end BLE HIL tests using hil_device (peripheral) + hil_central (central DK).

These tests require two nRF5340 DKs and are automatically skipped when
--hil-device / --hil-central-device are not supplied.
"""

from __future__ import annotations

import pytest

PERIPHERAL_FIRMWARE = "examples/nrf5340-ble-peripheral"
CENTRAL_FIRMWARE    = "examples/nrf5340-ble-central-fixture"
NOTIFY_UUID         = "EAB20002"
WRITE_UUID          = "EAB20003"
READ_UUID           = "EAB20004"


@pytest.mark.hil_autofault
def test_ble_connect_and_notify(hil_device, hil_central):
    """Peripheral advertises → central connects, subscribes, receives 5 notifications."""
    # Flash both boards
    hil_device.flash(PERIPHERAL_FIRMWARE)
    hil_central.flash(CENTRAL_FIRMWARE)

    hil_device.reset()
    hil_central.reset()

    # Peripheral boots
    hil_device.wait("Advertising as: EAB-Peripheral", timeout=10)

    # Central scans and connects
    hil_central.scan("EAB-Peripheral", timeout=15)
    hil_central.connect(timeout=15)

    # Peripheral sees the connection
    hil_device.wait("Connected", timeout=10)

    # Subscribe and assert notifications arrive
    hil_central.subscribe(NOTIFY_UUID, timeout=10)
    values = hil_central.assert_notify(NOTIFY_UUID, count=5, timeout=20)
    assert len(values) == 5, f"Expected 5 notifications, got {len(values)}"

    # Write to change peripheral mode
    hil_central.write(WRITE_UUID, "01", timeout=10)
    hil_device.wait("mode=fast", timeout=5)

    # Clean up
    hil_central.disconnect(timeout=10)
    hil_device.assert_no_fault()
    hil_central.assert_no_fault()


@pytest.mark.hil_autofault
def test_ble_read_characteristic(hil_device, hil_central):
    """Connect and read a status characteristic."""
    hil_device.flash(PERIPHERAL_FIRMWARE)
    hil_central.flash(CENTRAL_FIRMWARE)
    hil_device.reset()
    hil_central.reset()

    hil_device.wait("Advertising as: EAB-Peripheral", timeout=10)
    hil_central.scan("EAB-Peripheral", timeout=15)
    hil_central.connect(timeout=15)

    raw = hil_central.read(READ_UUID, timeout=10)
    assert len(raw) > 0, "Read returned empty value"

    hil_central.disconnect()
