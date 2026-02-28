"""Tests for exit-code behaviour of the `eabctl status` command.

Covers:
- status --json (json_mode=True) returns 0 when daemon is running and healthy
- status --json (json_mode=True) returns 1 when daemon is not running or unhealthy
- plain status (json_mode=False) returns the same exit codes
"""

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


def _write_status(tmp_path, connection_status: str, health_status: str) -> None:
    """Write a status.json fixture to tmp_path."""
    (tmp_path / "status.json").write_text(
        json.dumps({
            "connection": {"status": connection_status},
            "health": {"status": health_status},
        })
    )


class TestCmdStatusExitCodes:
    """Exit-code tests for cmd_status covering healthy and unhealthy scenarios."""

    # ------------------------------------------------------------------
    # JSON mode — healthy (exit 0)
    # ------------------------------------------------------------------

    def test_json_mode_returns_0_when_running_and_healthy(self, tmp_path, monkeypatch):
        """status --json exits 0 when daemon is running and status shows healthy."""
        from eab.cli.serial.status_cmds import cmd_status

        _write_status(tmp_path, "connected", "healthy")
        monkeypatch.setattr(
            "eab.cli.serial.status_cmds.check_singleton",
            lambda **kwargs: _make_existing(is_alive=True),
        )

        result = cmd_status(base_dir=str(tmp_path), json_mode=True)

        assert result == 0

    def test_json_mode_returns_0_when_running_and_idle(self, tmp_path, monkeypatch):
        """status --json exits 0 when daemon is running and status shows idle."""
        from eab.cli.serial.status_cmds import cmd_status

        _write_status(tmp_path, "connected", "idle")
        monkeypatch.setattr(
            "eab.cli.serial.status_cmds.check_singleton",
            lambda **kwargs: _make_existing(is_alive=True),
        )

        result = cmd_status(base_dir=str(tmp_path), json_mode=True)

        assert result == 0

    # ------------------------------------------------------------------
    # JSON mode — unhealthy / not running (exit 1)
    # ------------------------------------------------------------------

    def test_json_mode_returns_1_when_daemon_not_running(self, tmp_path, monkeypatch):
        """status --json exits 1 when daemon is not running (check_singleton returns None)."""
        from eab.cli.serial.status_cmds import cmd_status

        # No status.json and no running daemon
        monkeypatch.setattr(
            "eab.cli.serial.status_cmds.check_singleton",
            lambda **kwargs: None,
        )

        result = cmd_status(base_dir=str(tmp_path), json_mode=True)

        assert result == 1

    def test_json_mode_returns_1_when_daemon_alive_but_status_json_missing(
        self, tmp_path, monkeypatch
    ):
        """status --json exits 1 when process is alive but status.json is absent."""
        from eab.cli.serial.status_cmds import cmd_status

        # Daemon alive but no status.json written
        monkeypatch.setattr(
            "eab.cli.serial.status_cmds.check_singleton",
            lambda **kwargs: _make_existing(is_alive=True),
        )

        result = cmd_status(base_dir=str(tmp_path), json_mode=True)

        assert result == 1

    def test_json_mode_returns_1_when_daemon_stale_pid(self, tmp_path, monkeypatch):
        """status --json exits 1 when check_singleton returns a stale (not-alive) daemon."""
        from eab.cli.serial.status_cmds import cmd_status

        # Stale PID file: process is no longer alive
        monkeypatch.setattr(
            "eab.cli.serial.status_cmds.check_singleton",
            lambda **kwargs: _make_existing(is_alive=False),
        )

        result = cmd_status(base_dir=str(tmp_path), json_mode=True)

        assert result == 1

    def test_json_mode_returns_1_when_disconnected(self, tmp_path, monkeypatch):
        """status --json exits 1 when connection status is not 'connected'."""
        from eab.cli.serial.status_cmds import cmd_status

        _write_status(tmp_path, "disconnected", "healthy")
        monkeypatch.setattr(
            "eab.cli.serial.status_cmds.check_singleton",
            lambda **kwargs: _make_existing(is_alive=True),
        )

        result = cmd_status(base_dir=str(tmp_path), json_mode=True)

        assert result == 1

    def test_json_mode_returns_1_when_health_error(self, tmp_path, monkeypatch):
        """status --json exits 1 when health status is not healthy/idle."""
        from eab.cli.serial.status_cmds import cmd_status

        _write_status(tmp_path, "connected", "error")
        monkeypatch.setattr(
            "eab.cli.serial.status_cmds.check_singleton",
            lambda **kwargs: _make_existing(is_alive=True),
        )

        result = cmd_status(base_dir=str(tmp_path), json_mode=True)

        assert result == 1

    # ------------------------------------------------------------------
    # Text mode (non-JSON) — exit codes must match JSON mode
    # ------------------------------------------------------------------

    def test_text_mode_returns_0_when_running_and_healthy(self, tmp_path, monkeypatch):
        """Plain status exits 0 when daemon is running and status shows healthy."""
        from eab.cli.serial.status_cmds import cmd_status

        _write_status(tmp_path, "connected", "healthy")
        monkeypatch.setattr(
            "eab.cli.serial.status_cmds.check_singleton",
            lambda **kwargs: _make_existing(is_alive=True),
        )

        result = cmd_status(base_dir=str(tmp_path), json_mode=False)

        assert result == 0

    def test_text_mode_returns_1_when_daemon_not_running(self, tmp_path, monkeypatch):
        """Plain status exits 1 when daemon is not running."""
        from eab.cli.serial.status_cmds import cmd_status

        monkeypatch.setattr(
            "eab.cli.serial.status_cmds.check_singleton",
            lambda **kwargs: None,
        )

        result = cmd_status(base_dir=str(tmp_path), json_mode=False)

        assert result == 1

    def test_text_mode_returns_1_when_unhealthy(self, tmp_path, monkeypatch):
        """Plain status exits 1 when status.json shows disconnected/unhealthy."""
        from eab.cli.serial.status_cmds import cmd_status

        _write_status(tmp_path, "disconnected", "error")
        monkeypatch.setattr(
            "eab.cli.serial.status_cmds.check_singleton",
            lambda **kwargs: _make_existing(is_alive=True),
        )

        result = cmd_status(base_dir=str(tmp_path), json_mode=False)

        assert result == 1

    def test_text_mode_returns_1_when_stale_pid(self, tmp_path, monkeypatch):
        """Plain status exits 1 when the daemon process is no longer alive."""
        from eab.cli.serial.status_cmds import cmd_status

        monkeypatch.setattr(
            "eab.cli.serial.status_cmds.check_singleton",
            lambda **kwargs: _make_existing(is_alive=False),
        )

        result = cmd_status(base_dir=str(tmp_path), json_mode=False)

        assert result == 1

    # ------------------------------------------------------------------
    # Cross-mode consistency
    # ------------------------------------------------------------------

    def test_json_and_text_agree_on_exit_code_healthy(
        self, tmp_path, monkeypatch, tmp_path_factory
    ):
        """JSON mode and text mode must return the same exit code when healthy."""
        from eab.cli.serial.status_cmds import cmd_status

        status = {"connection": {"status": "connected"}, "health": {"status": "healthy"}}

        # JSON mode
        (tmp_path / "status.json").write_text(json.dumps(status))
        monkeypatch.setattr(
            "eab.cli.serial.status_cmds.check_singleton",
            lambda **kwargs: _make_existing(is_alive=True),
        )
        r_json = cmd_status(base_dir=str(tmp_path), json_mode=True)

        # Text mode (separate tmp dir to avoid stale JSON state)
        tmp2 = tmp_path_factory.mktemp("text_healthy")
        (tmp2 / "status.json").write_text(json.dumps(status))
        r_text = cmd_status(base_dir=str(tmp2), json_mode=False)

        assert r_json == r_text == 0

    def test_json_and_text_agree_on_exit_code_unhealthy(
        self, tmp_path, monkeypatch, tmp_path_factory
    ):
        """JSON mode and text mode must return the same exit code when unhealthy."""
        from eab.cli.serial.status_cmds import cmd_status

        monkeypatch.setattr(
            "eab.cli.serial.status_cmds.check_singleton",
            lambda **kwargs: None,
        )

        r_json = cmd_status(base_dir=str(tmp_path), json_mode=True)

        tmp2 = tmp_path_factory.mktemp("text_unhealthy")
        r_text = cmd_status(base_dir=str(tmp2), json_mode=False)

        assert r_json == r_text == 1


