"""Per-test RTT log capture and pytest report attachment."""

from __future__ import annotations

import os
from typing import Optional

import pytest


class RttCapture:
    """Snapshot RTT log lines for a single test.

    Usage (internal — called from plugin hooks):

        cap = RttCapture(device="nrf5340")
        cap.start()          # record start offset
        ... test runs ...
        lines = cap.stop()   # read lines since start
    """

    def __init__(self, device: Optional[str]) -> None:
        self.device = device
        self._start_offset: int = 0
        self._log_path: Optional[str] = None
        self._lines: list = []

    def _resolve_log_path(self) -> Optional[str]:
        if not self.device:
            return None
        base = os.path.join("/tmp/eab-devices", self.device)
        for candidate in [
            os.path.join(base, "rtt-raw.log"),
            os.path.join(base, "latest.log"),
            "/tmp/eab-devices/default/rtt-raw.log",
        ]:
            if os.path.exists(candidate):
                return candidate
        return None

    def start(self) -> None:
        """Record the current log file size as the capture start point."""
        self._log_path = self._resolve_log_path()
        if self._log_path:
            try:
                self._start_offset = os.path.getsize(self._log_path)
            except OSError:
                self._start_offset = 0

    def stop(self) -> list:
        """Read all log lines written since start().  Returns list of strings."""
        if not self._log_path:
            return []
        try:
            with open(self._log_path, "r", encoding="utf-8", errors="replace") as f:
                f.seek(self._start_offset)
                self._lines = [ln.rstrip() for ln in f.readlines()]
        except OSError:
            self._lines = []
        return self._lines

    @property
    def text(self) -> str:
        return "\n".join(self._lines)


# ---------------------------------------------------------------------------
# pytest hook implementation
# ---------------------------------------------------------------------------

# Key used to stash RttCapture on the pytest item
_RTT_CAPTURE_KEY = pytest.StashKey()


def pytest_runtest_setup(item: pytest.Item) -> None:
    """Start RTT capture before each test.

    Registered in pytest_plugin.py via hookimpl.
    """
    device = item.config.getoption("--hil-device", default=None)
    cap = RttCapture(device=device)
    cap.start()
    item.stash[_RTT_CAPTURE_KEY] = cap


@pytest.hookimpl(hookwrapper=True)
def pytest_runtest_makereport(item: pytest.Item, call: pytest.CallInfo):
    """Attach RTT log to the report *only* on failure/error.

    Registered in pytest_plugin.py.
    """
    outcome = yield
    report = outcome.get_result()

    if report.when != "call":
        return

    cap = item.stash.get(_RTT_CAPTURE_KEY, None)
    if cap is None:
        return

    lines = cap.stop()

    # Always attach to report sections (visible in html reports, etc.)
    if lines:
        log_text = "\n".join(lines)
        report.sections.append(("RTT log", log_text))

    # If test failed and there's a pending autofault error, append it
    autofault_err = getattr(item, "_hil_autofault_error", None)
    if autofault_err and report.failed:
        report.sections.append(("HIL autofault", autofault_err))
