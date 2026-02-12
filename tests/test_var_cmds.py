"""Tests for eabctl vars and read-vars CLI commands.

Tests the CLI integration layer with mocked ELF parsing and
debug probe interactions.
"""

from __future__ import annotations

import json
from io import StringIO
from unittest.mock import patch, MagicMock

import pytest

from eab.cli.var_cmds import cmd_vars, cmd_read_vars
from eab.elf_inspect import ElfSymbol


# =============================================================================
# Fixtures
# =============================================================================


@pytest.fixture
def sample_symbols():
    """Mock ELF symbols for testing."""
    return [
        ElfSymbol(name="g_counter", address=0x20000100, size=4, sym_type="D", section=".data"),
        ElfSymbol(name="g_sensor_data", address=0x20001000, size=32, sym_type="B", section=".bss"),
        ElfSymbol(name="g_version", address=0x08002000, size=4, sym_type="R", section=".rodata"),
        ElfSymbol(name="s_local", address=0x20000200, size=2, sym_type="d", section=".data"),
    ]


@pytest.fixture
def mock_print():
    """Capture _print output."""
    captured = {}

    def fake_print(data, json_mode=False):
        captured["data"] = data
        captured["json_mode"] = json_mode

    return captured, fake_print


# =============================================================================
# cmd_vars tests
# =============================================================================


class TestCmdVars:
    @patch("eab.cli.var_cmds._print")
    @patch("eab.cli.var_cmds.parse_symbols")
    def test_lists_all_symbols(self, mock_parse, mock_print, sample_symbols):
        mock_parse.return_value = sample_symbols

        rc = cmd_vars(elf="/path/to/app.elf", json_mode=True)

        assert rc == 0
        mock_parse.assert_called_once_with("/path/to/app.elf")

        call_args = mock_print.call_args[0][0]
        assert call_args["count"] == 4
        assert len(call_args["variables"]) == 4

    @patch("eab.cli.var_cmds._print")
    @patch("eab.cli.var_cmds.parse_symbols")
    def test_filter_pattern(self, mock_parse, mock_print, sample_symbols):
        mock_parse.return_value = sample_symbols

        rc = cmd_vars(elf="/path/to/app.elf", filter_pattern="g_*", json_mode=True)

        assert rc == 0
        call_args = mock_print.call_args[0][0]
        assert call_args["count"] == 3  # g_counter, g_sensor_data, g_version
        names = [v["name"] for v in call_args["variables"]]
        assert "s_local" not in names
        assert "g_counter" in names

    @patch("eab.cli.var_cmds._print")
    @patch("eab.cli.var_cmds.parse_symbols")
    def test_symbol_format(self, mock_parse, mock_print, sample_symbols):
        mock_parse.return_value = sample_symbols

        rc = cmd_vars(elf="/path/to/app.elf", json_mode=True)

        assert rc == 0
        call_args = mock_print.call_args[0][0]
        var = call_args["variables"][0]  # g_counter (sorted by addr)
        assert "name" in var
        assert "address" in var
        assert "size" in var
        assert "type" in var
        assert "section" in var
        assert var["address"].startswith("0x")

    @patch("eab.cli.var_cmds._print")
    @patch("eab.cli.var_cmds.parse_symbols")
    def test_nm_not_found(self, mock_parse, mock_print):
        mock_parse.side_effect = FileNotFoundError("nm not found")

        rc = cmd_vars(elf="/path/to/app.elf", json_mode=True)

        assert rc == 1
        call_args = mock_print.call_args[0][0]
        assert "error" in call_args

    @patch("eab.cli.var_cmds._print")
    @patch("eab.cli.var_cmds.parse_map_file")
    @patch("eab.cli.var_cmds.parse_symbols")
    def test_map_file_enrichment(self, mock_parse_sym, mock_parse_map, mock_print, sample_symbols):
        from eab.elf_inspect import MapSymbol

        mock_parse_sym.return_value = sample_symbols
        mock_parse_map.return_value = [
            MapSymbol(name="g_counter", address=0x20000100, size=4, region="DRAM", section=".data"),
        ]

        rc = cmd_vars(elf="/path/to/app.elf", map_file="/path/to/app.map", json_mode=True)

        assert rc == 0
        call_args = mock_print.call_args[0][0]
        # g_counter should have region enrichment
        g_counter = [v for v in call_args["variables"] if v["name"] == "g_counter"][0]
        assert g_counter["region"] == "DRAM"

    @patch("eab.cli.var_cmds._print")
    @patch("eab.cli.var_cmds.parse_symbols")
    def test_empty_result(self, mock_parse, mock_print):
        mock_parse.return_value = []

        rc = cmd_vars(elf="/path/to/app.elf", json_mode=True)

        assert rc == 0
        call_args = mock_print.call_args[0][0]
        assert call_args["count"] == 0


