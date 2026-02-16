"""Variable streaming engine for C2000 real-time monitoring.

Polls variables via memory reads and outputs JSONL for dashboards/plots.
Uses the MAP file parser for symbol addresses and type_decode for value
conversion. Works with any memory_reader (XDS110Probe or DSSTransport).
"""

from __future__ import annotations

import json
import time
from dataclasses import dataclass
from typing import IO, Callable, Optional

from .type_decode import C2000Type, byte_size, decode_value


MemoryReader = Callable[[int, int], Optional[bytes]]


@dataclass
class StreamVar:
    """A variable to stream."""

    name: str
    address: int
    c2000_type: C2000Type
    size_bytes: int = 0  # Auto-computed from type if 0

    def __post_init__(self):
        if self.size_bytes == 0:
            self.size_bytes = byte_size(self.c2000_type)


class VarStream:
    """Variable streaming engine.

    Reads variables from target memory at a fixed interval and outputs
    JSONL (one JSON object per line) with timestamps.

    Args:
        memory_reader: Callable(address, size) -> bytes | None.
        variables: List of variables to stream.
        interval_ms: Polling interval in milliseconds.
    """

    def __init__(
        self,
        memory_reader: MemoryReader,
        variables: list[StreamVar],
        interval_ms: int = 100,
    ):
        self._reader = memory_reader
        self._variables = variables
        self._interval_s = interval_ms / 1000.0

    def read_once(self) -> dict[str, int | float | None]:
        """Read all variables once.

        Returns:
            Dict mapping variable name to decoded value (None if read failed).
        """
        result: dict[str, int | float | None] = {}
        for var in self._variables:
            data = self._reader(var.address, var.size_bytes)
            if data is not None:
                try:
                    result[var.name] = decode_value(data, var.c2000_type)
                except (ValueError, struct.error):
                    result[var.name] = None
            else:
                result[var.name] = None
        return result

    def stream_jsonl(self, output: IO[str], count: int = 0) -> int:
        """Stream JSONL to output file-like object.

        Each line: {"ts": epoch_float, "var1": value1, "var2": value2}

        Args:
            output: File-like object with write() method.
            count: Number of samples (0 = infinite, use Ctrl+C to stop).

        Returns:
            Number of samples written.
        """
        samples = 0
        try:
            while count == 0 or samples < count:
                values = self.read_once()
                record = {"ts": time.time()}
                record.update(values)
                output.write(json.dumps(record) + "\n")
                output.flush()
                samples += 1
                if count == 0 or samples < count:
                    time.sleep(self._interval_s)
        except KeyboardInterrupt:
            pass
        return samples

    def read_batch(self, count: int) -> list[dict]:
        """Read count samples, return list of dicts.

        Args:
            count: Number of samples to read.

        Returns:
            List of dicts with "ts" and variable values.
        """
        results = []
        for i in range(count):
            values = self.read_once()
            record = {"ts": time.time()}
            record.update(values)
            results.append(record)
            if i < count - 1:
                time.sleep(self._interval_s)
        return results


# Avoid circular import — only needed for type annotation in read_once
import struct
