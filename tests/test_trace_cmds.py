"""Tests for eabctl trace start/stop/export commands."""

from __future__ import annotations

import json
import os
import signal
import struct
import time
from pathlib import Path
from unittest.mock import MagicMock, patch

import pytest

from eab.cli.trace.cmd_start import (
    _emit,
    _is_trace_running,
    _resolve_log_path,
    cmd_trace_start,
)
from eab.cli.trace.cmd_stop import cmd_trace_stop
from eab.cli.trace.cmd_export import cmd_trace_export
from eab.cli.trace.perfetto import rttbin_to_perfetto
from eab.rtt_binary import BinaryWriter


# ── _resolve_log_path ────────────────────────────────────────────────────


class TestResolveLogPath:
    def test_rtt_returns_none(self):
        assert _resolve_log_path("rtt", None, None, "NRF5340_XXAA_APP") is None

    def test_serial_with_trace_dir(self, tmp_path):
        result = _resolve_log_path("serial", str(tmp_path), None, "NRF5340_XXAA_APP")
        assert result == str((tmp_path / "latest.log").resolve())

    def test_serial_auto_derive_nrf5340(self):
        result = _resolve_log_path("serial", None, None, "NRF5340_XXAA_APP")
        assert result is not None
        assert "nrf5340" in result
        assert result.endswith("latest.log")

    def test_serial_auto_derive_mcxn947(self):
        result = _resolve_log_path("serial", None, None, "MCXN947")
        assert result is not None
        assert "mcxn947" in result

    def test_logfile_mode(self, tmp_path):
        log = tmp_path / "test.log"
        result = _resolve_log_path("logfile", None, str(log), "X")
        assert result == str(log.resolve())


# ── _is_trace_running ───────────────────────────────────────────────────


class TestIsTraceRunning:
    def test_no_pid_file(self, tmp_path):
        assert _is_trace_running(tmp_path / "nope.pid") is False

    def test_stale_pid_file(self, tmp_path):
        pid_file = tmp_path / "trace.pid"
        pid_file.write_text("999999999")  # almost certainly dead
        assert _is_trace_running(pid_file) is False
        assert not pid_file.exists()  # cleaned up

    def test_own_pid_detected(self, tmp_path):
        pid_file = tmp_path / "trace.pid"
        pid_file.write_text(str(os.getpid()))
        assert _is_trace_running(pid_file) is True

    def test_invalid_pid_file(self, tmp_path):
        pid_file = tmp_path / "trace.pid"
        pid_file.write_text("not-a-number")
        assert _is_trace_running(pid_file) is False


# ── _emit ────────────────────────────────────────────────────────────────


class TestEmit:
    def test_json_mode(self, capsys):
        _emit({"key": "val"}, json_mode=True)
        assert json.loads(capsys.readouterr().out) == {"key": "val"}

    def test_human_error(self, capsys):
        _emit({"error": "bad"}, json_mode=False, error=True)
        assert "Error: bad" in capsys.readouterr().out

    def test_human_non_error(self, capsys):
        _emit({"a": 1, "b": 2}, json_mode=False)
        out = capsys.readouterr().out
        assert "a: 1" in out
        assert "b: 2" in out


# ── cmd_trace_start argument validation ──────────────────────────────────


class TestCmdTraceStartValidation:
    def test_logfile_requires_logfile_arg(self, capsys):
        rc = cmd_trace_start(output="/tmp/t.rttbin", source="logfile")
        assert rc == 1
        out = capsys.readouterr().out
        assert "--logfile is required" in out

    def test_logfile_requires_logfile_arg_json(self, capsys):
        rc = cmd_trace_start(
            output="/tmp/t.rttbin", source="logfile", json_mode=True
        )
        assert rc == 1
        data = json.loads(capsys.readouterr().out)
        assert "--logfile" in data["error"]

    def test_nonexistent_logfile(self, capsys, tmp_path):
        rc = cmd_trace_start(
            output="/tmp/t.rttbin",
            source="logfile",
            logfile=str(tmp_path / "nope.log"),
            json_mode=True,
        )
        assert rc == 1
        data = json.loads(capsys.readouterr().out)
        assert "not found" in data["error"]

    def test_nonexistent_trace_dir(self, capsys, tmp_path):
        rc = cmd_trace_start(
            output="/tmp/t.rttbin",
            source="serial",
            trace_dir=str(tmp_path / "nope"),
            json_mode=True,
        )
        assert rc == 1
        data = json.loads(capsys.readouterr().out)
        assert "not found" in data["error"]

    def test_already_running(self, capsys, tmp_path):
        pid_file = Path("/tmp/eab-trace.pid")
        pid_file.write_text(str(os.getpid()))
        try:
            rc = cmd_trace_start(
                output="/tmp/t.rttbin", source="rtt", json_mode=True
            )
            assert rc == 1
            data = json.loads(capsys.readouterr().out)
            assert "already running" in data["error"]
        finally:
            pid_file.unlink(missing_ok=True)


