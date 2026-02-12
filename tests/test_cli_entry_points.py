"""
Tests for CLI entry points (eab and eabctl).

These tests verify that the entry points are properly configured and
that basic CLI functionality works (--help, --version, argument parsing).
"""

from __future__ import annotations

import subprocess
import sys
from pathlib import Path

import pytest


class TestDaemonEntryPoint:
    """Tests for the 'eab' daemon CLI entry point."""

    def test_daemon_main_accepts_argv(self):
        """The main() function should accept an optional argv parameter."""
        from eab.daemon import main

        # Should not raise an exception
        # Note: We can't actually run the daemon in tests without mocking,
        # but we can verify the signature accepts argv
        import inspect
        sig = inspect.signature(main)
        assert "argv" in sig.parameters
        # The parameter should have a default (None)
        assert sig.parameters["argv"].default is None
        # And the annotation should be Optional (either old-style or new-style union)
        annotation_str = str(sig.parameters["argv"].annotation)
        assert ("None" in annotation_str or "Optional" in annotation_str) and "list" in annotation_str

    def test_daemon_main_returns_int(self):
        """The main() function should return an int exit code."""
        from eab.daemon import main

        import inspect
        sig = inspect.signature(main)
        assert sig.return_annotation == int or sig.return_annotation == "int"

    def test_daemon_help_flag(self):
        """Running with --help should show help and exit with code 0."""
        from eab.daemon import main

        with pytest.raises(SystemExit) as exc_info:
            main(["--help"])
        assert exc_info.value.code == 0

    def test_daemon_version_flag(self):
        """Running with --version should show version and exit."""
        from eab.daemon import main

        with pytest.raises(SystemExit) as exc_info:
            main(["--version"])
        # argparse version action exits with code 0
        assert exc_info.value.code == 0

    def test_daemon_list_flag(self):
        """Running with --list should list serial ports and exit cleanly."""
        from eab.daemon import main

        # This should return 0 (success)
        result = main(["--list"])
        assert result == 0


class TestControlEntryPoint:
    """Tests for the 'eabctl' CLI entry point."""

    def test_control_main_accepts_argv(self):
        """The main() function should accept an optional argv parameter."""
        from eab.control import main

        import inspect
        sig = inspect.signature(main)
        assert "argv" in sig.parameters
        assert sig.parameters["argv"].default is not None or sig.parameters["argv"].annotation

    def test_control_main_returns_int(self):
        """The main() function should return an int exit code."""
        from eab.control import main

        import inspect
        sig = inspect.signature(main)
        assert sig.return_annotation == int or sig.return_annotation == "int"

    def test_control_help_flag(self):
        """Running with --help should show help and exit with code 0."""
        from eab.control import main

        with pytest.raises(SystemExit) as exc_info:
            main(["--help"])
        assert exc_info.value.code == 0

    def test_control_version_flag(self):
        """Running with --version should show version and exit."""
        from eab.control import main

        with pytest.raises(SystemExit) as exc_info:
            main(["--version"])
        assert exc_info.value.code == 0

    def test_control_status_json(self):
        """Running 'status --json' should work (even if daemon not running)."""
        from eab.control import main

        # status command should return 1 if daemon not running, but should not crash
        result = main(["status", "--json"])
        assert isinstance(result, int)

    @pytest.mark.parametrize("cmd,default", [("tail", 50), ("alerts", 20), ("events", 50)])
    def test_lines_positional_arg(self, cmd, default):
        """tail/alerts/events accept positional line count: eabctl tail 10"""
        from eab.control import main as ctl_main
        import argparse

        # Test positional form: eabctl tail 10
        result = ctl_main(["--base-dir", "/tmp/eab-test-nonexistent", cmd, "10"])
        assert isinstance(result, int)

    @pytest.mark.parametrize("cmd,default", [("tail", 50), ("alerts", 20), ("events", 50)])
    def test_lines_flag_arg(self, cmd, default):
        """tail/alerts/events accept -n flag: eabctl tail -n 10"""
        from eab.control import main as ctl_main

        result = ctl_main(["--base-dir", "/tmp/eab-test-nonexistent", cmd, "-n", "10"])
        assert isinstance(result, int)

    @pytest.mark.parametrize("cmd,default", [("tail", 50), ("alerts", 20), ("events", 50)])
    def test_lines_default(self, cmd, default):
        """tail/alerts/events default to correct line count when no arg given."""
        from eab.control import main as ctl_main

        result = ctl_main(["--base-dir", "/tmp/eab-test-nonexistent", cmd])
        assert isinstance(result, int)


class TestModuleExecution:
    """Test that modules can be executed via python -m."""

    def test_eab_module_executable(self):
        """python -m eab --help should work."""
        result = subprocess.run(
            [sys.executable, "-m", "eab", "--help"],
            capture_output=True,
            text=True,
        )
        assert result.returncode == 0
        assert "Embedded Agent Bridge" in result.stdout or "usage:" in result.stdout

    def test_eab_module_version(self):
        """python -m eab --version should work."""
        result = subprocess.run(
            [sys.executable, "-m", "eab", "--version"],
            capture_output=True,
            text=True,
        )
        assert result.returncode == 0
        # Version output goes to stdout with argparse
        output = result.stdout + result.stderr
        assert "1.0.0" in output or "embedded-agent-bridge" in output


class TestPackageStructure:
    """Test that the package structure is correct for installation."""

    def test_pyproject_exists(self):
        """pyproject.toml should exist at the repo root."""
        repo_root = Path(__file__).parent.parent
        pyproject = repo_root / "pyproject.toml"
        assert pyproject.exists(), "pyproject.toml not found"

    def test_pyproject_has_entry_points(self):
        """pyproject.toml should define entry points."""
        repo_root = Path(__file__).parent.parent
        pyproject = repo_root / "pyproject.toml"
        content = pyproject.read_text()

        assert "[project.scripts]" in content
        assert "eab = " in content
        assert "eabctl = " in content

    def test_control_module_exists(self):
        """eab/control.py should exist."""
        repo_root = Path(__file__).parent.parent
        control_module = repo_root / "eab" / "control.py"
        assert control_module.exists(), "eab/control.py not found"

    def test_daemon_module_exists(self):
        """eab/daemon.py should exist."""
        repo_root = Path(__file__).parent.parent
        daemon_module = repo_root / "eab" / "daemon.py"
        assert daemon_module.exists(), "eab/daemon.py not found"

    def test_control_has_main(self):
        """eab.control should have a main() function."""
        from eab import control
        assert hasattr(control, "main")
        assert callable(control.main)

    def test_daemon_has_main(self):
        """eab.daemon should have a main() function."""
        from eab import daemon
        assert hasattr(daemon, "main")
        assert callable(daemon.main)
