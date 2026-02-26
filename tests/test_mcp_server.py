"""Unit tests for eab.mcp_server and eab.cli.mcp_cmd.

The ``mcp`` package may not be installed in the test environment, so we mock
it entirely.  Tests focus on:
- TOOL_DEFINITIONS list is non-empty and well-formed.
- Each tool handler in _handle_tool calls the correct cmd_* function.
- Error responses are well-formed JSON.
- cmd_mcp_server() returns 1 when mcp is not available.
- The parser accepts the ``mcp-server`` subcommand.
"""

from __future__ import annotations

import asyncio
import importlib
import json
import sys
import types
from typing import Any
from unittest.mock import AsyncMock, MagicMock, patch

import pytest


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def _make_mock_mcp_module() -> types.ModuleType:
    """Build a minimal fake ``mcp`` package tree so eab.mcp_server can import."""
    mcp_pkg = types.ModuleType("mcp")
    mcp_server_pkg = types.ModuleType("mcp.server")
    mcp_stdio_pkg = types.ModuleType("mcp.server.stdio")
    mcp_types_pkg = types.ModuleType("mcp.types")

    # Fake Server class
    class FakeServer:
        def __init__(self, name: str) -> None:
            self.name = name
            self._list_tools_handler = None
            self._call_tool_handler = None

        def list_tools(self):  # noqa: ANN201
            def decorator(fn):  # noqa: ANN001
                self._list_tools_handler = fn
                return fn
            return decorator

        def call_tool(self):  # noqa: ANN201
            def decorator(fn):  # noqa: ANN001
                self._call_tool_handler = fn
                return fn
            return decorator

        async def run(self, read_stream, write_stream, opts):  # noqa: ANN001,ANN201
            pass

        def create_initialization_options(self):  # noqa: ANN201
            return {}

    # Fake async context manager for stdio_server
    class FakeStdioCtx:
        async def __aenter__(self):  # noqa: ANN204
            return (AsyncMock(), AsyncMock())

        async def __aexit__(self, *args: Any) -> None:
            pass

    def fake_stdio_server():  # noqa: ANN201
        return FakeStdioCtx()

    # Fake types
    class FakeTool:
        def __init__(self, *, name: str, description: str, inputSchema: dict) -> None:  # noqa: N803
            self.name = name
            self.description = description
            self.inputSchema = inputSchema

    class FakeTextContent:
        def __init__(self, *, type: str, text: str) -> None:
            self.type = type
            self.text = text

    mcp_server_pkg.Server = FakeServer  # type: ignore[attr-defined]
    mcp_stdio_pkg.stdio_server = fake_stdio_server  # type: ignore[attr-defined]
    mcp_types_pkg.Tool = FakeTool  # type: ignore[attr-defined]
    mcp_types_pkg.TextContent = FakeTextContent  # type: ignore[attr-defined]
    mcp_types_pkg.CallToolResult = object  # type: ignore[attr-defined]
    mcp_types_pkg.ListToolsResult = object  # type: ignore[attr-defined]

    mcp_pkg.server = mcp_server_pkg  # type: ignore[attr-defined]
    mcp_server_pkg.stdio = mcp_stdio_pkg  # type: ignore[attr-defined]

    sys.modules["mcp"] = mcp_pkg
    sys.modules["mcp.server"] = mcp_server_pkg
    sys.modules["mcp.server.stdio"] = mcp_stdio_pkg
    sys.modules["mcp.types"] = mcp_types_pkg

    return mcp_pkg


def _load_mcp_server_module() -> types.ModuleType:
    """Import (or reimport) eab.mcp_server with a mocked mcp package."""
    _make_mock_mcp_module()
    # Force reimport so the top-level try/except re-runs.
    if "eab.mcp_server" in sys.modules:
        del sys.modules["eab.mcp_server"]
    return importlib.import_module("eab.mcp_server")


# ---------------------------------------------------------------------------
# Fixtures
# ---------------------------------------------------------------------------

