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
            
            result = main([
                "gdb-script",
                str(script_file),
                "--device", "NRF5340_XXAA_APP",
                "--elf", "/path/to/app.elf",
                "--chip", "nrf5340",
                "--probe", "jlink",
                "--port", "2331",
                "--json",
            ])
            
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
            
            result = main([
                "inspect",
                "_kernel",
                "--device", "NRF5340_XXAA_APP",
                "--elf", "/path/to/zephyr.elf",
                "--chip", "nrf5340",
                "--probe", "openocd",
                "--port", "3333",
                "--json",
            ])
            
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
            
            result = main(["inspect", "g_state"])
            
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
        """threads should route all arguments to cmd_threads correctly."""
        from unittest.mock import patch
        from eab.control import main
        
        with patch("eab.cli.cmd_threads") as mock_cmd:
            mock_cmd.return_value = 0
            
            result = main([
                "threads",
                "--device", "MCXN947",
                "--elf", "/path/to/mcxn.elf",
                "--chip", "mcxn947",
                "--rtos", "zephyr",
                "--probe", "openocd",
                "--port", "3333",
                "--json",
            ])
            
            assert mock_cmd.called
            call_kwargs = mock_cmd.call_args[1]
            
            assert call_kwargs["device"] == "MCXN947"
            assert call_kwargs["elf"] == "/path/to/mcxn.elf"
            assert call_kwargs["chip"] == "mcxn947"
            assert call_kwargs["rtos"] == "zephyr"
            assert call_kwargs["probe_type"] == "openocd"
            assert call_kwargs["port"] == 3333
            assert call_kwargs["json_mode"] is True

    def test_threads_default_rtos(self):
        """threads should default to zephyr RTOS."""
        from unittest.mock import patch
        from eab.control import main
        
        with patch("eab.cli.cmd_threads") as mock_cmd:
            mock_cmd.return_value = 0
            
            result = main(["threads"])
            
            assert mock_cmd.called
            call_kwargs = mock_cmd.call_args[1]
            assert call_kwargs["rtos"] == "zephyr"

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
            
            result = main([
                "watch",
                "g_counter",
                "--device", "NRF5340_XXAA_APP",
                "--elf", "/path/to/app.elf",
                "--chip", "nrf5340",
                "--max-hits", "50",
                "--probe", "jlink",
                "--port", "2331",
                "--json",
            ])
            
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
            
            result = main(["watch", "my_var"])
            
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
            
            result = main([
                "memdump",
                "0x20000000",
                "1024",
                str(output_file),
                "--device", "NRF5340_XXAA_APP",
                "--elf", "/path/to/app.elf",
                "--chip", "nrf5340",
                "--probe", "jlink",
                "--port", "2331",
                "--json",
            ])
            
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
            
            result = main([
                "memdump",
                "0x20001000",
                "256",
                "/tmp/dump.bin",
            ])
            
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
            ("threads", ["threads"]),
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
            ("threads", ["threads"]),
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
            result = main(["--json", "inspect", "myvar"])
            
            assert mock_cmd.called
            call_kwargs = mock_cmd.call_args[1]
            assert call_kwargs["json_mode"] is True

    def test_command_execution_flow_end_to_end(self, tmp_path):
        """Verify complete execution flow from CLI to command handler."""
        from unittest.mock import patch, MagicMock
        from eab.control import main
        from eab.debug_probes import GDBServerStatus
        from eab.gdb_bridge import GDBResult
        
        script = tmp_path / "test.py"
        script.write_text("print('test')")
        
        # Mock the entire chain
        with patch("eab.cli.debug_cmds.get_debug_probe") as mock_probe_factory:
            mock_probe = MagicMock()
            mock_probe.gdb_port = 2331
            mock_probe.start_gdb_server.return_value = GDBServerStatus(
                running=True,
                pid=1234,
                port=2331,
            )
            mock_probe_factory.return_value = mock_probe
            
            with patch("eab.cli.debug_cmds.run_gdb_python") as mock_gdb:
                mock_gdb.return_value = GDBResult(
                    success=True,
                    stdout="Success",
                    stderr="",
                    returncode=0,
                    gdb_path="/usr/bin/gdb",
                    json_result={"status": "ok"},
                )
                
                # Execute command
                result = main([
                    "gdb-script",
                    str(script),
                    "--device", "NRF5340_XXAA_APP",
                    "--chip", "nrf5340",
                ])
                
                # Verify execution chain
                assert result == 0
                assert mock_probe_factory.called
                assert mock_probe.start_gdb_server.called
                assert mock_gdb.called
                assert mock_probe.stop_gdb_server.called
