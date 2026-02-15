"""Stop active trace capture (works for all sources: RTT, serial, logfile)."""

from __future__ import annotations

import json
import logging
import os
import signal
from pathlib import Path

logger = logging.getLogger(__name__)


def cmd_trace_stop(*, json_mode: bool = False) -> int:
    """Stop active trace capture (any source).

    Args:
        json_mode: Emit JSON output

    Returns:
        Exit code: 0 on success, 1 if no trace running
    """
    pid_file = Path("/tmp/eab-trace.pid")

    if not pid_file.exists():
        result = {"error": "No trace capture running"}
        if json_mode:
            print(json.dumps(result))
        else:
            print("Error: No trace capture running")
        return 1

    try:
        pid = int(pid_file.read_text().strip())
    except ValueError:
        result = {"error": "Invalid PID file"}
        if json_mode:
            print(json.dumps(result))
        else:
            print("Error: Invalid PID file")
        pid_file.unlink()
        return 1

    # Try to stop the process
    try:
        os.kill(pid, signal.SIGTERM)
        pid_file.unlink()

        result = {
            "stopped": True,
            "pid": pid,
        }

        if json_mode:
            print(json.dumps(result))
        else:
            print(f"Trace capture stopped (PID {pid})")

        return 0

    except ProcessLookupError:
        # Process already dead
        pid_file.unlink()
        result = {"stopped": True, "pid": pid, "note": "Process already terminated"}

        if json_mode:
            print(json.dumps(result))
        else:
            print(f"Process {pid} already terminated")

        return 0

    except PermissionError:
        result = {"error": f"Permission denied to stop PID {pid}"}
        if json_mode:
            print(json.dumps(result))
        else:
            print(f"Error: Permission denied to stop PID {pid}")
        return 1
