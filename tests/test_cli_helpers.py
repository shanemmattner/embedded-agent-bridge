"""Tests for eab/cli/helpers.py — shared CLI utilities."""

from __future__ import annotations

import json
import os
import time

import pytest

from eab.cli.helpers import (
    _now_iso,
    _print,
    _resolve_base_dir,
    _read_text,
    _tail_lines,
    _read_bytes,
    _parse_event_line,
    _tail_events,
    _parse_log_line,
    _event_matches,
)


class TestNowIso:
    def test_returns_iso_format(self):
        result = _now_iso()
        assert "T" in result
        assert len(result) == 19  # YYYY-MM-DDTHH:MM:SS


class TestPrint:
    def test_json_mode(self, capsys):
        _print({"key": "val"}, json_mode=True)
        out = capsys.readouterr().out
        data = json.loads(out)
        assert data["key"] == "val"

    def test_text_mode_string(self, capsys):
        _print("hello", json_mode=False)
        assert "hello" in capsys.readouterr().out

    def test_text_mode_dict(self, capsys):
        _print({"a": 1}, json_mode=False)
        out = capsys.readouterr().out
        assert json.loads(out)["a"] == 1


class TestResolveBaseDir:
    def test_explicit_override(self, monkeypatch):
        monkeypatch.setenv("EAB_RUN_DIR", "/tmp/test")
        assert _resolve_base_dir("/my/dir") == "/my/dir"

    def test_device_name(self, tmp_path, monkeypatch):
        monkeypatch.setenv("EAB_RUN_DIR", str(tmp_path))
        result = _resolve_base_dir(None, device="nrf5340")
        assert result.endswith("nrf5340")

    def test_default_fallback(self, tmp_path, monkeypatch):
        monkeypatch.setenv("EAB_RUN_DIR", str(tmp_path))
        result = _resolve_base_dir(None)
        assert result.endswith("default")
        assert "eab-devices" in result


class TestReadText:
    def test_reads_file(self, tmp_path):
        f = tmp_path / "test.txt"
        f.write_text("hello world")
        assert _read_text(str(f)) == "hello world"

    def test_missing_file_raises(self, tmp_path):
        with pytest.raises(FileNotFoundError):
            _read_text(str(tmp_path / "nope"))


class TestTailLines:
    def test_basic_tail(self, tmp_path):
        f = tmp_path / "log.txt"
        f.write_text("a\nb\nc\nd\ne\n")
        assert _tail_lines(str(f), 3) == ["c", "d", "e"]

    def test_fewer_lines(self, tmp_path):
        f = tmp_path / "log.txt"
        f.write_text("a\nb\n")
        assert _tail_lines(str(f), 10) == ["a", "b"]

    def test_zero_lines(self, tmp_path):
        f = tmp_path / "log.txt"
        f.write_text("a\nb\n")
        assert _tail_lines(str(f), 0) == []

    def test_missing_file(self, tmp_path):
        assert _tail_lines(str(tmp_path / "nope"), 10) == []


class TestReadBytes:
    def test_reads_range(self, tmp_path):
        f = tmp_path / "data.bin"
        f.write_bytes(b"\x00\x01\x02\x03\x04")
        assert _read_bytes(str(f), 1, 3) == b"\x01\x02\x03"

    def test_zero_length(self, tmp_path):
        f = tmp_path / "data.bin"
        f.write_bytes(b"\x00\x01")
        assert _read_bytes(str(f), 0, 0) == b""


class TestParseEventLine:
    def test_valid_json(self):
        result = _parse_event_line('{"type": "alert"}')
        assert result["type"] == "alert"

    def test_invalid_json(self):
        result = _parse_event_line("not json")
        assert result["error"] == "invalid_json"
        assert result["raw"] == "not json"


class TestTailEvents:
    def test_parses_jsonl(self, tmp_path):
        f = tmp_path / "events.jsonl"
        f.write_text('{"type":"a"}\n{"type":"b"}\n{"type":"c"}\n')
        events = _tail_events(str(f), 2)
        assert len(events) == 2
        assert events[0]["type"] == "b"
        assert events[1]["type"] == "c"


class TestParseLogLine:
    def test_with_timestamp(self):
        result = _parse_log_line("[12:34:56.789] Hello world")
        assert result["timestamp"] == "12:34:56.789"
        assert result["content"] == "Hello world"

    def test_without_timestamp(self):
        result = _parse_log_line("plain text")
        assert result["timestamp"] is None
        assert result["content"] == "plain text"


class TestEventMatches:
    def test_type_filter(self):
        event = {"type": "alert", "data": {}}
        assert _event_matches(event, event_type="alert", contains=None, command=None) is True
        assert _event_matches(event, event_type="other", contains=None, command=None) is False

    def test_command_filter(self):
        event = {"type": "command_sent", "data": {"command": "reset"}}
        assert _event_matches(event, event_type=None, contains=None, command="reset") is True
        assert _event_matches(event, event_type=None, contains=None, command="help") is False

    def test_contains_filter(self):
        event = {"type": "alert", "message": "watchdog fired"}
        assert _event_matches(event, event_type=None, contains="watchdog", command=None) is True
        assert _event_matches(event, event_type=None, contains="missing", command=None) is False

    def test_all_none_matches_everything(self):
        assert _event_matches({}, event_type=None, contains=None, command=None) is True
