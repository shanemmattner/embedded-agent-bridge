"""Tests for eab.thread_inspector module.

Tests ThreadInfo construction/serialization, state mapping, script generation,
and inspect_threads() with a mocked GDB bridge (no real hardware needed).
"""

from __future__ import annotations

from unittest.mock import MagicMock, patch

import pytest

from eab.thread_inspector import (
    _THREAD_PENDING,
    _THREAD_RUNNING,
    _THREAD_SUSPENDED,
    ThreadInfo,
    _generate_thread_script,
    _map_thread_state,
    inspect_threads,
)

# =============================================================================
# ThreadInfo dataclass tests
# =============================================================================


class TestThreadInfo:
    def test_construction(self):
        t = ThreadInfo(
            name="main",
            state="RUNNING",
            priority=0,
            stack_base=0x20001000,
            stack_size=2048,
            stack_used=512,
            stack_free=1536,
        )
        assert t.name == "main"
        assert t.state == "RUNNING"
        assert t.priority == 0
        assert t.stack_base == 0x20001000
        assert t.stack_size == 2048
        assert t.stack_used == 512
        assert t.stack_free == 1536

    def test_frozen(self):
        t = ThreadInfo(
            name="idle",
            state="READY",
            priority=15,
            stack_base=0x20002000,
            stack_size=1024,
            stack_used=128,
            stack_free=896,
        )
        with pytest.raises(AttributeError):
            t.name = "other"  # type: ignore[misc]

    def test_to_dict_all_keys(self):
        t = ThreadInfo(
            name="sensor",
            state="PENDING",
            priority=5,
            stack_base=0x20003000,
            stack_size=4096,
            stack_used=300,
            stack_free=3796,
        )
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

    def test_to_dict_json_serializable(self):
        import json

        t = ThreadInfo(
            name="test",
            state="READY",
            priority=1,
            stack_base=0x20000000,
            stack_size=1024,
            stack_used=64,
            stack_free=960,
        )
        # Should not raise
        serialized = json.dumps(t.to_dict())
        assert "test" in serialized


# =============================================================================
# State mapping tests
# =============================================================================


class TestMapThreadState:
    def test_running(self):
        assert _map_thread_state(_THREAD_RUNNING) == "RUNNING"

    def test_running_takes_priority_over_other_bits(self):
        # RUNNING | PENDING | SUSPENDED
        assert _map_thread_state(_THREAD_RUNNING | _THREAD_PENDING | _THREAD_SUSPENDED) == "RUNNING"

    def test_pending(self):
        assert _map_thread_state(_THREAD_PENDING) == "PENDING"

    def test_suspended(self):
        assert _map_thread_state(_THREAD_SUSPENDED) == "SUSPENDED"

    def test_ready_when_no_bits(self):
        assert _map_thread_state(0) == "READY"

    def test_ready_when_only_queued(self):
        # Bit 1 (QUEUED) is not mapped to a special state
        assert _map_thread_state(0x02) == "READY"

    def test_pending_overrides_suspended(self):
        assert _map_thread_state(_THREAD_PENDING | _THREAD_SUSPENDED) == "PENDING"


# =============================================================================
# Script generator tests
# =============================================================================


class TestGenerateThreadScript:
    def test_returns_string(self):
        script = _generate_thread_script()
        assert isinstance(script, str)

    def test_contains_result_file_pattern(self):
        script = _generate_thread_script()
        assert 'gdb.convenience_variable("result_file")' in script

    def test_contains_kernel_access(self):
        script = _generate_thread_script()
        assert "_kernel" in script

    def test_contains_json_dump(self):
        script = _generate_thread_script()
        assert "json.dump(result, f" in script

    def test_contains_safety_limit(self):
        script = _generate_thread_script()
        assert "max_threads" in script

    def test_contains_required_field_accesses(self):
        script = _generate_thread_script()
        assert "thread_state" in script
        assert "prio" in script
        assert "stack_info" in script
        assert "stack_delta" in script or "delta" in script


