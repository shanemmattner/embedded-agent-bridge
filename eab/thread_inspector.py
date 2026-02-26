"""Zephyr RTOS thread inspection via GDB Python scripting.

Walks the ``_kernel.threads`` linked list on a live target to extract
thread state, priority, name, and stack usage. Results are returned as
``ThreadInfo`` dataclass instances.

Architecture:
    _generate_thread_script() → GDB Python script string
    inspect_threads(device, elf_path) → list[ThreadInfo]
        uses run_gdb_python() from eab.gdb_bridge for one-shot execution
"""

from __future__ import annotations

import logging
import tempfile
from dataclasses import dataclass
from pathlib import Path
from typing import Any

from eab.gdb_bridge import run_gdb_python

logger = logging.getLogger(__name__)


# =============================================================================
# Constants — Zephyr thread_state bitmask values
# =============================================================================

# Zephyr kernel/include/kernel_structs.h (common values, may vary by version).
# Bits are checked in priority order: RUNNING overrides everything else.
# UNCERTAIN: exact bit values depend on Zephyr version; documented here for
# visibility and tested via mocked integers covering each branch.
_THREAD_RUNNING = 1 << 0    # 0x01 – thread is currently executing
_THREAD_QUEUED = 1 << 1     # 0x02 – thread is in the ready queue
_THREAD_PENDING = 1 << 2    # 0x04 – thread is waiting on an object
_THREAD_SUSPENDED = 1 << 3  # 0x08 – thread has been suspended


# =============================================================================
# Data Classes
# =============================================================================