# ── cmd_trace_stop ───────────────────────────────────────────────────────


class TestCmdTraceStop:
    def test_no_trace_running(self, capsys):
        pid_file = Path("/tmp/eab-trace.pid")
        pid_file.unlink(missing_ok=True)
        rc = cmd_trace_stop(json_mode=True)
        assert rc == 1
        data = json.loads(capsys.readouterr().out)
        assert "No trace" in data["error"]

    def test_invalid_pid_file(self, capsys):
        pid_file = Path("/tmp/eab-trace.pid")
        pid_file.write_text("garbage")
        try:
            rc = cmd_trace_stop(json_mode=True)
            assert rc == 1
        finally:
            pid_file.unlink(missing_ok=True)

    def test_process_already_dead(self, capsys):
        pid_file = Path("/tmp/eab-trace.pid")
        pid_file.write_text("999999999")
        try:
            rc = cmd_trace_stop(json_mode=True)
            assert rc == 0
            data = json.loads(capsys.readouterr().out)
            assert data["stopped"] is True
        finally:
            pid_file.unlink(missing_ok=True)


# ── Perfetto converter ───────────────────────────────────────────────────


class TestRttbinToPerfetto:
    def _write_rttbin(self, path: Path, lines: list[str]) -> None:
        """Write a minimal .rttbin file with text lines as frames."""
        writer = BinaryWriter(
            path, channels=[0], sample_width=1, timestamp_hz=1000
        )
        for i, line in enumerate(lines):
            writer.write_frame(
                channel=0,
                payload=(line + "\n").encode(),
                timestamp=i * 100,
            )
        writer.close()

    def test_basic_conversion(self, tmp_path):
        rttbin = tmp_path / "test.rttbin"
        out_json = tmp_path / "test.json"
        self._write_rttbin(rttbin, ["hello world", "line two"])

        summary = rttbin_to_perfetto(rttbin, out_json)
        assert summary["frame_count"] == 2
        assert summary["event_count"] == 4  # 2 instant + 2 counter
        assert 0 in summary["channels"]
        assert out_json.exists()

        data = json.loads(out_json.read_text())
        assert "traceEvents" in data
        instant_events = [e for e in data["traceEvents"] if e.get("ph") == "i"]
        assert len(instant_events) == 2
        assert instant_events[0]["name"] == "hello world"

    def test_empty_rttbin(self, tmp_path):
        rttbin = tmp_path / "empty.rttbin"
        out_json = tmp_path / "empty.json"
        writer = BinaryWriter(
            rttbin, channels=[0], sample_width=1, timestamp_hz=1000
        )
        writer.close()

        summary = rttbin_to_perfetto(rttbin, out_json)
        assert summary["frame_count"] == 0
        assert summary["event_count"] == 0

    def test_long_line_truncated_in_name(self, tmp_path):
        rttbin = tmp_path / "long.rttbin"
        out_json = tmp_path / "long.json"
        self._write_rttbin(rttbin, ["x" * 200])

        summary = rttbin_to_perfetto(rttbin, out_json)
        data = json.loads(out_json.read_text())
        instant = [e for e in data["traceEvents"] if e.get("ph") == "i"][0]
        assert len(instant["name"]) == 80  # truncated
        assert len(instant["args"]["raw"]) == 200  # full in args


# ── cmd_trace_export ─────────────────────────────────────────────────────


class TestCmdTraceExport:
    def test_missing_input(self, capsys, tmp_path):
        rc = cmd_trace_export(
            input=str(tmp_path / "nope.rttbin"),
            output=str(tmp_path / "out.json"),
            json_mode=True,
        )
        assert rc == 1
        data = json.loads(capsys.readouterr().out)
        assert "not found" in data["error"]

    def test_perfetto_export(self, capsys, tmp_path):
        # Write a test .rttbin
        rttbin = tmp_path / "test.rttbin"
        writer = BinaryWriter(
            rttbin, channels=[0], sample_width=1, timestamp_hz=1000
        )
        writer.write_frame(channel=0, payload=b"test line\n", timestamp=0)
        writer.close()

        out_json = tmp_path / "test.json"
        rc = cmd_trace_export(
            input=str(rttbin),
            output=str(out_json),
            json_mode=True,
        )
        assert rc == 0
        data = json.loads(capsys.readouterr().out)
        assert data["exported"] is True
        assert data["format"] == "perfetto"
        assert data["frame_count"] == 1
