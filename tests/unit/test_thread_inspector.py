"""Unit tests for thread_inspector, CLI snapshot/watch commands, and HIL steps.

No hardware required — all GDB bridge calls are mocked.
"""

from __future__ import annotations

import json
from unittest.mock import MagicMock, patch

import pytest

from eab.cli.regression.models import StepSpec
from eab.thread_inspector import ThreadInfo, inspect_threads

# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def _make_thread_info(
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


def _make_gdb_result(json_result: object) -> MagicMock:
    mock = MagicMock()
    mock.json_result = json_result
    mock.stderr = ""
    return mock


_SAMPLE_JSON: dict = {
    "status": "ok",
    "threads": [
        {
            "name": "main",
            "thread_state": 0x01,  # RUNNING
            "prio": 0,
            "stack_start": 0x20001000,
            "stack_size": 2048,
            "stack_delta": 512,
        },
        {
            "name": "idle",
            "thread_state": 0x00,  # READY
            "prio": 15,
            "stack_start": 0x20002000,
            "stack_size": 1024,
            "stack_delta": 128,
        },
        {
            "name": "sensor",
            "thread_state": 0x04,  # PENDING
            "prio": 5,
            "stack_start": 0x20003000,
            "stack_size": 4096,
            "stack_delta": 300,
        },
        {
            "name": "monitor",
            "thread_state": 0x08,  # SUSPENDED
            "prio": 3,
            "stack_start": 0x20004000,
            "stack_size": 2048,
            "stack_delta": 200,
        },
    ],
}


# ===========================================================================
# 1. ThreadInfo dataclass
# ===========================================================================


class TestThreadInfoDataclass:
    def test_construction_all_fields(self):
        t = _make_thread_info()
        assert t.name == "main"
        assert t.state == "RUNNING"
        assert t.priority == 0
        assert t.stack_base == 0x20000000
        assert t.stack_size == 2048
        assert t.stack_used == 512
        assert t.stack_free == 1536

    def test_to_dict_keys(self):
        t = _make_thread_info()
        d = t.to_dict()
        assert set(d.keys()) == {
            "name",
            "state",
            "priority",
            "stack_base",
            "stack_size",
            "stack_used",
            "stack_free",
        }

    def test_to_dict_values(self):
        t = ThreadInfo(
            name="sensor",
            state="SUSPENDED",
            priority=3,
            stack_base=0x20004000,
            stack_size=2048,
            stack_used=200,
            stack_free=1848,
        )
        d = t.to_dict()
        assert d["name"] == "sensor"
        assert d["state"] == "SUSPENDED"
        assert d["priority"] == 3
        assert d["stack_base"] == 0x20004000
        assert d["stack_size"] == 2048
        assert d["stack_used"] == 200
        assert d["stack_free"] == 1848

    def test_stack_free_equals_size_minus_used(self):
        # ThreadInfo stores stack_free explicitly; verify the relationship holds.
        stack_size = 4096
        stack_used = 320
        t = ThreadInfo(
            name="t",
            state="READY",
            priority=1,
            stack_base=0x20000000,
            stack_size=stack_size,
            stack_used=stack_used,
            stack_free=stack_size - stack_used,
        )
        assert t.stack_free == stack_size - stack_used

    def test_to_dict_is_json_serializable(self):
        t = _make_thread_info()
        serialized = json.dumps(t.to_dict())
        assert "main" in serialized


# ===========================================================================
# 2. GDB output parsing — mock run_gdb_python
# ===========================================================================


