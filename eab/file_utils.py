"""Shared file I/O utilities for EAB.

Extracted from duplicated patterns in jlink_bridge, openocd_bridge, and others.
"""

from __future__ import annotations

import json
import os
import tempfile
from pathlib import Path
from typing import Optional, Union


def read_json_file(path: Union[str, Path]) -> Optional[dict]:
    """Read a JSON file and return its contents as a dict.

    Returns ``None`` if the file is missing, unreadable, or not valid JSON.
    """
    p = Path(path)
    if not p.exists():
        return None
    try:
        return json.loads(p.read_text(encoding="utf-8"))
    except (json.JSONDecodeError, OSError):
        return None


def write_json_file(path: Union[str, Path], data: dict) -> None:
    """Atomically write *data* as JSON to *path*.

    Writes to a temporary file in the same directory and renames, so
    readers never see a half-written file.
    """
    p = Path(path)
    p.parent.mkdir(parents=True, exist_ok=True)
    fd, tmp = tempfile.mkstemp(dir=str(p.parent), suffix=".tmp")
    try:
        with os.fdopen(fd, "w", encoding="utf-8") as f:
            json.dump(data, f, indent=2, sort_keys=True)
        os.replace(tmp, str(p))
    except BaseException:
        try:
            os.unlink(tmp)
        except OSError:
            pass
        raise


def read_text_safe(path: Union[str, Path]) -> str:
    """Read text from *path*, returning an empty string on any error."""
    try:
        return Path(path).read_text(encoding="utf-8", errors="replace")
    except OSError:
        return ""


def tail_file(path: Union[str, Path], n: int = 20) -> list[str]:
    """Return the last *n* lines from *path*.

    Returns an empty list if the file is missing or unreadable.
    """
    text = read_text_safe(path)
    if not text:
        return []
    return text.splitlines()[-n:]
