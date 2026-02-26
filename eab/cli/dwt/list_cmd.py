"""cmd_dwt_list — show active DWT comparators."""

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

from eab.dwt_watchpoint import (
    DWT_FUNCT_BASE,
    DWT_COMP_STRIDE,
    DWT_FUNC_DISABLED,
    ComparatorAllocator,
)
from eab.cli.dwt._helpers import _open_jlink


def cmd_dwt_list(
    *,
    device: Optional[str] = None,
    probe_selector: Optional[str] = None,
    json_mode: bool = False,
) -> int:
    """Show active DWT comparators.

    If --device is given, reads live DWT_FUNCTn registers via J-Link.
    Otherwise reads from the persisted state file.

    Args:
        device:         Optional J-Link device string.
        probe_selector: Optional J-Link serial number.
        json_mode:      Output JSON.

    Returns:
        0 on success.
    """
    if device:
        if pylink is None:
            _emit_error(
                "pylink-square required for live read. Install: pip install pylink-square",
                json_mode,
            )
            return 1
        try:
            jlink = _open_jlink(device, probe_selector=probe_selector)
        except Exception as exc:
            _emit_error(f"Failed to connect J-Link: {exc}", json_mode)
            return 1

        allocator = ComparatorAllocator(jlink)
        numcomp = allocator.detect_numcomp()
        rows = []
        for idx in range(numcomp):
            funct_addr = DWT_FUNCT_BASE + idx * DWT_COMP_STRIDE
            try:
                funct_val = jlink.memory_read32(funct_addr, 1)[0]
            except Exception:
                funct_val = 0
            func_code = funct_val & 0xF
            active = func_code != DWT_FUNC_DISABLED
            rows.append({
                "index": idx,
                "funct_addr": f"0x{funct_addr:08X}",
                "funct_val": f"0x{funct_val:08X}",
                "active": active,
                "func_code": func_code,
            })
    else:
        # No device — just show empty list
        rows = []

    if json_mode:
        print(json.dumps({"comparators": rows}), flush=True)
    else:
        if not rows:
            print("No active DWT comparators found.", flush=True)
        else:
            print(f"{'Slot':<6} {'FUNCT Addr':<14} {'FUNCT Val':<12} {'Active':<8} {'Func Code'}")
            for r in rows:
                print(
                    f"{r['index']:<6} {r['funct_addr']:<14} {r['funct_val']:<12} "
                    f"{str(r['active']):<8} {r['func_code']}"
                )

    return 0


def _emit_error(message: str, json_mode: bool) -> None:
    if json_mode:
        print(json.dumps({"error": message}), file=sys.stderr, flush=True)
    else:
        print(f"Error: {message}", file=sys.stderr, flush=True)
