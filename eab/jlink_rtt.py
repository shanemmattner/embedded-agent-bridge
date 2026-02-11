"""J-Link RTT management via pylink-square.

Direct Python access to SEGGER RTT ring buffers with proper initialization
handshake. No GDB server or JLinkRTTClient subprocess needed.
"""

from __future__ import annotations

import json
import logging
import threading
import time
from dataclasses import dataclass
from pathlib import Path
from typing import Optional

try:
    import pylink
except ImportError:
    pylink = None  # type: ignore[assignment]

from .rtt_stream import RTTStreamProcessor

logger = logging.getLogger(__name__)


@dataclass(frozen=True)
class JLinkRTTStatus:
    running: bool
    device: Optional[str]
    log_path: str
    channel: int = 0
    num_up_channels: int = 0
    num_down_channels: int = 0
    bytes_read: int = 0
    last_error: Optional[str] = None


class JLinkRTTManager:
    """Manages RTT streaming via pylink-square.

    Connects directly to J-Link probe, starts RTT, and polls
    rtt_read() in a background thread. No GDB server needed.
    """

    def __init__(self, base_dir: Path):
        self.rtt_log_path = base_dir / "rtt.log"
        self.rtt_jsonl_path = base_dir / "rtt.jsonl"
        self.rtt_status_path = base_dir / "jlink_rtt.status.json"

        self._jlink = None
        self._thread: Optional[threading.Thread] = None
        self._stop_event = threading.Event()
        self._processor: Optional[RTTStreamProcessor] = None
        self._bytes_read = 0
        self._device: Optional[str] = None
        self._num_up: int = 0
        self._num_down: int = 0
        self._last_error: Optional[str] = None

    def status(self) -> JLinkRTTStatus:
        running = self._thread is not None and self._thread.is_alive()
        return JLinkRTTStatus(
            running=running,
            device=self._device,
            log_path=str(self.rtt_log_path),
            channel=0,
            num_up_channels=self._num_up,
            num_down_channels=self._num_down,
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
        queue=None,
    ) -> JLinkRTTStatus:
        """Start RTT streaming.

        Args:
            device: J-Link device string (e.g., NRF5340_XXAA_APP)
            interface: Debug interface (SWD or JTAG)
            speed: Interface speed in kHz
            rtt_channel: RTT channel number (default 0)
            block_address: Optional RTT control block address from .map file
            queue: Optional asyncio.Queue for plotter integration
        """
        if pylink is None:
            self._last_error = (
                "pylink-square not installed. "
                "Install with: pip install pylink-square"
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
            queue=queue,
        )

        try:
            jlink = pylink.JLink()
            jlink.open()

            iface = pylink.enums.JLinkInterfaces.SWD
            if interface.upper() == "JTAG":
                iface = pylink.enums.JLinkInterfaces.JTAG
            jlink.set_tif(iface)
            jlink.connect(device, speed)

            # Start RTT — does NOT wait for control block
            jlink.rtt_start(block_address)

            # Poll until control block found (up to 10 seconds)
            deadline = time.time() + 10.0
            while time.time() < deadline:
                try:
                    num_up = jlink.rtt_get_num_up_buffers()
                    num_down = jlink.rtt_get_num_down_buffers()
                    self._num_up = num_up
                    self._num_down = num_down
                    break
                except Exception:
                    time.sleep(0.1)
            else:
                jlink.close()
                self._last_error = "RTT control block not found within 10s"
                self._write_status({"running": False, "device": device,
                                    "last_error": self._last_error})
                return self.status()

            # First-read flush: drain stale buffer content
            try:
                stale = jlink.rtt_read(rtt_channel, 4096)
                if stale:
                    self._processor.drain_initial(bytes(stale))
            except Exception:
                pass

            self._jlink = jlink

        except Exception as e:
            self._last_error = str(e)
            self._write_status({"running": False, "device": device,
                                "last_error": str(e)})
            return self.status()

        # Start reader thread
        self._thread = threading.Thread(
            target=self._reader_loop,
            args=(jlink, self._processor, rtt_channel),
            daemon=True,
            name="eab-rtt-reader",
        )
        self._thread.start()

        self._write_status({
            "running": True,
            "device": device,
            "channel": rtt_channel,
            "num_up_channels": self._num_up,
            "num_down_channels": self._num_down,
            "block_address": block_address,
            "timestamp": time.strftime("%Y-%m-%dT%H:%M:%S"),
        })

        logger.info(
            "RTT started: %s, %d up / %d down channels",
            device, self._num_up, self._num_down,
        )
        return self.status()

    def stop(self, timeout_s: float = 5.0) -> JLinkRTTStatus:
        """Stop RTT streaming and close pylink connection."""
        self._stop_event.set()

        if self._thread and self._thread.is_alive():
            self._thread.join(timeout=timeout_s)

        if self._processor:
            self._processor.flush()

        if self._jlink:
            try:
                self._jlink.rtt_stop()
            except Exception:
                pass
            try:
                self._jlink.close()
            except Exception:
                pass
            self._jlink = None

        self._thread = None
        self._processor = None
        self._device = None
        self._last_error = None

        self._write_status({"running": False})
        return self.status()

    def _reader_loop(
        self,
        jlink,
        processor: RTTStreamProcessor,
        channel: int,
    ) -> None:
        """Poll rtt_read() and feed into stream processor. Runs in thread."""
        last_data_time = time.monotonic()

        while not self._stop_event.is_set():
            try:
                if not jlink.connected():
                    self._last_error = "J-Link disconnected"
                    logger.warning("J-Link disconnected during RTT read")
                    break

                raw_list = jlink.rtt_read(channel, 1024)
                if raw_list:
                    raw = bytes(raw_list)
                    self._bytes_read += len(raw)
                    processor.feed(raw)
                    last_data_time = time.monotonic()
                else:
                    # No data — check if we should flush partial line buffer
                    if time.monotonic() - last_data_time > 0.2:
                        processor.flush()
                        last_data_time = time.monotonic()

            except Exception as e:
                err_str = str(e)
                if "-11" in err_str:
                    self._last_error = "Device disconnected (error -11)"
                    logger.warning("RTT read error -11, device disconnected")
                    break
                else:
                    self._last_error = f"RTT read error: {err_str}"
                    logger.error("RTT read error: %s", err_str)
                    break

            time.sleep(0.1)  # 10Hz poll

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
