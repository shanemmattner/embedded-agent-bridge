"""MCP server for the Embedded Agent Bridge (EAB).

Exposes EAB CLI commands as MCP tools so Claude Desktop and other MCP-aware
agents can interact with embedded devices without spawning subprocesses.

Transport: stdio only (stdin → JSON-RPC → stdout).

Usage::

    python -m eab.mcp_server          # direct
    eabmcp                            # via installed script
    eabctl mcp-server                 # via eabctl dispatcher

If the ``mcp`` package is not installed, importing this module will raise an
``ImportError`` with a helpful installation hint.
"""

from __future__ import annotations

import json
import logging
from typing import Any

log = logging.getLogger(__name__)

# ---------------------------------------------------------------------------
# Optional import — graceful failure if mcp package not installed
# ---------------------------------------------------------------------------
try:
    from mcp.server import Server
    from mcp.server.stdio import stdio_server
    from mcp.types import (
        CallToolResult,
        ListToolsResult,
        TextContent,
        Tool,
    )

    _MCP_AVAILABLE = True
except ImportError:  # pragma: no cover
    _MCP_AVAILABLE = False
    Server = None  # type: ignore[assignment,misc]
    stdio_server = None  # type: ignore[assignment]
    CallToolResult = None  # type: ignore[assignment,misc]
    ListToolsResult = None  # type: ignore[assignment,misc]
    TextContent = None  # type: ignore[assignment,misc]
    Tool = None  # type: ignore[assignment,misc]

# ---------------------------------------------------------------------------
# Tool schema helpers
# ---------------------------------------------------------------------------

_BASE_DIR_PROP: dict[str, Any] = {
    "base_dir": {
        "type": "string",
        "description": ("Session directory for the target device (default: /tmp/eab-devices/<device>/)."),
    }
}

_JSON_MODE_PROP: dict[str, Any] = {
    "json_mode": {
        "type": "boolean",
        "description": "Return machine-parseable JSON (default: true).",
        "default": True,
    }
}


def _schema(props: dict[str, Any], required: list[str] | None = None) -> dict[str, Any]:
    return {
        "type": "object",
        "properties": props,
        "required": required or [],
    }


