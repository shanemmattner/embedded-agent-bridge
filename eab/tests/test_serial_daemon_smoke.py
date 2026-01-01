"""
Smoke tests for the legacy `serial_daemon.py` module.

This module is largely standalone, but it ships in the package and is worth
keeping importable and minimally exercised.
"""

from __future__ import annotations

import os
import sys
from pathlib import Path

import pytest

# Add parent directory to path for imports (consistent with existing tests).
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__)))))


class _FakeSerial:
    def __init__(self) -> None:
        self.writes: list[bytes] = []

    def write(self, data: bytes) -> int:
        self.writes.append(data)
        return len(data)

    def close(self) -> None:
        return None


def test_serial_monitor_daemon_command_roundtrip(tmp_path: Path, monkeypatch: pytest.MonkeyPatch):
    import eab.serial_daemon as sd

    # Redirect all fixed paths to the test temp directory.
    monkeypatch.setattr(sd, "LOG_DIR", str(tmp_path))
    monkeypatch.setattr(sd, "LATEST_LOG", str(tmp_path / "latest.log"))
    monkeypatch.setattr(sd, "ALERTS_FILE", str(tmp_path / "alerts.log"))
    monkeypatch.setattr(sd, "CMD_FILE", str(tmp_path / "cmd.txt"))
    monkeypatch.setattr(sd, "STATS_FILE", str(tmp_path / "stats.json"))

    daemon = sd.SerialMonitorDaemon(port="/dev/fake", baud=115200, output_file=str(tmp_path / "out.log"))
    daemon.serial = _FakeSerial()

    daemon.start_logging()

    # Write a command into the command file and verify it gets sent and cleared.
    Path(sd.CMD_FILE).write_text("AT+RST\n", encoding="utf-8")
    daemon.check_commands()

    assert daemon.serial.writes == [b"AT+RST\n"]
    assert Path(sd.CMD_FILE).read_text(encoding="utf-8") == ""

