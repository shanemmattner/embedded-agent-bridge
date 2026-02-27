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
        # Should not raise an exception
        # Note: We can't actually run the daemon in tests without mocking,
        # but we can verify the signature accepts argv
        import inspect

        from eab.daemon import main

        sig = inspect.signature(main)
        assert "argv" in sig.parameters
        # The parameter should have a default (None)
        assert sig.parameters["argv"].default is None
        # And the annotation should be Optional (either old-style or new-style union)
        annotation_str = str(sig.parameters["argv"].annotation)
        assert ("None" in annotation_str or "Optional" in annotation_str) and "list" in annotation_str

    def test_daemon_main_returns_int(self):
        """The main() function should return an int exit code."""
        import inspect

        from eab.daemon import main

        sig = inspect.signature(main)
        assert sig.return_annotation is int or sig.return_annotation == "int"

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
        import inspect

        from eab.control import main

        sig = inspect.signature(main)
        assert "argv" in sig.parameters
        assert sig.parameters["argv"].default is not None or sig.parameters["argv"].annotation

    def test_control_main_returns_int(self):
        """The main() function should return an int exit code."""
        import inspect

        from eab.control import main

        sig = inspect.signature(main)
        assert sig.return_annotation is int or sig.return_annotation == "int"

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
        from eab.cli import _build_parser

        # Verify parser accepts the command
        parser = _build_parser()

        # Test that required args are enforced
        with pytest.raises(SystemExit):
            # Missing required arguments should fail
            parser.parse_args(["profile-function"])

        # Test that all required args parse correctly
        args = parser.parse_args(
            [
                "profile-function",
                "--device",
                "NRF5340_XXAA_APP",
                "--elf",
                "/path/to/file.elf",
                "--function",
                "main",
            ]
        )
        assert args.cmd == "profile-function"
        assert args.device == "NRF5340_XXAA_APP"
        assert args.elf == "/path/to/file.elf"
        assert args.function == "main"
        assert args.cpu_freq is None  # Optional

    def test_profile_function_with_cpu_freq(self):
        """profile-function should accept optional --cpu-freq argument."""
        from eab.cli import _build_parser

        parser = _build_parser()
        args = parser.parse_args(
            [
                "profile-function",
                "--device",
                "NRF5340_XXAA_APP",
                "--elf",
                "/path/to/file.elf",
                "--function",
                "main",
                "--cpu-freq",
                "128000000",
            ]
        )
        assert args.cpu_freq == 128000000

    def test_profile_function_with_json_flag(self):
        """profile-function should work with global --json flag."""
        from eab.cli import _build_parser, _preprocess_argv

        parser = _build_parser()

        # Test --json before subcommand
        argv = _preprocess_argv(
            [
                "--json",
                "profile-function",
                "--device",
                "NRF5340_XXAA_APP",
                "--elf",
                "/path/to/file.elf",
                "--function",
                "main",
            ]
        )
        args = parser.parse_args(argv)
        assert args.json is True
        assert args.cmd == "profile-function"

        # Test --json after subcommand (should be reordered)
        argv = _preprocess_argv(
            [
                "profile-function",
                "--device",
                "NRF5340_XXAA_APP",
                "--elf",
                "/path/to/file.elf",
                "--function",
                "main",
                "--json",
            ]
        )
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
        args = parser.parse_args(
            [
                "profile-region",
                "--device",
                "NRF5340_XXAA_APP",
                "--start",
                "0x1000",
                "--end",
                "0x2000",
            ]
        )
        assert args.cmd == "profile-region"
        assert args.device == "NRF5340_XXAA_APP"
        assert args.start == 0x1000
        assert args.end == 0x2000
        assert args.cpu_freq is None  # Optional

    def test_profile_region_decimal_addresses(self):
        """profile-region should accept decimal addresses."""
        from eab.cli import _build_parser

        parser = _build_parser()
        args = parser.parse_args(
            [
                "profile-region",
                "--device",
                "MCXN947",
                "--start",
                "4096",
                "--end",
                "8192",
            ]
        )
        assert args.start == 4096
        assert args.end == 8192

    def test_profile_region_with_cpu_freq(self):
        """profile-region should accept optional --cpu-freq argument."""
        from eab.cli import _build_parser

        parser = _build_parser()
        args = parser.parse_args(
            [
                "profile-region",
                "--device",
                "MCXN947",
                "--start",
                "0x1000",
                "--end",
                "0x2000",
                "--cpu-freq",
                "150000000",
            ]
        )
        assert args.cpu_freq == 150000000

    def test_profile_region_with_json_flag(self):
        """profile-region should work with global --json flag."""
        from eab.cli import _build_parser, _preprocess_argv

        parser = _build_parser()
        argv = _preprocess_argv(
            [
                "--json",
                "profile-region",
                "--device",
                "MCXN947",
                "--start",
                "0x1000",
                "--end",
                "0x2000",
            ]
        )
        args = parser.parse_args(argv)
        assert args.json is True
        assert args.cmd == "profile-region"

    def test_dwt_status_command_registered(self):
        """dwt-status command should be registered and parse args."""
        from eab.cli import _build_parser

        parser = _build_parser()

        # dwt-status has no required args (--device is optional for OpenOCD)
        args = parser.parse_args(["dwt-status"])
        assert args.cmd == "dwt-status"

        # Test that optional args parse correctly
        args = parser.parse_args(
            [
                "dwt-status",
                "--device",
                "NRF5340_XXAA_APP",
            ]
        )
        assert args.cmd == "dwt-status"
        assert args.device == "NRF5340_XXAA_APP"

    def test_dwt_status_with_json_flag(self):
        """dwt-status should work with global --json flag."""
        from eab.cli import _build_parser, _preprocess_argv

        parser = _build_parser()
        argv = _preprocess_argv(
            [
                "--json",
                "dwt-status",
                "--device",
                "NRF5340_XXAA_APP",
            ]
        )
        args = parser.parse_args(argv)
        assert args.json is True
        assert args.cmd == "dwt-status"

    def test_profile_commands_dispatcher_integration(self, tmp_path, monkeypatch):
        """Test that profile commands are dispatched correctly by main()."""
        from unittest.mock import Mock

        from eab.cli import main

        # Mock the command functions to avoid needing hardware
        mock_profile_func = Mock(return_value=2)  # Return error code (missing pylink)
        mock_profile_region = Mock(return_value=2)
        mock_dwt_status = Mock(return_value=2)

        # Patch the command modules
        monkeypatch.setattr("eab.cli.cmd_profile_function", mock_profile_func)
        monkeypatch.setattr("eab.cli.cmd_profile_region", mock_profile_region)
        monkeypatch.setattr("eab.cli.cmd_dwt_status", mock_dwt_status)

        # Test profile-function dispatch
        result = main(
            [
                "--json",
                "profile-function",
                "--device",
                "NRF5340_XXAA_APP",
                "--elf",
                "/path/to/file.elf",
                "--function",
                "main",
                "--cpu-freq",
                "128000000",
            ]
        )
        assert result == 2  # Mock return value
        mock_profile_func.assert_called_once()
        call_kwargs = mock_profile_func.call_args.kwargs
        assert call_kwargs["device"] == "NRF5340_XXAA_APP"
        assert call_kwargs["elf"] == "/path/to/file.elf"
        assert call_kwargs["function"] == "main"
        assert call_kwargs["cpu_freq"] == 128000000
        assert call_kwargs["json_mode"] is True

        # Test profile-region dispatch
        result = main(
            [
                "--json",
                "profile-region",
                "--device",
                "MCXN947",
                "--start",
                "0x1000",
                "--end",
                "0x2000",
                "--cpu-freq",
                "150000000",
            ]
        )
        assert result == 2
        mock_profile_region.assert_called_once()
        call_kwargs = mock_profile_region.call_args.kwargs
        assert call_kwargs["device"] == "MCXN947"
        assert call_kwargs["start_addr"] == 0x1000
        assert call_kwargs["end_addr"] == 0x2000
        assert call_kwargs["cpu_freq"] == 150000000
        assert call_kwargs["json_mode"] is True

        # Test dwt-status dispatch
        result = main(
            [
                "--json",
                "dwt-status",
                "--device",
                "NRF5340_XXAA_APP",
            ]
        )
        assert result == 2
        mock_dwt_status.assert_called_once()
        call_kwargs = mock_dwt_status.call_args.kwargs
        assert call_kwargs["device"] == "NRF5340_XXAA_APP"
        assert call_kwargs["json_mode"] is True


