"""Log-tail capture worker — launched as a subprocess by cmd_start.py.

Tails a text log file (e.g. an EAB daemon's ``latest.log``) and writes
each new line as a ``.rttbin`` frame with a millisecond wall-clock
timestamp.  Handles log rotation (file truncation / inode change)
gracefully.  Runs until SIGTERM or SIGINT.

Usage (by cmd_start.py):
    python -m eab.cli.trace._tail_worker <log_path> <output_path> <eab_root>
"""

from __future__ import annotations

import os
import signal
import sys
import time

# Flush to the .rttbin file every N frames to balance I/O and data safety.
_FLUSH_INTERVAL = 100


def _log(msg: str) -> None:
    """Write to stderr, swallowing BrokenPipeError.

    The parent process exits after the 1.5s startup check, closing
    the read end of our stderr pipe.  Any later write would raise.
    """
    try:
        print(msg, file=sys.stderr, flush=True)
    except OSError:
        pass


def main() -> None:
    """Entry point for the log-tail capture subprocess."""
    log_path = sys.argv[1]
    output_path = sys.argv[2]
    eab_root = sys.argv[3]

    sys.path.insert(0, eab_root)

    from eab.rtt_binary import BinaryWriter

    if not os.path.exists(log_path):
        _log(f"Error: log file not found: {log_path}")
        sys.exit(1)

    writer = BinaryWriter(
        output_path,
        channels=[0],
        sample_width=1,
        timestamp_hz=1000,
    )

    start_ms = int(time.time() * 1000)
    frame_count = 0
    _log(f"Tailing {log_path} -> {output_path}")

    running = True

    def handle_stop(signum: int, frame: object) -> None:
        nonlocal running
        running = False

    signal.signal(signal.SIGTERM, handle_stop)
    signal.signal(signal.SIGINT, handle_stop)

    try:
        f = open(log_path, "r")
        # Seek to end so we only capture new output
        f.seek(0, 2)
        last_inode = os.stat(log_path).st_ino

        while running:
            # Detect log rotation: file truncated or replaced with new inode
            try:
                st = os.stat(log_path)
            except OSError:
                time.sleep(0.1)
                continue

            if st.st_ino != last_inode or st.st_size < f.tell():
                _log("Log rotated, reopening")
                f.close()
                f = open(log_path, "r")
                last_inode = st.st_ino

            line = f.readline()
            if line:
                tick = int(time.time() * 1000) - start_ms
                writer.write_frame(
                    channel=0,
                    payload=line.encode("utf-8", errors="replace"),
                    timestamp=tick,
                )
                frame_count += 1
                if frame_count % _FLUSH_INTERVAL == 0:
                    writer.flush()
            else:
                writer.flush()
                time.sleep(0.05)
    except (KeyboardInterrupt, SystemExit):
        pass
    finally:
        f.close()
        writer.close()
        _log(f"Stopped: {frame_count} frames written to {output_path}")


if __name__ == "__main__":
    main()
