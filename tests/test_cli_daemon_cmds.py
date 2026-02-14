"""
Tests for daemon command functions in eab.cli.daemon_cmds.

Verifies session file cleanup helpers and other daemon management utilities.
"""

from __future__ import annotations

import os
import json
import pytest


class TestClearSessionFiles:
    """Tests for _clear_session_files helper function."""

    def test_clear_all_files_when_present(self, tmp_path):
        """Should remove all session files when they exist."""
        from eab.cli.daemon_cmds import _clear_session_files

        # Create all session files with some content
        status_path = tmp_path / "status.json"
        alerts_path = tmp_path / "alerts.log"
        events_path = tmp_path / "events.jsonl"

        status_path.write_text(json.dumps({"status": "running"}))
        alerts_path.write_text("Alert 1\nAlert 2\n")
        events_path.write_text('{"type": "test"}\n')

        # Verify files exist
        assert status_path.exists()
        assert alerts_path.exists()
        assert events_path.exists()

        # Clear session files
        _clear_session_files(str(tmp_path))

        # Verify files are removed
        assert not status_path.exists()
        assert not alerts_path.exists()
        assert not events_path.exists()

    def test_clear_when_files_missing(self, tmp_path):
        """Should handle missing files gracefully without raising errors."""
        from eab.cli.daemon_cmds import _clear_session_files

        # Don't create any files - just call the function
        # This should not raise FileNotFoundError
        _clear_session_files(str(tmp_path))

        # No files should exist
        assert not (tmp_path / "status.json").exists()
        assert not (tmp_path / "alerts.log").exists()
        assert not (tmp_path / "events.jsonl").exists()

    def test_clear_partial_files(self, tmp_path):
        """Should handle case where only some files exist."""
        from eab.cli.daemon_cmds import _clear_session_files

        # Create only some files
        status_path = tmp_path / "status.json"
        events_path = tmp_path / "events.jsonl"

        status_path.write_text(json.dumps({"status": "test"}))
        events_path.write_text('{"type": "event"}\n')

        # alerts.log does not exist
        assert status_path.exists()
        assert not (tmp_path / "alerts.log").exists()
        assert events_path.exists()

        # Clear session files
        _clear_session_files(str(tmp_path))

        # All should be gone or remain non-existent
        assert not status_path.exists()
        assert not (tmp_path / "alerts.log").exists()
        assert not events_path.exists()

    def test_clear_does_not_affect_other_files(self, tmp_path):
        """Should only remove specific session files, leaving others intact."""
        from eab.cli.daemon_cmds import _clear_session_files

        # Create session files
        status_path = tmp_path / "status.json"
        alerts_path = tmp_path / "alerts.log"
        events_path = tmp_path / "events.jsonl"

        status_path.write_text(json.dumps({"status": "running"}))
        alerts_path.write_text("Alert\n")
        events_path.write_text('{"type": "test"}\n')

        # Create other files that should not be affected
        other_file = tmp_path / "other.txt"
        cmd_file = tmp_path / "cmd.txt"
        pause_file = tmp_path / "pause.txt"

        other_file.write_text("keep me")
        cmd_file.write_text("command")
        pause_file.write_text("1234567890")

        # Clear session files
        _clear_session_files(str(tmp_path))

        # Session files removed
        assert not status_path.exists()
        assert not alerts_path.exists()
        assert not events_path.exists()

        # Other files preserved
        assert other_file.exists()
        assert other_file.read_text() == "keep me"
        assert cmd_file.exists()
        assert cmd_file.read_text() == "command"
        assert pause_file.exists()
        assert pause_file.read_text() == "1234567890"

    def test_clear_empty_directory(self, tmp_path):
        """Should handle empty directory without errors."""
        from eab.cli.daemon_cmds import _clear_session_files

        # Empty directory
        assert len(list(tmp_path.iterdir())) == 0

        # Should not raise any errors
        _clear_session_files(str(tmp_path))

        # Directory should still be empty
        assert len(list(tmp_path.iterdir())) == 0

    def test_clear_nonexistent_directory(self):
        """Should handle non-existent directory path."""
        from eab.cli.daemon_cmds import _clear_session_files

        # This directory doesn't exist
        nonexistent = "/tmp/eab-test-nonexistent-dir-12345"
        assert not os.path.exists(nonexistent)

        # Should not raise errors (FileNotFoundError is caught)
        _clear_session_files(nonexistent)

    def test_clear_files_with_content(self, tmp_path):
        """Should remove files regardless of content size."""
        from eab.cli.daemon_cmds import _clear_session_files

        # Create files with varying content sizes
        status_path = tmp_path / "status.json"
        alerts_path = tmp_path / "alerts.log"
        events_path = tmp_path / "events.jsonl"

        # Large status file
        status_data = {"test": "x" * 10000}
        status_path.write_text(json.dumps(status_data))

        # Many alerts
        alerts_path.write_text("Alert\n" * 1000)

        # Many events
        events_path.write_text('{"type": "event"}\n' * 500)

        # Verify files have content
        assert status_path.stat().st_size > 10000
        assert alerts_path.stat().st_size > 5000
        assert events_path.stat().st_size > 1000

        # Clear session files
        _clear_session_files(str(tmp_path))

        # All removed
        assert not status_path.exists()
        assert not alerts_path.exists()
        assert not events_path.exists()