class TestGDBOutputParsing:
    @patch("eab.thread_inspector.run_gdb_python")
    def test_returns_list_of_thread_info(self, mock_run):
        mock_run.return_value = _make_gdb_result(_SAMPLE_JSON)
        result = inspect_threads("localhost:3333", "/path/to/app.elf")
        assert isinstance(result, list)
        assert len(result) == 4
        assert all(isinstance(t, ThreadInfo) for t in result)

    @patch("eab.thread_inspector.run_gdb_python")
    def test_thread_state_running(self, mock_run):
        mock_run.return_value = _make_gdb_result(_SAMPLE_JSON)
        result = inspect_threads("localhost:3333", "/path/to/app.elf")
        assert result[0].state == "RUNNING"

    @patch("eab.thread_inspector.run_gdb_python")
    def test_thread_state_ready(self, mock_run):
        mock_run.return_value = _make_gdb_result(_SAMPLE_JSON)
        result = inspect_threads("localhost:3333", "/path/to/app.elf")
        assert result[1].state == "READY"

    @patch("eab.thread_inspector.run_gdb_python")
    def test_thread_state_pending(self, mock_run):
        mock_run.return_value = _make_gdb_result(_SAMPLE_JSON)
        result = inspect_threads("localhost:3333", "/path/to/app.elf")
        assert result[2].state == "PENDING"

    @patch("eab.thread_inspector.run_gdb_python")
    def test_thread_state_suspended(self, mock_run):
        mock_run.return_value = _make_gdb_result(_SAMPLE_JSON)
        result = inspect_threads("localhost:3333", "/path/to/app.elf")
        assert result[3].state == "SUSPENDED"

    @patch("eab.thread_inspector.run_gdb_python")
    def test_thread_names_preserved(self, mock_run):
        mock_run.return_value = _make_gdb_result(_SAMPLE_JSON)
        result = inspect_threads("localhost:3333", "/path/to/app.elf")
        assert [t.name for t in result] == ["main", "idle", "sensor", "monitor"]

    @patch("eab.thread_inspector.run_gdb_python")
    def test_all_fields_parsed(self, mock_run):
        mock_run.return_value = _make_gdb_result(_SAMPLE_JSON)
        result = inspect_threads("localhost:3333", "/path/to/app.elf")
        main = result[0]
        assert main.priority == 0
        assert main.stack_base == 0x20001000
        assert main.stack_size == 2048
        assert main.stack_used == 512
        assert main.stack_free == 1536


# ===========================================================================
# 3. Stack headroom calculation
# ===========================================================================


class TestStackHeadroomCalculation:
    @patch("eab.thread_inspector.run_gdb_python")
    def test_stack_free_computed_as_size_minus_used(self, mock_run):
        mock_run.return_value = _make_gdb_result(_SAMPLE_JSON)
        result = inspect_threads("localhost:3333", "/path/to/app.elf")
        for t in result:
            assert t.stack_free == t.stack_size - t.stack_used

    def test_manual_headroom_large_stack(self):
        t = ThreadInfo(
            name="bt_rx",
            state="PENDING",
            priority=2,
            stack_base=0x20008000,
            stack_size=4096,
            stack_used=512,
            stack_free=3584,
        )
        assert t.stack_free == 3584
        assert t.stack_free == t.stack_size - t.stack_used

    def test_manual_headroom_small_stack(self):
        t = ThreadInfo(
            name="idle",
            state="READY",
            priority=15,
            stack_base=0x2000A000,
            stack_size=256,
            stack_used=200,
            stack_free=56,
        )
        assert t.stack_free == 56
        assert t.stack_free == t.stack_size - t.stack_used


# ===========================================================================
# 4. CLI snapshot JSON output
# ===========================================================================


_SAMPLE_THREADS = [
    _make_thread_info("main", "RUNNING", 0, 0x20000000, 2048, 512, 1536),
    _make_thread_info("idle", "READY", 15, 0x20001000, 1024, 128, 896),
]


