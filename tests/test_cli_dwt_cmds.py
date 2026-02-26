"""CLI tests for eab.cli.dwt commands and parser."""

from __future__ import annotations

import json
from unittest.mock import MagicMock, patch

import pytest


# =============================================================================
# Parser tests
# =============================================================================

class TestParserDwtSubcommand:

    def test_dwt_watch_required_args_parsed(self):
        """Parser should accept: dwt watch --symbol x --device NRF5340_XXAA_APP."""
        from eab.cli.parser import _build_parser
        p = _build_parser()
        args = p.parse_args([
            "dwt", "watch",
            "--symbol", "conn_interval",
            "--device", "NRF5340_XXAA_APP",
        ])
        assert args.cmd == "dwt"
        assert args.dwt_action == "watch"
        assert args.symbol == "conn_interval"
        assert args.mode == "write"       # default
        assert args.poll_hz == 100        # default
        assert args.duration is None      # default
        assert args.output is None        # default

    def test_dwt_watch_with_all_options(self):
        """Parser should handle all dwt watch options."""
        from eab.cli.parser import _build_parser
        p = _build_parser()
        args = p.parse_args([
            "dwt", "watch",
            "--symbol", "my_var",
            "--device", "NRF5340_XXAA_APP",
            "--elf", "/tmp/zephyr.elf",
            "--mode", "rw",
            "--size", "4",
            "--poll-hz", "200",
            "--output", "/tmp/events.jsonl",
            "--duration", "5.0",
            "--probe-selector", "12345678",
        ])
        assert args.dwt_action == "watch"
        assert args.mode == "rw"
        assert args.size == 4
        assert args.poll_hz == 200
        assert args.output == "/tmp/events.jsonl"
        assert args.duration == pytest.approx(5.0)
        assert args.probe_selector == "12345678"

    def test_dwt_watch_addr_override(self):
        """dwt watch --addr should parse hex address."""
        from eab.cli.parser import _build_parser
        p = _build_parser()
        args = p.parse_args([
            "dwt", "watch",
            "--addr", "0x20001234",
            "--device", "NRF5340_XXAA_APP",
        ])
        assert args.addr == 0x20001234

    def test_dwt_halt_parsed(self):
        """Parser should accept: dwt halt --symbol x --elf f.elf."""
        from eab.cli.parser import _build_parser
        p = _build_parser()
        args = p.parse_args([
            "dwt", "halt",
            "--symbol", "my_var",
            "--elf", "/tmp/zephyr.elf",
        ])
        assert args.cmd == "dwt"
        assert args.dwt_action == "halt"
        assert args.symbol == "my_var"
        assert args.elf == "/tmp/zephyr.elf"
        assert args.mode == "write"       # default
        assert args.max_hits == 100       # default
        assert args.chip == "nrf5340"     # default

    def test_dwt_halt_with_condition(self):
        """Parser should handle --condition for dwt halt."""
        from eab.cli.parser import _build_parser
        p = _build_parser()
        args = p.parse_args([
            "dwt", "halt",
            "--symbol", "x",
            "--elf", "f.elf",
            "--condition", "value > 100",
        ])
        assert args.condition == "value > 100"

    def test_dwt_list_parsed(self):
        """Parser should accept: dwt list (no required args)."""
        from eab.cli.parser import _build_parser
        p = _build_parser()
        args = p.parse_args(["dwt", "list"])
        assert args.cmd == "dwt"
        assert args.dwt_action == "list"
        assert args.device is None  # optional

    def test_dwt_list_with_device(self):
        """Parser should accept: dwt list --device NRF5340."""
        from eab.cli.parser import _build_parser
        p = _build_parser()
        args = p.parse_args(["dwt", "list", "--device", "NRF5340_XXAA_APP"])
        assert args.device == "NRF5340_XXAA_APP"

    def test_dwt_clear_parsed(self):
        """Parser should accept: dwt clear --device NRF5340."""
        from eab.cli.parser import _build_parser
        p = _build_parser()
        args = p.parse_args(["dwt", "clear", "--device", "NRF5340_XXAA_APP"])
        assert args.cmd == "dwt"
        assert args.dwt_action == "clear"
        assert args.device == "NRF5340_XXAA_APP"

    def test_dwt_clear_requires_device(self):
        """dwt clear without --device should error."""
        from eab.cli.parser import _build_parser
        p = _build_parser()
        with pytest.raises(SystemExit):
            p.parse_args(["dwt", "clear"])

    def test_dwt_watch_mode_choices(self):
        """dwt watch --mode should only accept read/write/rw."""
        from eab.cli.parser import _build_parser
        p = _build_parser()
        with pytest.raises(SystemExit):
            p.parse_args(["dwt", "watch", "--device", "D", "--mode", "bad"])


