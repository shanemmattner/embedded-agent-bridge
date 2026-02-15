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
    eab_root = Path(__file__).parent.parent.parent.parent

    if source == "rtt":
        cmd = _build_rtt_cmd(eab_root, device, channel, output_path)
    else:
        cmd = _build_tail_cmd(eab_root, log_path_str, output_path)

    proc = subprocess.Popen(
        cmd,
        stdout=subprocess.DEVNULL,
        stderr=subprocess.PIPE,
        start_new_session=True,  # detach from terminal
    )

    # Give the subprocess a moment to start (or fail immediately)
    time.sleep(1.5)
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
    """Return True if a trace subprocess is already alive."""
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

    Returns None for RTT mode (no log file needed).
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
        return str(Path(logfile).resolve())

    return None  # RTT mode


def _emit(data: dict, json_mode: bool, *, error: bool = False) -> None:
    """Print a result dict as JSON or human-readable text."""
    if json_mode:
        print(json.dumps(data))
    else:
        if error and "error" in data:
            print(f"Error: {data['error']}")
        else:
            for k, v in data.items():
                print(f"{k}: {v}")


def _build_rtt_cmd(
    eab_root: Path, device: str, channel: int, output_path: Path
) -> list[str]:
    """Build the subprocess argv for RTT capture via J-Link.

    Uses RTTBinaryCapture which handles J-Link connect, RTT attach,
    binary framing, and clean shutdown on SIGTERM.
    """
    return [
        sys.executable,
        "-c",
        f"""
import sys, signal, time
sys.path.insert(0, {str(eab_root)!r})

from eab.rtt_transport import JLinkTransport
from eab.rtt_binary import RTTBinaryCapture

def _log(msg):
    try:
        print(msg, file=sys.stderr, flush=True)
    except OSError:
        pass

transport = JLinkTransport()
capture = RTTBinaryCapture(
    transport=transport,
    device={device!r},
    channels=[{channel}],
    output_path={str(output_path)!r},
    sample_width=1,
    timestamp_hz=1000,
)

capture.start()
_log(f'Capturing RTT channel {channel} to {str(output_path)!r}')

def handle_stop(signum, frame):
    result = capture.stop()
    _log(f'Stopped: {{result}}')
    sys.exit(0)

signal.signal(signal.SIGTERM, handle_stop)
signal.signal(signal.SIGINT, handle_stop)

try:
    while True:
        time.sleep(1)
except (KeyboardInterrupt, SystemExit):
    pass
""",
    ]


def _build_tail_cmd(
    eab_root: Path, log_path: str, output_path: Path
) -> list[str]:
    """Build the subprocess argv for tailing a text log into .rttbin.

    Seeks to end-of-file and captures only *new* lines.  Each line
    becomes one .rttbin frame on channel 0 with a millisecond wall-clock
    timestamp.  Handles SIGTERM for clean shutdown and log rotation
    (file truncation) gracefully.
    """
    return [
        sys.executable,
        "-c",
        f"""
import sys, signal, time, os
sys.path.insert(0, {str(eab_root)!r})

from eab.rtt_binary import BinaryWriter

log_path = {log_path!r}
output_path = {str(output_path)!r}

def _log(msg):
    '''Write to stderr, swallowing BrokenPipeError.
    The parent process exits after the 1.5s startup check, closing
    the read end of our stderr pipe.  Any later write would raise.'''
    try:
        print(msg, file=sys.stderr, flush=True)
    except OSError:
        pass

if not os.path.exists(log_path):
    _log(f'Error: log file not found: {{log_path}}')
    sys.exit(1)

writer = BinaryWriter(
    output_path,
    channels=[0],
    sample_width=1,
    timestamp_hz=1000,
)

start_ms = int(time.time() * 1000)
frame_count = 0
_log(f'Tailing {{log_path}} -> {{output_path}}')

running = True

def handle_stop(signum, frame):
    global running
    running = False

signal.signal(signal.SIGTERM, handle_stop)
signal.signal(signal.SIGINT, handle_stop)

try:
    f = open(log_path, 'r')
    # Seek to end so we only capture new output
    f.seek(0, 2)
    last_inode = os.stat(log_path).st_ino

    while running:
        # Handle log rotation: detect truncation or new inode
        try:
            st = os.stat(log_path)
        except OSError:
            time.sleep(0.1)
            continue

        if st.st_ino != last_inode or st.st_size < f.tell():
            # File was replaced or truncated — reopen
            _log('Log rotated, reopening')
            f.close()
            f = open(log_path, 'r')
            last_inode = st.st_ino

        line = f.readline()
        if line:
            tick = int(time.time() * 1000) - start_ms
            writer.write_frame(
                channel=0,
                payload=line.encode('utf-8', errors='replace'),
                timestamp=tick,
            )
            frame_count += 1
            # Flush every 100 frames to balance I/O and data safety
            if frame_count % 100 == 0:
                writer.flush()
        else:
            writer.flush()
            time.sleep(0.05)
except (KeyboardInterrupt, SystemExit):
    pass
finally:
    f.close()
    writer.close()
    _log(f'Stopped: {{frame_count}} frames written to {{output_path}}')
""",
    ]
