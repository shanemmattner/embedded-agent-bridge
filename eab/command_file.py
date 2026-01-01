"""
Utilities for safely writing/reading the daemon command file.

The daemon watches a text file (typically `cmd.txt`) for commands to send to the
device. Historically this file was overwritten, which could lose commands and
race with the daemon reading at the same time.

This module provides a simple, line-based FIFO protocol using `fcntl.flock`
when available:
- Writers append one command per line under an exclusive lock.
- The daemon drains the file under an exclusive lock and truncates it.

This is intentionally minimal (single-writer friendly) and avoids introducing
additional state files unless needed.
"""

from __future__ import annotations

import os
from typing import IO, List, Optional

try:  # Unix only
    import fcntl  # type: ignore
except Exception:  # pragma: no cover
    fcntl = None  # type: ignore[assignment]


def _lock_ex(file: IO[str]) -> None:
    if fcntl is None:  # pragma: no cover
        return
    fcntl.flock(file.fileno(), fcntl.LOCK_EX)


def _unlock(file: IO[str]) -> None:
    if fcntl is None:  # pragma: no cover
        return
    fcntl.flock(file.fileno(), fcntl.LOCK_UN)


def append_command(cmd_path: str, command: str) -> None:
    """
    Append a single command to the command file, one command per line.

    This is safe against daemon reads when both sides use this module.
    """
    normalized = command.rstrip("\n")
    if not normalized:
        return

    parent = os.path.dirname(cmd_path)
    if parent:
        os.makedirs(parent, exist_ok=True)

    f: Optional[IO[str]] = None
    try:
        f = open(cmd_path, "a", encoding="utf-8")
        _lock_ex(f)
        f.write(normalized + "\n")
        f.flush()
        os.fsync(f.fileno())
    finally:
        if f is not None:
            try:
                _unlock(f)
            except Exception:
                pass
            f.close()


def drain_commands(cmd_path: str) -> List[str]:
    """
    Drain all queued commands from the command file.

    Returns a list of commands (strings) in the order they were written.
    The file is truncated to empty under lock before returning.
    """
    if not os.path.exists(cmd_path):
        return []

    f: Optional[IO[str]] = None
    try:
        f = open(cmd_path, "r+", encoding="utf-8")
        _lock_ex(f)
        content = f.read()
        f.seek(0)
        f.truncate(0)
        f.flush()
        os.fsync(f.fileno())
    finally:
        if f is not None:
            try:
                _unlock(f)
            except Exception:
                pass
            f.close()

    commands: List[str] = []
    for line in content.splitlines():
        cmd = line.strip()
        if cmd:
            commands.append(cmd)
    return commands