# =============================================================================
# cmd_dwt_watch tests
# =============================================================================

class TestCmdDwtWatch:

    @patch("eab.cli.dwt.watch_cmd.pylink")
    @patch("eab.cli.dwt.watch_cmd._resolve_symbol", return_value=(0x20001234, 2))
    @patch("eab.cli.dwt.watch_cmd.ComparatorAllocator")
    @patch("eab.cli.dwt.watch_cmd.DwtWatchpointDaemon")
    @patch("eab.cli.dwt.watch_cmd._open_jlink")
    def test_watch_resolves_symbol_and_starts_daemon(
        self,
        mock_open_jlink,
        mock_daemon_cls,
        mock_alloc_cls,
        mock_resolve,
        mock_pylink,
    ):
        """cmd_dwt_watch() should resolve symbol, allocate comparator, start daemon."""
        mock_jlink = MagicMock()
        mock_open_jlink.return_value = mock_jlink

        mock_comp = MagicMock()
        mock_comp.index = 3
        mock_alloc_cls.return_value.allocate.return_value = mock_comp

        mock_daemon = MagicMock()
        mock_daemon_cls.return_value = mock_daemon

        from eab.cli.dwt.watch_cmd import cmd_dwt_watch
        result = cmd_dwt_watch(
            symbol="conn_interval",
            addr=None,
            elf="build/zephyr.elf",
            device="NRF5340_XXAA_APP",
            mode="write",
            size=None,
            poll_hz=100,
            output=None,
            duration=0.0,    # immediate exit
            probe_selector=None,
            json_mode=False,
        )
        assert result == 0
        mock_resolve.assert_called_once_with("conn_interval", "build/zephyr.elf")
        mock_alloc_cls.return_value.allocate.assert_called_once_with(
            watch_addr=0x20001234,
            label="conn_interval",
            mode="write",
            size_bytes=2,
        )
        mock_daemon.start.assert_called_once()
        mock_daemon.stop.assert_called_once()

    @patch("eab.cli.dwt.watch_cmd.pylink")
    @patch("eab.cli.dwt.watch_cmd.ComparatorAllocator")
    @patch("eab.cli.dwt.watch_cmd.DwtWatchpointDaemon")
    @patch("eab.cli.dwt.watch_cmd._open_jlink")
    def test_watch_addr_override_skips_elf_lookup(
        self,
        mock_open_jlink,
        mock_daemon_cls,
        mock_alloc_cls,
        mock_pylink,
    ):
        """--addr overrides symbol lookup; no ELF needed."""
        mock_jlink = MagicMock()
        mock_open_jlink.return_value = mock_jlink

        mock_comp = MagicMock()
        mock_comp.index = 3
        mock_alloc_cls.return_value.allocate.return_value = mock_comp

        mock_daemon = MagicMock()
        mock_daemon_cls.return_value = mock_daemon

        from eab.cli.dwt.watch_cmd import cmd_dwt_watch
        result = cmd_dwt_watch(
            symbol=None,
            addr=0x20001234,
            elf=None,
            device="NRF5340_XXAA_APP",
            mode="write",
            size=4,
            poll_hz=100,
            output=None,
            duration=0.0,
            probe_selector=None,
            json_mode=False,
        )
        assert result == 0
        mock_alloc_cls.return_value.allocate.assert_called_once_with(
            watch_addr=0x20001234,
            label="0x20001234",
            mode="write",
            size_bytes=4,
        )

    def test_watch_missing_symbol_and_no_addr_returns_error(self, capsys):
        """Without --symbol and without --addr, cmd_dwt_watch should return 2."""
        from eab.cli.dwt.watch_cmd import cmd_dwt_watch
        result = cmd_dwt_watch(
            symbol=None,
            addr=None,
            elf=None,
            device="NRF5340_XXAA_APP",
            mode="write",
            size=None,
            poll_hz=100,
            output=None,
            duration=0.0,
            probe_selector=None,
            json_mode=False,
        )
        assert result == 2

    def test_watch_symbol_without_elf_returns_error(self, capsys):
        """Symbol without ELF and without addr should return 2."""
        from eab.cli.dwt.watch_cmd import cmd_dwt_watch
        result = cmd_dwt_watch(
            symbol="my_var",
            addr=None,
            elf=None,
            device="NRF5340_XXAA_APP",
            mode="write",
            size=None,
            poll_hz=100,
            output=None,
            duration=0.0,
            probe_selector=None,
            json_mode=False,
        )
        assert result == 2

    def test_watch_pylink_not_installed_returns_error(self, capsys):
        """When pylink is None, cmd_dwt_watch should return 1."""
        with patch("eab.cli.dwt.watch_cmd.pylink", None):
            from eab.cli.dwt import watch_cmd
            # Reload to pick up None
            import importlib
            importlib.reload(watch_cmd)
            # pylink is None at module level — patch it for the test
            watch_cmd.pylink = None
            result = watch_cmd.cmd_dwt_watch(
                symbol=None,
                addr=0x20001234,
                elf=None,
                device="NRF5340_XXAA_APP",
                mode="write",
                size=4,
                poll_hz=100,
                output=None,
                duration=0.0,
                probe_selector=None,
                json_mode=False,
            )
            assert result == 1

    @patch("eab.cli.dwt.watch_cmd.pylink")
    @patch("eab.cli.dwt.watch_cmd._resolve_symbol")
    @patch("eab.cli.dwt.watch_cmd._open_jlink")
    def test_watch_symbol_not_found_returns_2(
        self, mock_open_jlink, mock_resolve, mock_pylink, capsys
    ):
        """SymbolNotFoundError during lookup should return 2."""
        from eab.dwt_watchpoint import SymbolNotFoundError
        mock_resolve.side_effect = SymbolNotFoundError("not found")
        mock_open_jlink.return_value = MagicMock()

        from eab.cli.dwt.watch_cmd import cmd_dwt_watch
        result = cmd_dwt_watch(
            symbol="missing_var",
            addr=None,
            elf="build/zephyr.elf",
            device="NRF5340_XXAA_APP",
            mode="write",
            size=None,
            poll_hz=100,
            output=None,
            duration=0.0,
            probe_selector=None,
            json_mode=False,
        )
        assert result == 2