# =============================================================================
# inspect_threads() integration tests (mocked GDB bridge)
# =============================================================================

_SAMPLE_THREADS_JSON = {
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


class TestInspectThreads:
    def _make_mock_result(self, json_result):
        mock = MagicMock()
        mock.json_result = json_result
        mock.stderr = ""
        return mock

    @patch("eab.thread_inspector.run_gdb_python")
    def test_returns_list_of_thread_info(self, mock_run):
        mock_run.return_value = self._make_mock_result(_SAMPLE_THREADS_JSON)
        result = inspect_threads("localhost:3333", "/path/to/app.elf")
        assert isinstance(result, list)
        assert len(result) == 4
        assert all(isinstance(t, ThreadInfo) for t in result)

    @patch("eab.thread_inspector.run_gdb_python")
    def test_thread_states_mapped_correctly(self, mock_run):
        mock_run.return_value = self._make_mock_result(_SAMPLE_THREADS_JSON)
        result = inspect_threads("localhost:3333", "/path/to/app.elf")
        assert result[0].state == "RUNNING"
        assert result[1].state == "READY"
        assert result[2].state == "PENDING"
        assert result[3].state == "SUSPENDED"

    @patch("eab.thread_inspector.run_gdb_python")
    def test_stack_free_computed_correctly(self, mock_run):
        mock_run.return_value = self._make_mock_result(_SAMPLE_THREADS_JSON)
        result = inspect_threads("localhost:3333", "/path/to/app.elf")
        for t in result:
            assert t.stack_free == t.stack_size - t.stack_used

    @patch("eab.thread_inspector.run_gdb_python")
    def test_thread_names_preserved(self, mock_run):
        mock_run.return_value = self._make_mock_result(_SAMPLE_THREADS_JSON)
        result = inspect_threads("localhost:3333", "/path/to/app.elf")
        names = [t.name for t in result]
        assert names == ["main", "idle", "sensor", "monitor"]

    @patch("eab.thread_inspector.run_gdb_python")
    def test_priority_and_stack_fields(self, mock_run):
        mock_run.return_value = self._make_mock_result(_SAMPLE_THREADS_JSON)
        result = inspect_threads("localhost:3333", "/path/to/app.elf")
        main = result[0]
        assert main.priority == 0
        assert main.stack_base == 0x20001000
        assert main.stack_size == 2048
        assert main.stack_used == 512
        assert main.stack_free == 1536

    @patch("eab.thread_inspector.run_gdb_python")
    def test_raises_runtime_error_on_no_json(self, mock_run):
        mock_run.return_value = self._make_mock_result(None)
        with pytest.raises(RuntimeError, match="no JSON result"):
            inspect_threads("localhost:3333", "/path/to/app.elf")

    @patch("eab.thread_inspector.run_gdb_python")
    def test_raises_runtime_error_on_gdb_error_status(self, mock_run):
        mock_run.return_value = self._make_mock_result({"status": "error", "error": "symbol not found: _kernel"})
        with pytest.raises(RuntimeError, match="symbol not found"):
            inspect_threads("localhost:3333", "/path/to/app.elf")

    @patch("eab.thread_inspector.run_gdb_python")
    def test_empty_thread_list(self, mock_run):
        mock_run.return_value = self._make_mock_result({"status": "ok", "threads": []})
        result = inspect_threads("localhost:3333", "/path/to/app.elf")
        assert result == []

    @patch("eab.thread_inspector.run_gdb_python")
    def test_gdb_bridge_called_with_correct_args(self, mock_run):
        mock_run.return_value = self._make_mock_result({"status": "ok", "threads": []})
        inspect_threads("localhost:3333", "/firmware/app.elf")
        mock_run.assert_called_once()
        call_kwargs = mock_run.call_args.kwargs
        assert call_kwargs["target"] == "localhost:3333"
        assert call_kwargs["elf"] == "/firmware/app.elf"
        # chip="" is the correct fallback for generic GDB
        assert call_kwargs["chip"] == ""