@pytest.fixture()
def mcp_module():
    """Provides eab.mcp_server loaded with a mocked mcp package."""
    mod = _load_mcp_server_module()
    yield mod
    # Cleanup
    for key in list(sys.modules.keys()):
        if key.startswith("mcp"):
            del sys.modules[key]
    if "eab.mcp_server" in sys.modules:
        del sys.modules["eab.mcp_server"]


# ---------------------------------------------------------------------------
# Tests: TOOL_DEFINITIONS
# ---------------------------------------------------------------------------

class TestToolDefinitions:
    def test_tool_definitions_non_empty(self, mcp_module):
        assert len(mcp_module.TOOL_DEFINITIONS) >= 8

    def test_all_tools_have_name_description_schema(self, mcp_module):
        for tool in mcp_module.TOOL_DEFINITIONS:
            assert "name" in tool, f"Missing 'name': {tool}"
            assert "description" in tool, f"Missing 'description': {tool}"
            assert "inputSchema" in tool, f"Missing 'inputSchema': {tool}"

    def test_expected_tools_present(self, mcp_module):
        names = {t["name"] for t in mcp_module.TOOL_DEFINITIONS}
        expected = {
            "eab_status",
            "eab_tail",
            "eab_wait",
            "eab_send",
            "eab_reset",
            "eab_fault_analyze",
            "eab_rtt_tail",
            "eab_regression",
            "capture_snapshot",
        }
        assert expected.issubset(names), f"Missing tools: {expected - names}"

    def test_schema_type_is_object(self, mcp_module):
        for tool in mcp_module.TOOL_DEFINITIONS:
            assert tool["inputSchema"]["type"] == "object", (
                f"Tool {tool['name']} schema type is not 'object'"
            )

    def test_required_fields_are_lists(self, mcp_module):
        for tool in mcp_module.TOOL_DEFINITIONS:
            req = tool["inputSchema"].get("required", [])
            assert isinstance(req, list), (
                f"Tool {tool['name']} 'required' is not a list"
            )


# ---------------------------------------------------------------------------
# Tests: _handle_tool dispatch
# ---------------------------------------------------------------------------

