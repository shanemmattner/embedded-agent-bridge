"""Tests for eab.cli.threads CLI commands (snapshot and watch)."""

from __future__ import annotations

import json
from unittest.mock import patch

import pytest

from eab.thread_inspector import ThreadInfo


def _make_thread(
    name: str = "main",
    state: str = "RUNNING",
    priority: int = 0,
    stack_base: int = 0x20000000,
    stack_size: int = 2048,
    stack_used: int = 512,
    stack_free: int = 1536,
) -> ThreadInfo:
    return ThreadInfo(
        name=name,
        state=state,
        priority=priority,
        stack_base=stack_base,
        stack_size=stack_size,
        stack_used=stack_used,
        stack_free=stack_free,
    )


SAMPLE_THREADS = [
    _make_thread("main", "RUNNING", 0, 0x20000000, 2048, 512, 1536),
    _make_thread("idle", "READY", 15, 0x20001000, 1024, 128, 896),
]


# =============================================================================
# Parser tests
# =============================================================================


class TestParserThreadsSubcommand:
    """Parser correctly sets up threads snapshot and watch subcommands."""

    def test_snapshot_required_args_parsed(self):
        from eab.cli.parser import _build_parser

        p = _build_parser()
        args = p.parse_args([
            "threads", "snapshot",
            "--device", "NRF5340_XXAA_APP",
            "--elf", "/tmp/zephyr.elf",
        ])
        assert args.cmd == "threads"
        assert args.threads_action == "snapshot"
        assert args.device == "NRF5340_XXAA_APP"
        assert args.elf == "/tmp/zephyr.elf"

    def test_watch_required_args_and_defaults(self):
        from eab.cli.parser import _build_parser

        p = _build_parser()
        args = p.parse_args([
            "threads", "watch",
            "--device", "NRF5340_XXAA_APP",
            "--elf", "/tmp/zephyr.elf",
        ])
        assert args.cmd == "threads"
        assert args.threads_action == "watch"
        assert args.device == "NRF5340_XXAA_APP"
        assert args.elf == "/tmp/zephyr.elf"
        assert args.interval == pytest.approx(5.0)

    def test_watch_custom_interval(self):
        from eab.cli.parser import _build_parser

        p = _build_parser()
        args = p.parse_args([
            "threads", "watch",
            "--device", "NRF5340_XXAA_APP",
            "--elf", "/tmp/zephyr.elf",
            "--interval", "10",
        ])
        assert args.interval == pytest.approx(10.0)

    def test_snapshot_missing_device_fails(self):

        from eab.cli.parser import _build_parser

        p = _build_parser()
        with pytest.raises(SystemExit):
            p.parse_args(["threads", "snapshot", "--elf", "/tmp/zephyr.elf"])

    def test_snapshot_missing_elf_fails(self):
        from eab.cli.parser import _build_parser

        p = _build_parser()
        with pytest.raises(SystemExit):
            p.parse_args(["threads", "snapshot", "--device", "NRF5340_XXAA_APP"])


# =============================================================================
# snapshot_cmd tests
# =============================================================================


class TestCmdThreadsSnapshot:
    """Tests for cmd_threads_snapshot()."""

    @patch("eab.thread_inspector.inspect_threads")
    def test_json_output_is_valid_array(self, mock_inspect, capsys):
        from eab.cli.threads.snapshot_cmd import cmd_threads_snapshot

        mock_inspect.return_value = SAMPLE_THREADS
        result = cmd_threads_snapshot(
            device="NRF5340_XXAA_APP",
            elf="/tmp/zephyr.elf",
            json_mode=True,
        )

        assert result == 0
        captured = capsys.readouterr()
        data = json.loads(captured.out)
        assert isinstance(data, list)
        assert len(data) == 2
        assert data[0]["name"] == "main"
        assert data[0]["state"] == "RUNNING"
        assert data[1]["name"] == "idle"

    @patch("eab.thread_inspector.inspect_threads")
    def test_json_output_contains_all_fields(self, mock_inspect, capsys):
        from eab.cli.threads.snapshot_cmd import cmd_threads_snapshot

        mock_inspect.return_value = [SAMPLE_THREADS[0]]
        result = cmd_threads_snapshot(
            device="NRF5340_XXAA_APP",
            elf="/tmp/zephyr.elf",
            json_mode=True,
        )

        assert result == 0
        data = json.loads(capsys.readouterr().out)
        t = data[0]
        assert "name" in t
        assert "state" in t
        assert "priority" in t
        assert "stack_used" in t
        assert "stack_size" in t
        assert "stack_free" in t

    @patch("eab.thread_inspector.inspect_threads")
    def test_table_output_contains_header(self, mock_inspect, capsys):
        from eab.cli.threads.snapshot_cmd import cmd_threads_snapshot

        mock_inspect.return_value = SAMPLE_THREADS
        result = cmd_threads_snapshot(
            device="NRF5340_XXAA_APP",
            elf="/tmp/zephyr.elf",
            json_mode=False,
        )

        assert result == 0
        captured = capsys.readouterr()
        assert "Name" in captured.out
        assert "State" in captured.out
        assert "Priority" in captured.out
        assert "Stack Used" in captured.out

    @patch("eab.thread_inspector.inspect_threads")
    def test_table_output_contains_thread_names(self, mock_inspect, capsys):
        from eab.cli.threads.snapshot_cmd import cmd_threads_snapshot

        mock_inspect.return_value = SAMPLE_THREADS
        result = cmd_threads_snapshot(
            device="NRF5340_XXAA_APP",
            elf="/tmp/zephyr.elf",
            json_mode=False,
        )

        assert result == 0
        captured = capsys.readouterr()
        assert "main" in captured.out
        assert "idle" in captured.out
        assert "RUNNING" in captured.out

    @patch("eab.thread_inspector.inspect_threads")
    def test_import_error_returns_1(self, mock_inspect, capsys):
        from eab.cli.threads.snapshot_cmd import cmd_threads_snapshot

        mock_inspect.side_effect = ImportError("pylink-square is not installed")
        result = cmd_threads_snapshot(
            device="NRF5340_XXAA_APP",
            elf="/tmp/zephyr.elf",
            json_mode=True,
        )

        assert result == 1

    @patch("eab.thread_inspector.inspect_threads")
    def test_runtime_error_returns_1(self, mock_inspect, capsys):
        from eab.cli.threads.snapshot_cmd import cmd_threads_snapshot

        mock_inspect.side_effect = RuntimeError("GDB connection failed")
        result = cmd_threads_snapshot(
            device="NRF5340_XXAA_APP",
            elf="/tmp/zephyr.elf",
            json_mode=False,
        )

        assert result == 1

    @patch("eab.thread_inspector.inspect_threads")
    def test_inspect_called_with_correct_args(self, mock_inspect):
        from eab.cli.threads.snapshot_cmd import cmd_threads_snapshot

        mock_inspect.return_value = []
        cmd_threads_snapshot(
            device="NRF5340_XXAA_APP",
            elf="/path/to/app.elf",
            json_mode=True,
        )
        mock_inspect.assert_called_once_with(device="NRF5340_XXAA_APP", elf_path="/path/to/app.elf")