class TestCliSnapshotJsonOutput:
    @patch("eab.thread_inspector.inspect_threads", return_value=_SAMPLE_THREADS)
    def test_json_output_is_valid_array(self, _mock, capsys):
        from eab.cli.threads.snapshot_cmd import cmd_threads_snapshot

        rc = cmd_threads_snapshot(device="NRF5340_XXAA_APP", elf="/tmp/a.elf", json_mode=True)
        assert rc == 0
        data = json.loads(capsys.readouterr().out)
        assert isinstance(data, list)
        assert len(data) == 2

    @patch("eab.thread_inspector.inspect_threads", return_value=_SAMPLE_THREADS)
    def test_json_array_contains_expected_names(self, _mock, capsys):
        from eab.cli.threads.snapshot_cmd import cmd_threads_snapshot

        cmd_threads_snapshot(device="NRF5340_XXAA_APP", elf="/tmp/a.elf", json_mode=True)
        data = json.loads(capsys.readouterr().out)
        names = [t["name"] for t in data]
        assert "main" in names
        assert "idle" in names

    @patch("eab.thread_inspector.inspect_threads", return_value=_SAMPLE_THREADS)
    def test_json_array_has_required_fields(self, _mock, capsys):
        from eab.cli.threads.snapshot_cmd import cmd_threads_snapshot

        cmd_threads_snapshot(device="NRF5340_XXAA_APP", elf="/tmp/a.elf", json_mode=True)
        data = json.loads(capsys.readouterr().out)
        t = data[0]
        for key in ("name", "state", "priority", "stack_size", "stack_used", "stack_free"):
            assert key in t, f"missing key: {key}"

    @patch("eab.thread_inspector.inspect_threads")
    def test_exception_returns_error(self, mock_inspect, capsys):
        from eab.cli.threads.snapshot_cmd import cmd_threads_snapshot

        mock_inspect.side_effect = RuntimeError("GDB connection refused")
        rc = cmd_threads_snapshot(device="NRF5340_XXAA_APP", elf="/tmp/a.elf", json_mode=True)
        assert rc == 1


# ===========================================================================
# 5. CLI watch JSONL output
# ===========================================================================


class TestCliWatchJsonlOutput:
    @patch("eab.thread_inspector.inspect_threads", return_value=_SAMPLE_THREADS)
    @patch("eab.cli.threads.watch_cmd.time")
    def test_jsonl_has_timestamp(self, mock_time, _mock_inspect, capsys):
        from eab.cli.threads.watch_cmd import cmd_threads_watch

        mock_time.sleep.side_effect = KeyboardInterrupt

        rc = cmd_threads_watch(device="NRF5340_XXAA_APP", elf="/tmp/a.elf", json_mode=True)
        assert rc == 0
        captured = capsys.readouterr()
        lines = [ln for ln in captured.out.splitlines() if ln.strip()]
        assert len(lines) >= 1
        record = json.loads(lines[0])
        assert "timestamp" in record

    @patch("eab.thread_inspector.inspect_threads", return_value=_SAMPLE_THREADS)
    @patch("eab.cli.threads.watch_cmd.time")
    def test_jsonl_each_line_is_valid_json(self, mock_time, _mock_inspect, capsys):
        from eab.cli.threads.watch_cmd import cmd_threads_watch

        call_count = 0

        def sleep_se(interval: float) -> None:
            nonlocal call_count
            call_count += 1
            if call_count >= 2:
                raise KeyboardInterrupt

        mock_time.sleep.side_effect = sleep_se

        cmd_threads_watch(device="NRF5340_XXAA_APP", elf="/tmp/a.elf", json_mode=True)
        captured = capsys.readouterr()
        lines = [ln for ln in captured.out.splitlines() if ln.strip()]
        assert len(lines) >= 1
        for line in lines:
            obj = json.loads(line)
            assert "timestamp" in obj
            assert "threads" in obj
            assert isinstance(obj["threads"], list)

    @patch("eab.thread_inspector.inspect_threads", return_value=_SAMPLE_THREADS)
    @patch("eab.cli.threads.watch_cmd.time")
    def test_jsonl_threads_have_expected_names(self, mock_time, _mock_inspect, capsys):
        from eab.cli.threads.watch_cmd import cmd_threads_watch

        mock_time.sleep.side_effect = KeyboardInterrupt

        cmd_threads_watch(device="NRF5340_XXAA_APP", elf="/tmp/a.elf", json_mode=True)
        captured = capsys.readouterr()
        lines = [ln for ln in captured.out.splitlines() if ln.strip()]
        record = json.loads(lines[0])
        names = [t["name"] for t in record["threads"]]
        assert "main" in names
        assert "idle" in names


# ===========================================================================
# 6. HIL step pass — stack_headroom_assert
# ===========================================================================