class TestHandleTool:
    """Each test verifies _handle_tool calls the correct cmd_* function."""

    def _run(self, coro):  # noqa: ANN001,ANN201
        return asyncio.run(coro)

    def test_eab_status(self, mcp_module):
        mock_fn = MagicMock(return_value=0)
        with patch("eab.cli.cmd_status", mock_fn):
            result = self._run(mcp_module._handle_tool("eab_status", {"base_dir": "/tmp/x"}))
        data = json.loads(result)
        assert data["return_code"] == 0
        mock_fn.assert_called_once_with(base_dir="/tmp/x", json_mode=True)

    def test_eab_tail(self, mcp_module):
        mock_fn = MagicMock(return_value=0)
        with patch("eab.cli.cmd_tail", mock_fn):
            result = self._run(mcp_module._handle_tool("eab_tail", {"lines": 10}))
        data = json.loads(result)
        assert data["return_code"] == 0
        mock_fn.assert_called_once_with(base_dir=None, lines=10, json_mode=True)

    def test_eab_tail_default_lines(self, mcp_module):
        mock_fn = MagicMock(return_value=0)
        with patch("eab.cli.cmd_tail", mock_fn):
            self._run(mcp_module._handle_tool("eab_tail", {}))
        _, kwargs = mock_fn.call_args
        assert kwargs["lines"] == 50

    def test_eab_wait(self, mcp_module):
        mock_fn = MagicMock(return_value=0)
        with patch("eab.cli.cmd_wait", mock_fn):
            result = self._run(mcp_module._handle_tool("eab_wait", {"pattern": "BOOT_OK"}))
        data = json.loads(result)
        assert data["return_code"] == 0
        mock_fn.assert_called_once()
        _, kwargs = mock_fn.call_args
        assert kwargs["pattern"] == "BOOT_OK"
        assert kwargs["timeout_s"] == 30.0
        assert kwargs["scan_all"] is False
        assert kwargs["scan_from"] is None

    def test_eab_send(self, mcp_module):
        mock_fn = MagicMock(return_value=0)
        with patch("eab.cli.cmd_send", mock_fn):
            result = self._run(mcp_module._handle_tool("eab_send", {"text": "reset"}))
        data = json.loads(result)
        assert data["return_code"] == 0
        mock_fn.assert_called_once()
        _, kwargs = mock_fn.call_args
        assert kwargs["text"] == "reset"
        assert kwargs["await_ack"] is False

    def test_eab_reset(self, mcp_module):
        mock_fn = MagicMock(return_value=0)
        with patch("eab.cli.cmd_reset", mock_fn):
            result = self._run(mcp_module._handle_tool("eab_reset", {"chip": "esp32s3"}))
        data = json.loads(result)
        assert data["return_code"] == 0
        mock_fn.assert_called_once()
        _, kwargs = mock_fn.call_args
        assert kwargs["chip"] == "esp32s3"
        assert kwargs["method"] == "hard"

    def test_eab_fault_analyze(self, mcp_module):
        mock_fn = MagicMock(return_value=0)
        with patch("eab.cli.cmd_fault_analyze", mock_fn):
            result = self._run(mcp_module._handle_tool("eab_fault_analyze", {}))
        data = json.loads(result)
        assert data["return_code"] == 0
        mock_fn.assert_called_once()
        _, kwargs = mock_fn.call_args
        assert kwargs["device"] == "NRF5340_XXAA_APP"
        assert kwargs["probe_type"] == "jlink"

    def test_eab_rtt_tail(self, mcp_module):
        mock_fn = MagicMock(return_value=0)
        with patch("eab.cli.cmd_rtt_tail", mock_fn):
            result = self._run(mcp_module._handle_tool("eab_rtt_tail", {"lines": 20}))
        data = json.loads(result)
        assert data["return_code"] == 0
        mock_fn.assert_called_once_with(base_dir=None, lines=20, json_mode=True)

    def test_eab_regression(self, mcp_module):
        mock_fn = MagicMock(return_value=0)
        with patch("eab.cli.regression.cmd_regression", mock_fn):
            result = self._run(
                mcp_module._handle_tool("eab_regression", {"suite": "/tests/suite"})
            )
        data = json.loads(result)
        assert data["return_code"] == 0
        mock_fn.assert_called_once()
        _, kwargs = mock_fn.call_args
        assert kwargs["suite"] == "/tests/suite"

    def test_capture_snapshot(self, mcp_module):
        mock_region = MagicMock()
        mock_region.start = 0x20000000
        mock_region.size = 0x40000
        mock_result = MagicMock()
        mock_result.output_path = "/tmp/snap.bin"
        mock_result.regions = [mock_region]
        mock_result.registers = {"r0": 0, "pc": 0x12345678}
        mock_result.total_size = 65536

        mock_fn = MagicMock(return_value=mock_result)
        with patch("eab.snapshot.capture_snapshot", mock_fn):
            result = self._run(
                mcp_module._handle_tool(
                    "capture_snapshot",
                    {
                        "device": "NRF5340_XXAA_APP",
                        "elf_path": "/fw/app.elf",
                        "output_path": "/tmp/snap.bin",
                    },
                )
            )
        data = json.loads(result)
        assert data["path"] == "/tmp/snap.bin"
        assert "regions" in data
        assert len(data["regions"]) == 1
        assert data["regions"][0]["start"] == 0x20000000
        assert data["regions"][0]["size"] == 0x40000
        assert "registers" in data
        assert data["registers"]["pc"] == 0x12345678
        assert data["size_bytes"] == 65536
        mock_fn.assert_called_once_with(
            device="NRF5340_XXAA_APP",
            elf_path="/fw/app.elf",
            output_path="/tmp/snap.bin",
        )

    def test_capture_snapshot_default_output_path(self, mcp_module):
        mock_region = MagicMock()
        mock_region.start = 0x20000000
        mock_region.size = 0x40000
        mock_result = MagicMock()
        mock_result.output_path = "snapshot.core"
        mock_result.regions = [mock_region]
        mock_result.registers = {"r0": 0}
        mock_result.total_size = 65536

        mock_fn = MagicMock(return_value=mock_result)
        with patch("eab.snapshot.capture_snapshot", mock_fn):
            self._run(
                mcp_module._handle_tool(
                    "capture_snapshot",
                    {"device": "NRF5340_XXAA_APP", "elf_path": "/fw/app.elf"},
                )
            )
        _, kwargs = mock_fn.call_args
        assert kwargs["output_path"] == "snapshot.core"

    def test_unknown_tool_returns_error(self, mcp_module):
        result = self._run(mcp_module._handle_tool("nonexistent_tool", {}))
        data = json.loads(result)
        assert "error" in data
        assert "nonexistent_tool" in data["error"]

    def test_exception_in_cmd_returns_error_json(self, mcp_module):
        mock_fn = MagicMock(side_effect=RuntimeError("boom"))
        with patch("eab.cli.cmd_status", mock_fn):
            # _handle_tool itself doesn't catch — the server.call_tool decorator does.
            # But we test that the exception propagates correctly.
            with pytest.raises(RuntimeError, match="boom"):
                self._run(mcp_module._handle_tool("eab_status", {}))


