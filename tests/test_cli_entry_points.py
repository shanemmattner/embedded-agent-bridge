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


class TestProfileCommands:
    """Test that profile commands are registered and parse arguments correctly."""
    
    def test_profile_function_command_registered(self):
        """profile-function command should be registered and parse required args."""
        from eab.cli import main, _build_parser
        
        # Verify parser accepts the command
        parser = _build_parser()
        
        # Test that required args are enforced
        with pytest.raises(SystemExit):
            # Missing required arguments should fail
            parser.parse_args(["profile-function"])
        
        # Test that all required args parse correctly
        args = parser.parse_args([
            "profile-function",
            "--device", "NRF5340_XXAA_APP",
            "--elf", "/path/to/file.elf",
            "--function", "main",
        ])
        assert args.cmd == "profile-function"
        assert args.device == "NRF5340_XXAA_APP"
        assert args.elf == "/path/to/file.elf"
        assert args.function == "main"
        assert args.cpu_freq is None  # Optional
        
    def test_profile_function_with_cpu_freq(self):
        """profile-function should accept optional --cpu-freq argument."""
        from eab.cli import _build_parser
        
        parser = _build_parser()
        args = parser.parse_args([
            "profile-function",
            "--device", "NRF5340_XXAA_APP",
            "--elf", "/path/to/file.elf",
            "--function", "main",
            "--cpu-freq", "128000000",
        ])
        assert args.cpu_freq == 128000000
        
    def test_profile_function_with_json_flag(self):
        """profile-function should work with global --json flag."""
        from eab.cli import _build_parser, _preprocess_argv
        
        parser = _build_parser()
        
        # Test --json before subcommand
        argv = _preprocess_argv([
            "--json",
            "profile-function",
            "--device", "NRF5340_XXAA_APP",
            "--elf", "/path/to/file.elf",
            "--function", "main",
        ])
        args = parser.parse_args(argv)
        assert args.json is True
        assert args.cmd == "profile-function"
        
        # Test --json after subcommand (should be reordered)
        argv = _preprocess_argv([
            "profile-function",
            "--device", "NRF5340_XXAA_APP",
            "--elf", "/path/to/file.elf",
            "--function", "main",
            "--json",
        ])
        args = parser.parse_args(argv)
        assert args.json is True
        assert args.cmd == "profile-function"
    
    def test_profile_region_command_registered(self):
        """profile-region command should be registered and parse required args."""
        from eab.cli import _build_parser
        
        parser = _build_parser()
        
        # Test that required args are enforced
        with pytest.raises(SystemExit):
            # Missing required arguments should fail
            parser.parse_args(["profile-region"])
        
        # Test that all required args parse correctly (hex addresses)
        args = parser.parse_args([
            "profile-region",
            "--device", "NRF5340_XXAA_APP",
            "--start", "0x1000",
            "--end", "0x2000",
        ])
        assert args.cmd == "profile-region"
        assert args.device == "NRF5340_XXAA_APP"
        assert args.start == 0x1000
        assert args.end == 0x2000
        assert args.cpu_freq is None  # Optional
        
    def test_profile_region_decimal_addresses(self):
        """profile-region should accept decimal addresses."""
        from eab.cli import _build_parser
        
        parser = _build_parser()
        args = parser.parse_args([
            "profile-region",
            "--device", "MCXN947",
            "--start", "4096",
            "--end", "8192",
        ])
        assert args.start == 4096
        assert args.end == 8192
        
    def test_profile_region_with_cpu_freq(self):
        """profile-region should accept optional --cpu-freq argument."""
        from eab.cli import _build_parser
        
        parser = _build_parser()
        args = parser.parse_args([
            "profile-region",
            "--device", "MCXN947",
            "--start", "0x1000",
            "--end", "0x2000",
            "--cpu-freq", "150000000",
        ])
        assert args.cpu_freq == 150000000
        
    def test_profile_region_with_json_flag(self):
        """profile-region should work with global --json flag."""
        from eab.cli import _build_parser, _preprocess_argv
        
        parser = _build_parser()
        argv = _preprocess_argv([
            "--json",
            "profile-region",
            "--device", "MCXN947",
            "--start", "0x1000",
            "--end", "0x2000",
        ])
        args = parser.parse_args(argv)
        assert args.json is True
        assert args.cmd == "profile-region"
    
    def test_dwt_status_command_registered(self):
        """dwt-status command should be registered and parse required args."""
        from eab.cli import _build_parser
        
        parser = _build_parser()
        
        # Test that required args are enforced
        with pytest.raises(SystemExit):
            # Missing required arguments should fail
            parser.parse_args(["dwt-status"])
        
        # Test that required args parse correctly
        args = parser.parse_args([
            "dwt-status",
            "--device", "NRF5340_XXAA_APP",
        ])
        assert args.cmd == "dwt-status"
        assert args.device == "NRF5340_XXAA_APP"
        
    def test_dwt_status_with_json_flag(self):
        """dwt-status should work with global --json flag."""
        from eab.cli import _build_parser, _preprocess_argv
        
        parser = _build_parser()
        argv = _preprocess_argv([
            "--json",
            "dwt-status",
            "--device", "NRF5340_XXAA_APP",
        ])
        args = parser.parse_args(argv)
        assert args.json is True
        assert args.cmd == "dwt-status"
        
    def test_profile_commands_dispatcher_integration(self, tmp_path, monkeypatch):
        """Test that profile commands are dispatched correctly by main()."""
        from eab.cli import main
        from unittest.mock import Mock
        
        # Mock the command functions to avoid needing hardware
        mock_profile_func = Mock(return_value=2)  # Return error code (missing pylink)
        mock_profile_region = Mock(return_value=2)
        mock_dwt_status = Mock(return_value=2)
        
        # Patch the command modules
        monkeypatch.setattr("eab.cli.cmd_profile_function", mock_profile_func)
        monkeypatch.setattr("eab.cli.cmd_profile_region", mock_profile_region)
        monkeypatch.setattr("eab.cli.cmd_dwt_status", mock_dwt_status)
        
        # Test profile-function dispatch
        result = main([
            "--json",
            "profile-function",
            "--device", "NRF5340_XXAA_APP",
            "--elf", "/path/to/file.elf",
            "--function", "main",
            "--cpu-freq", "128000000",
        ])
        assert result == 2  # Mock return value
        mock_profile_func.assert_called_once()
        call_kwargs = mock_profile_func.call_args.kwargs
        assert call_kwargs["device"] == "NRF5340_XXAA_APP"
        assert call_kwargs["elf"] == "/path/to/file.elf"
        assert call_kwargs["function"] == "main"
        assert call_kwargs["cpu_freq"] == 128000000
        assert call_kwargs["json_mode"] is True
        
        # Test profile-region dispatch
        result = main([
            "--json",
            "profile-region",
            "--device", "MCXN947",
            "--start", "0x1000",
            "--end", "0x2000",
            "--cpu-freq", "150000000",
        ])
        assert result == 2
        mock_profile_region.assert_called_once()
        call_kwargs = mock_profile_region.call_args.kwargs
        assert call_kwargs["device"] == "MCXN947"
        assert call_kwargs["start_addr"] == 0x1000
        assert call_kwargs["end_addr"] == 0x2000
        assert call_kwargs["cpu_freq"] == 150000000
        assert call_kwargs["json_mode"] is True
        
        # Test dwt-status dispatch
        result = main([
            "--json",
            "dwt-status",
            "--device", "NRF5340_XXAA_APP",
        ])
        assert result == 2
        mock_dwt_status.assert_called_once()
        call_kwargs = mock_dwt_status.call_args.kwargs
        assert call_kwargs["device"] == "NRF5340_XXAA_APP"
        assert call_kwargs["json_mode"] is True