class TestCmdStatusJsonBody:
    """Verify that `status --json` outputs valid JSON in both healthy and unhealthy scenarios."""

    # ------------------------------------------------------------------
    # Healthy — exit 0, JSON body present and well-formed
    # ------------------------------------------------------------------

    def test_json_body_healthy_exit_0(self, tmp_path, monkeypatch, capsys):
        """status --json outputs valid JSON with expected keys and returns exit code 0."""
        from eab.cli.serial.status_cmds import cmd_status

        _write_status(tmp_path, "connected", "healthy")
        monkeypatch.setattr(
            "eab.cli.serial.status_cmds.check_singleton",
            lambda **kwargs: _make_existing(is_alive=True),
        )

        result = cmd_status(base_dir=str(tmp_path), json_mode=True)

        captured = capsys.readouterr()
        parsed = json.loads(captured.out)

        assert result == 0
        assert parsed["schema_version"] == 1
        assert "daemon" in parsed
        assert parsed["daemon"] != {"running": False}
        assert parsed["status"] is not None
        assert parsed["status"]["connection"]["status"] == "connected"
        assert parsed["status"]["health"]["status"] == "healthy"

    # ------------------------------------------------------------------
    # Unhealthy — exit 1, JSON body still present
    # ------------------------------------------------------------------

    def test_json_body_daemon_not_running_exit_1(self, tmp_path, monkeypatch, capsys):
        """status --json outputs JSON with daemon={"running": False} and returns exit code 1."""
        from eab.cli.serial.status_cmds import cmd_status

        monkeypatch.setattr(
            "eab.cli.serial.status_cmds.check_singleton",
            lambda **kwargs: None,
        )

        result = cmd_status(base_dir=str(tmp_path), json_mode=True)

        captured = capsys.readouterr()
        parsed = json.loads(captured.out)

        assert result == 1
        assert parsed["schema_version"] == 1
        assert parsed["daemon"] == {"running": False}
        assert parsed["status"] is None

    def test_json_body_disconnected_exit_1(self, tmp_path, monkeypatch, capsys):
        """status --json outputs JSON with status.connection.status=='disconnected' and exits 1."""
        from eab.cli.serial.status_cmds import cmd_status

        _write_status(tmp_path, "disconnected", "error")
        monkeypatch.setattr(
            "eab.cli.serial.status_cmds.check_singleton",
            lambda **kwargs: _make_existing(is_alive=True),
        )

        result = cmd_status(base_dir=str(tmp_path), json_mode=True)

        captured = capsys.readouterr()
        parsed = json.loads(captured.out)

        assert result == 1
        assert parsed["schema_version"] == 1
        assert "daemon" in parsed
        assert parsed["daemon"] != {"running": False}
        assert parsed["status"]["connection"]["status"] == "disconnected"