# =============================================================================
# watch_cmd tests
# =============================================================================


class TestCmdThreadsWatch:
    """Tests for cmd_threads_watch()."""

    @patch("eab.thread_inspector.inspect_threads")
    @patch("eab.cli.threads.watch_cmd.time")
    def test_json_mode_emits_jsonl_with_timestamp(self, mock_time, mock_inspect, capsys):
        from eab.cli.threads.watch_cmd import cmd_threads_watch

        mock_inspect.return_value = SAMPLE_THREADS
        call_count = 0

        def sleep_side_effect(interval):
            nonlocal call_count
            call_count += 1
            if call_count >= 1:
                raise KeyboardInterrupt

        mock_time.sleep.side_effect = sleep_side_effect

        result = cmd_threads_watch(
            device="NRF5340_XXAA_APP",
            elf="/tmp/zephyr.elf",
            interval=5.0,
            json_mode=True,
        )

        assert result == 0
        captured = capsys.readouterr()
        lines = [ln for ln in captured.out.splitlines() if ln.strip()]
        assert len(lines) >= 1
        record = json.loads(lines[0])
        assert "timestamp" in record
        assert "threads" in record
        assert isinstance(record["threads"], list)
        assert record["threads"][0]["name"] == "main"

    @patch("eab.thread_inspector.inspect_threads")
    @patch("eab.cli.threads.watch_cmd.time")
    def test_keyboard_interrupt_returns_0(self, mock_time, mock_inspect, capsys):
        from eab.cli.threads.watch_cmd import cmd_threads_watch

        mock_inspect.return_value = []
        mock_time.sleep.side_effect = KeyboardInterrupt

        result = cmd_threads_watch(
            device="NRF5340_XXAA_APP",
            elf="/tmp/zephyr.elf",
            interval=5.0,
            json_mode=True,
        )

        assert result == 0

    @patch("eab.thread_inspector.inspect_threads")
    @patch("eab.cli.threads.watch_cmd.time")
    def test_table_mode_clears_terminal(self, mock_time, mock_inspect, capsys):
        from eab.cli.threads.watch_cmd import cmd_threads_watch

        mock_inspect.return_value = SAMPLE_THREADS
        mock_time.sleep.side_effect = KeyboardInterrupt

        result = cmd_threads_watch(
            device="NRF5340_XXAA_APP",
            elf="/tmp/zephyr.elf",
            interval=5.0,
            json_mode=False,
        )

        assert result == 0
        captured = capsys.readouterr()
        # Should contain the ANSI clear sequence and header
        assert "\033[2J\033[H" in captured.out
        assert "Name" in captured.out

    @patch("eab.thread_inspector.inspect_threads")
    def test_import_error_returns_1(self, mock_inspect):
        from eab.cli.threads.watch_cmd import cmd_threads_watch

        mock_inspect.side_effect = ImportError("pylink-square not installed")
        result = cmd_threads_watch(
            device="NRF5340_XXAA_APP",
            elf="/tmp/zephyr.elf",
            interval=5.0,
            json_mode=True,
        )

        assert result == 1

    @patch("eab.thread_inspector.inspect_threads")
    @patch("eab.cli.threads.watch_cmd.time")
    def test_watch_uses_configured_interval(self, mock_time, mock_inspect):
        from eab.cli.threads.watch_cmd import cmd_threads_watch

        mock_inspect.return_value = []
        mock_time.sleep.side_effect = KeyboardInterrupt

        cmd_threads_watch(
            device="NRF5340_XXAA_APP",
            elf="/tmp/zephyr.elf",
            interval=10.0,
            json_mode=True,
        )

        mock_time.sleep.assert_called_with(10.0)