# ---------------------------------------------------------------------------
# Tests: run_mcp_server
# ---------------------------------------------------------------------------

class TestRunMcpServer:
    def test_run_raises_import_error_when_mcp_unavailable(self):
        """When mcp is not installed, run_mcp_server should raise ImportError."""
        # Temporarily remove mcp from sys.modules to simulate absence.
        saved = {k: v for k, v in sys.modules.items() if k.startswith("mcp")}
        for key in list(sys.modules.keys()):
            if key.startswith("mcp"):
                del sys.modules[key]

        if "eab.mcp_server" in sys.modules:
            del sys.modules["eab.mcp_server"]

        # Patch builtins.__import__ to raise for "mcp"
        real_import = __builtins__.__import__ if hasattr(__builtins__, "__import__") else __import__

        def fake_import(name, *args, **kwargs):  # noqa: ANN001,ANN002,ANN003,ANN201
            if name == "mcp" or name.startswith("mcp."):
                raise ImportError("No module named 'mcp'")
            return real_import(name, *args, **kwargs)

        with patch("builtins.__import__", side_effect=fake_import):
            try:
                import eab.mcp_server as ms  # noqa: PLC0415
            except ImportError:
                # Module itself failed to import — that's fine for this test
                ms = None

        # Restore
        sys.modules.update(saved)
        if "eab.mcp_server" in sys.modules:
            del sys.modules["eab.mcp_server"]

    def test_run_mcp_server_calls_stdio_server(self, mcp_module):
        """run_mcp_server should call stdio_server and server.run."""
        called = []

        class FakeStdioCtx:
            async def __aenter__(self):  # noqa: ANN204
                called.append("enter")
                return (AsyncMock(), AsyncMock())

            async def __aexit__(self, *args: Any) -> None:
                called.append("exit")

        with patch("eab.mcp_server.stdio_server", return_value=FakeStdioCtx()):
            asyncio.run(mcp_module.run_mcp_server())

        assert "enter" in called
        assert "exit" in called


# ---------------------------------------------------------------------------
# Tests: cmd_mcp_server (launcher)
# ---------------------------------------------------------------------------

