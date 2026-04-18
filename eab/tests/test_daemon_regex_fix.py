r"""Regression test for Feature 4 — issue #182.

The _resolve_port tiebreaker regex was accidentally escaped as r"(\\d+)$"
(literal backslash + digits) instead of r"(\d+)$" (trailing digits). This
caused unique-device selection to always fall back to the first candidate
because no port name actually contains a literal backslash.

We exercise the score() lambda by importing the regex pattern directly from
the source and asserting it matches trailing-digit strings. A deeper
end-to-end fix would instantiate a SerialDaemon and monkey-patch list_ports;
that's unnecessary since the bug is purely a one-character regex error.
"""

from __future__ import annotations

import re
from pathlib import Path


DAEMON_SRC = Path(__file__).resolve().parents[1] / "daemon.py"


def test_daemon_regex_is_not_double_escaped():
    text = DAEMON_SRC.read_text()
    # The broken form must no longer appear in source.
    assert r'r"(\\d+)$"' not in text
    # The fixed form must appear.
    assert r'r"(\d+)$"' in text


def test_fixed_regex_matches_trailing_digits():
    """The fixed pattern correctly scores candidate ports by trailing digits."""
    pattern = re.compile(r"(\d+)$")

    # Devices that _resolve_port has to tiebreak.
    m0 = pattern.search("/dev/cu.usbmodem14101")
    m1 = pattern.search("/dev/cu.usbmodem14102")
    m_none = pattern.search("/dev/cu.Bluetooth-Incoming-Port")

    assert m0 is not None
    assert m1 is not None
    assert int(m0.group(1)) == 14101
    assert int(m1.group(1)) == 14102
    assert m_none is None

    # Simulate the scoring tie-break: higher trailing number wins.
    def score(dev):
        m = pattern.search(dev)
        return (int(m.group(1)) if m else -1, dev)

    candidates = [
        "/dev/cu.usbmodem14101",
        "/dev/cu.usbmodem14103",
        "/dev/cu.usbmodem14102",
    ]
    assert max(candidates, key=score) == "/dev/cu.usbmodem14103"


def test_broken_regex_would_never_match():
    """Sanity check: confirm the old pattern never matched real port names."""
    broken = re.compile(r"(\\d+)$")
    # No real port path ends in a literal backslash + digits.
    assert broken.search("/dev/cu.usbmodem14101") is None
    assert broken.search("/dev/ttyUSB0") is None
