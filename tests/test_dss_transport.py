"""Tests for DSS transport (CCS scripting API)."""

from __future__ import annotations

import struct
from pathlib import Path
from unittest.mock import MagicMock, patch

import pytest

from eab.transports.dss import DSSTransport, find_dss, find_ccs_root, _BRIDGE_JS


# =========================================================================
# find_dss / find_ccs_root
# =========================================================================


class TestFindDss:
    @patch("eab.transports.dss._DSS_SEARCH_PATHS", [Path("/fake/dss.sh")])
    @patch("pathlib.Path.exists", return_value=True)
    def test_found(self, mock_exists):
        assert find_dss() == "/fake/dss.sh"

    @patch("eab.transports.dss._DSS_SEARCH_PATHS", [Path("/fake/dss.sh")])
    @patch("pathlib.Path.exists", return_value=False)
    def test_not_found(self, mock_exists):
        assert find_dss() is None


class TestFindCcsRoot:
    @patch("eab.transports.dss._CCS_SEARCH_PATHS", [Path("/fake/ccs")])
    @patch("pathlib.Path.exists", return_value=True)
    def test_found(self, mock_exists):
        assert find_ccs_root() == Path("/fake/ccs")

    @patch("eab.transports.dss._CCS_SEARCH_PATHS", [Path("/fake/ccs")])
    @patch("pathlib.Path.exists", return_value=False)
    def test_not_found(self, mock_exists):
        assert find_ccs_root() is None


# =========================================================================
# DSSTransport init
# =========================================================================


class TestDSSTransportInit:
    def test_init(self):
        t = DSSTransport(ccxml="/path/to/target.ccxml")
        assert t._ccxml == "/path/to/target.ccxml"

    def test_not_running_initially(self):
        t = DSSTransport(ccxml="/path/to/target.ccxml")
        assert t.is_running is False

    def test_init_with_ccs_root(self):
        t = DSSTransport(ccxml="/path/to/target.ccxml", ccs_root="/opt/ti/ccs2041/ccs")
        assert t._ccs_root == Path("/opt/ti/ccs2041/ccs")

    def test_init_with_timeout(self):
        t = DSSTransport(ccxml="/path/to/target.ccxml", timeout=5.0)
        assert t._timeout_ms == 5000


# =========================================================================
# Memory operations (mocked CCS scripting session)
# =========================================================================


class TestDSSMemoryOps:
    def _make_connected_transport(self):
        """Create a DSSTransport with a mocked CCS session."""
        t = DSSTransport(ccxml="test.ccxml")
        t._session = MagicMock()
        t._ds = MagicMock()
        return t

    def test_memory_read(self):
        t = self._make_connected_transport()
        # Simulate reading 2 words (4 bytes) from C2000
        t._session.memory.read.return_value = [0x3412, 0x7856]
        data = t.memory_read(0xC002, 4)
        assert data == struct.pack("<HH", 0x3412, 0x7856)
        t._session.memory.read.assert_called_once_with(0xC002, 2)

    def test_memory_read_odd_size(self):
        t = self._make_connected_transport()
        t._session.memory.read.return_value = [0x00FF]
        data = t.memory_read(0xC002, 1)
        assert len(data) == 1
        assert data == b"\xff"

    def test_memory_read_not_connected(self):
        t = DSSTransport(ccxml="test.ccxml")
        assert t.memory_read(0xC002, 4) is None

    def test_memory_read_exception(self):
        t = self._make_connected_transport()
        t._session.memory.read.side_effect = RuntimeError("JTAG error")
        assert t.memory_read(0xC002, 4) is None

    def test_memory_write(self):
        t = self._make_connected_transport()
        result = t.memory_write(0xC002, b"\x12\x34")
        assert result is True
        t._session.memory.write.assert_called_once_with(0xC002, [0x3412])

    def test_memory_write_not_connected(self):
        t = DSSTransport(ccxml="test.ccxml")
        assert t.memory_write(0xC002, b"\x12\x34") is False

    def test_memory_write_exception(self):
        t = self._make_connected_transport()
        t._session.memory.write.side_effect = RuntimeError("JTAG error")
        assert t.memory_write(0xC002, b"\x12\x34") is False


# =========================================================================
# CPU control
# =========================================================================


class TestDSSCpuControl:
    def _make_connected_transport(self):
        t = DSSTransport(ccxml="test.ccxml")
        t._session = MagicMock()
        t._ds = MagicMock()
        return t

    def test_halt(self):
        t = self._make_connected_transport()
        assert t.halt() is True
        t._session.target.halt.assert_called_once()

    def test_halt_not_connected(self):
        t = DSSTransport(ccxml="test.ccxml")
        assert t.halt() is False

    def test_halt_exception(self):
        t = self._make_connected_transport()
        t._session.target.halt.side_effect = RuntimeError("target error")
        assert t.halt() is False

    def test_resume(self):
        t = self._make_connected_transport()
        assert t.resume() is True
        t._session.target.run.assert_called_once()

    def test_resume_not_connected(self):
        t = DSSTransport(ccxml="test.ccxml")
        assert t.resume() is False

    def test_reset(self):
        t = self._make_connected_transport()
        assert t.reset() is True
        t._session.target.reset.assert_called_once()

    def test_reset_not_connected(self):
        t = DSSTransport(ccxml="test.ccxml")
        assert t.reset() is False


# =========================================================================
# Start / Stop lifecycle
# =========================================================================


class TestDSSLifecycle:
    @patch("eab.transports.dss._ensure_scripting_importable")
    def test_start_failure_no_ccs(self, mock_ensure):
        mock_ensure.side_effect = FileNotFoundError("CCS 2041+ not found")
        t = DSSTransport(ccxml="test.ccxml")
        result = t.start()
        assert result is False
        assert t.is_running is False

    def test_stop_without_start(self):
        t = DSSTransport(ccxml="test.ccxml")
        t.stop()
        assert t.is_running is False

    def test_stop_cleans_up(self):
        t = DSSTransport(ccxml="test.ccxml")
        t._session = MagicMock()
        t._ds = MagicMock()
        t.stop()
        assert t._session is None
        assert t._ds is None
        assert t.is_running is False

    @patch("eab.transports.dss._ensure_scripting_importable")
    def test_context_manager_calls_stop(self, mock_ensure):
        mock_ensure.return_value = Path("/fake/ccs")
        t = DSSTransport(ccxml="test.ccxml")

        # Mock the scripting import that happens inside start()
        mock_ds = MagicMock()
        mock_session = MagicMock()
        mock_ds.openSession.return_value = mock_session

        with patch.dict("sys.modules", {"scripting": MagicMock()}):
            with patch("eab.transports.dss.DSSTransport.start") as mock_start:
                mock_start.side_effect = lambda: setattr(t, "_session", mock_session) or setattr(t, "_ds", mock_ds) or True
                with t:
                    assert t.is_running
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
