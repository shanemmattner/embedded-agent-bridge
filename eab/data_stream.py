"""
High-speed data stream writer for Embedded Agent Bridge.

Writes raw binary chunks to data.bin and returns metadata for events.
"""

from __future__ import annotations

import os
import zlib

from .interfaces import FileSystemInterface, ClockInterface


class DataStreamWriter:
    """Append-only binary writer with offset tracking."""

    def __init__(
        self,
        filesystem: FileSystemInterface,
        clock: ClockInterface,
        data_path: str,
    ) -> None:
        self._fs = filesystem
        self._clock = clock
        self._data_path = data_path

        data_dir = os.path.dirname(data_path) or "."
        self._fs.ensure_dir(data_dir)
        self._offset = self._get_size()

    def append(self, chunk: bytes) -> dict[str, int | str]:
        if not chunk:
            return {"offset": self._offset, "length": 0, "crc32": "0"}

        offset = self._offset
        with open(self._data_path, "ab") as f:
            f.write(chunk)
            f.flush()

        self._offset += len(chunk)
        crc = zlib.crc32(chunk) & 0xFFFFFFFF
        return {
            "offset": offset,
            "length": len(chunk),
            "crc32": f"{crc:08x}",
        }

    def current_offset(self) -> int:
        return self._offset

    def truncate(self) -> None:
        with open(self._data_path, "wb") as f:
            f.truncate(0)
        self._offset = 0

    def _get_size(self) -> int:
        try:
            return os.path.getsize(self._data_path)
        except OSError:
            return 0
