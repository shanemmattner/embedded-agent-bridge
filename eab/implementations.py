"""
Real implementations of interfaces for production use.

These classes wrap actual system resources (serial ports, files, etc.)
and implement the abstract interfaces.
"""

from typing import Optional, List
from datetime import datetime
import os
import time

import serial
import serial.tools.list_ports

from .interfaces import (
    SerialPortInterface, FileSystemInterface, ClockInterface, LoggerInterface,
    PortInfo
)


class RealSerialPort(SerialPortInterface):
    """
    Real serial port implementation using pyserial.
    """

    def __init__(self):
        self._serial: Optional[serial.Serial] = None

    def open(self, port: str, baud: int, timeout: float = 1.0) -> bool:
        try:
            self._serial = serial.Serial(port, baud, timeout=timeout)
            return True
        except Exception:
            self._serial = None
            return False

    def close(self) -> None:
        if self._serial:
            try:
                self._serial.close()
            except Exception:
                pass
            self._serial = None

    def is_open(self) -> bool:
        if self._serial is None:
            return False
        try:
            return self._serial.is_open
        except Exception:
            return False

    def read_line(self) -> Optional[bytes]:
        if not self._serial:
            return None
        try:
            if self._serial.in_waiting:
                return self._serial.readline()
            return None
        except Exception:
            return None

    def read_bytes(self, max_bytes: int) -> bytes:
        if not self._serial:
            return b""
        if max_bytes <= 0:
            return b""
        try:
            waiting = self._serial.in_waiting
            if not waiting:
                return b""
            size = min(waiting, max_bytes)
            return self._serial.read(size)
        except Exception:
            return b""

    def write(self, data: bytes) -> int:
        if not self._serial:
            return 0
        try:
            return self._serial.write(data)
        except Exception:
            return 0

    def bytes_available(self) -> int:
        if not self._serial:
            return 0
        try:
            return self._serial.in_waiting
        except Exception:
            return 0

    @staticmethod
    def list_ports() -> List[PortInfo]:
        ports = []
        for p in serial.tools.list_ports.comports():
            ports.append(PortInfo(
                device=p.device,
                description=p.description or "",
                hwid=p.hwid or "",
            ))
        return ports


class RealFileSystem(FileSystemInterface):
    """
    Real file system implementation.
    """

    def read_file(self, path: str) -> str:
        with open(path, "r") as f:
            return f.read()

    def write_file(self, path: str, content: str, append: bool = False) -> None:
        # Ensure parent directory exists
        parent = os.path.dirname(path)
        if parent and not os.path.exists(parent):
            os.makedirs(parent, exist_ok=True)

        mode = "a" if append else "w"
        with open(path, mode) as f:
            f.write(content)
            f.flush()
            os.fsync(f.fileno())  # Ensure written to disk

    def file_exists(self, path: str) -> bool:
        return os.path.exists(path)

    def get_mtime(self, path: str) -> float:
        return os.path.getmtime(path)

    def ensure_dir(self, path: str) -> None:
        os.makedirs(path, exist_ok=True)

    def delete_file(self, path: str) -> None:
        if os.path.exists(path):
            os.remove(path)

    def file_size(self, path: str) -> int:
        return os.path.getsize(path)

    def rename_file(self, old_path: str, new_path: str) -> None:
        os.rename(old_path, new_path)

    def list_dir(self, path: str) -> List[str]:
        return os.listdir(path)


class RealClock(ClockInterface):
    """
    Real clock implementation using system time.
    """

    def now(self) -> datetime:
        return datetime.now()

    def timestamp(self) -> float:
        return time.time()

    def sleep(self, seconds: float) -> None:
        time.sleep(seconds)


class ConsoleLogger(LoggerInterface):
    """
    Simple console logger implementation.
    """

    def __init__(self, prefix: str = "EAB"):
        self._prefix = prefix

    def debug(self, msg: str) -> None:
        print(f"[{self._prefix}] DEBUG: {msg}")

    def info(self, msg: str) -> None:
        print(f"[{self._prefix}] INFO: {msg}")

    def warning(self, msg: str) -> None:
        print(f"[{self._prefix}] WARN: {msg}")

    def error(self, msg: str) -> None:
        print(f"[{self._prefix}] ERROR: {msg}")
