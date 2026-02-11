"""J-Link RTT management via JLinkRTTLogger subprocess.

Spawns SEGGER's native JLinkRTTLogger binary to read RTT data at full
J-Link DLL speed. A background thread tails the raw output file and
feeds lines through RTTStreamProcessor for structured logging (log,
JSONL, CSV).

This avoids the pylink-square dependency and its ctypes FFI overhead.
JLinkRTTLogger must be on PATH (ships with J-Link Software Pack).

Architecture:
    JLinkRTTLogger (C binary)
        └─ writes raw RTT text to rtt-raw.log
    _tailer_loop (Python thread)
        └─ tails rtt-raw.log, feeds lines to RTTStreamProcessor
    RTTStreamProcessor
        ├─ rtt.log   (cleaned text)
        ├─ rtt.jsonl (structured records)
        └─ rtt.csv   (DATA key=value rows)
"""

from __future__ import annotations

import asyncio
import json
import logging
import os
import shutil
import subprocess
import threading
import time
from dataclasses import dataclass
from pathlib import Path
from typing import Optional

from .rtt_stream import RTTStreamProcessor

logger = logging.getLogger(__name__)

# Stderr patterns from JLinkRTTLogger
_RTT_FOUND_MARKER = "up-channels found:"
_TRANSFER_RATE_PREFIX = "Transfer rate:"


def _find_rtt_logger() -> Optional[str]:
    """Find JLinkRTTLogger binary on PATH or known install locations."""
    found = shutil.which("JLinkRTTLogger")
    if found:
        return found
    # macOS default install locations
    for candidate in [
        "/Applications/SEGGER/JLink/JLinkRTTLoggerExe",
        "/Applications/SEGGER/JLink/JLinkRTTLogger",
        "/usr/local/bin/JLinkRTTLogger",
    ]:
        if os.path.isfile(candidate) and os.access(candidate, os.X_OK):
            return candidate
    return None


@dataclass(frozen=True)
class JLinkRTTStatus:
    running: bool
    device: Optional[str]
    log_path: str
    channel: int = 0
    num_up_channels: int = 0
    bytes_read: int = 0
    last_error: Optional[str] = None


