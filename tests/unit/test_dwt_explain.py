"""Unit tests for eab.dwt_explain — no hardware or real ELF files required."""

from __future__ import annotations

import asyncio
import json
from unittest.mock import MagicMock, mock_open, patch

import pytest

from eab.dwt_explain import (
    capture_events,
    enrich_events,
    format_explain_prompt,
    resolve_source_line,
    run_dwt_explain,
)
from eab.dwt_watchpoint import SymbolNotFoundError

# =============================================================================
# Shared fixtures
# =============================================================================


@pytest.fixture
def sample_raw_events() -> list[dict]:
    return [
        {"ts": 1000, "label": "conn_interval", "addr": "0x20001234", "value": "0x4"},
        {"ts": 2000, "label": "tx_power", "addr": "0x20001238", "value": "0x0"},
    ]


@pytest.fixture
def sample_enriched_events() -> list[dict]:
    return [
        {
            "ts": 1000,
            "label": "conn_interval",
            "addr": "0x20001234",
            "value": "0x4",
            "source_file": "sensor.c",
            "line_number": 17,
            "function_name": "sensor_read",
        },
        {
            "ts": 2000,
            "label": "tx_power",
            "addr": "0x20001238",
            "value": "0x0",
            "source_file": "sensor.c",
            "line_number": 42,
            "function_name": "sensor_write",
        },
    ]


# =============================================================================
# 1. Test ELF source-line enrichment
# =============================================================================


class TestResolveSourceLine:
    @patch("eab.dwt_explain.subprocess.run")
    @patch("eab.dwt_explain.which_or_sdk")
    @patch("eab.dwt_explain.os.path.isfile")
    def test_returns_expected_source_location(
        self, mock_isfile, mock_which, mock_subrun
    ):
        mock_isfile.return_value = True
        mock_which.return_value = "/usr/bin/arm-none-eabi-addr2line"

        proc = MagicMock()
        proc.returncode = 0
        proc.stdout = "sensor_read\n/src/sensor.c:42\n"
        mock_subrun.return_value = proc

        result = resolve_source_line(0x20001234, "/fake/app.elf")

        assert result["source_file"] == "/src/sensor.c"
        assert result["line_number"] == 42
        assert result["function_name"] == "sensor_read"

    @patch("eab.dwt_explain.subprocess.run")
    @patch("eab.dwt_explain.which_or_sdk")
    @patch("eab.dwt_explain.os.path.isfile")
    def test_returns_fallback_when_addr2line_not_found(
        self, mock_isfile, mock_which, mock_subrun
    ):
        mock_isfile.return_value = True
        mock_which.return_value = None

        result = resolve_source_line(0x20001234, "/fake/app.elf")

        assert result["source_file"] == "??"
        assert result["line_number"] == 0
        assert result["function_name"] == "??"
        mock_subrun.assert_not_called()

    @patch("eab.dwt_explain.os.path.isfile")
    def test_raises_value_error_when_elf_missing(self, mock_isfile):
        mock_isfile.return_value = False

        with pytest.raises(ValueError, match="ELF file not found"):
            resolve_source_line(0x20001234, "/nonexistent/app.elf")


# =============================================================================
# 2. Test event capture with mock stream
# =============================================================================


class TestCaptureEvents:
    @patch("eab.dwt_explain.time.sleep")
    @patch("eab.dwt_explain.os.unlink")
    @patch("eab.dwt_explain.DwtWatchpointDaemon")
    @patch("eab.dwt_explain.tempfile.NamedTemporaryFile")
    def test_returns_parsed_events(
        self, mock_tf_cls, mock_daemon_cls, mock_unlink, mock_sleep, sample_raw_events
    ):
        # Set up fake temp file path
        mock_tf = MagicMock()
        mock_tf.name = "/tmp/fake_events.jsonl"
        mock_tf_cls.return_value = mock_tf

        # Set up daemon mock
        mock_daemon = MagicMock()
        mock_daemon_cls.return_value = mock_daemon

        # Produce JSONL content that the function will read
        jsonl_content = "\n".join(json.dumps(e) for e in sample_raw_events) + "\n"

        mock_jlink = MagicMock()
        mock_comp = MagicMock()

        with patch("builtins.open", mock_open(read_data=jsonl_content)):
            result = capture_events([mock_comp], mock_jlink, 0.1)

        assert result == sample_raw_events
        mock_sleep.assert_called_once_with(0.1)
        mock_daemon.start.assert_called_once()
        mock_daemon.stop.assert_called_once()

    @patch("eab.dwt_explain.time.sleep")
    @patch("eab.dwt_explain.os.unlink")
    @patch("eab.dwt_explain.DwtWatchpointDaemon")
    @patch("eab.dwt_explain.tempfile.NamedTemporaryFile")
    def test_returns_empty_list_when_no_events(
        self, mock_tf_cls, mock_daemon_cls, mock_unlink, mock_sleep
    ):
        mock_tf = MagicMock()
        mock_tf.name = "/tmp/fake_events.jsonl"
        mock_tf_cls.return_value = mock_tf
        mock_daemon_cls.return_value = MagicMock()

        mock_jlink = MagicMock()
        mock_comp = MagicMock()

        with patch("builtins.open", mock_open(read_data="")):
            result = capture_events([mock_comp], mock_jlink, 0.1)

        assert result == []


