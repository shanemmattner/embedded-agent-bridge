"""EAB pytest plugin — auto-loaded via entry_points pytest11.

Registers:
  - CLI options: --hil-device, --hil-chip, --hil-probe, --hil-timeout
  - Fixture:     hil_device (function-scoped)
  - Hooks:       pytest_runtest_setup, pytest_runtest_makereport
"""

from __future__ import annotations

import pytest

from eab.hil.device_fixture import pytest_addoption as _add_hil_options
from eab.hil.rtt_capture import (
    pytest_runtest_setup as _rtt_setup,
    pytest_runtest_makereport as _rtt_makereport,
    _RTT_CAPTURE_KEY,
)


def pytest_addoption(parser: pytest.Parser) -> None:
    _add_hil_options(parser)


def pytest_configure(config: pytest.Config) -> None:
    config.addinivalue_line(
        "markers",
        "hil_autofault: automatically call hil_device.assert_no_fault() in teardown",
    )
    config.addinivalue_line(
        "markers",
        "hil: test requires physical hardware; skipped without --hil-device",
    )


# Re-export hooks so pytest discovers them on this module
pytest_runtest_setup = _rtt_setup
pytest_runtest_makereport = _rtt_makereport


# Re-export fixture so pytest discovers it from this module
from eab.hil.device_fixture import hil_device  # noqa: F401, E402
