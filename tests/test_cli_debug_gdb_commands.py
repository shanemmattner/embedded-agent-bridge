"""Tests for GDB Python scripting CLI commands in eab/cli/debug_cmds.py.

Tests verify that the new GDB scripting commands (gdb-script, inspect, threads,
watch, memdump) properly parse arguments, manage debug probe lifecycle, and
output JSON results correctly.
"""

from __future__ import annotations

import json
import tempfile
from pathlib import Path
from unittest.mock import MagicMock, Mock, patch

import pytest

from eab.cli.debug import (
    cmd_gdb_script,
    cmd_inspect,
    cmd_threads,
    cmd_watch,
    cmd_memdump,
)
from eab.debug_probes import GDBServerStatus
from eab.gdb_bridge import GDBResult


class TestCmdGdbScript:
    """Tests for cmd_gdb_script() function."""

    @patch("eab.cli.debug._helpers.get_debug_probe")
    @patch("eab.cli.debug.gdb_cmds.run_gdb_python")
    def test_successful_execution_jlink(self, mock_run_gdb, mock_get_probe, tmp_path, capsys):
        """cmd_gdb_script should execute script via J-Link probe and return result."""
        # Create test script
        script = tmp_path / "test.py"
        script.write_text("# test")

        # Mock probe
        mock_probe = MagicMock()
        mock_probe.gdb_port = 2331
        mock_probe.start_gdb_server.return_value = GDBServerStatus(running=True, pid=1234, port=2331)
        mock_get_probe.return_value = mock_probe

        # Mock GDB execution
        mock_run_gdb.return_value = GDBResult(
            success=True,
            stdout="GDB output",
            stderr="",
            returncode=0,
            gdb_path="/usr/bin/gdb",
            json_result={"status": "ok", "data": [1, 2, 3]},
        )

        # Execute
        result = cmd_gdb_script(
            base_dir="/tmp/test",
            script_path=str(script),
            device="NRF5340_XXAA_APP",
            elf="/path/to/app.elf",
            chip="nrf5340",
            probe_type="jlink",
            port=None,
            json_mode=True,
        )

        # Verify
        assert result == 0
        mock_probe.start_gdb_server.assert_called_once_with(device="NRF5340_XXAA_APP")
        mock_probe.stop_gdb_server.assert_called_once()
        mock_run_gdb.assert_called_once()
        
        # Check GDB call args
        call_kwargs = mock_run_gdb.call_args[1]
        assert call_kwargs["chip"] == "nrf5340"
        assert call_kwargs["script_path"] == str(script)
        assert call_kwargs["target"] == "localhost:2331"
        assert call_kwargs["elf"] == "/path/to/app.elf"

        # Verify JSON output
        captured = capsys.readouterr()
        output = json.loads(captured.out)
        assert output["success"] is True
        assert output["result"]["status"] == "ok"
        assert output["result"]["data"] == [1, 2, 3]

    @patch("eab.cli.debug._helpers.get_debug_probe")
    @patch("eab.cli.debug.gdb_cmds.run_gdb_python")
    def test_gdb_server_start_failure(self, mock_run_gdb, mock_get_probe, tmp_path, capsys):
        """cmd_gdb_script should return error if GDB server fails to start."""
        script = tmp_path / "test.py"
        script.write_text("# test")

        mock_probe = MagicMock()
        mock_probe.start_gdb_server.return_value = GDBServerStatus(
            running=False,
            last_error="Failed to connect to probe",
        )
        mock_get_probe.return_value = mock_probe

        result = cmd_gdb_script(
            base_dir="/tmp/test",
            script_path=str(script),
            device="NRF5340_XXAA_APP",
            elf=None,
            chip="nrf5340",
            probe_type="jlink",
            port=None,
            json_mode=True,
        )

        assert result == 1
        mock_run_gdb.assert_not_called()
        
        captured = capsys.readouterr()
        output = json.loads(captured.out)
        assert output["success"] is False
        assert "Failed to start GDB server" in output["error"]

    @patch("eab.cli.debug._helpers.get_debug_probe")
    @patch("eab.cli.debug.gdb_cmds.run_gdb_python")
    @patch("eab.cli.debug._helpers.ZephyrProfile")
    def test_openocd_probe_type(self, mock_profile, mock_run_gdb, mock_get_probe, tmp_path):
        """cmd_gdb_script should configure OpenOCD probe correctly."""
        script = tmp_path / "test.py"
        script.write_text("# test")

        # Mock Zephyr profile
        mock_cfg = MagicMock()
        mock_cfg.interface_cfg = "interface/cmsis-dap.cfg"
        mock_cfg.target_cfg = "target/nrf5340.cfg"
        mock_cfg.transport = "swd"
        mock_cfg.extra_commands = []
        mock_profile.return_value.get_openocd_config.return_value = mock_cfg

        # Mock probe
        mock_probe = MagicMock()
        mock_probe.gdb_port = 3333
        mock_probe.start_gdb_server.return_value = GDBServerStatus(running=True, pid=5678, port=3333)
        mock_get_probe.return_value = mock_probe

        mock_run_gdb.return_value = GDBResult(
            success=True,
            stdout="",
            stderr="",
            returncode=0,
            gdb_path="/usr/bin/gdb",
        )

        result = cmd_gdb_script(
            base_dir="/tmp/test",
            script_path=str(script),
            device=None,
            elf=None,
            chip="nrf5340",
            probe_type="openocd",
            port=None,
            json_mode=False,
        )

        assert result == 0
        
        # Verify OpenOCD config was built
        mock_profile.assert_called_once_with(variant="nrf5340")
        
        # Verify probe was created with OpenOCD config
        probe_kwargs = mock_get_probe.call_args[1]
        assert probe_kwargs["interface_cfg"] == "interface/cmsis-dap.cfg"
        assert probe_kwargs["target_cfg"] == "target/nrf5340.cfg"
        assert probe_kwargs["transport"] == "swd"

    @patch("eab.cli.debug._helpers.get_debug_probe")
    @patch("eab.cli.debug.gdb_cmds.run_gdb_python")
    def test_custom_port_override(self, mock_run_gdb, mock_get_probe, tmp_path):
        """cmd_gdb_script should use custom port when provided."""
        script = tmp_path / "test.py"
        script.write_text("# test")

        mock_probe = MagicMock()
        mock_probe.gdb_port = 2331
        mock_probe.start_gdb_server.return_value = GDBServerStatus(running=True, pid=1234, port=2331)
        mock_get_probe.return_value = mock_probe

        mock_run_gdb.return_value = GDBResult(
            success=True,
            stdout="",
            stderr="",
            returncode=0,
            gdb_path="/usr/bin/gdb",
        )

        result = cmd_gdb_script(
            base_dir="/tmp/test",
            script_path=str(script),
            device="NRF5340_XXAA_APP",
            elf=None,
            chip="nrf5340",
            probe_type="jlink",
            port=9999,
            json_mode=False,
        )

        assert result == 0
        
        # Verify custom port was used
        call_kwargs = mock_run_gdb.call_args[1]
        assert call_kwargs["target"] == "localhost:9999"


