"""Tests for exit-code behaviour of cmd_status in eab.cli.serial.status_cmds."""

from __future__ import annotations

import json

from eab.singleton import ExistingDaemon


def _make_existing(*, is_alive: bool = True) -> ExistingDaemon:
    """Return a minimal ExistingDaemon instance for tests."""
    return ExistingDaemon(
        pid=12345,
        is_alive=is_alive,
        port="/dev/ttyUSB0",
        base_dir="/tmp/eab-test",
        started="2026-02-28T00:00:00",
    )


def _make_status(connection_status: str, health_status: str) -> dict:
    return {
        "connection": {"status": connection_status},
        "health": {"status": health_status},
    }


class TestCmdStatusExitCode:
    """Exit-code tests for cmd_status."""

    def _run(self, tmp_path, monkeypatch, status_data, *, json_mode: bool, alive: bool = True):
        from eab.cli.serial.status_cmds import cmd_status

        if status_data is not None:
            (tmp_path / "status.json").write_text(json.dumps(status_data))

        mock = _make_existing(is_alive=alive)

        monkeypatch.setattr(
            "eab.cli.serial.status_cmds.check_singleton",
            lambda **kwargs: mock,
        )

        return cmd_status(base_dir=str(tmp_path), json_mode=json_mode)

    def test_returns_0_when_connected_and_healthy_json(self, tmp_path, monkeypatch):
        result = self._run(
            tmp_path, monkeypatch,
            _make_status("connected", "healthy"),
            json_mode=True,
        )
        assert result == 0

    def test_returns_0_when_connected_and_healthy_text(self, tmp_path, monkeypatch):
        result = self._run(
            tmp_path, monkeypatch,
            _make_status("connected", "healthy"),
            json_mode=False,
        )
        assert result == 0

    def test_returns_0_when_connected_and_idle_json(self, tmp_path, monkeypatch):
        result = self._run(
            tmp_path, monkeypatch,
            _make_status("connected", "idle"),
            json_mode=True,
        )
        assert result == 0

    def test_returns_0_when_connected_and_idle_text(self, tmp_path, monkeypatch):
        result = self._run(
            tmp_path, monkeypatch,
            _make_status("connected", "idle"),
            json_mode=False,
        )
        assert result == 0

    def test_returns_1_when_connection_disconnected(self, tmp_path, monkeypatch):
        result = self._run(
            tmp_path, monkeypatch,
            _make_status("disconnected", "healthy"),
            json_mode=True,
        )
        assert result == 1

    def test_returns_1_when_status_json_missing(self, tmp_path, monkeypatch):
        result = self._run(
            tmp_path, monkeypatch,
            None,  # no status.json written
            json_mode=True,
        )
        assert result == 1

    def test_returns_1_when_health_starting(self, tmp_path, monkeypatch):
        """Placeholder status written by cmd_start should still yield exit code 1."""
        result = self._run(
            tmp_path, monkeypatch,
            _make_status("starting", "starting"),
            json_mode=True,
        )
        assert result == 1

    def test_returns_1_when_status_json_invalid(self, tmp_path, monkeypatch):
        (tmp_path / "status.json").write_text("not-valid-json{{")
        from eab.cli.serial.status_cmds import cmd_status

        monkeypatch.setattr(
            "eab.cli.serial.status_cmds.check_singleton",
            lambda **kwargs: _make_existing(is_alive=True),
        )
        result = cmd_status(base_dir=str(tmp_path), json_mode=True)
        assert result == 1

    def test_json_mode_same_exit_code_as_text_mode_healthy(self, tmp_path, monkeypatch, tmp_path_factory):
        """json_mode and text mode must agree on exit code when healthy."""
        status = _make_status("connected", "healthy")
        r_json = self._run(tmp_path, monkeypatch, status, json_mode=True)

        tmp2 = tmp_path_factory.mktemp("text")
        r_text = self._run(tmp2, monkeypatch, status, json_mode=False)

        assert r_json == r_text == 0

    def test_json_mode_same_exit_code_as_text_mode_unhealthy(self, tmp_path, monkeypatch, tmp_path_factory):
        """json_mode and text mode must agree on exit code when unhealthy."""
        status = _make_status("disconnected", "error")
        r_json = self._run(tmp_path, monkeypatch, status, json_mode=True)

        tmp2 = tmp_path_factory.mktemp("text2")
        r_text = self._run(tmp2, monkeypatch, status, json_mode=False)

        assert r_json == r_text == 1
