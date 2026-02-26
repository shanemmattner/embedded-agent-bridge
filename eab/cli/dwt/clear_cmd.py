"""cmd_dwt_clear — release all DWT comparators."""

from __future__ import annotations

import json
import logging
import sys
from typing import Optional

logger = logging.getLogger(__name__)

try:
    import pylink
except ImportError:
    pylink = None  # type: ignore

from eab.dwt_watchpoint import ComparatorAllocator
from eab.cli.dwt._helpers import _open_jlink


def cmd_dwt_clear(
    *,
    device: str,
    probe_selector: Optional[str] = None,
    json_mode: bool = False,
) -> int:
    """Release all DWT comparators by writing DWT_FUNC_DISABLED to each.

    Args:
        device:         J-Link device string.
        probe_selector: Optional J-Link serial number.
        json_mode:      Output JSON.

    Returns:
        0 on success, non-zero on error.
    """
    if pylink is None:
        _emit_error(
            "pylink-square required. Install: pip install pylink-square",
            json_mode,
        )
        return 1

    try:
        jlink = _open_jlink(device, probe_selector=probe_selector)
    except Exception as exc:
        _emit_error(f"Failed to connect J-Link: {exc}", json_mode)
        return 1

    allocator = ComparatorAllocator(jlink)
    try:
        allocator.release_all()
    except Exception as exc:
        _emit_error(f"Failed to clear comparators: {exc}", json_mode)
        return 1

    if json_mode:
        print(json.dumps({"status": "cleared", "device": device}), flush=True)
    else:
        print(f"All DWT comparators cleared on {device}.", flush=True)

    return 0


def _emit_error(message: str, json_mode: bool) -> None:
    if json_mode:
        print(json.dumps({"error": message}), file=sys.stderr, flush=True)
    else:
        print(f"Error: {message}", file=sys.stderr, flush=True)