class JLinkRTTManager:
    """Manages RTT streaming via JLinkRTTLogger subprocess.

    Spawns JLinkRTTLogger to capture raw RTT data to a file, then tails
    that file in a background thread to feed RTTStreamProcessor.
    """

    def __init__(self, base_dir: Path):
        self.rtt_raw_path = base_dir / "rtt-raw.log"
        self.rtt_log_path = base_dir / "rtt.log"
        self.rtt_jsonl_path = base_dir / "rtt.jsonl"
        self.rtt_csv_path = base_dir / "rtt.csv"
        self.rtt_status_path = base_dir / "jlink_rtt.status.json"

        self._proc: Optional[subprocess.Popen] = None
        self._tailer: Optional[threading.Thread] = None
        self._stderr_thread: Optional[threading.Thread] = None
        self._stop_event = threading.Event()
        self._processor: Optional[RTTStreamProcessor] = None
        self._bytes_read = 0
        self._device: Optional[str] = None
        self._num_up: int = 0
        self._last_error: Optional[str] = None

    def status(self) -> JLinkRTTStatus:
        running = self._proc is not None and self._proc.poll() is None
        return JLinkRTTStatus(
            running=running,
            device=self._device,
            log_path=str(self.rtt_log_path),
            channel=0,
            num_up_channels=self._num_up,
            bytes_read=self._bytes_read,
            last_error=self._last_error,
        )

    def start(
        self,
        device: str,
        interface: str = "SWD",
        speed: int = 4000,
        rtt_channel: int = 0,
        block_address: Optional[int] = None,
        queue: Optional[asyncio.Queue] = None,
    ) -> JLinkRTTStatus:
        """Start RTT streaming via JLinkRTTLogger subprocess.

        Args:
            device: J-Link device string (e.g., NRF5340_XXAA_APP)
            interface: Debug interface (SWD or JTAG)
            speed: Interface speed in kHz
            rtt_channel: RTT channel number (default 0)
            block_address: Optional RTT control block address from .map file
            queue: Optional asyncio.Queue for plotter integration
        """
        rtt_logger = _find_rtt_logger()
        if rtt_logger is None:
            self._last_error = (
                "JLinkRTTLogger not found. "
                "Install J-Link Software Pack from segger.com"
            )
            return self.status()

        cur = self.status()
        if cur.running:
            return cur

        self._device = device
        self._last_error = None
        self._bytes_read = 0
        self._stop_event.clear()

        self._processor = RTTStreamProcessor(
            log_path=self.rtt_log_path,
            jsonl_path=self.rtt_jsonl_path,
            csv_path=self.rtt_csv_path,
            queue=queue,
        )

        # Build JLinkRTTLogger command
        cmd = [
            rtt_logger,
            "-Device", device,
            "-If", interface.upper(),
            "-Speed", str(speed),
            "-RTTChannel", str(rtt_channel),
        ]
        if block_address is not None:
            cmd.extend(["-RTTAddress", f"0x{block_address:X}"])
        cmd.append(str(self.rtt_raw_path))

        logger.info("Starting JLinkRTTLogger: %s", " ".join(cmd))

        try:
            # Truncate raw log to avoid tailing stale data
            self.rtt_raw_path.write_bytes(b"")

            # JLinkRTTLogger writes status/progress to stdout, data to file.
            # stdin must be PIPE (not DEVNULL) because JLinkRTTLogger
            # reads stdin for "press any key to quit" — DEVNULL gives
            # immediate EOF which kills the process.
            self._proc = subprocess.Popen(
                cmd,
                stdout=subprocess.PIPE,
                stderr=subprocess.STDOUT,
                stdin=subprocess.PIPE,
            )
        except Exception as e:
            self._last_error = f"Failed to start JLinkRTTLogger: {e}"
            self._write_status({"running": False, "device": device,
                                "last_error": self._last_error})
            return self.status()

        # Thread to parse JLinkRTTLogger stdout for status info
        self._stderr_thread = threading.Thread(
            target=self._stdout_reader,
            daemon=True,
            name="eab-rtt-stdout",
        )
        self._stderr_thread.start()

        # Wait briefly for JLinkRTTLogger to connect and start writing
        deadline = time.time() + 10.0
        while time.time() < deadline:
            if self._proc.poll() is not None:
                # Process exited early — read stderr for error
                self._last_error = f"JLinkRTTLogger exited with code {self._proc.returncode}"
                self._write_status({"running": False, "device": device,
                                    "last_error": self._last_error})
                return self.status()
            if self._num_up > 0:
                break
            time.sleep(0.2)

        # Start file tailer thread
        self._tailer = threading.Thread(
            target=self._tailer_loop,
            daemon=True,
            name="eab-rtt-tailer",
        )
        self._tailer.start()

        self._write_status({
            "running": True,
            "device": device,
            "channel": rtt_channel,
            "num_up_channels": self._num_up,
            "block_address": block_address,
            "timestamp": time.strftime("%Y-%m-%dT%H:%M:%S"),
        })

        logger.info(
            "RTT started: %s, %d up channels (via JLinkRTTLogger)",
            device, self._num_up,
        )
        return self.status()

    def stop(self, timeout_s: float = 5.0) -> JLinkRTTStatus:
        """Stop RTT streaming and kill JLinkRTTLogger subprocess."""
        self._stop_event.set()

        if self._proc and self._proc.poll() is None:
            self._proc.terminate()
            try:
                self._proc.wait(timeout=timeout_s)
            except subprocess.TimeoutExpired:
                self._proc.kill()
                self._proc.wait(timeout=2)

        if self._tailer and self._tailer.is_alive():
            self._tailer.join(timeout=timeout_s)

        if self._stderr_thread and self._stderr_thread.is_alive():
            self._stderr_thread.join(timeout=2)

        if self._processor:
            self._processor.flush()
            self._processor.close()

        self._proc = None
        self._tailer = None
        self._stderr_thread = None
        self._processor = None
        self._device = None
        self._last_error = None

        self._write_status({"running": False})
        return self.status()

    def _stdout_reader(self) -> None:
        """Parse JLinkRTTLogger stdout for connection status and errors.

        JLinkRTTLogger writes all status/progress to stdout:
        - "3 up-channels found:" — RTT ready
        - "RTT Control Block not found" — connection failed
        - "Transfer rate: XX KB/s" — periodic throughput
        """
        if not self._proc or not self._proc.stdout:
            return

        try:
            for raw_line in self._proc.stdout:
                line = raw_line.decode("utf-8", errors="replace").strip()
                if not line:
                    continue

                # Parse channel count: "3 up-channels found:"
                if _RTT_FOUND_MARKER in line:
                    try:
                        self._num_up = int(line.split()[0])
                    except (ValueError, IndexError):
                        pass

                # Detect failure
                if "Control Block not found" in line:
                    self._last_error = "RTT control block not found"
                    logger.error("JLinkRTTLogger: %s", line)

                # Log transfer rate updates for debugging
                if _TRANSFER_RATE_PREFIX in line:
                    logger.debug("JLinkRTTLogger: %s", line)

                if self._stop_event.is_set():
                    break
        except Exception:
            pass

    def _tailer_loop(self) -> None:
        """Tail rtt-raw.log and feed lines to RTTStreamProcessor.

        Opens the raw log file and reads new data as JLinkRTTLogger
        appends to it. Uses a poll-based approach with short sleeps.
        """
        processor = self._processor
        if processor is None:
            return

        # Wait for the raw file to appear
        deadline = time.time() + 10.0
        while not self.rtt_raw_path.exists() and time.time() < deadline:
            if self._stop_event.is_set():
                return
            time.sleep(0.1)

        last_data_time = time.monotonic()

        try:
            with open(self.rtt_raw_path, "r", encoding="utf-8", errors="replace") as f:
                while not self._stop_event.is_set():
                    # Check if JLinkRTTLogger process died
                    if self._proc and self._proc.poll() is not None:
                        # Read any remaining data
                        remaining = f.read()
                        if remaining:
                            self._bytes_read += len(remaining)
                            processor.feed_text(remaining)
                        self._last_error = f"JLinkRTTLogger exited (code {self._proc.returncode})"
                        logger.warning(self._last_error)
                        break

                    data = f.read(8192)
                    if data:
                        self._bytes_read += len(data)
                        processor.feed_text(data)
                        last_data_time = time.monotonic()
                    else:
                        # No new data — flush if idle for >200ms
                        if time.monotonic() - last_data_time > 0.2:
                            processor.flush()
                            last_data_time = time.monotonic()
                        time.sleep(0.01)  # 100Hz tail poll

        except Exception as e:
            self._last_error = f"Tailer error: {e}"
            logger.error("RTT tailer error: %s", e)

        # Final flush
        try:
            processor.flush()
        except Exception:
            pass

    def _write_status(self, data: dict) -> None:
        """Write RTT status JSON file."""
        try:
            self.rtt_status_path.write_text(
                json.dumps(data, indent=2, sort_keys=True)
            )
        except OSError:
            pass