class TestCmdInspect:
    """Tests for cmd_inspect() function."""

    @patch("eab.cli.debug._helpers.get_debug_probe")
    @patch("eab.cli.debug.inspection_cmds.run_gdb_python")
    @patch("eab.cli.debug.inspection_cmds.generate_struct_inspector")
    def test_inspect_variable(self, mock_gen_script, mock_run_gdb, mock_get_probe, capsys):
        """cmd_inspect should generate inspector script and execute it."""
        mock_gen_script.return_value = "# generated script"

        mock_probe = MagicMock()
        mock_probe.gdb_port = 2331
        mock_probe.start_gdb_server.return_value = GDBServerStatus(running=True, pid=1234, port=2331)
        mock_get_probe.return_value = mock_probe

        mock_run_gdb.return_value = GDBResult(
            success=True,
            stdout="",
            stderr="",
            returncode=0,
            gdb_path="/usr/bin/gdb",
            json_result={
                "status": "ok",
                "var_name": "_kernel",
                "fields": {"ready_q": 0x20001000, "threads": 0x20002000},
            },
        )

        result = cmd_inspect(
            base_dir="/tmp/test",
            variable="_kernel",
            device="NRF5340_XXAA_APP",
            elf="/path/to/app.elf",
            chip="nrf5340",
            probe_type="jlink",
            port=None,
            json_mode=True,
        )

        assert result == 0
        
        # Verify script generation
        mock_gen_script.assert_called_once_with(
            elf_path="/path/to/app.elf",
            struct_name="",
            var_name="_kernel",
        )

        # Verify JSON output includes variable name and fields
        captured = capsys.readouterr()
        output = json.loads(captured.out)
        assert output["success"] is True
        assert output["variable"] == "_kernel"
        assert output["fields"]["ready_q"] == 0x20001000