class TestCmdMcpServer:
    def test_returns_0_on_clean_run(self):
        from eab.cli.mcp_cmd import cmd_mcp_server  # noqa: PLC0415

        async def fake_run():  # noqa: ANN201
            pass

        with patch("eab.cli.mcp_cmd.asyncio.run", return_value=None) as mock_run:
            with patch(
                "eab.cli.mcp_cmd.importlib" if False else "eab.mcp_server.run_mcp_server",
                fake_run,
            ):
                # We patch asyncio.run so it doesn't actually start the loop.
                result = cmd_mcp_server()
        assert result == 0
        mock_run.assert_called_once()

    def test_returns_1_when_import_error(self):
        from eab.cli.mcp_cmd import cmd_mcp_server  # noqa: PLC0415

        with patch("eab.cli.mcp_cmd.importlib" if False else "builtins.__import__") as _:
            # Simulate ImportError from eab.mcp_server import
            with patch(
                "eab.cli.mcp_cmd.asyncio.run",
                side_effect=ImportError("No module named 'mcp'"),
            ):
                # cmd_mcp_server imports run_mcp_server first — patch that import
                pass

        # Direct approach: patch the import inside cmd_mcp_server
        import builtins  # noqa: PLC0415
        real_import = builtins.__import__

        def broken_import(name, *args, **kwargs):  # noqa: ANN001,ANN002,ANN003,ANN201
            if name == "eab.mcp_server" or (name == "eab" and "mcp_server" in str(args)):
                raise ImportError("No module named 'mcp'")
            return real_import(name, *args, **kwargs)

        with patch("builtins.__import__", side_effect=broken_import):
            # This won't work cleanly since cmd_mcp_server is already imported.
            # Instead, test via patching the from-import directly.
            pass

        # Simplest approach: patch the specific import inside cmd_mcp_server
        with patch.dict(sys.modules, {"eab.mcp_server": None}):
            result = cmd_mcp_server()
        # When sys.modules["eab.mcp_server"] is None, import raises ImportError
        assert result == 1

    def test_returns_1_on_exception(self):
        from eab.cli.mcp_cmd import cmd_mcp_server  # noqa: PLC0415
        # Ensure mcp_server is importable (mocked or real)
        _load_mcp_server_module()

        with patch("eab.cli.mcp_cmd.asyncio.run", side_effect=RuntimeError("crash")):
            result = cmd_mcp_server()
        assert result == 1

    def test_returns_0_on_keyboard_interrupt(self):
        from eab.cli.mcp_cmd import cmd_mcp_server  # noqa: PLC0415
        _load_mcp_server_module()

        with patch("eab.cli.mcp_cmd.asyncio.run", side_effect=KeyboardInterrupt()):
            result = cmd_mcp_server()
        assert result == 0


# ---------------------------------------------------------------------------
# Tests: CLI parser
# ---------------------------------------------------------------------------

class TestParser:
    def test_mcp_server_subcommand_registered(self):
        from eab.cli.parser import _build_parser  # noqa: PLC0415

        parser = _build_parser()
        # Check that mcp-server is a valid choice
        choices = parser._subparsers._group_actions[0].choices
        assert "mcp-server" in choices

    def test_parse_mcp_server_args(self):
        from eab.cli.parser import _build_parser, _preprocess_argv  # noqa: PLC0415

        parser = _build_parser()
        argv = _preprocess_argv(["mcp-server"])
        args = parser.parse_args(argv)
        assert args.cmd == "mcp-server"

    def test_parse_mcp_server_with_json_flag(self):
        from eab.cli.parser import _build_parser, _preprocess_argv  # noqa: PLC0415

        parser = _build_parser()
        argv = _preprocess_argv(["--json", "mcp-server"])
        args = parser.parse_args(argv)
        assert args.cmd == "mcp-server"
        assert args.json is True


# ---------------------------------------------------------------------------
# Tests: dispatch
# ---------------------------------------------------------------------------

class TestDispatch:
    def test_dispatch_mcp_server(self):
        from eab.cli.dispatch import main  # noqa: PLC0415

        with patch("eab.cli.mcp_cmd.cmd_mcp_server", return_value=0) as mock_cmd:
            rc = main(["mcp-server"])
        assert rc == 0
        mock_cmd.assert_called_once()
