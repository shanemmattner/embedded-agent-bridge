"""Thread stack inspection via eabctl threads --json."""

from __future__ import annotations

import json
import subprocess
from dataclasses import dataclass
from typing import Any


@dataclass
class ThreadInfo:
    """Information about a single RTOS thread."""

    name: str = ""
    stack_free: int = 0

    @classmethod
    def from_dict(cls, data: dict[str, Any]) -> "ThreadInfo":
        return cls(
            name=data.get("name", ""),
            stack_free=int(data.get("stack_free", 0)),
        )


def inspect_threads(device: str, elf: str) -> list[ThreadInfo]:
    """Inspect RTOS thread stack usage via eabctl.

    Args:
        device: Device identifier passed to ``eabctl --device``.
        elf: Path to the ELF file for symbol resolution.

    Returns:
        A list of :class:`ThreadInfo` objects, one per thread reported
        by ``eabctl threads``.

    Raises:
        RuntimeError: If ``eabctl threads`` returns a non-zero exit code
            or cannot be executed.
    """
    cmd = ["eabctl", "--device", device, "threads", "--elf", elf, "--json"]
    try:
        result = subprocess.run(
            cmd, capture_output=True, text=True, timeout=60,
        )
    except subprocess.TimeoutExpired:
        raise RuntimeError("eabctl threads timed out")
    except FileNotFoundError:
        raise RuntimeError("eabctl not found")

    if result.returncode != 0:
        detail = result.stderr.strip() or result.stdout.strip()
        raise RuntimeError(f"eabctl threads failed: {detail}")

    try:
        output: dict[str, Any] = json.loads(result.stdout)
    except (json.JSONDecodeError, ValueError) as exc:
        raise RuntimeError(f"Failed to parse eabctl threads output: {exc}") from exc

    threads_raw = output.get("threads", [])
    return [ThreadInfo.from_dict(t) for t in threads_raw]
