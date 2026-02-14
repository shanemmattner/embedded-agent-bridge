"""Internal helpers for daemon commands."""

from __future__ import annotations

import os


def _clear_session_files(base_dir: str) -> None:
    """Remove or reset session files in the base directory.

    Cleans up status.json, alerts.log, and events.jsonl files,
    handling missing files gracefully.

    Args:
        base_dir: Session directory containing state files.
    """
    files_to_clear = ["status.json", "alerts.log", "events.jsonl"]
    for filename in files_to_clear:
        filepath = os.path.join(base_dir, filename)
        try:
            os.remove(filepath)
        except FileNotFoundError:
            pass
