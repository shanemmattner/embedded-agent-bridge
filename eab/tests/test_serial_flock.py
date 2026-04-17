"""Unit tests for Feature 1 — device-node ``fcntl.flock`` in ``RealSerialPort``.

All hardware access is mocked. These tests MUST NOT open a real serial port.
They verify:

1. Successful open calls ``fcntl.flock(fd, LOCK_EX | LOCK_NB)``.
2. EAGAIN from flock closes the serial object, returns False, and sets
   ``get_last_flock_status() == "port-locked-by-other"``.
3. close() releases the flock (LOCK_UN).
"""

from __future__ import annotations

import errno
from unittest.mock import MagicMock, patch

import pytest


@pytest.fixture
def fake_serial():
    """Patch ``serial.Serial`` in ``eab.implementations`` with a fake object."""
    fake_obj = MagicMock()
    fake_obj.fileno.return_value = 42
    fake_obj.is_open = True
    with patch("eab.implementations.serial.Serial", return_value=fake_obj) as ctor:
        yield ctor, fake_obj


def test_flock_acquired_with_lock_ex_lock_nb(fake_serial):
    """On successful open, fcntl.flock is called with LOCK_EX | LOCK_NB."""
    from eab.implementations import RealSerialPort
    import eab.implementations as impls

    _, fake_obj = fake_serial
    with patch.object(impls, "fcntl") as mock_fcntl, \
         patch.object(impls, "_HAS_FCNTL", True):
        mock_fcntl.LOCK_EX = 2
        mock_fcntl.LOCK_NB = 4
        mock_fcntl.LOCK_UN = 8
        mock_fcntl.flock.return_value = None

        port = RealSerialPort()
        ok = port.open("/dev/cu.usbmodem_fake", 115200)

        assert ok is True, "open should succeed when flock returns"
        mock_fcntl.flock.assert_called_once_with(42, 2 | 4)
        assert impls.get_last_flock_status() is None


def test_flock_failure_sets_port_locked_status(fake_serial):
    """EAGAIN from flock closes serial, returns False, status sentinel set."""
    from eab.implementations import RealSerialPort, get_last_flock_status
    import eab.implementations as impls

    _, fake_obj = fake_serial
    with patch.object(impls, "fcntl") as mock_fcntl, \
         patch.object(impls, "_HAS_FCNTL", True):
        mock_fcntl.LOCK_EX = 2
        mock_fcntl.LOCK_NB = 4
        err = OSError(errno.EAGAIN, "Resource temporarily unavailable")
        mock_fcntl.flock.side_effect = err

        port = RealSerialPort()
        ok = port.open("/dev/cu.usbmodem_fake", 115200)

        assert ok is False
        fake_obj.close.assert_called_once()
        assert get_last_flock_status() == "port-locked-by-other"


def test_close_releases_flock(fake_serial):
    """close() should call flock(LOCK_UN) before closing the serial handle."""
    from eab.implementations import RealSerialPort
    import eab.implementations as impls

    _, fake_obj = fake_serial
    with patch.object(impls, "fcntl") as mock_fcntl, \
         patch.object(impls, "_HAS_FCNTL", True):
        mock_fcntl.LOCK_EX = 2
        mock_fcntl.LOCK_NB = 4
        mock_fcntl.LOCK_UN = 8
        mock_fcntl.flock.return_value = None

        port = RealSerialPort()
        assert port.open("/dev/cu.usbmodem_fake", 115200) is True

        # Reset to distinguish open-time flock from close-time unlock.
        mock_fcntl.flock.reset_mock()
        port.close()

        mock_fcntl.flock.assert_called_once_with(42, 8)
        fake_obj.close.assert_called_once()