class TestCmdThreads:
    """Tests for cmd_threads() function."""

    @patch("eab.cli.debug._helpers.get_debug_probe")
    @patch("eab.cli.debug.inspection_cmds.run_gdb_python")
    @patch("eab.cli.debug.inspection_cmds.generate_thread_inspector")
    def test_list_threads_zephyr(self, mock_gen_script, mock_run_gdb, mock_get_probe, capsys):
        """cmd_threads should generate thread inspector for Zephyr RTOS."""
        mock_gen_script.return_value = "# thread inspector"

        mock_probe = MagicMock()
        mock_probe.gdb_port = 2331
        mock_probe.start_gdb_server.return_value = GDBServerStatus(running=True, pid=1234, port=2331)
        mock_get_probe.return_value = mock_probe

        mock_run_gdb.return_value = GDBResult(
            success=True,
            stdout="",
            stderr="",
            returncode=0,
            gdb_path="/usr/bin/gdb",
            json_result={
                "status": "ok",
                "rtos": "zephyr",
                "thread_count": 3,
                "threads": [
                    {"address": 0x20001000, "node_ptr": "0x20001000"},
                    {"address": 0x20002000, "node_ptr": "0x20002000"},
                    {"address": 0x20003000, "node_ptr": "0x20003000"},
                ],
            },
        )

        result = cmd_threads(
            base_dir="/tmp/test",
            device="NRF5340_XXAA_APP",
            elf="/path/to/app.elf",
            chip="nrf5340",
            rtos="zephyr",
            probe_type="jlink",
            port=None,
            json_mode=True,
        )

        assert result == 0
        
        # Verify thread inspector was generated for Zephyr
        mock_gen_script.assert_called_once_with(rtos="zephyr")

        # Verify JSON output
        captured = capsys.readouterr()
        output = json.loads(captured.out)
        assert output["success"] is True
        assert output["rtos"] == "zephyr"
        assert output["thread_count"] == 3
        assert len(output["threads"]) == 3


