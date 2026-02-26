"""hil_device fixture — function-scoped HilDevice for HIL tests."""

from __future__ import annotations

import pytest
from eab.hil.hil_device import HilDevice


def pytest_addoption(parser: pytest.Parser) -> None:
    """Register HIL CLI options.  Called from pytest_plugin.py."""
    group = parser.getgroup("hil", "Hardware-in-the-loop options")
    group.addoption(
        "--hil-device",
        default=None,
        metavar="DEVICE",
        help="EAB device name (e.g. nrf5340).  Required to run HIL tests.",
    )
    group.addoption(
        "--hil-chip",
        default=None,
        metavar="CHIP",
        help="Chip identifier forwarded to flash/reset (e.g. NRF5340_XXAA_APP).",
    )
    group.addoption(
        "--hil-probe",
        default=None,
        metavar="PROBE",
        help="Probe selector string (e.g. 0483:3748 or J-Link serial).",
    )
    group.addoption(
        "--hil-timeout",
        default=30,
        type=int,
        metavar="SECONDS",
        help="Default timeout for HIL operations (default: 30).",
    )


@pytest.fixture(scope="function")
def hil_device(request: pytest.FixtureRequest) -> HilDevice:
    """Provide a HilDevice for the current test.

    Scope is *function* (not session/module) to guarantee a fresh log-offset
    anchor, independent flash state, and automatic cleanup after each test.

    Skips the test automatically when ``--hil-device`` is not supplied.

    Teardown (always runs, even on failure):
      - Calls ``assert_no_fault()`` if ``hil_autofault`` marker is present.
    """
    device_name = request.config.getoption("--hil-device", default=None)
    chip = request.config.getoption("--hil-chip", default=None)
    probe = request.config.getoption("--hil-probe", default=None)
    default_timeout = request.config.getoption("--hil-timeout", default=30)

    if device_name is None:
        pytest.skip("HIL test skipped: --hil-device not set")

    if chip is None:
        pytest.skip("HIL test skipped: --hil-chip not set")

    dev = HilDevice(
        device=device_name,
        chip=chip,
        probe=probe,
        default_timeout=default_timeout,
    )

    yield dev

    # --- Teardown (runs regardless of pass/fail) ---
    # Auto-fault check if marker present:
    marker = request.node.get_closest_marker("hil_autofault")
    if marker:
        try:
            dev.assert_no_fault()
        except Exception as exc:
            # Store on the node so the hook can attach it to the report
            request.node._hil_autofault_error = str(exc)
