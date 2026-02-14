from __future__ import annotations

from pathlib import Path

import pytest

from eab.openocd_bridge import OpenOCDBridge


class _Proc:
    def __init__(self, pid: int, alive: bool = True):
        self.pid = pid
        self._alive = alive

    def poll(self):
        return None if self._alive else 1


def test_openocd_start_writes_cfg_and_status(tmp_path: Path, monkeypatch: pytest.MonkeyPatch):
    bridge = OpenOCDBridge(str(tmp_path))

    def fake_popen(*args, **kwargs):
        return _Proc(12345, alive=True)

    # Pretend process is alive.
    monkeypatch.setattr("eab.openocd_bridge.subprocess.Popen", fake_popen)
    monkeypatch.setattr("eab.openocd_bridge.pid_alive", lambda pid: True)

    st = bridge.start(chip="esp32s3", vid="0x303a", pid="0x1001")
    assert st.running is True
    assert st.pid == 12345
    assert (tmp_path / "openocd.cfg").exists()
    assert (tmp_path / "openocd.pid").read_text().strip() == "12345"
    assert (tmp_path / "openocd.status.json").exists()


def test_openocd_start_cleans_pid_on_fast_failure(tmp_path: Path, monkeypatch: pytest.MonkeyPatch):
    bridge = OpenOCDBridge(str(tmp_path))
    (tmp_path / "openocd.err").write_text("boom\n", encoding="utf-8")

    def fake_popen(*args, **kwargs):
        return _Proc(23456, alive=False)

    monkeypatch.setattr("eab.openocd_bridge.subprocess.Popen", fake_popen)
    monkeypatch.setattr("eab.openocd_bridge.pid_alive", lambda pid: False)

    st = bridge.start()
    assert st.running is False
    assert st.pid is None
    assert not (tmp_path / "openocd.pid").exists()

