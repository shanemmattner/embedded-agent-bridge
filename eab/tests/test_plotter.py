"""Tests for the EAB RTT plotter (server.py).

Covers:
- RTTStreamProcessor line parsing (data, state, log formats)
- Buffer cap: unbounded no-newline data gets capped
- _enqueue: backpressure drop policy
- tail_log: file-tailing with buffer cap
- run_plotter: signature accepts new params
"""

from __future__ import annotations

import asyncio
import inspect
import os
import tempfile
from unittest.mock import AsyncMock, patch

import pytest

from eab.plotter.server import (
    _BUFFER_CAP,
    _enqueue,
    _enqueue_status,
    run_plotter,
    tail_log,
)
from eab.rtt_stream import RTTStreamProcessor


# ---------------------------------------------------------------------------
# RTTStreamProcessor parsing (replaces parse_rtt_line tests)
# ---------------------------------------------------------------------------


class TestRTTStreamParsing:
    """Test RTTStreamProcessor parses lines correctly."""

    def _parse(self, line: str) -> list[dict]:
        """Helper: feed a single line through processor, return records."""
        proc = RTTStreamProcessor()
        return proc.feed((line + "\n").encode("utf-8"))

    def test_data_line_basic(self):
        results = self._parse("DATA: sine_a=0.68 sine_b=0.72 temp=22.95")
        data_results = [r for r in results if r["type"] == "data"]
        assert len(data_results) == 1
        assert data_results[0]["values"]["sine_a"] == pytest.approx(0.68)
        assert data_results[0]["values"]["sine_b"] == pytest.approx(0.72)
        assert data_results[0]["values"]["temp"] == pytest.approx(22.95)

    def test_data_line_with_timestamp(self):
        results = self._parse("[00:01:23.456] DATA: voltage=3.3")
        data_results = [r for r in results if r["type"] == "data"]
        assert len(data_results) == 1
        assert data_results[0]["ts"] == "00:01:23.456"
        assert data_results[0]["values"]["voltage"] == pytest.approx(3.3)

    def test_data_line_with_ansi(self):
        results = self._parse("\x1b[32mDATA: x=1.0\x1b[0m")
        data_results = [r for r in results if r["type"] == "data"]
        assert len(data_results) == 1
        assert data_results[0]["values"]["x"] == pytest.approx(1.0)

    def test_data_line_negative_values(self):
        results = self._parse("DATA: accel_x=-9.81 accel_y=0.0")
        data_results = [r for r in results if r["type"] == "data"]
        assert len(data_results) == 1
        assert data_results[0]["values"]["accel_x"] == pytest.approx(-9.81)
        assert data_results[0]["values"]["accel_y"] == pytest.approx(0.0)

    def test_state_line(self):
        results = self._parse("STATE: IDLE")
        state_results = [r for r in results if r["type"] == "state"]
        assert len(state_results) == 1
        assert state_results[0]["state"] == "IDLE"

    def test_state_line_with_timestamp(self):
        results = self._parse("[00:00:01.000] STATE: RUNNING")
        state_results = [r for r in results if r["type"] == "state"]
        assert len(state_results) == 1
        assert state_results[0]["ts"] == "00:00:01.000"
        assert state_results[0]["state"] == "RUNNING"

    def test_empty_line(self):
        results = self._parse("")
        assert len(results) == 0

    def test_ansi_only(self):
        results = self._parse("\x1b[0m\x1b[32m")
        assert len(results) == 0

    def test_generic_log_line(self):
        """Non-DATA/STATE lines should still produce a log record."""
        results = self._parse("just some random text")
        assert len(results) == 1
        assert results[0]["type"] == "log"

    def test_data_without_kvs(self):
        """DATA: with no key=value pairs produces a log record, not data."""
        results = self._parse("DATA: no values here")
        data_results = [r for r in results if r["type"] == "data"]
        assert len(data_results) == 0


# ---------------------------------------------------------------------------
# _enqueue backpressure
# ---------------------------------------------------------------------------


class TestEnqueue:
    def test_enqueue_normal(self):
        q = asyncio.Queue(maxsize=3)
        _enqueue(q, {"type": "data"})
        assert q.qsize() == 1

    def test_enqueue_overflow_drops_oldest(self):
        q = asyncio.Queue(maxsize=2)
        _enqueue(q, {"n": 1})
        _enqueue(q, {"n": 2})
        _enqueue(q, {"n": 3})  # Should drop n=1, add n=3
        assert q.qsize() == 2
        items = [q.get_nowait() for _ in range(2)]
        nums = [i["n"] for i in items]
        assert nums == [2, 3]

    def test_enqueue_status(self):
        q = asyncio.Queue(maxsize=10)
        _enqueue_status(q, "test message")
        item = q.get_nowait()
        assert item["type"] == "status"
        assert item["message"] == "test message"


