"""RTT capture worker — launched as a subprocess by cmd_start.py.

Connects to a J-Link probe, attaches to RTT, and writes binary frames
to a .rttbin file.  Runs until SIGTERM or SIGINT.

Usage (by cmd_start.py):
    python -m eab.cli.trace._rtt_worker <device> <channel> <output_path> <eab_root>
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
    """Entry point for the RTT capture subprocess."""
    device = sys.argv[1]
    channel = int(sys.argv[2])
    output_path = sys.argv[3]
    eab_root = sys.argv[4]

    sys.path.insert(0, eab_root)

    from eab.rtt_transport import JLinkTransport
    from eab.rtt_binary import RTTBinaryCapture

    transport = JLinkTransport()
    capture = RTTBinaryCapture(
        transport=transport,
        device=device,
        channels=[channel],
        output_path=output_path,
        sample_width=1,
        timestamp_hz=1000,
    )

    capture.start()
    _log(f"Capturing RTT channel {channel} to {output_path!r}")

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
