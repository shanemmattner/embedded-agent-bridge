"""Binary RTT capture format (.rttbin) writer, reader, and high-level API.

File format:
    Header (64 bytes, fixed):
        magic:         4B  "RTTB"
        version:       1B  (1)
        header_size:   1B  (64)
        channel_count: 1B  (number of RTT channels captured)
        sample_width:  1B  (bytes per sample: 1, 2, or 4)
        sample_rate:   4B  uint32 LE (Hz, 0 = unknown/variable)
        timestamp_hz:  4B  uint32 LE (timestamp resolution, 0 = none)
        start_time:    8B  uint64 LE (Unix epoch microseconds)
        channel_mask:  4B  uint32 LE (bitmask of active channels)
        reserved:      36B (zero-filled)

    Frame (variable, repeated):
        timestamp:     4B  uint32 LE (ticks since start)
        channel:       1B  uint8
        length:        2B  uint16 LE (payload bytes)
        payload:       <length> bytes
"""

from __future__ import annotations

import io
import logging
import struct
import threading
import time
from pathlib import Path
from typing import BinaryIO, Optional

logger = logging.getLogger(__name__)

MAGIC = b"RTTB"
VERSION = 1
HEADER_SIZE = 64
HEADER_FMT = "<4sBBBBIIQI36s"  # 4+1+1+1+1+4+4+8+4+36 = 64
FRAME_HEADER_FMT = "<IBH"  # timestamp(4) + channel(1) + length(2) = 7
FRAME_HEADER_SIZE = struct.calcsize(FRAME_HEADER_FMT)


class BinaryWriter:
    """Writes .rttbin files frame by frame."""

    def __init__(
        self,
        file: BinaryIO | Path | str,
        *,
        channels: list[int],
        sample_width: int = 2,
        sample_rate: int = 0,
        timestamp_hz: int = 0,
    ):
        self._owns_file = False
        if isinstance(file, (str, Path)):
            self._f = open(file, "wb")
            self._owns_file = True
        else:
            self._f = file

        self._channels = channels
        self._sample_width = sample_width
        self._sample_rate = sample_rate
        self._timestamp_hz = timestamp_hz
        self._start_time = int(time.time() * 1_000_000)
        self._frame_count = 0

        channel_mask = 0
        for ch in channels:
            channel_mask |= 1 << ch

        header = struct.pack(
            HEADER_FMT,
            MAGIC,
            VERSION,
            HEADER_SIZE,
            len(channels),
            sample_width,
            sample_rate,
            timestamp_hz,
            self._start_time,
            channel_mask,
            b"\x00" * 36,
        )
        self._f.write(header)

    def write_frame(self, channel: int, payload: bytes, timestamp: int = 0) -> None:
        """Write a single frame.

        Args:
            channel: RTT channel index.
            payload: Raw binary payload.
            timestamp: Tick count since capture start (0 if no timestamps).
        """
        if len(payload) > 65535:
            raise ValueError(f"Payload too large: {len(payload)} bytes (max 65535)")
        frame_hdr = struct.pack(FRAME_HEADER_FMT, timestamp, channel, len(payload))
        self._f.write(frame_hdr)
        self._f.write(payload)
        self._frame_count += 1

    def flush(self) -> None:
        self._f.flush()

    def close(self) -> None:
        self.flush()
        if self._owns_file:
            self._f.close()

    @property
    def frame_count(self) -> int:
        return self._frame_count

    @property
    def start_time(self) -> int:
        return self._start_time

    def __enter__(self):
        return self

    def __exit__(self, exc_type, exc_val, exc_tb):
        self.close()
        return False


class BinaryReader:
    """Reads .rttbin files frame by frame."""

    def __init__(self, file: BinaryIO | Path | str):
        self._owns_file = False
        if isinstance(file, (str, Path)):
            self._f = open(file, "rb")
            self._owns_file = True
        else:
            self._f = file

        raw_header = self._f.read(HEADER_SIZE)
        if len(raw_header) < HEADER_SIZE:
            raise ValueError(f"File too small for header: {len(raw_header)} bytes")

        (
            magic,
            version,
            header_size,
            channel_count,
            sample_width,
            sample_rate,
            timestamp_hz,
            start_time,
            channel_mask,
            _reserved,
        ) = struct.unpack(HEADER_FMT, raw_header)

        if magic != MAGIC:
            raise ValueError(f"Invalid magic: {magic!r} (expected {MAGIC!r})")
        if version > VERSION:
            raise ValueError(f"Unsupported version: {version} (max {VERSION})")

        self.version = version
        self.channel_count = channel_count
        self.sample_width = sample_width
        self.sample_rate = sample_rate
        self.timestamp_hz = timestamp_hz
        self.start_time = start_time
        self.channel_mask = channel_mask

        # Seek past header (in case header_size > 64 in future versions)
        if header_size > HEADER_SIZE:
            self._f.seek(header_size)

    def read_frame(self) -> tuple[int, int, bytes] | None:
        """Read the next frame.

        Returns:
            (timestamp, channel, payload) or None at EOF.
        """
        hdr = self._f.read(FRAME_HEADER_SIZE)
        if len(hdr) < FRAME_HEADER_SIZE:
            return None

        timestamp, channel, length = struct.unpack(FRAME_HEADER_FMT, hdr)
        payload = self._f.read(length)
        if len(payload) < length:
            return None

        return timestamp, channel, payload

    def read_all(self) -> list[tuple[int, int, bytes]]:
        """Read all frames into a list."""
        frames = []
        while True:
            frame = self.read_frame()
            if frame is None:
                break
            frames.append(frame)
        return frames

    def close(self) -> None:
        if self._owns_file:
            self._f.close()

    def __enter__(self):
        return self

    def __exit__(self, exc_type, exc_val, exc_tb):
        self.close()
        return False


