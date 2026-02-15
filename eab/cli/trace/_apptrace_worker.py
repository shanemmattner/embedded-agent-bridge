"""Apptrace capture worker — launched as a subprocess by cmd_start.py.

Connects to an ESP32 via OpenOCD, starts apptrace streaming, and writes binary
frames to a .rttbin file.  Runs until SIGTERM or SIGINT.

Usage (by cmd_start.py):
    python -m eab.cli.trace._apptrace_worker <device> <output_path> <eab_root>

Args:
    device: ESP32 chip variant (e.g., "esp32c6", "esp32s3").
    output_path: Path to .rttbin output file.
    eab_root: Path to EAB repository root (for sys.path).
"""

from __future__ import annotations

import signal
import sys
import time


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
    """Entry point for the apptrace capture subprocess."""
    device = sys.argv[1]
    output_path = sys.argv[2]
    eab_root = sys.argv[3]

    sys.path.insert(0, eab_root)

    from eab.apptrace_transport import OpenOCDApptrace
    from eab.rtt_binary import RTTBinaryCapture

    # Apptrace transport wraps OpenOCD with TCP streaming
    transport = OpenOCDApptrace()

    # RTTBinaryCapture works with any transport that has read() method
    # Apptrace has a single stream (no channels), so use channel 0
    capture = RTTBinaryCapture(
        transport=transport,
        device=device,
        channels=[0],
        output_path=output_path,
        sample_width=1,
        timestamp_hz=1000,
    )

    capture.start()
    _log(f"Capturing apptrace from {device} to {output_path!r}")

    def handle_stop(signum: int, frame: object) -> None:
        result = capture.stop()
        _log(f"Stopped: {result}")
        sys.exit(0)

    signal.signal(signal.SIGTERM, handle_stop)
    signal.signal(signal.SIGINT, handle_stop)

    try:
        while True:
            time.sleep(1)
    except (KeyboardInterrupt, SystemExit):
        pass


if __name__ == "__main__":
    main()