# =============================================================================
# 3. Test event enrichment
# =============================================================================


class TestEnrichEvents:
    @patch("eab.dwt_explain.resolve_source_line")
    def test_enriched_events_have_source_fields(
        self, mock_resolve, sample_raw_events
    ):
        mock_resolve.return_value = {
            "source_file": "sensor.c",
            "line_number": 17,
            "function_name": "sensor_read",
        }

        result = enrich_events(sample_raw_events, "/fake/app.elf")

        assert len(result) == len(sample_raw_events)
        for event in result:
            assert event["source_file"] == "sensor.c"
            assert event["line_number"] == 17
            assert event["function_name"] == "sensor_read"

    @patch("eab.dwt_explain.resolve_source_line")
    def test_enriched_events_retain_original_fields(
        self, mock_resolve, sample_raw_events
    ):
        mock_resolve.return_value = {
            "source_file": "sensor.c",
            "line_number": 17,
            "function_name": "sensor_read",
        }

        result = enrich_events(sample_raw_events, "/fake/app.elf")

        for original, enriched in zip(sample_raw_events, result):
            assert enriched["ts"] == original["ts"]
            assert enriched["label"] == original["label"]
            assert enriched["addr"] == original["addr"]
            assert enriched["value"] == original["value"]

    @patch("eab.dwt_explain.resolve_source_line")
    def test_empty_events_returns_empty(self, mock_resolve):
        result = enrich_events([], "/fake/app.elf")
        assert result == []
        mock_resolve.assert_not_called()


# =============================================================================
# 4. Test prompt formatting
# =============================================================================


class TestFormatExplainPrompt:
    def test_result_has_required_keys(self, sample_enriched_events):
        result = format_explain_prompt(sample_enriched_events)

        assert "events" in result
        assert "source_context" in result
        assert "ai_prompt" in result
        assert "suggested_watchpoints" in result

    def test_ai_prompt_is_non_empty_string(self, sample_enriched_events):
        result = format_explain_prompt(sample_enriched_events)
        assert isinstance(result["ai_prompt"], str)
        assert len(result["ai_prompt"]) > 0

    def test_events_are_passed_through(self, sample_enriched_events):
        result = format_explain_prompt(sample_enriched_events)
        assert result["events"] == sample_enriched_events

    def test_suggested_watchpoints_contains_labels(self, sample_enriched_events):
        result = format_explain_prompt(sample_enriched_events)
        assert "conn_interval" in result["suggested_watchpoints"]
        assert "tx_power" in result["suggested_watchpoints"]

    def test_source_context_is_string(self, sample_enriched_events):
        result = format_explain_prompt(sample_enriched_events)
        assert isinstance(result["source_context"], str)


# =============================================================================
# 5. Test orchestrator run_dwt_explain
# =============================================================================