class TestCmdWatch:
    """Tests for cmd_watch() function."""

    @patch("eab.cli.debug._helpers.get_debug_probe")
    @patch("eab.cli.debug.inspection_cmds.run_gdb_python")
    @patch("eab.cli.debug.inspection_cmds.generate_watchpoint_logger")
    def test_watch_variable(self, mock_gen_script, mock_run_gdb, mock_get_probe, capsys):
        """cmd_watch should generate watchpoint logger and capture hits."""
        mock_gen_script.return_value = "# watchpoint logger"

        mock_probe = MagicMock()
        mock_probe.gdb_port = 2331
        mock_probe.start_gdb_server.return_value = GDBServerStatus(running=True, pid=1234, port=2331)
        mock_get_probe.return_value = mock_probe

        mock_run_gdb.return_value = GDBResult(
            success=True,
            stdout="",
            stderr="",
            returncode=0,
            gdb_path="/usr/bin/gdb",
            json_result={
                "status": "ok",
                "var_name": "g_counter",
                "max_hits": 50,
                "hit_count": 3,
                "hits": [
                    {"hit_number": 1, "value": 42, "backtrace": [{"frame": 0, "name": "main"}]},
                    {"hit_number": 2, "value": 43, "backtrace": [{"frame": 0, "name": "main"}]},
                    {"hit_number": 3, "value": 44, "backtrace": [{"frame": 0, "name": "main"}]},
                ],
            },
        )

        result = cmd_watch(
            base_dir="/tmp/test",
            variable="g_counter",
            device="NRF5340_XXAA_APP",
            elf="/path/to/app.elf",
            chip="nrf5340",
            max_hits=50,
            probe_type="jlink",
            port=None,
            json_mode=True,
        )

        assert result == 0
        
        # Verify watchpoint logger was generated with correct max_hits
        mock_gen_script.assert_called_once_with(var_name="g_counter", max_hits=50)

        # Verify JSON output
        captured = capsys.readouterr()
        output = json.loads(captured.out)
        assert output["success"] is True
        assert output["variable"] == "g_counter"
        assert output["max_hits"] == 50
        assert output["hit_count"] == 3
        assert len(output["hits"]) == 3


class TestCmdMemdump:
    """Tests for cmd_memdump() function."""

    @patch("eab.cli.debug._helpers.get_debug_probe")
    @patch("eab.cli.debug.inspection_cmds.run_gdb_python")
    @patch("eab.cli.debug.inspection_cmds.generate_memory_dump_script")
    def test_dump_memory_region(self, mock_gen_script, mock_run_gdb, mock_get_probe, capsys):
        """cmd_memdump should generate memory dump script and execute it."""
        mock_gen_script.return_value = "# memory dump"

        mock_probe = MagicMock()
        mock_probe.gdb_port = 2331
        mock_probe.start_gdb_server.return_value = GDBServerStatus(running=True, pid=1234, port=2331)
        mock_get_probe.return_value = mock_probe

        mock_run_gdb.return_value = GDBResult(
            success=True,
            stdout="",
            stderr="",
            returncode=0,
            gdb_path="/usr/bin/gdb",
            json_result={
                "status": "ok",
                "start_addr": "0x20000000",
                "size": 1024,
                "output_path": "/tmp/memdump.bin",
                "bytes_written": 1024,
            },
        )

        result = cmd_memdump(
            base_dir="/tmp/test",
            start_addr="0x20000000",
            size=1024,
            device="NRF5340_XXAA_APP",
            elf="/path/to/app.elf",
            chip="nrf5340",
            output_path="/tmp/memdump.bin",
            probe_type="jlink",
            port=None,
            json_mode=True,
        )

        assert result == 0
        
        # Verify memory dump script was generated with correct params
        mock_gen_script.assert_called_once_with(
            start_addr=0x20000000,
            size=1024,
            output_path="/tmp/memdump.bin",
        )

        # Verify JSON output
        captured = capsys.readouterr()
        output = json.loads(captured.out)
        assert output["success"] is True
        assert output["start_addr"] == "0x20000000"
        assert output["size"] == 1024
        assert output["bytes_written"] == 1024

    @patch("eab.cli.debug._helpers.get_debug_probe")
    def test_invalid_address_format(self, mock_get_probe, capsys):
        """cmd_memdump should return error for invalid address format."""
        result = cmd_memdump(
            base_dir="/tmp/test",
            start_addr="not_a_hex_address",
            size=1024,
            device="NRF5340_XXAA_APP",
            elf=None,
            chip="nrf5340",
            output_path="/tmp/out.bin",
            probe_type="jlink",
            port=None,
            json_mode=True,
        )

        assert result == 1
        
        captured = capsys.readouterr()
        output = json.loads(captured.out)
        assert output["success"] is False
        assert "Invalid address" in output["error"]

    @patch("eab.cli.debug._helpers.get_debug_probe")
    @patch("eab.cli.debug.inspection_cmds.run_gdb_python")
    @patch("eab.cli.debug.inspection_cmds.generate_memory_dump_script")
    def test_decimal_address(self, mock_gen_script, mock_run_gdb, mock_get_probe):
        """cmd_memdump should accept decimal addresses."""
        mock_gen_script.return_value = "# memory dump"

        mock_probe = MagicMock()
        mock_probe.gdb_port = 2331
        mock_probe.start_gdb_server.return_value = GDBServerStatus(running=True, pid=1234, port=2331)
        mock_get_probe.return_value = mock_probe

        mock_run_gdb.return_value = GDBResult(
            success=True,
            stdout="",
            stderr="",
            returncode=0,
            gdb_path="/usr/bin/gdb",
            json_result={"status": "ok"},
        )

        result = cmd_memdump(
            base_dir="/tmp/test",
            start_addr="536870912",  # Decimal for 0x20000000
            size=1024,
            device="NRF5340_XXAA_APP",
            elf=None,
            chip="nrf5340",
            output_path="/tmp/out.bin",
            probe_type="jlink",
            port=None,
            json_mode=False,
        )

        assert result == 0
        
        # Verify correct address was passed
        mock_gen_script.assert_called_once_with(
            start_addr=536870912,
            size=1024,
            output_path="/tmp/out.bin",
        )