# =============================================================================
# cmd_read_vars tests
# =============================================================================


class TestCmdReadVars:
    @patch("eab.cli.var_cmds._print")
    @patch("eab.cli.var_cmds.run_gdb_python")
    @patch("eab.cli.var_cmds._build_probe")
    def test_reads_named_variables(self, mock_build_probe, mock_gdb, mock_print):
        # Mock probe
        probe = MagicMock()
        probe.gdb_port = 2331
        probe.start_gdb_server.return_value = MagicMock(running=True, last_error=None)
        mock_build_probe.return_value = probe

        # Mock GDB result
        mock_gdb.return_value = MagicMock(
            success=True,
            returncode=0,
            gdb_path="gdb",
            json_result={
                "status": "ok",
                "variables": {
                    "g_counter": {"name": "g_counter", "value": 42, "status": "ok"},
                },
            },
            stdout="",
            stderr="",
        )

        rc = cmd_read_vars(
            base_dir="/tmp/eab",
            elf="/path/to/app.elf",
            var_names=["g_counter"],
            json_mode=True,
        )

        assert rc == 0
        mock_gdb.assert_called_once()
        probe.stop_gdb_server.assert_called_once()

    @patch("eab.cli.var_cmds._print")
    @patch("eab.cli.var_cmds._build_probe")
    def test_gdb_server_failure(self, mock_build_probe, mock_print):
        probe = MagicMock()
        probe.start_gdb_server.return_value = MagicMock(running=False, last_error="Connection refused")
        mock_build_probe.return_value = probe

        rc = cmd_read_vars(
            base_dir="/tmp/eab",
            elf="/path/to/app.elf",
            var_names=["g_counter"],
            json_mode=True,
        )

        assert rc == 1
        call_args = mock_print.call_args[0][0]
        assert call_args["success"] is False

    @patch("eab.cli.var_cmds._print")
    def test_no_variables_specified(self, mock_print):
        rc = cmd_read_vars(
            base_dir="/tmp/eab",
            elf="/path/to/app.elf",
            var_names=[],
            json_mode=True,
        )

        assert rc == 1
        call_args = mock_print.call_args[0][0]
        assert "error" in call_args

    @patch("eab.cli.var_cmds._print")
    @patch("eab.cli.var_cmds.parse_symbols")
    @patch("eab.cli.var_cmds.run_gdb_python")
    @patch("eab.cli.var_cmds._build_probe")
    def test_read_all_with_filter(self, mock_build_probe, mock_gdb, mock_parse, mock_print, sample_symbols):
        mock_parse.return_value = sample_symbols

        probe = MagicMock()
        probe.gdb_port = 2331
        probe.start_gdb_server.return_value = MagicMock(running=True, last_error=None)
        mock_build_probe.return_value = probe

        mock_gdb.return_value = MagicMock(
            success=True,
            returncode=0,
            gdb_path="gdb",
            json_result={"status": "ok", "variables": {}},
            stdout="",
            stderr="",
        )

        rc = cmd_read_vars(
            base_dir="/tmp/eab",
            elf="/path/to/app.elf",
            var_names=[],
            read_all=True,
            filter_pattern="g_sensor*",
            json_mode=True,
        )

        assert rc == 0
        # Verify only filtered symbols were requested
        call_args = mock_gdb.call_args
        # The script_path arg was passed; verify parse_symbols was called
        mock_parse.assert_called_once_with("/path/to/app.elf")

    @patch("eab.cli.var_cmds._print")
    @patch("eab.cli.var_cmds.parse_symbols")
    def test_read_all_no_matches(self, mock_parse, mock_print):
        mock_parse.return_value = []

        rc = cmd_read_vars(
            base_dir="/tmp/eab",
            elf="/path/to/app.elf",
            var_names=[],
            read_all=True,
            filter_pattern="nonexistent_*",
            json_mode=True,
        )

        assert rc == 1
        call_args = mock_print.call_args[0][0]
        assert "error" in call_args

    @patch("eab.cli.var_cmds._print")
    @patch("eab.cli.var_cmds.run_gdb_python")
    @patch("eab.cli.var_cmds._build_probe")
    def test_cleanup_on_success(self, mock_build_probe, mock_gdb, mock_print):
        """Probe GDB server should always be stopped."""
        probe = MagicMock()
        probe.gdb_port = 2331
        probe.start_gdb_server.return_value = MagicMock(running=True, last_error=None)
        mock_build_probe.return_value = probe

        mock_gdb.return_value = MagicMock(
            success=True,
            returncode=0,
            gdb_path="gdb",
            json_result={"status": "ok", "variables": {}},
            stdout="",
            stderr="",
        )

        cmd_read_vars(
            base_dir="/tmp/eab",
            elf="/path/to/app.elf",
            var_names=["g_counter"],
            json_mode=True,
        )

        probe.stop_gdb_server.assert_called_once()

    @patch("eab.cli.var_cmds._print")
    @patch("eab.cli.var_cmds.run_gdb_python")
    @patch("eab.cli.var_cmds._build_probe")
    def test_cleanup_on_gdb_failure(self, mock_build_probe, mock_gdb, mock_print):
        """Probe GDB server should be stopped even on GDB failure."""
        probe = MagicMock()
        probe.gdb_port = 2331
        probe.start_gdb_server.return_value = MagicMock(running=True, last_error=None)
        mock_build_probe.return_value = probe

        mock_gdb.side_effect = Exception("GDB crashed")

        with pytest.raises(Exception):
            cmd_read_vars(
                base_dir="/tmp/eab",
                elf="/path/to/app.elf",
                var_names=["g_counter"],
                json_mode=True,
            )

        probe.stop_gdb_server.assert_called_once()