@dataclass(frozen=True)
class ThreadInfo:
    """Information about a single Zephyr RTOS thread.

    Attributes:
        name: Thread name string (empty if CONFIG_THREAD_NAME not set).
        state: Human-readable state: RUNNING, READY, PENDING, or SUSPENDED.
        priority: Cooperative/preemptive priority value (lower = higher priority).
        stack_base: Address of the stack buffer start.
        stack_size: Total stack size in bytes.
        stack_used: High-water mark of stack bytes used (from canary check).
        stack_free: Remaining stack bytes (stack_size - stack_used).
    """

    name: str
    state: str
    priority: int
    stack_base: int
    stack_size: int
    stack_used: int
    stack_free: int

    def to_dict(self) -> dict[str, Any]:
        """Return a plain dict suitable for JSON serialization.

        Returns:
            Dict mapping each field name to its value.
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


# =============================================================================
# Private Helpers
# =============================================================================


def _map_thread_state(raw: int) -> str:
    """Map a raw Zephyr thread_state bitmask to a human-readable label.

    Checks bits in priority order so that the most specific label wins.

    Args:
        raw: Integer value of the ``base.thread_state`` field.

    Returns:
        One of: ``"RUNNING"``, ``"READY"``, ``"PENDING"``, ``"SUSPENDED"``.
    """
    if raw & _THREAD_RUNNING:
        return "RUNNING"
    if raw & _THREAD_PENDING:
        return "PENDING"
    if raw & _THREAD_SUSPENDED:
        return "SUSPENDED"
    # No special bits set → thread is in the ready queue (or newly created)
    return "READY"


def _generate_thread_script() -> str:
    """Return a GDB Python script string that walks Zephyr's thread list.

    The script reads ``$result_file`` from a GDB convenience variable and
    writes a JSON document to that path containing a ``"threads"`` array.
    Each element has keys: ``name``, ``thread_state``, ``prio``,
    ``stack_start``, ``stack_size``, ``stack_delta``.

    Returns:
        Complete GDB Python script as a string.
    """
    return r'''#!/usr/bin/env python3
"""Generated GDB Python script: inspect Zephyr thread list."""

import gdb
import json

result_file = str(gdb.convenience_variable("result_file")).strip('"')
result = {"status": "ok", "threads": []}

try:
    kernel = gdb.parse_and_eval("_kernel")

    # _kernel.threads is a sys_dlist_t; threads link via base.qnode_dlist.
    # The head node itself is not a thread — stop when we come back around.
    threads_head = kernel["threads"]
    head_addr = int(threads_head.address)

    current = threads_head["next"]
    thread_count = 0
    max_threads = 100  # Safety limit

    thread_type_ptr = gdb.lookup_type("struct k_thread").pointer()

    while int(current) != head_addr and thread_count < max_threads:
        try:
            # container_of: qnode_dlist is the first field of _thread_base,
            # which is the first field of k_thread — so the node pointer IS
            # the thread pointer for standard Zephyr layouts.
            node_addr = int(current)
            t = gdb.Value(node_addr).cast(thread_type_ptr).dereference()

            # Thread name (requires CONFIG_THREAD_NAME)
            try:
                raw_name = t["name"]
                name = raw_name.string() if raw_name else ""
            except (gdb.error, ValueError):
                name = ""

            thread_state = int(t["base"]["thread_state"])
            prio = int(t["base"]["prio"])
            stack_start = int(t["stack_info"]["start"])
            stack_size = int(t["stack_info"]["size"])
            stack_delta = int(t["stack_info"]["delta"])

            result["threads"].append({
                "name": name,
                "thread_state": thread_state,
                "prio": prio,
                "stack_start": stack_start,
                "stack_size": stack_size,
                "stack_delta": stack_delta,
            })

        except (gdb.error, ValueError) as e:
            result["threads"].append({
                "name": "",
                "error": str(e),
                "thread_state": 0,
                "prio": 0,
                "stack_start": 0,
                "stack_size": 0,
                "stack_delta": 0,
            })

        try:
            current = current["next"]
        except gdb.error:
            break
        thread_count += 1

    if thread_count >= max_threads:
        result["warning"] = f"Stopped after {max_threads} threads (safety limit)"

except gdb.error as e:
    result["status"] = "error"
    result["error"] = str(e)

with open(result_file, "w") as f:
    json.dump(result, f, indent=2)
'''


# =============================================================================
# Public API
# =============================================================================


def inspect_threads(device: str, elf_path: str) -> list[ThreadInfo]:
    """Inspect Zephyr RTOS threads on a live target via GDB.

    Generates a GDB Python script that walks ``_kernel.threads``, executes
    it against the target using the GDB one-shot bridge, and parses the
    resulting JSON into ``ThreadInfo`` objects.

    Args:
        device: GDB remote target string (e.g., ``"localhost:3333"``).
        elf_path: Path to the ELF file with DWARF debug symbols.

    Returns:
        List of ``ThreadInfo`` objects, one per thread found.

    Raises:
        RuntimeError: If GDB reports an error or returns no JSON result.
    """
    script = _generate_thread_script()

    tmp_path: str | None = None
    try:
        with tempfile.NamedTemporaryFile(
            mode="w", suffix=".py", delete=False
        ) as tmp:
            tmp.write(script)
            tmp_path = tmp.name

        logger.debug(
            "Running thread inspector GDB script against %s (elf=%s)",
            device,
            elf_path,
        )

        gdb_result = run_gdb_python(
            chip="",
            script_path=tmp_path,
            target=device,
            elf=elf_path,
        )
    finally:
        if tmp_path is not None:
            Path(tmp_path).unlink(missing_ok=True)

    if gdb_result.json_result is None:
        raise RuntimeError(
            f"GDB script produced no JSON result. "
            f"stderr: {gdb_result.stderr!r}"
        )

    json_data = gdb_result.json_result
    if json_data.get("status") == "error":
        raise RuntimeError(
            f"GDB thread inspection failed: {json_data.get('error', 'unknown error')}"
        )

    threads: list[ThreadInfo] = []
    for entry in json_data.get("threads", []):
        stack_size = entry["stack_size"]
        stack_used = entry["stack_delta"]
        stack_free = stack_size - stack_used

        threads.append(
            ThreadInfo(
                name=entry.get("name", ""),
                state=_map_thread_state(entry["thread_state"]),
                priority=entry["prio"],
                stack_base=entry["stack_start"],
                stack_size=stack_size,
                stack_used=stack_used,
                stack_free=stack_free,
            )
        )

    logger.info("Inspected %d threads on %s", len(threads), device)
    return threads
