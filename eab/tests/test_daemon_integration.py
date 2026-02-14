"""
Integration tests for the main daemon orchestration.

These focus on `eab/daemon.py` wiring rather than individual component unit tests.
"""

from __future__ import annotations

import json
import os
import runpy
import sys
from dataclasses import dataclass
from pathlib import Path

import pytest

# Add parent directory to path for imports (consistent with existing tests).
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__)))))

from eab.interfaces import PortInfo
from eab.mocks import MockClock, MockLogger, MockSerialPort


def _read_jsonl(path: Path) -> list[dict]:
    if not path.exists():
        return []
    events: list[dict] = []
    for line in path.read_text(encoding="utf-8").splitlines():
        if line.strip():
            events.append(json.loads(line))
    return events


def _isolate_singleton_and_locks(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    import eab.port_lock
    import eab.singleton

    monkeypatch.setattr(
        eab.singleton.SingletonDaemon, "PID_FILE", str(tmp_path / "eab-daemon.pid")
    )
    monkeypatch.setattr(
        eab.singleton.SingletonDaemon, "INFO_FILE", str(tmp_path / "eab-daemon.info")
    )
    monkeypatch.setattr(eab.port_lock.PortLock, "LOCK_DIR", str(tmp_path / "locks"))


def _make_daemon(tmp_path: Path, monkeypatch: pytest.MonkeyPatch):
    import eab.daemon as daemon_mod

    _isolate_singleton_and_locks(tmp_path, monkeypatch)

    # Avoid external tooling (e.g. lsof) in tests.
    monkeypatch.setattr(daemon_mod, "find_port_users", lambda _port: [])
    monkeypatch.setattr(daemon_mod, "list_all_locks", lambda: [])

    base_dir = tmp_path / "session"
    port_path = tmp_path / "fake_serial_port"
    port_path.write_text("", encoding="utf-8")  # Make os.path.exists() true for reconnection checks.

    serial = MockSerialPort()
    clock = MockClock()
    logger = MockLogger()

    daemon = daemon_mod.SerialDaemon(
        port=str(port_path),
        baud=115200,
        base_dir=str(base_dir),
        auto_detect=False,
        serial_port=serial,
        clock=clock,
        logger=logger,
    )

    return daemon, serial, base_dir


def test_daemon_start_process_line_and_cmd_roundtrip(tmp_path: Path, monkeypatch: pytest.MonkeyPatch, capsys):
    from eab.command_file import append_command

    daemon, serial, base_dir = _make_daemon(tmp_path, monkeypatch)

    assert daemon.start(force=True) is True

    # Exercise line processing (wires SessionLogger + StatusManager + PatternMatcher).
    daemon._process_line("hello from device")
    _ = capsys.readouterr()

    latest_log = base_dir / "latest.log"
    assert latest_log.exists()
    assert "hello from device" in latest_log.read_text(encoding="utf-8")

    # Exercise file-based command IPC path.
    append_command(str(base_dir / "cmd.txt"), "help")
    daemon._check_commands()
    assert serial.get_sent() == [b"help\n"]

    events = _read_jsonl(base_dir / "events.jsonl")
    event_types = [e.get("type") for e in events]
    assert "daemon_started" in event_types
    assert "command_sent" in event_types

    # Sanity check status.json exists and is parseable.
    status = json.loads((base_dir / "status.json").read_text(encoding="utf-8"))
    assert status["connection"]["status"] == "connected"


def test_stream_config_arms_and_marker_starts_stream(tmp_path: Path, monkeypatch: pytest.MonkeyPatch, capsys):
    daemon, _serial, base_dir = _make_daemon(tmp_path, monkeypatch)
    assert daemon.start(force=True) is True

    # Configure stream with a marker: should be enabled but not active until marker appears.
    (base_dir / "stream.json").write_text(
        json.dumps({"enabled": True, "mode": "raw", "chunk_size": 64, "marker": "===DATA_START==="}),
        encoding="utf-8",
    )
    daemon._check_stream_config()

    status = json.loads((base_dir / "status.json").read_text(encoding="utf-8"))
    assert status["stream"]["enabled"] is True
    assert status["stream"]["active"] is False
    assert status["stream"]["marker"] == "===DATA_START==="

    # When marker shows up in serial output, stream becomes active.
    daemon._process_line("boot... ===DATA_START===")
    _ = capsys.readouterr()

    status2 = json.loads((base_dir / "status.json").read_text(encoding="utf-8"))
    assert status2["stream"]["active"] is True

    events = _read_jsonl(base_dir / "events.jsonl")
    assert any(e.get("type") == "stream_started" for e in events)


def test_file_transfer_base64_payload_suppresses_health_and_patterns(tmp_path: Path, monkeypatch: pytest.MonkeyPatch, capsys):
    daemon, _serial, _base_dir = _make_daemon(tmp_path, monkeypatch)
    assert daemon.start(force=True) is True

    chip_lines: list[str] = []
    pattern_lines: list[str] = []

    def chip_spy(line: str) -> None:
        chip_lines.append(line)

    def pattern_spy(line: str):
        pattern_lines.append(line)
        return []

    monkeypatch.setattr(daemon._chip_recovery, "process_line", chip_spy)
    monkeypatch.setattr(daemon._pattern_matcher, "check_line", pattern_spy)

    daemon._process_line("===FILE_START===")
    daemon._process_line("===DATA===")

    chip_before = len(chip_lines)
    pattern_before = len(pattern_lines)

    # Looks like base64 and contains substrings that could falsely match patterns (e.g. WDT).
    daemon._process_line("V0RUX0ZBS0VfUEFZTE9BRF9MSU5FX1dJVEhfU09NRV9FWFRSQQ==")

    assert len(chip_lines) == chip_before
    assert len(pattern_lines) == pattern_before

    daemon._process_line("===FILE_END===")
    _ = capsys.readouterr()


@dataclass
class _FakeExisting:
    pid: int
    is_alive: bool
    port: str
    base_dir: str
    started: str


def test_main_list_and_status_paths(tmp_path: Path, monkeypatch: pytest.MonkeyPatch, capsys):
    import eab.daemon as daemon_mod

    monkeypatch.setattr(
        daemon_mod.RealSerialPort,
        "list_ports",
        staticmethod(
            lambda: [
                PortInfo(device="/dev/fake1", description="Fake", hwid="HWID"),
                PortInfo(device="/dev/fake2", description="Fake", hwid="HWID2"),
            ]
        ),
    )

    monkeypatch.setattr(daemon_mod, "check_singleton", lambda: None)

    monkeypatch.setattr(sys, "argv", ["eab", "--list"])
    daemon_mod.main()
    out = capsys.readouterr().out
    assert "Available serial ports:" in out
    assert "/dev/fake1" in out

    monkeypatch.setattr(sys, "argv", ["eab", "--status"])
    daemon_mod.main()
    out2 = capsys.readouterr().out
    assert "No EAB daemon is running" in out2


def test_main_cmd_and_pause_write_files(tmp_path: Path, monkeypatch: pytest.MonkeyPatch, capsys):
    import eab.daemon as daemon_mod

    base_dir = tmp_path / "session"
    base_dir.mkdir(parents=True, exist_ok=True)

    existing = _FakeExisting(
        pid=123,
        is_alive=True,
        port="/dev/fake",
        base_dir=str(base_dir),
        started="now",
    )
    monkeypatch.setattr(daemon_mod, "check_singleton", lambda: existing)

    # --cmd appends to cmd.txt
    monkeypatch.setattr(sys, "argv", ["eab", "--cmd", "help"])
    daemon_mod.main()
    _ = capsys.readouterr()
    assert (base_dir / "cmd.txt").read_text(encoding="utf-8").strip() == "help"

    # --pause writes pause.txt (mock time + sleep to keep test fast)
    import time as time_mod

    monkeypatch.setattr(time_mod, "time", lambda: 1000.0)
    monkeypatch.setattr(time_mod, "sleep", lambda _s: None)
    monkeypatch.setattr(sys, "argv", ["eab", "--pause", "10"])
    daemon_mod.main()
    _ = capsys.readouterr()
    assert (base_dir / "pause.txt").read_text(encoding="utf-8") == "1010.0"


def test___main___executes_daemon_main(monkeypatch: pytest.MonkeyPatch):
    import eab.daemon as daemon_mod

    called = {"ok": False}

    def fake_main() -> None:
        called["ok"] = True

    monkeypatch.setattr(daemon_mod, "main", fake_main)
    runpy.run_module("eab.__main__", run_name="__main__")
    assert called["ok"] is True
