"""DLOG buffer capture for C2000 data logging.

Reads TI DLOG_4CH circular buffers after capture completes. The firmware
fills buffers at ISR rate; we read the whole buffer once capture is done.
This is the high-bandwidth complement to variable streaming.

Typical firmware setup (C2000ware DLOG_4CH):
- dLog1: DLOG_4CH struct with status, pre_scalar, size, trigger, etc.
- dBuff1-dBuff4: float32 circular buffers (typically 200-400 words each)
- dLog1.status transitions: WAIT → TRIGGERED → COMPLETE
- dLog1.size: number of samples per buffer

Usage:
    capture = DLOGCapture(memory_reader, buffers={
        "dBuff1": 0xC100,
        "dBuff2": 0xC200,
    }, status_addr=0xC000, size_addr=0xC004, trigger_addr=0xC006,
       buffer_size=200)
    result = capture.read_buffers()
"""

from __future__ import annotations

import csv
import io
import json
import struct
import time
from dataclasses import dataclass, field
from typing import Callable, IO, Optional


MemoryReader = Callable[[int, int], Optional[bytes]]
MemoryWriter = Callable[[int, bytes], bool]


# DLOG_4CH status values (from C2000ware dlog_4ch.h)
DLOG_STATUS_IDLE = 0
DLOG_STATUS_WAIT = 1
DLOG_STATUS_TRIGGERED = 2
DLOG_STATUS_COMPLETE = 3


@dataclass
class DLOGResult:
    """Result of a DLOG buffer capture."""

    buffers: dict[str, list[float]]
    buffer_size: int
    status: int
    timestamp: float = 0.0

    def to_csv(self, output: IO[str]) -> None:
        """Write buffers as CSV columns.

        Args:
            output: File-like object with write() method.
        """
        names = sorted(self.buffers.keys())
        writer = csv.writer(output)
        writer.writerow(["sample"] + names)
        for i in range(self.buffer_size):
            row = [i]
            for name in names:
                buf = self.buffers[name]
                row.append(buf[i] if i < len(buf) else "")
            writer.writerow(row)

    def to_json(self) -> dict:
        """Convert to JSON-serializable dict."""
        return {
            "status": self.status,
            "buffer_size": self.buffer_size,
            "timestamp": self.timestamp,
            "buffers": self.buffers,
        }

    def to_jsonl(self, output: IO[str]) -> None:
        """Write as JSONL (one sample per line) for streaming tools.

        Args:
            output: File-like object with write() method.
        """
        names = sorted(self.buffers.keys())
        for i in range(self.buffer_size):
            record = {"sample": i}
            for name in names:
                buf = self.buffers[name]
                record[name] = buf[i] if i < len(buf) else None
            output.write(json.dumps(record) + "\n")


class DLOGCapture:
    """DLOG buffer capture engine for C2000.

    Reads TI DLOG_4CH circular buffers from target memory. Supports
    polling for capture completion and triggering captures.

    Args:
        memory_reader: Callable(address, size_bytes) -> bytes | None.
        memory_writer: Callable(address, data) -> bool (optional, for trigger).
        buffers: Dict mapping buffer name to word address.
        status_addr: Word address of dLog1.status field.
        size_addr: Word address of dLog1.size field.
        trigger_addr: Word address of dLog1.cntr field (write 0 to re-trigger).
        buffer_size: Number of float32 samples per buffer.
    """

    def __init__(
        self,
        memory_reader: MemoryReader,
        buffers: dict[str, int],
        status_addr: int,
        size_addr: int,
        buffer_size: int = 200,
        memory_writer: Optional[MemoryWriter] = None,
        trigger_addr: Optional[int] = None,
    ):
        self._reader = memory_reader
        self._writer = memory_writer
        self._buffers = buffers
        self._status_addr = status_addr
        self._size_addr = size_addr
        self._trigger_addr = trigger_addr
        self._buffer_size = buffer_size

    def read_status(self) -> Optional[int]:
        """Read DLOG status register.

        Returns:
            Status value (0=idle, 1=wait, 2=triggered, 3=complete),
            or None if read failed.
        """
        data = self._reader(self._status_addr, 2)
        if data is None or len(data) < 2:
            return None
        return struct.unpack("<H", data[:2])[0]

    def read_size(self) -> Optional[int]:
        """Read DLOG buffer size from target.

        Returns:
            Buffer size in samples, or None if read failed.
        """
        data = self._reader(self._size_addr, 2)
        if data is None or len(data) < 2:
            return None
        return struct.unpack("<H", data[:2])[0]

    def trigger(self) -> bool:
        """Trigger a new DLOG capture by resetting the counter.

        Writes 0 to the trigger address (dLog1.cntr) to restart capture.

        Returns:
            True if trigger succeeded.
        """
        if self._writer is None or self._trigger_addr is None:
            return False
        return self._writer(self._trigger_addr, struct.pack("<H", 0))

    def is_complete(self) -> bool:
        """Check if DLOG capture is complete."""
        status = self.read_status()
        return status == DLOG_STATUS_COMPLETE

    def read_buffer(self, address: int, count: int) -> Optional[list[float]]:
        """Read a single float32 buffer from target memory.

        Each float32 is 2 words (4 bytes) on C2000.

        Args:
            address: Word address of buffer start.
            count: Number of float32 samples to read.

        Returns:
            List of float values, or None if read failed.
        """
        size_bytes = count * 4  # float32 = 4 bytes
        data = self._reader(address, size_bytes)
        if data is None or len(data) < size_bytes:
            return None

        values = []
        for i in range(count):
            offset = i * 4
            val = struct.unpack("<f", data[offset : offset + 4])[0]
            values.append(val)
        return values

    def read_buffers(self) -> Optional[DLOGResult]:
        """Read all configured DLOG buffers.

        Does NOT check status — reads buffers as-is. Call is_complete()
        first if you want to wait for capture to finish.

        Returns:
            DLOGResult with all buffer data, or None if any read failed.
        """
        status = self.read_status()
        if status is None:
            return None

        result_buffers: dict[str, list[float]] = {}
        for name, addr in self._buffers.items():
            values = self.read_buffer(addr, self._buffer_size)
            if values is None:
                return None
            result_buffers[name] = values

        return DLOGResult(
            buffers=result_buffers,
            buffer_size=self._buffer_size,
            status=status,
            timestamp=time.time(),
        )

    def wait_and_read(
        self,
        timeout_s: float = 10.0,
        poll_interval_s: float = 0.1,
    ) -> Optional[DLOGResult]:
        """Wait for capture to complete, then read all buffers.

        Args:
            timeout_s: Maximum time to wait for completion.
            poll_interval_s: Time between status polls.

        Returns:
            DLOGResult if capture completed, None on timeout or read failure.
        """
        deadline = time.time() + timeout_s
        while time.time() < deadline:
            if self.is_complete():
                return self.read_buffers()
            time.sleep(poll_interval_s)
        return None

    def trigger_and_read(
        self,
        timeout_s: float = 10.0,
        poll_interval_s: float = 0.1,
    ) -> Optional[DLOGResult]:
        """Trigger a capture, wait for completion, then read buffers.

        Args:
            timeout_s: Maximum time to wait for completion.
            poll_interval_s: Time between status polls.

        Returns:
            DLOGResult if capture completed, None on trigger/timeout/read failure.
        """
        if not self.trigger():
            return None
        return self.wait_and_read(timeout_s, poll_interval_s)
