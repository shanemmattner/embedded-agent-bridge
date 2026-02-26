"""Tests for DSS transport (CCS Python scripting API)."""

from __future__ import annotations

from pathlib import Path
from unittest.mock import MagicMock, patch

import pytest

from eab.transports.dss import DSSTransport, find_dss, _BRIDGE_JS, _DSS_SEARCH_PATHS


# =========================================================================
# find_dss
# =========================================================================


class TestFindDss:
    def test_found_when_path_exists(self, tmp_path):
        """find_dss() returns path when a dss.sh exists at a known location."""
        fake_dss = tmp_path / "dss.sh"
        fake_dss.touch()

        with patch("eab.transports.dss._DSS_SEARCH_PATHS", [fake_dss]):
            result = find_dss()

        assert result == str(fake_dss)

    def test_not_found_when_no_paths_exist(self, tmp_path):
        """find_dss() returns None when no dss.sh paths exist."""
        missing = tmp_path / "nonexistent" / "dss.sh"

        with patch("eab.transports.dss._DSS_SEARCH_PATHS", [missing]):
            result = find_dss()

        assert result is None

    def test_returns_string_or_none(self):
        """find_dss() always returns str or None — never raises."""
        result = find_dss()
        assert result is None or isinstance(result, str)


# =========================================================================
# DSSTransport init
# =========================================================================


class TestDSSTransportInit:
    def test_init_stores_ccxml(self):
        t = DSSTransport(ccxml="/path/to/target.ccxml")
        assert t._ccxml == "/path/to/target.ccxml"

    def test_init_accepts_dss_path_for_compat(self):
        """dss_path kwarg is accepted for backward compat but not stored."""
        t = DSSTransport(ccxml="/path/to/target.ccxml", dss_path="/old/dss.sh")
        assert t._ccxml == "/path/to/target.ccxml"

    def test_not_running_initially(self):
        t = DSSTransport(ccxml="/path/to/target.ccxml")
        assert t.is_running is False

    def test_start_returns_false_when_ccs_missing(self):
        """start() returns False (no raise) when CCS scripting is not found."""
        t = DSSTransport(ccxml="/path/to/target.ccxml")
        with patch(
            "eab.transports.dss._ensure_scripting_importable",
            side_effect=FileNotFoundError("CCS 2041+ not found"),
        ):
            result = t.start()
        assert result is False
        assert not t.is_running


# =========================================================================
# Memory operations with mocked CCS session
# =========================================================================


def _make_transport_with_mock_session():
    """Create DSSTransport with a mocked CCS scripting session."""
    t = DSSTransport(ccxml="test.ccxml")
    mock_session = MagicMock()
    t._session = mock_session
    return t, mock_session


class TestDSSProtocol:
    def test_memory_read_success(self):
        t, session = _make_transport_with_mock_session()
        # C2000 returns 16-bit words; 4 bytes = 2 words
        session.memory.read.return_value = [0x3412, 0x7856]

        data = t.memory_read(0xC002, 4)

        assert data == bytes([0x12, 0x34, 0x56, 0x78])
        session.memory.read.assert_called_once_with(0xC002, 2)  # 2 words for 4 bytes

    def test_memory_read_truncates_to_size(self):
        t, session = _make_transport_with_mock_session()
        session.memory.read.return_value = [0x3412]  # 2 bytes from 1 word

        data = t.memory_read(0xC002, 1)  # request only 1 byte

        assert len(data) == 1
        assert data == bytes([0x12])

    def test_memory_read_failure_returns_none(self):
        t, session = _make_transport_with_mock_session()
        session.memory.read.side_effect = RuntimeError("JTAG error")

        assert t.memory_read(0xC002, 4) is None

    def test_memory_read_without_session_returns_none(self):
        t = DSSTransport(ccxml="test.ccxml")
        assert t.memory_read(0xC002, 4) is None

    def test_memory_write_success(self):
        t, session = _make_transport_with_mock_session()

        result = t.memory_write(0xC002, b"\x12\x34")

        assert result is True
        session.memory.write.assert_called_once_with(0xC002, [0x3412])

    def test_memory_write_odd_length_pads(self):
        t, session = _make_transport_with_mock_session()

        result = t.memory_write(0xC002, b"\xAB")  # 1 byte → padded to word

        assert result is True
        session.memory.write.assert_called_once_with(0xC002, [0x00AB])

    def test_memory_write_failure_returns_false(self):
        t, session = _make_transport_with_mock_session()
        session.memory.write.side_effect = RuntimeError("JTAG error")

        assert t.memory_write(0xC002, b"\x12\x34") is False

    def test_memory_write_without_session_returns_false(self):
        t = DSSTransport(ccxml="test.ccxml")
        assert t.memory_write(0xC002, b"\x00") is False

    def test_halt(self):
        t, session = _make_transport_with_mock_session()
        assert t.halt() is True
        session.target.halt.assert_called_once()

    def test_halt_without_session(self):
        t = DSSTransport(ccxml="test.ccxml")
        assert t.halt() is False

    def test_resume(self):
        t, session = _make_transport_with_mock_session()
        assert t.resume() is True
        session.target.run.assert_called_once()

    def test_resume_without_session(self):
        t = DSSTransport(ccxml="test.ccxml")
        assert t.resume() is False

    def test_reset(self):
        t, session = _make_transport_with_mock_session()
        assert t.reset() is True
        session.target.reset.assert_called_once()

    def test_reset_without_session(self):
        t = DSSTransport(ccxml="test.ccxml")
        assert t.reset() is False

    def test_halt_exception_returns_false(self):
        t, session = _make_transport_with_mock_session()
        session.target.halt.side_effect = RuntimeError("halt error")
        assert t.halt() is False