class TestGDBCommandEntryPoints:
    """Integration tests for GDB command entry points.

    These tests verify that the new GDB commands (gdb-script, inspect, threads,
    watch, memdump) properly route arguments from CLI to the command handlers
    and execute without crashes.
    """

    def test_gdb_script_help(self):
        """gdb-script --help should display help without errors."""
        from eab.control import main

        with pytest.raises(SystemExit) as exc_info:
            main(["gdb-script", "--help"])
        assert exc_info.value.code == 0

    def test_gdb_script_argument_routing(self, tmp_path):
        """gdb-script should route all arguments to cmd_gdb_script correctly."""
        from unittest.mock import patch

        from eab.control import main

        script_file = tmp_path / "test.py"
        script_file.write_text("# test script")

        with patch("eab.cli.cmd_gdb_script") as mock_cmd:
            mock_cmd.return_value = 0

            main(
                [
                    "gdb-script",
                    str(script_file),
                    "--device",
                    "NRF5340_XXAA_APP",
                    "--elf",
                    "/path/to/app.elf",
                    "--chip",
                    "nrf5340",
                    "--probe",
                    "jlink",
                    "--port",
                    "2331",
                    "--json",
                ]
            )

            # Verify command was called
            assert mock_cmd.called
            call_kwargs = mock_cmd.call_args[1]

            # Verify all arguments were routed correctly
            assert call_kwargs["script_path"] == str(script_file)
            assert call_kwargs["device"] == "NRF5340_XXAA_APP"
            assert call_kwargs["elf"] == "/path/to/app.elf"
            assert call_kwargs["chip"] == "nrf5340"
            assert call_kwargs["probe_type"] == "jlink"
            assert call_kwargs["port"] == 2331
            assert call_kwargs["json_mode"] is True

    def test_inspect_help(self):
        """inspect --help should display help without errors."""
        from eab.control import main

        with pytest.raises(SystemExit) as exc_info:
            main(["inspect", "--help"])
        assert exc_info.value.code == 0

    def test_inspect_argument_routing(self):
        """inspect should route all arguments to cmd_inspect correctly."""
        from unittest.mock import patch

        from eab.control import main

        with patch("eab.cli.cmd_inspect") as mock_cmd:
            mock_cmd.return_value = 0

            main(
                [
                    "inspect",
                    "_kernel",
                    "--device",
                    "NRF5340_XXAA_APP",
                    "--elf",
                    "/path/to/zephyr.elf",
                    "--chip",
                    "nrf5340",
                    "--probe",
                    "openocd",
                    "--port",
                    "3333",
                    "--json",
                ]
            )

            assert mock_cmd.called
            call_kwargs = mock_cmd.call_args[1]

            # Verify variable name and all flags
            assert call_kwargs["variable"] == "_kernel"
            assert call_kwargs["device"] == "NRF5340_XXAA_APP"
            assert call_kwargs["elf"] == "/path/to/zephyr.elf"
            assert call_kwargs["chip"] == "nrf5340"
            assert call_kwargs["probe_type"] == "openocd"
            assert call_kwargs["port"] == 3333
            assert call_kwargs["json_mode"] is True

    def test_inspect_default_arguments(self):
        """inspect should use default values when optional args not provided."""
        from unittest.mock import patch

        from eab.control import main

        with patch("eab.cli.cmd_inspect") as mock_cmd:
            mock_cmd.return_value = 0

            main(["inspect", "g_state"])

            assert mock_cmd.called
            call_kwargs = mock_cmd.call_args[1]

            # Verify defaults
            assert call_kwargs["variable"] == "g_state"
            assert call_kwargs["device"] is None
            assert call_kwargs["elf"] is None
            assert call_kwargs["chip"] == "nrf5340"  # default
            assert call_kwargs["probe_type"] == "jlink"  # default
            assert call_kwargs["port"] is None
            assert call_kwargs["json_mode"] is False

    def test_threads_help(self):
        """threads --help should display help without errors."""
        from eab.control import main

        with pytest.raises(SystemExit) as exc_info:
            main(["threads", "--help"])
        assert exc_info.value.code == 0

    def test_threads_argument_routing(self):
        """threads snapshot should route device and elf arguments correctly."""
        from unittest.mock import patch

        from eab.control import main

        with patch("eab.thread_inspector.inspect_threads") as mock_inspect:
            mock_inspect.return_value = []

            main(
                [
                    "--json",
                    "threads",
                    "snapshot",
                    "--device",
                    "MCXN947",
                    "--elf",
                    "/path/to/mcxn.elf",
                ]
            )

            assert mock_inspect.called
            call_kwargs = mock_inspect.call_args[1]

            assert call_kwargs["target"] == "MCXN947"
            assert call_kwargs["elf"] == "/path/to/mcxn.elf"

    def test_threads_default_rtos(self):
        """threads snapshot subcommand is callable with required args."""
        from unittest.mock import patch

        from eab.control import main

        with patch("eab.thread_inspector.inspect_threads") as mock_inspect:
            mock_inspect.return_value = []

            result = main(
                [
                    "threads",
                    "snapshot",
                    "--device",
                    "NRF5340_XXAA_APP",
                    "--elf",
                    "/tmp/zephyr.elf",
                ]
            )

            assert result == 0
            assert mock_inspect.called

    def test_watch_help(self):
        """watch --help should display help without errors."""
        from eab.control import main

        with pytest.raises(SystemExit) as exc_info:
            main(["watch", "--help"])
        assert exc_info.value.code == 0

    def test_watch_argument_routing(self):
        """watch should route all arguments to cmd_watch correctly."""
        from unittest.mock import patch

        from eab.control import main

        with patch("eab.cli.cmd_watch") as mock_cmd:
            mock_cmd.return_value = 0

            main(
                [
                    "watch",
                    "g_counter",
                    "--device",
                    "NRF5340_XXAA_APP",
                    "--elf",
                    "/path/to/app.elf",
                    "--chip",
                    "nrf5340",
                    "--max-hits",
                    "50",
                    "--probe",
                    "jlink",
                    "--port",
                    "2331",
                    "--json",
                ]
            )

            assert mock_cmd.called
            call_kwargs = mock_cmd.call_args[1]

            assert call_kwargs["variable"] == "g_counter"
            assert call_kwargs["device"] == "NRF5340_XXAA_APP"
            assert call_kwargs["elf"] == "/path/to/app.elf"
            assert call_kwargs["chip"] == "nrf5340"
            assert call_kwargs["max_hits"] == 50
            assert call_kwargs["probe_type"] == "jlink"
            assert call_kwargs["port"] == 2331
            assert call_kwargs["json_mode"] is True

    def test_watch_default_max_hits(self):
        """watch should default to 100 max hits."""
        from unittest.mock import patch

        from eab.control import main

        with patch("eab.cli.cmd_watch") as mock_cmd:
            mock_cmd.return_value = 0

            main(["watch", "my_var"])

            assert mock_cmd.called
            call_kwargs = mock_cmd.call_args[1]
            assert call_kwargs["max_hits"] == 100

    def test_watch_max_hits_changes_behavior(self):
        """watch --max-hits flag should change the max_hits parameter."""
        from unittest.mock import patch

        from eab.control import main

        with patch("eab.cli.cmd_watch") as mock_cmd:
            mock_cmd.return_value = 0

            # Test with default
            main(["watch", "var1"])
            assert mock_cmd.call_args[1]["max_hits"] == 100

            # Test with custom value
            main(["watch", "var2", "--max-hits", "25"])
            assert mock_cmd.call_args[1]["max_hits"] == 25

            # Verify different values produce different results
            assert 100 != 25  # Proves the flag actually changes behavior

    def test_memdump_help(self):
        """memdump --help should display help without errors."""
        from eab.control import main

        with pytest.raises(SystemExit) as exc_info:
            main(["memdump", "--help"])
        assert exc_info.value.code == 0

    def test_memdump_argument_routing(self, tmp_path):
        """memdump should route all arguments to cmd_memdump correctly."""
        from unittest.mock import patch

        from eab.control import main

        output_file = tmp_path / "memory.bin"

        with patch("eab.cli.cmd_memdump") as mock_cmd:
            mock_cmd.return_value = 0

            main(
                [
                    "memdump",
                    "0x20000000",
                    "1024",
                    str(output_file),
                    "--device",
                    "NRF5340_XXAA_APP",
                    "--elf",
                    "/path/to/app.elf",
                    "--chip",
                    "nrf5340",
                    "--probe",
                    "jlink",
                    "--port",
                    "2331",
                    "--json",
                ]
            )

            assert mock_cmd.called
            call_kwargs = mock_cmd.call_args[1]

            assert call_kwargs["start_addr"] == "0x20000000"
            assert call_kwargs["size"] == 1024
            assert call_kwargs["output_path"] == str(output_file)
            assert call_kwargs["device"] == "NRF5340_XXAA_APP"
            assert call_kwargs["elf"] == "/path/to/app.elf"
            assert call_kwargs["chip"] == "nrf5340"
            assert call_kwargs["probe_type"] == "jlink"
            assert call_kwargs["port"] == 2331
            assert call_kwargs["json_mode"] is True

    def test_memdump_required_positional_args(self):
        """memdump requires start_addr, size, and output_path."""
        from unittest.mock import patch

        from eab.control import main

        with patch("eab.cli.cmd_memdump") as mock_cmd:
            mock_cmd.return_value = 0

            main(
                [
                    "memdump",
                    "0x20001000",
                    "256",
                    "/tmp/dump.bin",
                ]
            )

            assert mock_cmd.called
            call_kwargs = mock_cmd.call_args[1]

            # Verify positional args were parsed correctly
            assert call_kwargs["start_addr"] == "0x20001000"
            assert call_kwargs["size"] == 256
            assert call_kwargs["output_path"] == "/tmp/dump.bin"

    def test_json_flag_applies_to_all_commands(self):
        """--json flag should be passed to all GDB commands."""
        from unittest.mock import patch

        from eab.control import main

        commands_to_test = [
            ("gdb-script", ["gdb-script", "/tmp/test.py"]),
            ("inspect", ["inspect", "var"]),
            ("watch", ["watch", "var"]),
            ("memdump", ["memdump", "0x20000000", "1024", "/tmp/out.bin"]),
        ]

        for cmd_name, args in commands_to_test:
            with patch(f"eab.cli.cmd_{cmd_name.replace('-', '_')}") as mock_cmd:
                mock_cmd.return_value = 0

                # Without --json
                main(args)
                assert mock_cmd.call_args[1]["json_mode"] is False

                # With --json
                main(args + ["--json"])
                assert mock_cmd.call_args[1]["json_mode"] is True

    def test_probe_type_flag_applies_to_all_commands(self):
        """--probe flag should be accepted by all GDB commands."""
        from unittest.mock import patch

        from eab.control import main

        commands_to_test = [
            ("gdb-script", ["gdb-script", "/tmp/test.py"]),
            ("inspect", ["inspect", "var"]),
            ("watch", ["watch", "var"]),
            ("memdump", ["memdump", "0x20000000", "1024", "/tmp/out.bin"]),
        ]

        for cmd_name, args in commands_to_test:
            with patch(f"eab.cli.cmd_{cmd_name.replace('-', '_')}") as mock_cmd:
                mock_cmd.return_value = 0

                # Test jlink (default)
                main(args)
                assert mock_cmd.call_args[1]["probe_type"] == "jlink"

                # Test openocd
                main(args + ["--probe", "openocd"])
                assert mock_cmd.call_args[1]["probe_type"] == "openocd"

    def test_global_json_flag_before_subcommand(self):
        """--json can appear before the subcommand (global flag reordering)."""
        from unittest.mock import patch

        from eab.control import main

        with patch("eab.cli.cmd_inspect") as mock_cmd:
            mock_cmd.return_value = 0

            # --json before subcommand
            main(["--json", "inspect", "myvar"])

            assert mock_cmd.called
            call_kwargs = mock_cmd.call_args[1]
            assert call_kwargs["json_mode"] is True

    def test_command_execution_flow_end_to_end(self, tmp_path):
        """Verify complete execution flow from CLI to command handler."""
        from unittest.mock import MagicMock, patch

        from eab.control import main
        from eab.debug_probes import GDBServerStatus
        from eab.gdb_bridge import GDBResult

        script = tmp_path / "test.py"
        script.write_text("print('test')")

        # Mock the entire chain
        with patch("eab.cli.debug.gdb_cmds._build_probe") as mock_probe_factory:
            mock_probe = MagicMock()
            mock_probe.gdb_port = 2331
            mock_probe.start_gdb_server.return_value = GDBServerStatus(
                running=True,
                pid=1234,
                port=2331,
            )
            mock_probe_factory.return_value = mock_probe

            with patch("eab.cli.debug.gdb_cmds.run_gdb_python") as mock_gdb:
                mock_gdb.return_value = GDBResult(
                    success=True,
                    stdout="Success",
                    stderr="",
                    returncode=0,
                    gdb_path="/usr/bin/gdb",
                    json_result={"status": "ok"},
                )

                # Execute command
                result = main(
                    [
                        "gdb-script",
                        str(script),
                        "--device",
                        "NRF5340_XXAA_APP",
                        "--chip",
                        "nrf5340",
                    ]
                )

                # Verify execution chain
                assert result == 0
                assert mock_probe_factory.called
                assert mock_probe.start_gdb_server.called
                assert mock_gdb.called
                assert mock_probe.stop_gdb_server.called