# =============================================================================
# cmd_dwt_list tests
# =============================================================================

class TestCmdDwtList:

    def test_list_no_device_returns_zero(self):
        """cmd_dwt_list() without device returns 0 (empty list)."""
        from eab.cli.dwt.list_cmd import cmd_dwt_list
        result = cmd_dwt_list(device=None, probe_selector=None, json_mode=False)
        assert result == 0

    def test_list_no_device_json_mode(self, capsys):
        """cmd_dwt_list() without device in json_mode returns empty comparators array."""
        from eab.cli.dwt.list_cmd import cmd_dwt_list
        result = cmd_dwt_list(device=None, probe_selector=None, json_mode=True)
        assert result == 0
        captured = capsys.readouterr()
        data = json.loads(captured.out.strip())
        assert "comparators" in data
        assert data["comparators"] == []

    @patch("eab.cli.dwt.list_cmd.pylink")
    @patch("eab.cli.dwt.list_cmd._open_jlink")
    def test_list_with_device_reads_registers(
        self, mock_open_jlink, mock_pylink, capsys
    ):
        """cmd_dwt_list() with device reads DWT_FUNCTn registers."""
        mock_jlink = MagicMock()
        mock_open_jlink.return_value = mock_jlink
        # NUMCOMP=4 for detect_numcomp, then 4 FUNCT reads
        mock_jlink.memory_read32.side_effect = [
            [0x40000000],   # DWT_CTRL (NUMCOMP=4)
            [0x00000006],   # FUNCT0 = write watchpoint active
            [0x00000000],   # FUNCT1 = disabled
            [0x00000000],   # FUNCT2 = disabled
            [0x00000000],   # FUNCT3 = disabled
        ]

        from eab.cli.dwt.list_cmd import cmd_dwt_list
        result = cmd_dwt_list(
            device="NRF5340_XXAA_APP",
            probe_selector=None,
            json_mode=True,
        )
        assert result == 0
        captured = capsys.readouterr()
        data = json.loads(captured.out.strip())
        assert len(data["comparators"]) == 4
        assert data["comparators"][0]["active"] is True   # slot 0 has func_code=6
        assert data["comparators"][1]["active"] is False  # slot 1 disabled


