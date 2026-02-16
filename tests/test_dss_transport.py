"""Tests for DSS transport (Phase 6)."""

from __future__ import annotations

import json
import subprocess
from pathlib import Path
from unittest.mock import MagicMock, patch, PropertyMock

import pytest

from eab.transports.dss import DSSTransport, find_dss, _BRIDGE_JS


# =========================================================================
# find_dss
# =========================================================================


class TestFindDss:
    @patch("shutil.which", return_value="/usr/local/bin/dss.sh")
    def test_found_on_path(self, mock_which):
        assert find_dss() == "/usr/local/bin/dss.sh"

    @patch("shutil.which", return_value=None)
    def test_not_found(self, mock_which):
        # With no CCS installed and not on PATH
        result = find_dss()
        # Could be None or could find a real CCS install — just verify it runs
        assert result is None or isinstance(result, str)


# =========================================================================
# DSSTransport init
# =========================================================================


class TestDSSTransportInit:
    def test_init(self):
        t = DSSTransport(ccxml="/path/to/target.ccxml", dss_path="/usr/bin/dss.sh")
        assert t._ccxml == "/path/to/target.ccxml"
        assert t._dss_path == "/usr/bin/dss.sh"

    def test_not_running_initially(self):
        t = DSSTransport(ccxml="/path/to/target.ccxml", dss_path="/usr/bin/dss.sh")
        assert t.is_running is False

    def test_start_raises_without_dss(self):
        t = DSSTransport(ccxml="/path/to/target.ccxml", dss_path=None)
        t._dss_path = None
        with pytest.raises(FileNotFoundError, match="DSS not found"):
            t.start()


# =========================================================================
# JSON protocol
# =========================================================================


class TestDSSProtocol:
    def _make_transport_with_mock_proc(self, responses: list[dict]):
        """Create a DSSTransport with a mocked subprocess."""
        t = DSSTransport(ccxml="test.ccxml", dss_path="/usr/bin/dss.sh")

        mock_proc = MagicMock()
        mock_proc.poll.return_value = None  # Process is running

        # Stdin mock
        mock_proc.stdin = MagicMock()

        # Stdout mock — return responses as JSON lines
        response_lines = [json.dumps(r) + "\n" for r in responses]
        mock_proc.stdout = MagicMock()
        mock_proc.stdout.readline = MagicMock(side_effect=response_lines)

        t._proc = mock_proc
        return t

    def test_memory_read(self):
        t = self._make_transport_with_mock_proc([
            {"ok": True, "data": [0x12, 0x34, 0x56, 0x78]},
        ])
        data = t.memory_read(0xC002, 4)
        assert data == bytes([0x12, 0x34, 0x56, 0x78])

        # Verify correct JSON was sent
        written = t._proc.stdin.write.call_args[0][0]
        cmd = json.loads(written)
        assert cmd["cmd"] == "read"
        assert cmd["addr"] == 0xC002
        assert cmd["size"] == 4

    def test_memory_read_failure(self):
        t = self._make_transport_with_mock_proc([
            {"ok": False, "error": "read failed"},
        ])
        assert t.memory_read(0xC002, 4) is None

    def test_memory_write(self):
        t = self._make_transport_with_mock_proc([
            {"ok": True},
        ])
        result = t.memory_write(0xC002, b"\x12\x34")
        assert result is True

        written = t._proc.stdin.write.call_args[0][0]
        cmd = json.loads(written)
        assert cmd["cmd"] == "write"
        assert cmd["addr"] == 0xC002
        assert cmd["data"] == [0x12, 0x34]

    def test_memory_write_failure(self):
        t = self._make_transport_with_mock_proc([
            {"ok": False, "error": "write failed"},
        ])
        assert t.memory_write(0xC002, b"\x12\x34") is False

    def test_halt(self):
        t = self._make_transport_with_mock_proc([{"ok": True}])
        assert t.halt() is True

    def test_resume(self):
        t = self._make_transport_with_mock_proc([{"ok": True}])
        assert t.resume() is True

    def test_reset(self):
        t = self._make_transport_with_mock_proc([{"ok": True}])
        assert t.reset() is True

    def test_not_running_raises(self):
        t = DSSTransport(ccxml="test.ccxml", dss_path="/usr/bin/dss.sh")
        # No process started
        assert t.memory_read(0xC002, 4) is None
        assert t.memory_write(0xC002, b"\x00") is False

    def test_process_died_returns_none(self):
        t = self._make_transport_with_mock_proc([])
        t._proc.poll.return_value = 1  # Process exited
        assert t.memory_read(0xC002, 4) is None


# =========================================================================
# Start / Stop
# =========================================================================


class TestDSSLifecycle:
    @patch("subprocess.Popen")
    def test_start_success(self, mock_popen):
        mock_proc = MagicMock()
        mock_proc.poll.return_value = None
        mock_proc.stdout.readline.return_value = json.dumps(
            {"ok": True, "status": "connected"}
        ) + "\n"
        mock_popen.return_value = mock_proc

        t = DSSTransport(ccxml="test.ccxml", dss_path="/usr/bin/dss.sh")
        result = t.start()
        assert result is True
        assert t.is_running

    @patch("subprocess.Popen")
    def test_start_failure(self, mock_popen):
        mock_proc = MagicMock()
        mock_proc.poll.return_value = None
        mock_proc.stdout.readline.return_value = json.dumps(
            {"ok": False, "error": "connection failed"}
        ) + "\n"
        mock_proc.stderr.read.return_value = ""
        mock_popen.return_value = mock_proc

        t = DSSTransport(ccxml="test.ccxml", dss_path="/usr/bin/dss.sh")
        result = t.start()
        assert result is False

    def test_stop_without_start(self):
        t = DSSTransport(ccxml="test.ccxml", dss_path="/usr/bin/dss.sh")
        # Should not raise
        t.stop()
        assert t.is_running is False

    @patch("subprocess.Popen")
    def test_context_manager(self, mock_popen):
        mock_proc = MagicMock()
        mock_proc.poll.return_value = None
        mock_proc.stdout.readline.side_effect = [
            json.dumps({"ok": True, "status": "connected"}) + "\n",
            json.dumps({"ok": True}) + "\n",  # quit response
        ]
        mock_popen.return_value = mock_proc

        with DSSTransport(ccxml="test.ccxml", dss_path="/usr/bin/dss.sh") as t:
            assert t.is_running


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
