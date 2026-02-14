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
        self._interface: str = "SWD"
        self._speed: int = 4000
        self._channel: int = 0
        self._block_address: Optional[int] = None
        self._queue: Optional[asyncio.Queue] = None
        self._num_up: int = 0
        self._last_error: Optional[str] = None

    def _pid_alive(self, pid: int) -> bool:
        """Check if a process with the given PID is alive."""
        try:
            os.kill(pid, 0)
            return True
        except OSError:
            return False

    def _recover_from_disk(self) -> bool:
        """Try to recover running state from the status file on disk.

        When a new JLinkRTTManager instance is created (e.g. from a CLI call),
        _proc is None but JLinkRTTLogger may still be running from a previous
        invocation. This reads the status file to recover config and check
        if the process is still alive.

        Returns True if a running RTT session was recovered.
        """
        if self._proc is not None:
            return self._proc.poll() is None

        if not self.rtt_status_path.exists():
            return False

        try:
            data = json.loads(self.rtt_status_path.read_text(encoding="utf-8"))
        except (json.JSONDecodeError, OSError):
            return False

        if not data.get("running"):
            return False

        pid = data.get("pid")
        if not pid or not self._pid_alive(pid):
            return False

        # Recover config from status file
        self._device = data.get("device")
        self._interface = data.get("interface", "SWD")
        self._speed = data.get("speed", 4000)
        self._channel = data.get("channel", 0)
        self._block_address = data.get("block_address")
        self._num_up = data.get("num_up_channels", 0)
        return True

    def status(self) -> JLinkRTTStatus:
        running = self._proc is not None and self._proc.poll() is None
        if not running:
            running = self._recover_from_disk()
        return JLinkRTTStatus(
            running=running,
            device=self._device,
            log_path=str(self.rtt_log_path),
            channel=self._channel,
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
        self._interface = interface
        self._speed = speed
        self._channel = rtt_channel
        self._block_address = block_address
        self._queue = queue
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

            # JLinkRTTLogger reads stdin for "press any key to quit".
            # DEVNULL gives immediate EOF which kills the process.
            # PIPE closes when the parent Python process exits → SIGPIPE.
            # Solution: use os.pipe for stdin (read end blocks forever),
            # and redirect stdout to a file so the process survives
            # after the parent exits.
            stdin_r, self._stdin_w = os.pipe()
            self._stdout_path = self.rtt_raw_path.parent / "rtt-stdout.log"
            self._stdout_file = open(self._stdout_path, "w")
            self._proc = subprocess.Popen(
                cmd,
                stdout=self._stdout_file,
                stderr=subprocess.STDOUT,
                stdin=stdin_r,
                start_new_session=True,
            )
            os.close(stdin_r)  # child inherited it; close parent's copy
        except Exception as e:
            self._last_error = f"Failed to start JLinkRTTLogger: {e}"
            self._write_status({"running": False, "device": device,
                                "last_error": self._last_error})
            return self.status()

        # Thread to parse JLinkRTTLogger stdout (from file) for status info
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
            "pid": self._proc.pid,
            "device": device,
            "interface": interface,
            "speed": speed,
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
        elif self._proc is None:
            # No in-memory proc — try to kill by PID from status file
            self._kill_by_pid(timeout_s)

        if self._tailer and self._tailer.is_alive():
            self._tailer.join(timeout=timeout_s)

        if self._stderr_thread and self._stderr_thread.is_alive():
            self._stderr_thread.join(timeout=2)

        if self._processor:
            self._processor.flush()
            self._processor.close()

        if hasattr(self, "_stdin_w") and self._stdin_w is not None:
            try:
                os.close(self._stdin_w)
            except OSError:
                pass
            self._stdin_w = None
        if hasattr(self, "_stdout_file") and self._stdout_file:
            try:
                self._stdout_file.close()
            except OSError:
                pass
            self._stdout_file = None

        self._proc = None
        self._tailer = None
        self._stderr_thread = None
        self._processor = None
        self._device = None
        self._last_error = None

        self._write_status({"running": False})
        return self.status()

    def _kill_by_pid(self, timeout_s: float = 5.0) -> None:
        """Kill JLinkRTTLogger by PID from the status file."""
        if not self.rtt_status_path.exists():
            return
        try:
            data = json.loads(self.rtt_status_path.read_text(encoding="utf-8"))
        except (json.JSONDecodeError, OSError):
            return
        pid = data.get("pid")
        if not pid or not self._pid_alive(pid):
            return
        import signal
        try:
            os.kill(pid, signal.SIGTERM)
        except OSError:
            return
        deadline = time.time() + timeout_s
        while time.time() < deadline and self._pid_alive(pid):
            time.sleep(0.1)
        if self._pid_alive(pid):
            try:
                os.kill(pid, signal.SIGKILL)
            except OSError:
                pass

    def reset_target(self, wait_after_reset_s: float = 1.0) -> JLinkRTTStatus:
        """Stop RTT, reset target via pylink, restart RTT.

        Works around J-Link single-client limitation: JLinkRTTLogger holds
        the connection so you can't reset via JLinkExe simultaneously.
        This method stops RTT, opens a fresh pylink connection to reset,
        then restarts RTT with the same config.

        Args:
            wait_after_reset_s: Seconds to wait after reset before
                restarting RTT (allows boot to reach RTT init).

        Returns:
            JLinkRTTStatus after restart (or error status if not running).
        """
        if not self.status().running:
            self._last_error = "RTT not running — nothing to reset"
            return self.status()

        # Save current config
        saved_device = self._device
        saved_interface = self._interface
        saved_speed = self._speed
        saved_channel = self._channel
        saved_block_address = self._block_address
        saved_queue = self._queue

        t0 = time.monotonic()

        # Stop RTT (kills JLinkRTTLogger)
        self.stop()

        # Reset target via pylink
        try:
            import pylink
            jlink = pylink.JLink()
            jlink.open()
            if saved_interface.upper() == "SWD":
                jlink.set_tif(pylink.enums.JLinkInterfaces.SWD)
            else:
                jlink.set_tif(pylink.enums.JLinkInterfaces.JTAG)
            jlink.connect(saved_device, speed=saved_speed)
            jlink.reset(halt=False)
            jlink.close()
        except Exception as e:
            self._last_error = f"pylink reset failed: {e}"
            logger.error("Failed to reset target via pylink: %s", e)
            return self.status()

        time.sleep(wait_after_reset_s)

        # Restart RTT with saved config
        result = self.start(
            device=saved_device,
            interface=saved_interface,
            speed=saved_speed,
            rtt_channel=saved_channel,
            block_address=saved_block_address,
            queue=saved_queue,
        )

        downtime_ms = int((time.monotonic() - t0) * 1000)
        logger.info("RTT reset complete: downtime=%dms", downtime_ms)

        return result

    def _stdout_reader(self) -> None:
        """Parse JLinkRTTLogger stdout for connection status and errors.

        Tails the stdout log file (rtt-stdout.log) rather than reading
        from a pipe, so JLinkRTTLogger survives after the Python process exits.

        JLinkRTTLogger writes all status/progress to stdout:
        - "3 up-channels found:" — RTT ready
        - "RTT Control Block not found" — connection failed
        - "Transfer rate: XX KB/s" — periodic throughput
        """
        stdout_path = getattr(self, "_stdout_path", None)
        if stdout_path is None:
            return

        # Wait for file to appear
        deadline = time.time() + 5.0
        while not stdout_path.exists() and time.time() < deadline:
            if self._stop_event.is_set():
                return
            time.sleep(0.1)

        try:
            with open(stdout_path, "r", encoding="utf-8", errors="replace") as f:
                while not self._stop_event.is_set():
                    line = f.readline()
                    if not line:
                        if self._proc and self._proc.poll() is not None:
                            break
                        time.sleep(0.1)
                        continue

                    line = line.strip()
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