class TestProbeCleanup:
    """Test that all commands properly clean up probe resources."""

    @patch("eab.cli.debug._helpers.get_debug_probe")
    @patch("eab.cli.debug.gdb_cmds.run_gdb_python")
    def test_probe_stopped_on_success(self, mock_run_gdb, mock_get_probe, tmp_path):
        """Probe should be stopped even when command succeeds."""
        script = tmp_path / "test.py"
        script.write_text("# test")

        mock_probe = MagicMock()
        mock_probe.gdb_port = 2331
        mock_probe.start_gdb_server.return_value = GDBServerStatus(running=True, pid=1234, port=2331)
        mock_get_probe.return_value = mock_probe

        mock_run_gdb.return_value = GDBResult(
            success=True,
            stdout="",
            stderr="",
            returncode=0,
            gdb_path="/usr/bin/gdb",
        )

        cmd_gdb_script(
            base_dir="/tmp/test",
            script_path=str(script),
            device="NRF5340_XXAA_APP",
            elf=None,
            chip="nrf5340",
            probe_type="jlink",
            port=None,
            json_mode=False,
        )

        mock_probe.stop_gdb_server.assert_called_once()

    @patch("eab.cli.debug._helpers.get_debug_probe")
    @patch("eab.cli.debug.gdb_cmds.run_gdb_python")
    def test_probe_stopped_on_gdb_failure(self, mock_run_gdb, mock_get_probe, tmp_path):
        """Probe should be stopped even when GDB fails."""
        script = tmp_path / "test.py"
        script.write_text("# test")

        mock_probe = MagicMock()
        mock_probe.gdb_port = 2331
        mock_probe.start_gdb_server.return_value = GDBServerStatus(running=True, pid=1234, port=2331)
        mock_get_probe.return_value = mock_probe

        mock_run_gdb.side_effect = Exception("GDB crashed")

        with pytest.raises(Exception):
            cmd_gdb_script(
                base_dir="/tmp/test",
                script_path=str(script),
                device="NRF5340_XXAA_APP",
                elf=None,
                chip="nrf5340",
                probe_type="jlink",
                port=None,
                json_mode=False,
            )

        # Probe should still be stopped
        mock_probe.stop_gdb_server.assert_called_once()