class TestCmdStartSessionCleanup:
    """Tests verifying cmd_start() clears session files before starting daemon."""

    def test_cmd_start_clears_session_files(self, tmp_path, monkeypatch):
        """cmd_start should call _clear_session_files before spawning daemon."""
        from eab.cli.daemon_cmds import cmd_start
        import subprocess
        
        # Create stale session files
        status_path = tmp_path / "status.json"
        alerts_path = tmp_path / "alerts.log"
        events_path = tmp_path / "events.jsonl"
        
        status_path.write_text(json.dumps({"connection": {"status": "stale"}}))
        alerts_path.write_text("Old alert\n")
        events_path.write_text('{"type": "old_event"}\n')
        
        assert status_path.exists()
        assert alerts_path.exists()
        assert events_path.exists()
        
        # Mock subprocess.Popen to prevent actually spawning daemon
        popen_called = []
        class MockPopen:
            def __init__(self, *args, **kwargs):
                popen_called.append((args, kwargs))
                self.pid = 12345
        
        # Mock check_singleton to return None (no existing daemon)
        def mock_check_singleton(**kwargs):
            return None

        monkeypatch.setattr(subprocess, "Popen", MockPopen)
        monkeypatch.setattr("eab.cli.daemon_cmds.check_singleton", mock_check_singleton)

        # Mock cleanup_dead_locks to do nothing
        monkeypatch.setattr("eab.cli.daemon_cmds.cleanup_dead_locks", lambda: None)

        # Mock file operations for log files
        import builtins
        original_open = builtins.open
        def mock_open(path, *args, **kwargs):
            if path in ["/tmp/eab-daemon.log", "/tmp/eab-daemon.err"]:
                import io
                return io.StringIO()
            return original_open(path, *args, **kwargs)

        monkeypatch.setattr(builtins, "open", mock_open)

        # Call cmd_start
        result = cmd_start(
            base_dir=str(tmp_path),
            port="auto",
            baud=115200,
            force=False,
            json_mode=True
        )
        
        # Should succeed
        assert result == 0
        assert len(popen_called) == 1
        
        # alerts.log and events.jsonl should be cleared and not recreated
        assert not alerts_path.exists()
        assert not events_path.exists()
        
        # status.json is recreated with placeholder content after clearing
        assert status_path.exists()
        status_data = json.loads(status_path.read_text())
        # Should have fresh placeholder content, not the old stale content
        assert status_data.get("health", {}).get("status") == "starting"
        assert status_data.get("connection", {}).get("status") == "starting"
        assert "stale" not in status_path.read_text()

    def test_cmd_start_with_force_clears_session_files(self, tmp_path, monkeypatch):
        """cmd_start with --force should clear session files after killing daemon."""
        from eab.cli.daemon_cmds import cmd_start
        import subprocess
        
        # Create stale session files
        status_path = tmp_path / "status.json"
        alerts_path = tmp_path / "alerts.log"
        events_path = tmp_path / "events.jsonl"
        
        status_path.write_text(json.dumps({"pid": 999}))
        alerts_path.write_text("Stale alert\n")
        events_path.write_text('{"type": "stale"}\n')
        
        # Mock an existing daemon
        class MockExisting:
            def __init__(self):
                self.pid = 999
                self.is_alive = True
        
        def mock_check_singleton(**kwargs):
            return MockExisting()

        # Mock killing daemon
        def mock_kill_existing_daemon(**kwargs):
            return True
        
        # Mock list_all_locks to return empty (no port locks)
        def mock_list_all_locks():
            return []
        
        # Mock cleanup_dead_locks
        def mock_cleanup_dead_locks():
            pass
        
        # Mock subprocess.Popen
        class MockPopen:
            def __init__(self, *args, **kwargs):
                self.pid = 12345
        
        monkeypatch.setattr("eab.cli.daemon_cmds.check_singleton", mock_check_singleton)
        monkeypatch.setattr("eab.cli.daemon_cmds.kill_existing_daemon", mock_kill_existing_daemon)
        monkeypatch.setattr("eab.cli.daemon_cmds.list_all_locks", mock_list_all_locks)
        monkeypatch.setattr("eab.cli.daemon_cmds.cleanup_dead_locks", mock_cleanup_dead_locks)
        monkeypatch.setattr(subprocess, "Popen", MockPopen)
        
        # Mock file operations
        import builtins
        original_open = builtins.open
        def mock_open(path, *args, **kwargs):
            if path in ["/tmp/eab-daemon.log", "/tmp/eab-daemon.err"]:
                import io
                return io.StringIO()
            return original_open(path, *args, **kwargs)
        
        monkeypatch.setattr(builtins, "open", mock_open)
        
        # Call cmd_start with force=True
        result = cmd_start(
            base_dir=str(tmp_path),
            port="auto",
            baud=115200,
            force=True,
            json_mode=True
        )
        
        # Should succeed
        assert result == 0
        
        # alerts.log and events.jsonl should be cleared and not recreated
        assert not alerts_path.exists()
        assert not events_path.exists()
        
        # status.json is recreated with placeholder content after clearing
        assert status_path.exists()
        status_data = json.loads(status_path.read_text())
        # Should have fresh placeholder content, not the old stale content
        assert status_data.get("health", {}).get("status") == "starting"
        assert status_data.get("connection", {}).get("status") == "starting"
        # Old content should be gone
        assert status_data.get("pid") != 999

    def test_cmd_start_early_return_does_not_clear_files(self, tmp_path, monkeypatch):
        """cmd_start should NOT clear files when returning early (daemon already running)."""
        from eab.cli.daemon_cmds import cmd_start
        
        # Create existing session files
        status_path = tmp_path / "status.json"
        alerts_path = tmp_path / "alerts.log"
        events_path = tmp_path / "events.jsonl"
        
        status_path.write_text(json.dumps({"pid": 999, "running": True}))
        alerts_path.write_text("Current alert\n")
        events_path.write_text('{"type": "current"}\n')
        
        # Mock an existing daemon
        class MockExisting:
            def __init__(self):
                self.pid = 999
                self.is_alive = True
        
        def mock_check_singleton(**kwargs):
            return MockExisting()

        monkeypatch.setattr("eab.cli.daemon_cmds.check_singleton", mock_check_singleton)

        # Call cmd_start with force=False (should return early)
        result = cmd_start(
            base_dir=str(tmp_path),
            port="auto",
            baud=115200,
            force=False,
            json_mode=True
        )
        
        # Should return error code (daemon already running)
        assert result == 1
        
        # Session files should NOT be cleared (daemon is still running)
        assert status_path.exists()
        assert alerts_path.exists()
        assert events_path.exists()
        assert status_path.read_text() == json.dumps({"pid": 999, "running": True})
        assert alerts_path.read_text() == "Current alert\n"
        assert events_path.read_text() == '{"type": "current"}\n'