# ---------------------------------------------------------------------------
# tail_log
# ---------------------------------------------------------------------------


class TestTailLog:
    @pytest.mark.asyncio
    async def test_tail_log_parses_data_lines(self, tmp_path):
        """tail_log should parse DATA: lines and enqueue them."""
        log_file = tmp_path / "test.log"
        log_file.write_text("")

        q = asyncio.Queue(maxsize=100)

        # Start tailing
        task = asyncio.create_task(tail_log(str(log_file), q, poll_interval=0.05))
        await asyncio.sleep(0.1)

        # Write some data
        with open(log_file, "a") as f:
            f.write("DATA: temp=25.5 humidity=60.0\n")
            f.write("some log line\n")
            f.write("DATA: temp=26.0 humidity=59.0\n")

        await asyncio.sleep(0.3)
        task.cancel()
        try:
            await task
        except asyncio.CancelledError:
            pass

        items = []
        while not q.empty():
            items.append(q.get_nowait())

        data_items = [i for i in items if i.get("type") == "data"]
        assert len(data_items) == 2
        assert data_items[0]["values"]["temp"] == pytest.approx(25.5)
        assert data_items[1]["values"]["temp"] == pytest.approx(26.0)

    @pytest.mark.asyncio
    async def test_tail_log_handles_truncation(self, tmp_path):
        """tail_log should reset pos when file is truncated."""
        log_file = tmp_path / "test.log"
        big_initial = "DATA: x=1.0\n" * 100
        log_file.write_text(big_initial)

        q = asyncio.Queue(maxsize=1000)

        task = asyncio.create_task(tail_log(str(log_file), q, poll_interval=0.05))
        await asyncio.sleep(0.5)

        # Drain the queue
        while not q.empty():
            q.get_nowait()

        # Truncate to a shorter file (simulates new session)
        log_file.write_text("DATA: x=99.0\n")
        await asyncio.sleep(0.5)

        task.cancel()
        try:
            await task
        except asyncio.CancelledError:
            pass

        items = []
        while not q.empty():
            items.append(q.get_nowait())

        assert any(
            i.get("type") == "data" and i["values"]["x"] == pytest.approx(99.0)
            for i in items
        ), f"Expected x=99.0 in items, got: {items}"


# ---------------------------------------------------------------------------
# run_plotter signature
# ---------------------------------------------------------------------------


class TestRunPlotterSignature:
    def test_accepts_new_params(self):
        sig = inspect.signature(run_plotter)
        params = list(sig.parameters.keys())
        assert "host" in params
        assert "port" in params
        assert "device" in params
        assert "block_address" in params
        assert "log_path" in params
        assert "base_dir" in params
        assert "open_browser" in params
        assert "interface" in params
        assert "speed" in params

    def test_log_path_default_is_none(self):
        sig = inspect.signature(run_plotter)
        assert sig.parameters["log_path"].default is None

    def test_device_default_is_none(self):
        sig = inspect.signature(run_plotter)
        assert sig.parameters["device"].default is None


# ---------------------------------------------------------------------------
# jlink_bridge fd leak fix
# ---------------------------------------------------------------------------


class TestJLinkBridgeFdLeak:
    def test_start_process_closes_file_handles(self, tmp_path, monkeypatch):
        """File handles should be closed after Popen, even on success."""
        from eab.jlink_bridge import JLinkBridge, JLinkRTTStatus

        bridge = JLinkBridge(str(tmp_path))

        closed_handles = []
        original_open = open

        class TrackingFile:
            def __init__(self, *args, **kwargs):
                self._f = original_open(*args, **kwargs)
                self._closed = False

            def close(self):
                self._closed = True
                closed_handles.append(self)
                return self._f.close()

            def __getattr__(self, name):
                return getattr(self._f, name)

        class FakeProc:
            def __init__(self):
                self.pid = 99999

            def poll(self):
                return None

        def fake_popen(*args, **kwargs):
            return FakeProc()

        monkeypatch.setattr("eab.jlink_bridge.subprocess.Popen", fake_popen)
        monkeypatch.setattr("eab.jlink_bridge._pid_alive", lambda pid: True)
        monkeypatch.setattr("builtins.open", lambda *a, **kw: TrackingFile(*a, **kw))

        bridge._start_process(
            cmd=["echo", "test"],
            pid_path=tmp_path / "test.pid",
            log_path=tmp_path / "test.log",
            err_path=tmp_path / "test.err",
            status_path=tmp_path / "test.status.json",
            extra_status={"device": "TEST"},
            status_factory=lambda running, pid, last_error: JLinkRTTStatus(
                running=running, device="TEST", log_path=str(tmp_path / "test.log"),
            ),
        )

        # At least 2 handles should have been closed (log_f and err_f)
        assert len(closed_handles) >= 2
        assert all(h._closed for h in closed_handles)