class TestRunDwtExplain:
    @patch("eab.dwt_explain.capture_events")
    @patch("eab.dwt_explain.ComparatorAllocator")
    @patch("eab.cli.dwt._helpers._open_jlink")
    @patch("eab.dwt_explain._requires_write_to_clear_matched")
    @patch("eab.cli.dwt._helpers._resolve_symbol")
    @patch("eab.dwt_explain.os.path.isfile")
    @patch("eab.dwt_explain.resolve_source_line")
    def test_returns_complete_result(
        self,
        mock_resolve_src,
        mock_isfile,
        mock_resolve_sym,
        mock_wtc,
        mock_open_jlink,
        mock_allocator_cls,
        mock_capture,
        sample_raw_events,
    ):
        mock_isfile.return_value = True
        mock_resolve_sym.return_value = (0x20001234, 4)
        mock_wtc.return_value = False
        mock_open_jlink.return_value = MagicMock()
        mock_allocator = MagicMock()
        mock_allocator.allocate.return_value = MagicMock()
        mock_allocator_cls.return_value = mock_allocator
        mock_capture.return_value = sample_raw_events
        mock_resolve_src.return_value = {
            "source_file": "ble.c",
            "line_number": 10,
            "function_name": "ble_init",
        }

        result = run_dwt_explain(
            ["conn_interval"], 1.0, "/fake/app.elf", "NRF5340_XXAA_APP"
        )

        assert "events" in result
        assert "ai_prompt" in result
        assert "source_context" in result
        assert "suggested_watchpoints" in result
        assert len(result["events"]) == len(sample_raw_events)

    @patch("eab.dwt_explain.capture_events")
    @patch("eab.dwt_explain.ComparatorAllocator")
    @patch("eab.cli.dwt._helpers._open_jlink")
    @patch("eab.dwt_explain._requires_write_to_clear_matched")
    @patch("eab.cli.dwt._helpers._resolve_symbol")
    @patch("eab.dwt_explain.os.path.isfile")
    def test_calls_release_all_after_capture(
        self,
        mock_isfile,
        mock_resolve_sym,
        mock_wtc,
        mock_open_jlink,
        mock_allocator_cls,
        mock_capture,
    ):
        mock_isfile.return_value = True
        mock_resolve_sym.return_value = (0x20001234, 4)
        mock_wtc.return_value = False
        mock_open_jlink.return_value = MagicMock()
        mock_allocator = MagicMock()
        mock_allocator.allocate.return_value = MagicMock()
        mock_allocator_cls.return_value = mock_allocator
        mock_capture.return_value = []

        run_dwt_explain(["conn_interval"], 1.0, "/fake/app.elf", "NRF5340_XXAA_APP")

        mock_allocator.release_all.assert_called_once()


# =============================================================================
# 6. Edge case — no events captured
# =============================================================================


class TestRunDwtExplainNoEvents:
    @patch("eab.dwt_explain.capture_events")
    @patch("eab.dwt_explain.ComparatorAllocator")
    @patch("eab.cli.dwt._helpers._open_jlink")
    @patch("eab.dwt_explain._requires_write_to_clear_matched")
    @patch("eab.cli.dwt._helpers._resolve_symbol")
    @patch("eab.dwt_explain.os.path.isfile")
    def test_empty_events_handled_gracefully(
        self,
        mock_isfile,
        mock_resolve_sym,
        mock_wtc,
        mock_open_jlink,
        mock_allocator_cls,
        mock_capture,
    ):
        mock_isfile.return_value = True
        mock_resolve_sym.return_value = (0x20001234, 4)
        mock_wtc.return_value = False
        mock_open_jlink.return_value = MagicMock()
        mock_allocator = MagicMock()
        mock_allocator.allocate.return_value = MagicMock()
        mock_allocator_cls.return_value = mock_allocator
        mock_capture.return_value = []

        result = run_dwt_explain(
            ["conn_interval"], 1.0, "/fake/app.elf", "NRF5340_XXAA_APP"
        )

        assert result["events"] == []
        assert isinstance(result["ai_prompt"], str)
        assert len(result["ai_prompt"]) > 0

    def test_format_explain_prompt_empty_returns_non_empty_prompt(self):
        result = format_explain_prompt([])

        assert result["events"] == []
        assert isinstance(result["ai_prompt"], str)
        assert len(result["ai_prompt"]) > 0
        assert result["suggested_watchpoints"] == []


# =============================================================================
# 7. Edge case — unknown symbol
# =============================================================================


class TestRunDwtExplainUnknownSymbol:
    @patch("eab.cli.dwt._helpers._resolve_symbol")
    @patch("eab.dwt_explain.os.path.isfile")
    def test_raises_value_error_for_unknown_symbol(
        self, mock_isfile, mock_resolve_sym
    ):
        mock_isfile.return_value = True
        mock_resolve_sym.side_effect = SymbolNotFoundError("no_such_var not found")

        with pytest.raises(ValueError):
            run_dwt_explain(
                ["no_such_var"], 1.0, "/fake/app.elf", "NRF5340_XXAA_APP"
            )

    @patch("eab.cli.dwt._helpers._resolve_symbol")
    @patch("eab.dwt_explain.os.path.isfile")
    def test_error_message_contains_symbol_name(
        self, mock_isfile, mock_resolve_sym
    ):
        mock_isfile.return_value = True
        mock_resolve_sym.side_effect = SymbolNotFoundError("no_such_var not found")

        with pytest.raises(ValueError, match="no_such_var"):
            run_dwt_explain(
                ["no_such_var"], 1.0, "/fake/app.elf", "NRF5340_XXAA_APP"
            )


# =============================================================================
# 8. Input validation — empty symbols, non-positive duration
# =============================================================================


