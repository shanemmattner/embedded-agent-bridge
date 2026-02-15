"""Tests for daemon command functions (start, stop, pause, resume, diagnose)."""

from __future__ import annotations

import json
import os
import sys
from pathlib import Path
from unittest.mock import Mock, patch


# Add parent directory to path for imports (consistent with existing tests).
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__)))))

from eab.cli.daemon import cmd_start


def test_cmd_start_clears_stale_session_files(tmp_path: Path):
    """Test that cmd_start clears stale session files and writes placeholder status.
    
    This test verifies that when cmd_start() is called:
    1. Stale session files with old data (high idle_seconds, stuck health status) are cleared
    2. The placeholder status.json is written with 'starting' status
    3. The daemon subprocess is spawned correctly
    """
    base_dir = tmp_path / "session"
    base_dir.mkdir(parents=True)
    
    # Create stale session files with old data
    stale_status = {
        "session": {
            "id": "old-session-123",
            "started": "2023-01-01T00:00:00",
            "uptime_seconds": 86400,
        },
        "connection": {
            "port": "/dev/ttyUSB0",
            "baud": 115200,
            "status": "disconnected",
            "reconnects": 42,
        },
        "counters": {
            "lines_logged": 1000,
            "bytes_received": 50000,
            "commands_sent": 10,
            "alerts_triggered": 5,
        },
        "health": {
            "last_activity": "2023-01-01T12:00:00",
            "idle_seconds": 3600,  # High idle time
            "bytes_last_minute": 0,
            "read_errors": 2,
            "usb_disconnects": 1,
            "status": "stuck",  # Stuck status
        },
        "patterns": {
            "WATCHDOG": 15,
            "BOOT": 20,
        },
        "stream": {
            "enabled": False,
            "active": False,
        },
        "last_updated": "2023-01-01T12:00:00",
    }
    
    status_path = base_dir / "status.json"
    status_path.write_text(json.dumps(stale_status, indent=2), encoding="utf-8")
    
    # Create other stale session files
    (base_dir / "latest.log").write_text("old log data\n", encoding="utf-8")
    (base_dir / "alerts.log").write_text("old alert\n", encoding="utf-8")
    (base_dir / "events.jsonl").write_text('{"type":"old_event"}\n', encoding="utf-8")
    (base_dir / "cmd.txt").write_text("old_command\n", encoding="utf-8")
    (base_dir / "pause.txt").write_text("1234567890\n", encoding="utf-8")
    (base_dir / "stream.json").write_text('{"enabled":true}\n', encoding="utf-8")
    
    # Verify stale files exist before cmd_start
    assert status_path.exists()
    assert (base_dir / "latest.log").exists()
    
    # Verify stale status has stuck health status and high idle_seconds
    stale_data = json.loads(status_path.read_text(encoding="utf-8"))
    assert stale_data["health"]["status"] == "stuck"
    assert stale_data["health"]["idle_seconds"] == 3600
    
    # Mock subprocess.Popen to avoid actually starting a daemon
    mock_proc = Mock()
    mock_proc.pid = 12345
    
    with patch("eab.cli.daemon.lifecycle_cmds.subprocess.Popen", return_value=mock_proc) as mock_popen, \
         patch("eab.cli.daemon.lifecycle_cmds.check_singleton", return_value=None), \
         patch("eab.cli.daemon.lifecycle_cmds.cleanup_dead_locks"):
        
        # Call cmd_start
        result = cmd_start(
            base_dir=str(base_dir),
            port="/dev/ttyUSB0",
            baud=115200,
            force=False,
            json_mode=False,
        )
        
        # Verify cmd_start returned success
        assert result == 0
        
        # Verify subprocess.Popen was called to spawn daemon
        assert mock_popen.called
        popen_args = mock_popen.call_args
        assert popen_args.kwargs["start_new_session"] is True
        
    # Verify placeholder status.json was written
    assert status_path.exists()
    new_status = json.loads(status_path.read_text(encoding="utf-8"))
    
    # Verify placeholder contains 'starting' status
    assert new_status["health"]["status"] == "starting"
    assert new_status["connection"]["status"] == "starting"
    
    # Verify old stale data is replaced (not present in placeholder)
    assert "session" not in new_status or new_status.get("session") is None or new_status.get("session") == {}
    assert "counters" not in new_status or new_status.get("counters") is None or new_status.get("counters") == {}
    assert "patterns" not in new_status or new_status.get("patterns") is None or new_status.get("patterns") == {}
    
    # Verify idle_seconds and stuck status are not in the placeholder
    assert new_status["health"].get("idle_seconds") is None or "idle_seconds" not in new_status["health"]


def test_cmd_start_with_force_kills_existing_daemon(tmp_path: Path):
    """Test that cmd_start with force=True kills existing daemon before starting."""
    base_dir = tmp_path / "session"
    base_dir.mkdir(parents=True)
    
    # Mock existing daemon
    mock_existing = Mock()
    mock_existing.is_alive = True
    mock_existing.pid = 999
    
    mock_proc = Mock()
    mock_proc.pid = 12345
    
    with patch("eab.cli.daemon.lifecycle_cmds.subprocess.Popen", return_value=mock_proc), \
         patch("eab.cli.daemon.lifecycle_cmds.check_singleton", return_value=mock_existing), \
         patch("eab.cli.daemon.lifecycle_cmds.kill_existing_daemon") as mock_kill, \
         patch("eab.cli.daemon.lifecycle_cmds.cleanup_dead_locks"), \
         patch("eab.cli.daemon.lifecycle_cmds.list_all_locks", return_value=[]):
        
        result = cmd_start(
            base_dir=str(base_dir),
            port="/dev/ttyUSB0",
            baud=115200,
            force=True,
            json_mode=False,
        )
        
        # Verify kill_existing_daemon was called
        assert mock_kill.called
        
        # Verify cmd_start succeeded
        assert result == 0