TOOL_DEFINITIONS: list[dict[str, Any]] = [
    {
        "name": "eab_status",
        "description": (
            "Return the EAB daemon status for a device: running, PID, port, uptime, and last-seen timestamp."
        ),
        "inputSchema": _schema({**_BASE_DIR_PROP, **_JSON_MODE_PROP}),
    },
    {
        "name": "eab_tail",
        "description": ("Return the last N lines of the device serial log (latest.log)."),
        "inputSchema": _schema(
            {
                **_BASE_DIR_PROP,
                "lines": {
                    "type": "integer",
                    "description": "Number of lines to return (default: 50).",
                    "default": 50,
                },
                **_JSON_MODE_PROP,
            }
        ),
    },
    {
        "name": "eab_wait",
        "description": (
            "Wait up to *timeout* seconds for a regex *pattern* to appear "
            "in the device log.  Returns the matched line on success."
        ),
        "inputSchema": _schema(
            {
                **_BASE_DIR_PROP,
                "pattern": {
                    "type": "string",
                    "description": "Regular expression to match in the log.",
                },
                "timeout_s": {
                    "type": "number",
                    "description": "Seconds to wait before giving up (default: 30).",
                    "default": 30.0,
                },
                "scan_all": {
                    "type": "boolean",
                    "description": "Scan from the beginning of the log (default: false).",
                    "default": False,
                },
                "scan_from": {
                    "type": "integer",
                    "description": "Scan from byte offset in log file (optional).",
                },
                **_JSON_MODE_PROP,
            },
            required=["pattern"],
        ),
    },
    {
        "name": "eab_send",
        "description": ("Send a text command to the embedded device via the EAB daemon."),
        "inputSchema": _schema(
            {
                **_BASE_DIR_PROP,
                "text": {
                    "type": "string",
                    "description": "Command text to send to the device.",
                },
                "await_ack": {
                    "type": "boolean",
                    "description": "Wait for the daemon to confirm the command was sent (default: false).",
                    "default": False,
                },
                "await_event": {
                    "type": "boolean",
                    "description": "Wait for events.jsonl confirmation (default: false).",
                    "default": False,
                },
                "timeout_s": {
                    "type": "number",
                    "description": "Timeout in seconds (default: 10).",
                    "default": 10.0,
                },
                **_JSON_MODE_PROP,
            },
            required=["text"],
        ),
    },
    {
        "name": "eab_reset",
        "description": (
            "Hardware-reset the embedded device.  Requires --chip to be specified (e.g., esp32s3, stm32l4)."
        ),
        "inputSchema": _schema(
            {
                "chip": {
                    "type": "string",
                    "description": "Chip type (e.g., esp32s3, stm32l4, nrf5340).",
                },
                "method": {
                    "type": "string",
                    "description": "Reset method: hard, soft, or bootloader (default: hard).",
                    "enum": ["hard", "soft", "bootloader"],
                    "default": "hard",
                },
                "device": {
                    "type": "string",
                    "description": "J-Link device string (e.g., NRF5340_XXAA_APP).",
                },
                **_JSON_MODE_PROP,
            },
            required=["chip"],
        ),
    },
    {
        "name": "eab_fault_analyze",
        "description": (
            "Analyze Cortex-M fault registers via a debug probe and return a human-readable fault summary."
        ),
        "inputSchema": _schema(
            {
                **_BASE_DIR_PROP,
                "device": {
                    "type": "string",
                    "description": "J-Link device string (e.g., NRF5340_XXAA_APP).",
                    "default": "NRF5340_XXAA_APP",
                },
                "elf": {
                    "type": "string",
                    "description": "Path to ELF file for GDB symbol resolution.",
                },
                "chip": {
                    "type": "string",
                    "description": "Chip type for GDB selection (default: nrf5340).",
                    "default": "nrf5340",
                },
                "probe_type": {
                    "type": "string",
                    "description": "Debug probe type: jlink, openocd, or xds110 (default: jlink).",
                    "enum": ["jlink", "openocd", "xds110"],
                    "default": "jlink",
                },
                "probe_selector": {
                    "type": "string",
                    "description": "Probe serial number or identifier.",
                },
                **_JSON_MODE_PROP,
            }
        ),
    },
    {
        "name": "eab_rtt_tail",
        "description": ("Return the last N lines of the J-Link RTT log (rtt.log)."),
        "inputSchema": _schema(
            {
                **_BASE_DIR_PROP,
                "lines": {
                    "type": "integer",
                    "description": "Number of lines to return (default: 50).",
                    "default": 50,
                },
                **_JSON_MODE_PROP,
            }
        ),
    },
    {
        "name": "eab_regression",
        "description": ("Run hardware-in-the-loop regression tests from a YAML test suite."),
        "inputSchema": _schema(
            {
                "suite": {
                    "type": "string",
                    "description": "Directory containing *.yaml test files.",
                },
                "test": {
                    "type": "string",
                    "description": "Single test YAML file to run.",
                },
                "filter_pattern": {
                    "type": "string",
                    "description": "Glob pattern to filter test files (e.g., '*nrf*').",
                },
                "timeout": {
                    "type": "integer",
                    "description": "Timeout per test in seconds.",
                },
                **_JSON_MODE_PROP,
            }
        ),
    },
    {
        "name": "get_thread_state",
        "description": (
            "Inspect Zephyr RTOS threads on a live target via GDB and return "
            "thread state information including name, state, priority, and "
            "stack usage for each thread."
        ),
        "inputSchema": _schema(
            {
                "device": {
                    "type": "string",
                    "description": "GDB remote target string (e.g., 'localhost:3333').",
                },
                "elf_path": {
                    "type": "string",
                    "description": "Path to ELF file with DWARF debug symbols.",
                },
            },
            required=["device", "elf_path"],
        ),
    },
]


# ---------------------------------------------------------------------------
# Tool handler helpers
# ---------------------------------------------------------------------------


def _import_cli() -> Any:
    """Lazy import of eab.cli to allow monkeypatching in tests."""
    import eab.cli as cli  # noqa: PLC0415

    return cli


def _result_text(return_code: int, output: str | None = None) -> str:
    """Format tool result as a JSON string."""
    payload: dict[str, Any] = {"return_code": return_code}
    if output is not None:
        payload["output"] = output
    return json.dumps(payload)


def _capture_cmd(func: Any, *args: Any, **kwargs: Any) -> str:
    """Call a cmd_* function and capture its stdout output.

    cmd_* functions write to stdout and return an integer exit code.
    We capture stdout so the MCP tool can return it as text content.
    """
    import io
    import sys

    buf = io.StringIO()
    old_stdout = sys.stdout
    try:
        sys.stdout = buf
        rc = func(*args, **kwargs)
    finally:
        sys.stdout = old_stdout
    return json.dumps({"return_code": rc, "output": buf.getvalue()})


# ---------------------------------------------------------------------------
# Tool dispatch
# ---------------------------------------------------------------------------