class RTTBinaryCapture:
    """High-level API for binary RTT capture.

    Connects to a target via an RTTTransport, reads binary data from
    one or more RTT channels, and writes to a .rttbin file.

    Example::

        from eab.rtt_binary import RTTBinaryCapture
        from eab.rtt_transport import JLinkTransport

        capture = RTTBinaryCapture(
            transport=JLinkTransport(),
            device="NRF5340_XXAA_APP",
            channels=[1],
            sample_rate=10000,
            sample_width=2,
            output_path="adc.rttbin",
        )
        capture.start()
        # ... device streams data ...
        capture.stop()
        data = capture.to_numpy()
    """

    def __init__(
        self,
        transport,
        *,
        device: str,
        channels: list[int],
        output_path: str | Path,
        sample_width: int = 2,
        sample_rate: int = 0,
        timestamp_hz: int = 0,
        interface: str = "SWD",
        speed: int = 4000,
        block_address: int | None = None,
        poll_interval: float = 0.001,
    ):
        from eab.rtt_transport import RTTTransport

        if not isinstance(transport, RTTTransport):
            raise TypeError(f"transport must be RTTTransport, got {type(transport)}")

        self._transport = transport
        self._device = device
        self._channels = channels
        self._output_path = Path(output_path)
        self._sample_width = sample_width
        self._sample_rate = sample_rate
        self._timestamp_hz = timestamp_hz
        self._interface = interface
        self._speed = speed
        self._block_address = block_address
        self._poll_interval = poll_interval

        self._writer: Optional[BinaryWriter] = None
        self._thread: Optional[threading.Thread] = None
        self._stop_event = threading.Event()
        self._total_bytes = 0
        self._total_frames = 0

    def start(self) -> None:
        """Connect, start RTT, and begin capturing to file."""
        if self._thread and self._thread.is_alive():
            raise RuntimeError("Capture already running")

        self._transport.connect(self._device, self._interface, self._speed)
        self._transport.start_rtt(self._block_address)

        self._writer = BinaryWriter(
            self._output_path,
            channels=self._channels,
            sample_width=self._sample_width,
            sample_rate=self._sample_rate,
            timestamp_hz=self._timestamp_hz,
        )

        self._stop_event.clear()
        self._total_bytes = 0
        self._total_frames = 0

        self._thread = threading.Thread(
            target=self._capture_loop,
            daemon=True,
            name="eab-rtt-binary-capture",
        )
        self._thread.start()
        logger.info("Binary capture started → %s", self._output_path)

    def stop(self) -> dict:
        """Stop capture, close files, disconnect.

        Returns:
            Summary dict with total_bytes, total_frames, duration_s.
        """
        self._stop_event.set()

        if self._thread and self._thread.is_alive():
            self._thread.join(timeout=5.0)

        if self._writer:
            self._writer.close()
            start_us = self._writer.start_time
            self._writer = None
        else:
            start_us = 0

        try:
            self._transport.stop_rtt()
        except Exception:
            pass
        try:
            self._transport.disconnect()
        except Exception:
            pass

        duration_s = (time.time() * 1_000_000 - start_us) / 1_000_000 if start_us else 0

        summary = {
            "output_path": str(self._output_path),
            "total_bytes": self._total_bytes,
            "total_frames": self._total_frames,
            "duration_s": round(duration_s, 3),
        }
        logger.info("Binary capture stopped: %s", summary)
        return summary

    def to_numpy(self) -> dict:
        """Convert captured .rttbin to numpy arrays.

        Returns:
            dict mapping channel index to numpy array of samples.
        """
        from eab.rtt_convert import to_numpy
        return to_numpy(self._output_path, self._sample_width)

    def to_csv(self, output_path: str | Path | None = None) -> Path:
        """Convert captured .rttbin to CSV.

        Args:
            output_path: Output CSV path. Defaults to same name with .csv extension.

        Returns:
            Path to the written CSV file.
        """
        from eab.rtt_convert import to_csv
        if output_path is None:
            output_path = self._output_path.with_suffix(".csv")
        return to_csv(self._output_path, output_path)

    @property
    def is_running(self) -> bool:
        return self._thread is not None and self._thread.is_alive()

    @property
    def total_bytes(self) -> int:
        return self._total_bytes

    @property
    def total_frames(self) -> int:
        return self._total_frames

    def _capture_loop(self) -> None:
        """Background thread: read RTT channels and write frames."""
        tick = 0
        while not self._stop_event.is_set():
            got_data = False
            for ch in self._channels:
                data = self._transport.read(ch)
                if data:
                    self._writer.write_frame(ch, data, timestamp=tick)
                    self._total_bytes += len(data)
                    self._total_frames += 1
                    got_data = True

            if self._timestamp_hz > 0:
                tick += 1

            if not got_data:
                time.sleep(self._poll_interval)
            else:
                self._writer.flush()