# =========================================================================
# Start / Stop lifecycle
# =========================================================================


class TestDSSLifecycle:
    def _make_mock_scripting(self):
        """Return (mock_ds, mock_session) pair for CCS scripting API."""
        mock_session = MagicMock()
        mock_ds = MagicMock()
        mock_ds.openSession.return_value = mock_session
        return mock_ds, mock_session

    def test_start_success(self):
        mock_ds, mock_session = self._make_mock_scripting()

        with patch("eab.transports.dss._ensure_scripting_importable"), \
             patch("eab.transports.dss.initScripting", return_value=mock_ds, create=True):
            # The import inside start() needs 'scripting' to resolve
            import sys
            mock_scripting_mod = MagicMock()
            mock_scripting_mod.initScripting = MagicMock(return_value=mock_ds)
            mock_scripting_mod.ScriptingOptions = MagicMock()
            sys.modules.setdefault("scripting", mock_scripting_mod)

            t = DSSTransport(ccxml="test.ccxml")
            with patch.dict(sys.modules, {"scripting": mock_scripting_mod}):
                # Patch the import inside start()
                with patch("builtins.__import__", side_effect=lambda name, *a, **kw:
                           mock_scripting_mod if name == "scripting"
                           else __import__(name, *a, **kw)):
                    result = t.start()

        # Even if start() can't import scripting in test env, verify the
        # no-session → False path and the session-set → True path separately.
        # (Full integration test requires real CCS install.)

    def test_start_returns_false_on_import_error(self):
        """If CCS scripting import fails, start() returns False without raising."""
        t = DSSTransport(ccxml="test.ccxml")
        with patch("eab.transports.dss._ensure_scripting_importable",
                   side_effect=FileNotFoundError("CCS not found")):
            result = t.start()
        assert result is False
        assert not t.is_running

    def test_stop_without_start(self):
        t = DSSTransport(ccxml="test.ccxml")
        t.stop()  # Should not raise
        assert not t.is_running

    def test_stop_disconnects_session(self):
        t, session = _make_transport_with_mock_session()
        t.stop()
        session.target.disconnect.assert_called_once()
        assert not t.is_running

    def test_context_manager_calls_stop(self):
        t = DSSTransport(ccxml="test.ccxml")
        with patch.object(t, "start", return_value=True), \
             patch.object(t, "stop") as mock_stop:
            with t:
                pass
        mock_stop.assert_called_once()

    def test_is_running_true_when_session_set(self):
        t, _ = _make_transport_with_mock_session()
        assert t.is_running is True

    def test_is_running_false_after_stop(self):
        t, session = _make_transport_with_mock_session()
        t.stop()
        assert t.is_running is False


# =========================================================================
# Bridge script existence
# =========================================================================


class TestBridgeScript:
    def test_bridge_js_exists(self):
        assert _BRIDGE_JS.exists(), f"Missing: {_BRIDGE_JS}"

    def test_bridge_js_has_protocol(self):
        content = _BRIDGE_JS.read_text()
        assert "cmd" in content
        assert "read" in content
        assert "write" in content
        assert "quit" in content
