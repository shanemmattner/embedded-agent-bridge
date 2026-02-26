"""Thin launcher for the EAB MCP server.

Provides ``cmd_mcp_server()`` (called by the eabctl dispatcher) and a
``main()`` entry point for the ``eabmcp`` console script.
"""

from __future__ import annotations

import asyncio
import logging
import sys
from typing import Optional

log = logging.getLogger(__name__)


def cmd_mcp_server(
    base_dir: Optional[str] = None,
    json_mode: bool = False,
) -> int:
    """Launch the EAB MCP server.

    Args:
        base_dir: Unused — kept for dispatcher signature consistency.
        json_mode: Unused — MCP server communicates over JSON-RPC, not the
            EAB JSON output format.

    Returns:
        0 on clean exit, 1 on error.
    """
    try:
        from eab.mcp_server import run_mcp_server  # noqa: PLC0415
    except ImportError as exc:
        print(
            f"ERROR: {exc}\n"
            "Install the MCP extra with:  pip install embedded-agent-bridge[mcp]",
            file=sys.stderr,
        )
        return 1

    try:
        asyncio.run(run_mcp_server())
        return 0
    except KeyboardInterrupt:
        log.info("EAB MCP server stopped by user")
        return 0
    except Exception as exc:  # noqa: BLE001
        log.exception("EAB MCP server crashed: %s", exc)
        return 1


def main() -> None:
    """Entry point for the ``eabmcp`` console script."""
    sys.exit(cmd_mcp_server())
