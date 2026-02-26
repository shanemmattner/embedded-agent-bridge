"""Thread stack inspection via GDB Python scripting against a live Zephyr target."""

from __future__ import annotations

import tempfile
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Optional

from eab.gdb_bridge import GDBResult, run_gdb_python  # noqa: F401 (re-exported for mocking)

# ---------------------------------------------------------------------------
# Zephyr thread state bit masks (from zephyr/kernel/include/kernel_structs.h)
# ---------------------------------------------------------------------------

_THREAD_RUNNING: int = 0x01
_THREAD_PENDING: int = 0x04
_THREAD_SUSPENDED: int = 0x08


def _map_thread_state(flags: int) -> str:
    """Map Zephyr thread state flags to a human-readable state string.

    Args:
        flags: Raw ``thread_state`` integer from the Zephyr kernel struct.

    Returns:
        One of ``"RUNNING"``, ``"PENDING"``, ``"SUSPENDED"``, or ``"READY"``.
    """
    if flags & _THREAD_RUNNING:
        return "RUNNING"
    if flags & _THREAD_PENDING:
        return "PENDING"
    if flags & _THREAD_SUSPENDED:
        return "SUSPENDED"
    return "READY"


@dataclass(frozen=True)
class ThreadInfo:
    """Information about a single Zephyr RTOS thread."""

    name: str
    state: str = "READY"
    priority: int = 0
    stack_base: int = 0
    stack_size: int = 0
    stack_used: int = 0
    stack_free: int = 0

    def to_dict(self) -> dict[str, Any]:
        """Return a JSON-serialisable dict representation.

        Returns:
            Dict with keys: name, state, priority, stack_base,
            stack_size, stack_used, stack_free.
        """
        return {
            "name": self.name,
            "state": self.state,
            "priority": self.priority,
            "stack_base": self.stack_base,
            "stack_size": self.stack_size,
            "stack_used": self.stack_used,
            "stack_free": self.stack_free,
        }


def _generate_thread_script() -> str:
    """Return a GDB Python script that inspects Zephyr threads.

    The script reads the Zephyr kernel thread list via the ``_kernel`` global,
    collects per-thread state and stack information, and writes the result as
    JSON to the file path stored in the GDB convenience variable
    ``$result_file``.

    Returns:
        Multi-line string containing the GDB Python script.
    """
    return r"""
import gdb
import json

result_file = str(gdb.convenience_variable("result_file")).strip('"')

def _read_str(val):
    try:
        return val.string()
    except Exception:
        return str(val)

threads = []
max_threads = 256
count = 0

try:
    kernel = gdb.parse_and_eval("_kernel")
    t_ptr = kernel["threads"]

    while t_ptr and count < max_threads:
        t = t_ptr.dereference()

        # Thread name
        try:
            name = _read_str(t["name"])
        except Exception:
            name = "<unknown>"

        # Thread state flags
        try:
            thread_state = int(t["base"]["thread_state"])
        except Exception:
            thread_state = 0

        # Priority
        try:
            prio = int(t["base"]["prio"])
        except Exception:
            prio = 0

        # Stack info
        try:
            stack_info = t["stack_info"]
            stack_start = int(stack_info["start"])
            stack_size = int(stack_info["size"])
            stack_delta = int(stack_info["delta"])
        except Exception:
            stack_start = 0
            stack_size = 0
            stack_delta = 0

        threads.append({
            "name": name,
            "thread_state": thread_state,
            "prio": prio,
            "stack_start": stack_start,
            "stack_size": stack_size,
            "stack_delta": stack_delta,
        })

        t_ptr = t["base"]["next_thread"]
        count += 1

    result = {"status": "ok", "threads": threads}
except Exception as exc:
    result = {"status": "error", "error": str(exc)}

with open(result_file, "w") as f:
    json.dump(result, f)
"""


def inspect_threads(
    target: str,
    elf: str,
    *,
    chip: str = "",
    gdb_path: Optional[str] = None,
) -> list[ThreadInfo]:
    """Inspect Zephyr RTOS thread stack usage via GDB Python scripting.

    Connects to a running GDB server (e.g., OpenOCD or J-Link GDB server)
    at *target*, executes a built-in Python script inside GDB that walks the
    Zephyr kernel thread list, and returns structured :class:`ThreadInfo`
    objects.

    Args:
        target: GDB remote target string, e.g. ``"localhost:3333"``.
        elf: Path to the ELF file containing DWARF debug symbols.
        chip: Chip identifier used to select the correct GDB binary
            (e.g. ``"nrf5340"``).  Leave empty to use the system default.
        gdb_path: Explicit path to the GDB executable.  Auto-detected from
            *chip* if ``None``.

    Returns:
        A list of :class:`ThreadInfo` objects, one per thread reported by
        the GDB script.

    Raises:
        RuntimeError: If the GDB script reports an error status or returns
            no JSON result.
        Any exception raised by :func:`eab.gdb_bridge.run_gdb_python` is
        propagated without wrapping.
    """
    script_body = _generate_thread_script()

    with tempfile.NamedTemporaryFile(mode="w", suffix=".py", delete=False, prefix="eab_thread_") as tmp:
        tmp.write(script_body)
        script_path = tmp.name

    gdb_result: GDBResult = run_gdb_python(
        chip=chip,
        script_path=script_path,
        target=target,
        elf=elf,
        gdb_path=gdb_path,
    )

    Path(script_path).unlink(missing_ok=True)

    if gdb_result.json_result is None:
        raise RuntimeError("inspect_threads: no JSON result from GDB script")

    data = gdb_result.json_result
    if data.get("status") == "error":
        raise RuntimeError(data.get("error", "GDB script reported an error"))

    result: list[ThreadInfo] = []
    for raw in data.get("threads", []):
        stack_size = int(raw.get("stack_size", 0))
        stack_used = int(raw.get("stack_delta", 0))
        stack_free = stack_size - stack_used
        result.append(
            ThreadInfo(
                name=str(raw.get("name", "")),
                state=_map_thread_state(int(raw.get("thread_state", 0))),
                priority=int(raw.get("prio", 0)),
                stack_base=int(raw.get("stack_start", 0)),
                stack_size=stack_size,
                stack_used=stack_used,
                stack_free=stack_free,
            )
        )
    return result