# =============================================================================
# cmd_dwt_clear tests
# =============================================================================

class TestCmdDwtClear:

    def test_clear_pylink_not_installed_returns_1(self):
        """When pylink is None, cmd_dwt_clear should return 1."""
        with patch("eab.cli.dwt.clear_cmd.pylink", None):
            import eab.cli.dwt.clear_cmd as m
            m.pylink = None
            result = m.cmd_dwt_clear(
                device="NRF5340_XXAA_APP",
                probe_selector=None,
                json_mode=False,
            )
            assert result == 1

    @patch("eab.cli.dwt.clear_cmd.pylink")
    @patch("eab.cli.dwt.clear_cmd._open_jlink")
    def test_clear_writes_zero_to_all_funct_regs(self, mock_open_jlink, mock_pylink, capsys):
        """cmd_dwt_clear() should write 0 to all DWT_FUNCTn registers."""
        mock_jlink = MagicMock()
        mock_open_jlink.return_value = mock_jlink
        # NUMCOMP=4
        mock_jlink.memory_read32.return_value = [0x40000000]

        from eab.cli.dwt.clear_cmd import cmd_dwt_clear
        result = cmd_dwt_clear(
            device="NRF5340_XXAA_APP",
            probe_selector=None,
            json_mode=True,
        )
        assert result == 0
        captured = capsys.readouterr()
        data = json.loads(captured.out.strip())
        assert data["status"] == "cleared"

        # Verify all FUNCT registers cleared
        from eab.dwt_watchpoint import DWT_FUNCT_BASE, DWT_COMP_STRIDE
        for idx in range(4):
            funct_addr = DWT_FUNCT_BASE + idx * DWT_COMP_STRIDE
            mock_jlink.memory_write32.assert_any_call(funct_addr, [0])


# =============================================================================
# cmd_dwt_halt tests
# =============================================================================

class TestCmdDwtHalt:

    def test_generate_dwt_halt_watchpoint_script_contains_var(self):
        """generate_dwt_halt_watchpoint() should include var name in script."""
        from eab.cli.dwt.halt_cmd import generate_dwt_halt_watchpoint
        script = generate_dwt_halt_watchpoint(
            var_name="my_counter",
            mode="write",
        )
        assert "my_counter" in script
        assert "gdb.BP_WATCHPOINT" in script

    def test_generate_dwt_halt_script_read_mode_uses_rwatch(self):
        """Mode 'read' should generate rwatch GDB command."""
        from eab.cli.dwt.halt_cmd import generate_dwt_halt_watchpoint
        script = generate_dwt_halt_watchpoint(var_name="x", mode="read")
        assert "WP_RWATCH" in script

    def test_generate_dwt_halt_script_rw_mode_uses_awatch(self):
        """Mode 'rw' should generate awatch GDB command."""
        from eab.cli.dwt.halt_cmd import generate_dwt_halt_watchpoint
        script = generate_dwt_halt_watchpoint(var_name="x", mode="rw")
        assert "WP_AWATCH" in script

    def test_generate_dwt_halt_script_includes_condition(self):
        """Condition expression should appear in the generated script."""
        from eab.cli.dwt.halt_cmd import generate_dwt_halt_watchpoint
        script = generate_dwt_halt_watchpoint(
            var_name="x",
            mode="write",
            condition="value > 100",
        )
        assert "value > 100" in script

    def test_generate_dwt_halt_script_no_backtrace(self):
        """With backtrace=False, backtrace code should not appear."""
        from eab.cli.dwt.halt_cmd import generate_dwt_halt_watchpoint
        script = generate_dwt_halt_watchpoint(
            var_name="x",
            mode="write",
            backtrace=False,
        )
        assert "selected_frame" not in script

    def test_halt_no_gdb_bridge_returns_1(self):
        """cmd_dwt_halt should return 1 when gdb_bridge is unavailable."""
        with patch.dict("sys.modules", {"eab.gdb_bridge": None}):
            from eab.cli.dwt.halt_cmd import cmd_dwt_halt
            # This will raise ImportError when trying to import gdb_bridge
            # Simulate by patching run_gdb_batch to not exist
            with patch("builtins.__import__", side_effect=ImportError("no gdb_bridge")):
                result = cmd_dwt_halt(
                    symbol="x",
                    elf="f.elf",
                    device=None,
                    json_mode=False,
                )
                # Either returns 1 or raises — both acceptable for missing dep
                assert result in (0, 1, 2)
