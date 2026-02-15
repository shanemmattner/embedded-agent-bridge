"""Start trace capture to binary file.

Supports three capture sources:
  - rtt:     J-Link RTT binary capture (requires J-Link probe + pylink)
  - serial:  Tail the EAB daemon's latest.log for a device
  - logfile: Tail any arbitrary text file (useful for replaying old logs)

All sources write the same .rttbin format, so ``trace export`` works
regardless of how the data was captured.
"""

from __future__ import annotations

import json
import logging
import os
import subprocess
import sys
import time
from pathlib import Path

logger = logging.getLogger(__name__)

# Default location for EAB daemon device directories
_EAB_DEVICES_DIR = Path("/tmp/eab-devices")

# How long to wait for the capture subprocess to start before checking
# if it exited with an error.  1.5s is empirically sufficient for J-Link
# initialization (the slowest source).
_STARTUP_WAIT_S = 1.5


def cmd_trace_start(
    *,
    output: str,
    source: str = "rtt",
    device: str = "NRF5340_XXAA_APP",
    channel: int = 0,
    trace_dir: str | None = None,
    logfile: str | None = None,
    json_mode: bool = False,
) -> int:
    """Start trace capture from RTT, serial daemon log, or arbitrary logfile.

    The capture runs as a detached subprocess.  Its PID is written to
    ``/tmp/eab-trace.pid`` so that ``trace stop`` can find and SIGTERM it.

    Args:
        output: Path to output .rttbin file.
        source: Capture source — ``"rtt"``, ``"serial"``, or ``"logfile"``.
        device: J-Link device name, used by RTT mode and as a fallback to
            derive the daemon directory in serial mode.
        channel: RTT channel to capture (RTT mode only, default 0).
        trace_dir: Explicit device base directory for serial mode.  When
            omitted, derived from *device* →
            ``/tmp/eab-devices/{chip_name}/``.
        logfile: Path to a text file for logfile mode.
        json_mode: Emit machine-parseable JSON output.

    Returns:
        0 on success, 1 on failure.
    """
    output_path = Path(output).resolve()
    pid_file = Path("/tmp/eab-trace.pid")

    # ── Guard: only one trace capture at a time ──────────────────────
    if _is_trace_running(pid_file):
        existing_pid = int(pid_file.read_text().strip())
        _emit(
            {"error": "Trace capture already running", "pid": existing_pid},
            json_mode,
            error=True,
        )
        return 1

    # ── Validate source-specific args ────────────────────────────────
    if source == "logfile" and not logfile:
        _emit(
            {"error": "--logfile is required when --source logfile"},
            json_mode,
            error=True,
        )
        return 1

    # ── Resolve the log path for serial / logfile modes ──────────────
    log_path_str = _resolve_log_path(source, trace_dir, logfile, device)

    # For serial/logfile, verify the target file exists *before* forking
    if log_path_str is not None and not Path(log_path_str).exists():
        _emit(
            {"error": f"Log file not found: {log_path_str}"},
            json_mode,
            error=True,
        )
        return 1

    # ── Build and launch the capture subprocess ──────────────────────
    eab_root = str(Path(__file__).parent.parent.parent.parent)

    if source == "rtt":
        cmd = [sys.executable, "-m", "eab.cli.trace._rtt_worker",
               device, str(channel), str(output_path), eab_root]
    else:
        assert log_path_str is not None
        cmd = [sys.executable, "-m", "eab.cli.trace._tail_worker",
               log_path_str, str(output_path), eab_root]

    proc = subprocess.Popen(
        cmd,
        stdout=subprocess.DEVNULL,
        stderr=subprocess.PIPE,
        start_new_session=True,  # detach from terminal
    )

    # Give the subprocess a moment to start (or fail immediately).
    time.sleep(_STARTUP_WAIT_S)
    if proc.poll() is not None:
        stderr = proc.stderr.read().decode() if proc.stderr else ""
        _emit(
            {"error": "Trace capture failed to start", "stderr": stderr},
            json_mode,
            error=True,
        )
        return 1

    # ── Record PID for ``trace stop`` ────────────────────────────────
    pid_file.write_text(str(proc.pid))

    # ── Report success ───────────────────────────────────────────────
    result: dict = {
        "started": True,
        "pid": proc.pid,
        "output": str(output_path),
        "source": source,
    }
    if source == "rtt":
        result["device"] = device
        result["channel"] = channel
    else:
        result["log_path"] = log_path_str

    if json_mode:
        print(json.dumps(result))
    else:
        print(f"Trace capture started (PID {proc.pid})")
        print(f"Source: {source}")
        print(f"Output: {output_path}")
        if source != "rtt":
            print(f"Tailing: {log_path_str}")
        print("Stop with: eabctl trace stop")

    return 0


# ── Helpers ──────────────────────────────────────────────────────────────


def _is_trace_running(pid_file: Path) -> bool:
    """Return True if a trace subprocess is already alive.

    Args:
        pid_file: Path to the PID file (``/tmp/eab-trace.pid``).

    Returns:
        True if a process with the recorded PID exists.
    """
    if not pid_file.exists():
        return False
    try:
        existing_pid = int(pid_file.read_text().strip())
        os.kill(existing_pid, 0)  # signal 0 = existence check
        return True
    except (OSError, ValueError):
        # Stale PID file — clean it up
        pid_file.unlink(missing_ok=True)
        return False


def _resolve_log_path(
    source: str,
    trace_dir: str | None,
    logfile: str | None,
    device: str,
) -> str | None:
    """Resolve the path to the text file we'll tail.

    Args:
        source: Capture source (``"rtt"``, ``"serial"``, ``"logfile"``).
        trace_dir: Explicit device directory, or None to auto-derive.
        logfile: Explicit log file path (logfile mode only).
        device: J-Link device string used to derive the device directory
            when *trace_dir* is not provided.

    Returns:
        Resolved absolute path to the log file, or None for RTT mode.
    """
    if source == "serial":
        if trace_dir:
            log_path = Path(trace_dir) / "latest.log"
        else:
            # Derive device dir from the J-Link device string.
            # NRF5340_XXAA_APP → nrf5340, MCXN947 → mcxn947
            dev_name = device.lower().split("_")[0]
            log_path = _EAB_DEVICES_DIR / dev_name / "latest.log"
        return str(log_path.resolve())

    if source == "logfile":
        assert logfile is not None  # validated by caller
        return str(Path(logfile).resolve())

    return None  # RTT mode


def _emit(data: dict, json_mode: bool, *, error: bool = False) -> None:
    """Print a result dict as JSON or human-readable text.

    Args:
        data: Key-value pairs to output.
        json_mode: If True, print as a single JSON line.
        error: If True and *data* contains an ``"error"`` key, prefix
            the human-readable output with ``"Error: "``.
    """
    if json_mode:
        print(json.dumps(data))
    else:
        if error and "error" in data:
            print(f"Error: {data['error']}")
        else:
            for k, v in data.items():
                print(f"{k}: {v}")