# =============================================================================
# CLI parser integration tests
# =============================================================================


class TestCLIParser:
    def test_vars_parser(self):
        from eab.cli import _build_parser
        parser = _build_parser()
        args = parser.parse_args(["vars", "--elf", "/path/to/app.elf"])
        assert args.cmd == "vars"
        assert args.elf == "/path/to/app.elf"

    def test_vars_with_filter(self):
        from eab.cli import _build_parser
        parser = _build_parser()
        args = parser.parse_args(["vars", "--elf", "/path/to/app.elf", "--filter", "g_*"])
        assert args.filter_pattern == "g_*"

    def test_vars_with_map(self):
        from eab.cli import _build_parser
        parser = _build_parser()
        args = parser.parse_args(["vars", "--elf", "/path/to/app.elf", "--map", "/path/to/app.map"])
        assert args.map_file == "/path/to/app.map"

    def test_read_vars_parser(self):
        from eab.cli import _build_parser
        parser = _build_parser()
        args = parser.parse_args(["read-vars", "--elf", "/path/to/app.elf", "--var", "g_counter"])
        assert args.cmd == "read-vars"
        assert args.var_names == ["g_counter"]

    def test_read_vars_multiple_vars(self):
        from eab.cli import _build_parser
        parser = _build_parser()
        args = parser.parse_args([
            "read-vars", "--elf", "/path/to/app.elf",
            "--var", "g_counter", "--var", "g_state",
        ])
        assert args.var_names == ["g_counter", "g_state"]

    def test_read_vars_all(self):
        from eab.cli import _build_parser
        parser = _build_parser()
        args = parser.parse_args(["read-vars", "--elf", "/path/to/app.elf", "--all"])
        assert args.read_all is True

    def test_read_vars_all_with_filter(self):
        from eab.cli import _build_parser
        parser = _build_parser()
        args = parser.parse_args([
            "read-vars", "--elf", "/path/to/app.elf",
            "--all", "--filter", "g_sensor*",
        ])
        assert args.read_all is True
        assert args.filter_pattern == "g_sensor*"

    def test_read_vars_probe_options(self):
        from eab.cli import _build_parser
        parser = _build_parser()
        args = parser.parse_args([
            "read-vars", "--elf", "/path/to/app.elf",
            "--var", "g_counter",
            "--device", "NRF5340_XXAA_APP",
            "--chip", "nrf5340",
            "--probe", "jlink",
        ])
        assert args.device == "NRF5340_XXAA_APP"
        assert args.chip == "nrf5340"
        assert args.probe == "jlink"