def test_cmd_start_without_force_returns_error_if_daemon_running(tmp_path: Path):
    """Test that cmd_start without force returns error if daemon already running."""
    base_dir = tmp_path / "session"
    base_dir.mkdir(parents=True)
    
    # Mock existing running daemon
    mock_existing = Mock()
    mock_existing.is_alive = True
    mock_existing.pid = 999
    
    with patch("eab.cli.daemon.lifecycle_cmds.check_singleton", return_value=mock_existing), \
         patch("eab.cli.daemon.lifecycle_cmds.subprocess.Popen") as mock_popen:
        
        result = cmd_start(
            base_dir=str(base_dir),
            port="/dev/ttyUSB0",
            baud=115200,
            force=False,
            json_mode=False,
        )
        
        # Verify cmd_start returned error code 1
        assert result == 1
        
        # Verify subprocess.Popen was NOT called
        assert not mock_popen.called


def test_cmd_start_writes_placeholder_before_daemon_initializes(tmp_path: Path):
    """Test that placeholder status.json is written immediately after spawning daemon.
    
    This prevents race conditions where eabctl status is called before daemon
    has initialized its status.json file.
    """
    base_dir = tmp_path / "session"
    base_dir.mkdir(parents=True)
    
    status_path = base_dir / "status.json"
    
    # Ensure status.json doesn't exist before cmd_start
    assert not status_path.exists()
    
    mock_proc = Mock()
    mock_proc.pid = 12345
    
    with patch("eab.cli.daemon.lifecycle_cmds.subprocess.Popen", return_value=mock_proc), \
         patch("eab.cli.daemon.lifecycle_cmds.check_singleton", return_value=None), \
         patch("eab.cli.daemon.lifecycle_cmds.cleanup_dead_locks"):
        
        result = cmd_start(
            base_dir=str(base_dir),
            port="/dev/ttyUSB0",
            baud=115200,
            force=False,
            json_mode=False,
        )
        
        assert result == 0
    
    # Verify status.json exists after cmd_start
    assert status_path.exists()
    
    # Verify it contains placeholder data with 'starting' status
    status = json.loads(status_path.read_text(encoding="utf-8"))
    assert status["health"]["status"] == "starting"
    assert status["connection"]["status"] == "starting"
    
    # Verify it's minimal (no stale counters, patterns, etc.)
    assert len(status) == 2  # Only 'health' and 'connection'
    assert len(status["health"]) == 1  # Only 'status'
    assert len(status["connection"]) == 1  # Only 'status'


def test_cmd_start_creates_base_dir_if_not_exists(tmp_path: Path):
    """Test that cmd_start creates base_dir if it doesn't exist."""
    base_dir = tmp_path / "nonexistent" / "session"
    
    # Verify base_dir doesn't exist
    assert not base_dir.exists()
    
    mock_proc = Mock()
    mock_proc.pid = 12345
    
    with patch("eab.cli.daemon.lifecycle_cmds.subprocess.Popen", return_value=mock_proc), \
         patch("eab.cli.daemon.lifecycle_cmds.check_singleton", return_value=None), \
         patch("eab.cli.daemon.lifecycle_cmds.cleanup_dead_locks"):
        
        result = cmd_start(
            base_dir=str(base_dir),
            port="/dev/ttyUSB0",
            baud=115200,
            force=False,
            json_mode=False,
        )
        
        assert result == 0
    
    # Verify base_dir was created
    assert base_dir.exists()
    assert base_dir.is_dir()
    
    # Verify status.json was written in the new directory
    status_path = base_dir / "status.json"
    assert status_path.exists()


def test_cmd_start_json_mode_output(tmp_path: Path, capsys):
    """Test that cmd_start with json_mode=True outputs valid JSON."""
    base_dir = tmp_path / "session"
    base_dir.mkdir(parents=True)
    
    mock_proc = Mock()
    mock_proc.pid = 12345
    
    with patch("eab.cli.daemon.lifecycle_cmds.subprocess.Popen", return_value=mock_proc), \
         patch("eab.cli.daemon.lifecycle_cmds.check_singleton", return_value=None), \
         patch("eab.cli.daemon.lifecycle_cmds.cleanup_dead_locks"):
        
        result = cmd_start(
            base_dir=str(base_dir),
            port="/dev/ttyUSB0",
            baud=115200,
            force=False,
            json_mode=True,
        )
        
        assert result == 0
    
    # Verify JSON output
    captured = capsys.readouterr()
    output = json.loads(captured.out)
    
    assert output["schema_version"] == 1
    assert output["started"] is True
    assert output["pid"] == 12345
    assert "timestamp" in output
    assert "log_path" in output
    assert "err_path" in output