async def _handle_tool(name: str, arguments: dict[str, Any]) -> str:
    """Dispatch an MCP tool call to the corresponding cmd_* function.

    Returns a JSON string suitable for embedding in a TextContent block.
    """
    cli = _import_cli()

    if name == "eab_status":
        return _capture_cmd(
            cli.cmd_status,
            base_dir=arguments.get("base_dir"),
            json_mode=arguments.get("json_mode", True),
        )

    if name == "eab_tail":
        return _capture_cmd(
            cli.cmd_tail,
            base_dir=arguments.get("base_dir"),
            lines=arguments.get("lines", 50),
            json_mode=arguments.get("json_mode", True),
        )

    if name == "eab_wait":
        return _capture_cmd(
            cli.cmd_wait,
            base_dir=arguments.get("base_dir"),
            pattern=arguments["pattern"],
            timeout_s=arguments.get("timeout_s", 30.0),
            scan_all=arguments.get("scan_all", False),
            scan_from=arguments.get("scan_from"),
            json_mode=arguments.get("json_mode", True),
        )

    if name == "eab_send":
        return _capture_cmd(
            cli.cmd_send,
            base_dir=arguments.get("base_dir"),
            text=arguments["text"],
            await_ack=arguments.get("await_ack", False),
            await_event=arguments.get("await_event", False),
            timeout_s=arguments.get("timeout_s", 10.0),
            json_mode=arguments.get("json_mode", True),
        )

    if name == "eab_reset":
        return _capture_cmd(
            cli.cmd_reset,
            chip=arguments["chip"],
            method=arguments.get("method", "hard"),
            connect_under_reset=False,
            device=arguments.get("device"),
            json_mode=arguments.get("json_mode", True),
        )

    if name == "eab_fault_analyze":
        return _capture_cmd(
            cli.cmd_fault_analyze,
            base_dir=arguments.get("base_dir"),
            device=arguments.get("device", "NRF5340_XXAA_APP"),
            elf=arguments.get("elf"),
            chip=arguments.get("chip", "nrf5340"),
            probe_type=arguments.get("probe_type", "jlink"),
            probe_selector=arguments.get("probe_selector"),
            json_mode=arguments.get("json_mode", True),
        )

    if name == "eab_rtt_tail":
        return _capture_cmd(
            cli.cmd_rtt_tail,
            base_dir=arguments.get("base_dir"),
            lines=arguments.get("lines", 50),
            json_mode=arguments.get("json_mode", True),
        )

    if name == "eab_regression":
        from eab.cli.regression import cmd_regression  # noqa: PLC0415

        return _capture_cmd(
            cmd_regression,
            suite=arguments.get("suite"),
            test=arguments.get("test"),
            filter_pattern=arguments.get("filter_pattern"),
            timeout=arguments.get("timeout"),
            json_mode=arguments.get("json_mode", True),
        )

    if name == "get_thread_state":
        from eab.thread_inspector import inspect_threads  # noqa: PLC0415

        threads = inspect_threads(arguments["device"], arguments["elf_path"])
        return json.dumps({"threads": [t.to_dict() for t in threads]})

    return json.dumps({"error": f"Unknown tool: {name}"})


# ---------------------------------------------------------------------------
# MCP server entry point
# ---------------------------------------------------------------------------


async def run_mcp_server() -> None:
    """Run the EAB MCP server over stdio transport.

    Raises:
        ImportError: If the ``mcp`` package is not installed.
    """
    if not _MCP_AVAILABLE:
        raise ImportError(
            "The 'mcp' package is required to run the EAB MCP server.\n"
            "Install it with:  pip install embedded-agent-bridge[mcp]"
        )

    server = Server("embedded-agent-bridge")

    @server.list_tools()  # type: ignore[misc]
    async def list_tools() -> list[Tool]:  # type: ignore[return]
        return [
            Tool(
                name=t["name"],
                description=t["description"],
                inputSchema=t["inputSchema"],
            )
            for t in TOOL_DEFINITIONS
        ]

    @server.call_tool()  # type: ignore[misc]
    async def call_tool(name: str, arguments: dict[str, Any]) -> list[TextContent]:  # type: ignore[return]
        log.debug("MCP tool call: %s args=%r", name, arguments)
        try:
            result_text = await _handle_tool(name, arguments)
        except Exception as exc:  # noqa: BLE001
            log.exception("Tool %s raised an exception", name)
            result_text = json.dumps({"error": str(exc), "tool": name})
        return [TextContent(type="text", text=result_text)]

    log.info("EAB MCP server starting (stdio transport)")
    async with stdio_server() as (read_stream, write_stream):
        await server.run(read_stream, write_stream, server.create_initialization_options())
