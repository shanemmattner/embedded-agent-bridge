"""cmd_dwt_halt — halting DWT watchpoint via GDB with optional condition."""

from __future__ import annotations

import json
import logging
import sys
import tempfile
from typing import Optional

logger = logging.getLogger(__name__)


def generate_dwt_halt_watchpoint(
    var_name: str,
    mode: str = "write",
    condition: Optional[str] = None,
    max_hits: int = 100,
    backtrace: bool = True,
    result_file: Optional[str] = None,
) -> str:
    """Generate a GDB Python script for a halting watchpoint on var_name.

    The script:
      - Sets the watchpoint type based on mode (watch/rwatch/awatch).
      - If condition is set, evaluates it via gdb.parse_and_eval(); skips
        hit if condition is falsy.
      - Logs each qualifying hit as a JSON line to result_file.
      - Stops after max_hits.

    Args:
        var_name:    Variable name as it appears in debug symbols.
        mode:        "read", "write", or "rw".
        condition:   Optional Python expression evaluated at each hit.
        max_hits:    Maximum number of qualifying hits to record.
        backtrace:   If True, capture a backtrace at each hit.
        result_file: Path to JSONL output file (auto-temp if None).

    Returns:
        Complete GDB Python script as a string.
    """
    gdb_cmd = {"read": "rwatch", "write": "watch", "rw": "awatch"}.get(mode, "watch")

    if result_file is None:
        result_file = f"/tmp/eab-dwt-halt-{var_name}.jsonl"

    cond_check = ""
    if condition:
        cond_check = f"""
        try:
            cond_val = gdb.parse_and_eval({condition!r})
            if not cond_val:
                return
        except Exception as _cond_exc:
            pass
"""

    bt_code = ""
    if backtrace:
        bt_code = """
        try:
            bt_lines = []
            frame = gdb.selected_frame()
            while frame:
                sal = frame.find_sal()
                fn = frame.name() or '??'
                f_line = sal.line if sal.symtab else 0
                f_file = sal.symtab.filename if sal.symtab else '??'
                bt_lines.append(f'{fn} ({f_file}:{f_line})')
                frame = frame.older()
            hit_data['backtrace'] = bt_lines
        except Exception as _bt_exc:
            hit_data['backtrace'] = str(_bt_exc)
"""

    script = f"""
import gdb
import json
import time

_hit_count = [0]
_result_file = {result_file!r}
_max_hits = {max_hits}

class _DwtHaltWatchpoint(gdb.Breakpoint):
    def __init__(self):
        super().__init__({var_name!r}, gdb.BP_WATCHPOINT,
                         wp_class=gdb.WP_{gdb_cmd.upper()}, internal=False)
        self.silent = False

    def stop(self):
        if _hit_count[0] >= _max_hits:
            return False
{cond_check}
        ts_us = int(time.time() * 1_000_000)
        try:
            val = gdb.parse_and_eval({var_name!r})
            value_str = str(val)
        except Exception as _ve:
            value_str = str(_ve)

        hit_data = {{
            'ts': ts_us,
            'label': {var_name!r},
            'value': value_str,
            'hit': _hit_count[0] + 1,
        }}
{bt_code}
        with open(_result_file, 'a') as _fh:
            _fh.write(json.dumps(hit_data) + '\\n')

        _hit_count[0] += 1
        if _hit_count[0] >= _max_hits:
            gdb.post_event(lambda: gdb.execute('quit 0'))
        return False  # do not halt target

_DwtHaltWatchpoint()
"""
    return script


def cmd_dwt_halt(
    *,
    symbol: str,
    device: Optional[str] = None,
    elf: Optional[str] = None,
    chip: str = "nrf5340",
    mode: str = "write",
    condition: Optional[str] = None,
    max_hits: int = 100,
    backtrace: bool = True,
    probe_type: str = "jlink",
    probe_selector: Optional[str] = None,
    port: Optional[int] = None,
    json_mode: bool = False,
) -> int:
    """Halting watchpoint via GDB with optional condition filter.

    Generates a GDB Python script, runs it via run_gdb_batch(), and
    streams collected hit events as JSONL to stdout.

    Args:
        symbol:         Variable name to watch (must be in ELF debug symbols).
        device:         J-Link device string.
        elf:            ELF file for debug symbols (required for GDB).
        chip:           Chip type for GDB server selection.
        mode:           "read", "write", or "rw".
        condition:      Python expression evaluated at each hit.
        max_hits:       Maximum hits to record (default: 100).
        backtrace:      Capture backtrace at each hit.
        probe_type:     "jlink" or "openocd".
        probe_selector: Probe serial number.
        port:           GDB server port override.
        json_mode:      JSON output mode.

    Returns:
        0 on success, non-zero on error.
    """
    try:
        from eab.gdb_bridge import run_gdb_batch
    except ImportError:
        _emit_error("gdb_bridge module not available.", json_mode)
        return 1

    result_path = tempfile.mktemp(prefix="eab-dwt-halt-", suffix=".jsonl")

    script = generate_dwt_halt_watchpoint(
        var_name=symbol,
        mode=mode,
        condition=condition,
        max_hits=max_hits,
        backtrace=backtrace,
        result_file=result_path,
    )

    script_path = tempfile.mktemp(prefix="eab-dwt-", suffix=".py")
    with open(script_path, "w") as fh:
        fh.write(script)

    try:
        run_gdb_batch(
            script_path=script_path,
            device=device,
            elf=elf,
            chip=chip,
            probe_type=probe_type,
            probe_selector=probe_selector,
            port=port,
        )
    except Exception as exc:
        _emit_error(f"GDB execution failed: {exc}", json_mode)
        return 1

    # Stream results
    try:
        with open(result_path) as fh:
            for line in fh:
                print(line, end="", flush=True)
    except FileNotFoundError:
        pass  # No hits recorded

    return 0


def _emit_error(message: str, json_mode: bool) -> None:
    if json_mode:
        print(json.dumps({"error": message}), file=sys.stderr, flush=True)
    else:
        print(f"Error: {message}", file=sys.stderr, flush=True)