class TestRunDwtExplainInputValidation:
    def test_raises_value_error_for_empty_symbols(self):
        with pytest.raises(ValueError, match="symbols"):
            run_dwt_explain([], 1, "/fake/app.elf", "NRF5340_XXAA_APP")

    def test_raises_value_error_for_zero_duration(self):
        with pytest.raises(ValueError, match="duration_s"):
            run_dwt_explain(["conn_interval"], 0, "/fake/app.elf", "NRF5340_XXAA_APP")

    def test_raises_value_error_for_negative_duration(self):
        with pytest.raises(ValueError, match="duration_s"):
            run_dwt_explain(["conn_interval"], -5, "/fake/app.elf", "NRF5340_XXAA_APP")


# =============================================================================
# 9. CLI JSON output
# =============================================================================


class TestCmdDwtExplainJsonMode:
    """Tests for cmd_dwt_explain CLI handler with --json flag."""

    @pytest.fixture
    def fake_result(self) -> dict:
        return {
            "events": [
                {
                    "ts": 1000,
                    "label": "conn_interval",
                    "addr": "0x20001234",
                    "value": "0x4",
                    "source_file": "ble.c",
                    "line_number": 10,
                    "function_name": "ble_init",
                },
            ],
            "source_context": "DWT Watchpoint Hit Summary\n========",
            "ai_prompt": "You are an expert embedded-systems engineer.",
            "suggested_watchpoints": ["conn_interval"],
        }

    @patch("eab.cli.dwt.explain_cmd.run_dwt_explain")
    def test_json_mode_prints_valid_json(self, mock_run, fake_result, capsys):
        from eab.cli.dwt.explain_cmd import cmd_dwt_explain

        mock_run.return_value = fake_result

        rc = cmd_dwt_explain(
            device="NRF5340_XXAA_APP",
            symbols="conn_interval",
            elf="/fake/app.elf",
            duration=1,
            json_mode=True,
        )

        captured = capsys.readouterr()
        assert rc == 0
        parsed = json.loads(captured.out)
        assert "events" in parsed
        assert "source_context" in parsed
        assert "ai_prompt" in parsed
        assert "suggested_watchpoints" in parsed
        assert isinstance(parsed["suggested_watchpoints"], list)

    @patch("eab.cli.dwt.explain_cmd.run_dwt_explain")
    def test_non_json_mode_prints_ai_prompt(self, mock_run, fake_result, capsys):
        from eab.cli.dwt.explain_cmd import cmd_dwt_explain

        mock_run.return_value = fake_result

        rc = cmd_dwt_explain(
            device="NRF5340_XXAA_APP",
            symbols="conn_interval",
            elf="/fake/app.elf",
            duration=1,
            json_mode=False,
        )

        captured = capsys.readouterr()
        assert rc == 0
        assert fake_result["ai_prompt"] in captured.out
        # Should not be JSON-formatted output
        assert "{" not in captured.out


# =============================================================================
# 10. MCP tool handler
# =============================================================================


class TestMcpDwtStreamExplain:
    """Tests for the MCP _handle_tool dispatcher with dwt_stream_explain."""

    @pytest.fixture
    def fake_result(self) -> dict:
        return {
            "events": [
                {
                    "ts": 2000,
                    "label": "tx_power",
                    "addr": "0x20001238",
                    "value": "0x0",
                    "source_file": "radio.c",
                    "line_number": 55,
                    "function_name": "radio_configure",
                },
            ],
            "source_context": "DWT Watchpoint Hit Summary\n========",
            "ai_prompt": "You are an expert embedded-systems engineer.",
            "suggested_watchpoints": ["tx_power"],
        }

    @patch("eab.mcp_server.run_dwt_explain")
    def test_dwt_stream_explain_returns_valid_json(self, mock_run, fake_result):
        from eab.mcp_server import _handle_tool

        mock_run.return_value = fake_result

        raw = asyncio.run(
            _handle_tool(
                "dwt_stream_explain",
                {
                    "symbols": ["tx_power"],
                    "duration_s": 1,
                    "elf_path": "/fake/app.elf",
                },
            )
        )

        parsed = json.loads(raw)
        assert "events" in parsed
        assert "source_context" in parsed
        assert "ai_prompt" in parsed
        assert "suggested_watchpoints" in parsed
        assert isinstance(parsed["suggested_watchpoints"], list)
        mock_run.assert_called_once_with(
            symbols=["tx_power"],
            duration_s=1,
            elf_path="/fake/app.elf",
        )

    @patch("eab.mcp_server.run_dwt_explain")
    def test_unknown_tool_returns_error_json(self, mock_run):
        from eab.mcp_server import _handle_tool

        raw = asyncio.run(_handle_tool("no_such_tool", {}))

        parsed = json.loads(raw)
        assert "error" in parsed
        mock_run.assert_not_called()
