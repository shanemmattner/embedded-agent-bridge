"""hil_central fixture — function-scoped BleCentral for BLE HIL tests."""

from __future__ import annotations

import pytest

from eab.hil.hil_device import HilDevice
from eab.hil.ble_central import BleCentral


@pytest.fixture(scope="function")
def hil_central(request: pytest.FixtureRequest) -> BleCentral:
    """Provide a BleCentral for the current test.

    Requires ``--hil-central-device`` and ``--hil-central-chip`` to be set.
    Skips automatically if either is absent.

    Teardown (always runs, even on failure):
      - Calls ``assert_no_fault()`` if ``hil_autofault`` marker is present.
    """
    device_name = request.config.getoption("--hil-central-device", default=None)
    chip = request.config.getoption("--hil-central-chip", default=None)
    probe = request.config.getoption("--hil-central-probe", default=None)
    default_timeout = request.config.getoption("--hil-timeout", default=30)

    if device_name is None:
        pytest.skip("BLE HIL test skipped: --hil-central-device not set")

    if chip is None:
        pytest.skip("BLE HIL test skipped: --hil-central-chip not set")

    dev = HilDevice(
        device=device_name,
        chip=chip,
        probe=probe,
        default_timeout=default_timeout,
    )
    central = BleCentral(dev)

    yield central

    # --- Teardown (runs regardless of pass/fail) ---
    marker = request.node.get_closest_marker("hil_autofault")
    if marker:
        try:
            central.assert_no_fault()
        except Exception as exc:
            request.node._hil_autofault_error = str(exc)