class TestHilStepPass:
    def test_all_threads_pass_headroom_check(self):
        from eab.cli.regression.steps import _run_stack_headroom_assert

        good_threads = [
            _make_thread_info("main", "RUNNING", 0, 0x20000000, 2048, 512, 1536),
            _make_thread_info("idle", "READY", 15, 0x20001000, 1024, 64, 960),
            _make_thread_info("sensor", "PENDING", 5, 0x20002000, 4096, 300, 3796),
        ]
        step = StepSpec("stack_headroom_assert", {"min_free_bytes": 256})

        with patch("eab.cli.regression.steps.inspect_threads", return_value=good_threads):
            result = _run_stack_headroom_assert(step, device="test-device", chip="NRF5340_XXAA_APP", timeout=30)

        assert result.passed
        assert result.error is None
        assert result.step_type == "stack_headroom_assert"

    def test_pass_with_exact_threshold(self):
        from eab.cli.regression.steps import _run_stack_headroom_assert

        threads = [_make_thread_info("t", stack_size=2048, stack_used=1792, stack_free=256)]
        step = StepSpec("stack_headroom_assert", {"min_free_bytes": 256})

        with patch("eab.cli.regression.steps.inspect_threads", return_value=threads):
            result = _run_stack_headroom_assert(step, device="dev", chip="chip", timeout=30)

        assert result.passed


# ===========================================================================
# 7. HIL step fail — stack_headroom_assert
# ===========================================================================


class TestHilStepFail:
    def test_fails_when_thread_below_threshold(self):
        from eab.cli.regression.steps import _run_stack_headroom_assert

        threads = [
            _make_thread_info("main", stack_free=1000),
            _make_thread_info("low_stack_thread", stack_free=100),
        ]
        step = StepSpec("stack_headroom_assert", {"min_free_bytes": 256})

        with patch("eab.cli.regression.steps.inspect_threads", return_value=threads):
            result = _run_stack_headroom_assert(step, device="dev", chip="chip", timeout=30)

        assert not result.passed
        assert result.error is not None
        assert "low_stack_thread" in result.error

    def test_error_message_contains_thread_name_and_value(self):
        from eab.cli.regression.steps import _run_stack_headroom_assert

        threads = [_make_thread_info("bt_rx", stack_free=50)]
        step = StepSpec("stack_headroom_assert", {"min_free_bytes": 256})

        with patch("eab.cli.regression.steps.inspect_threads", return_value=threads):
            result = _run_stack_headroom_assert(step, device="dev", chip="chip", timeout=30)

        assert not result.passed
        assert "bt_rx" in result.error
        assert "50" in result.error

    def test_multiple_offending_threads_in_error(self):
        from eab.cli.regression.steps import _run_stack_headroom_assert

        threads = [
            _make_thread_info("a", stack_free=10),
            _make_thread_info("b", stack_free=20),
        ]
        step = StepSpec("stack_headroom_assert", {"min_free_bytes": 256})

        with patch("eab.cli.regression.steps.inspect_threads", return_value=threads):
            result = _run_stack_headroom_assert(step, device="dev", chip="chip", timeout=30)

        assert not result.passed
        assert "a" in result.error
        assert "b" in result.error


# ===========================================================================
# 8. GDB bridge error handling
# ===========================================================================


class TestGDBBridgeErrorHandling:
    @patch("eab.thread_inspector.run_gdb_python")
    def test_propagates_exception_from_bridge(self, mock_run):
        mock_run.side_effect = RuntimeError("GDB server not reachable")
        with pytest.raises(RuntimeError, match="GDB server not reachable"):
            inspect_threads("localhost:3333", "/path/to/app.elf")

    @patch("eab.thread_inspector.run_gdb_python")
    def test_raises_on_none_json_result(self, mock_run):
        mock_run.return_value = _make_gdb_result(None)
        with pytest.raises(RuntimeError, match="no JSON result"):
            inspect_threads("localhost:3333", "/path/to/app.elf")

    @patch("eab.thread_inspector.run_gdb_python")
    def test_raises_on_gdb_error_status(self, mock_run):
        mock_run.return_value = _make_gdb_result({"status": "error", "error": "symbol not found: _kernel"})
        with pytest.raises(RuntimeError, match="symbol not found"):
            inspect_threads("localhost:3333", "/path/to/app.elf")

    @patch("eab.thread_inspector.run_gdb_python")
    def test_propagates_connection_error(self, mock_run):
        mock_run.side_effect = ConnectionError("Connection refused")
        with pytest.raises(ConnectionError):
            inspect_threads("localhost:3333", "/path/to/app.elf")
