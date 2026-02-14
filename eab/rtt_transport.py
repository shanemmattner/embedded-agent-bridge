"""Pluggable RTT transport backends for binary capture.

Provides an abstract transport interface and concrete backends for
J-Link (pylink-square), probe-rs CLI, and OpenOCD TCP.

Each backend connects to target hardware, starts RTT, and exposes
raw binary read/write on RTT channels.
"""

from __future__ import annotations

import logging
import shutil
import subprocess
import time
from abc import ABC, abstractmethod
from typing import Optional

logger = logging.getLogger(__name__)


class RTTTransport(ABC):
    """Abstract base class for RTT transport backends.

    Subclasses implement connection and RTT I/O for a specific debug probe.
    """

    @abstractmethod
    def connect(self, device: str, interface: str = "SWD", speed: int = 4000) -> None:
        """Connect to target device.

        Args:
            device: Device/chip identifier (e.g., "NRF5340_XXAA_APP").
            interface: Debug interface ("SWD" or "JTAG").
            speed: Interface speed in kHz.
        """

    @abstractmethod
    def start_rtt(self, block_address: int | None = None) -> int:
        """Start RTT on the target.

        Args:
            block_address: Optional RTT control block address.
                If None, the probe searches RAM automatically.

        Returns:
            Number of up (target→host) channels found.
        """

    @abstractmethod
    def read(self, channel: int, max_bytes: int = 4096) -> bytes:
        """Read raw bytes from an RTT up channel.

        Non-blocking: returns empty bytes if no data available.

        Args:
            channel: RTT up channel index.
            max_bytes: Maximum bytes to read per call.

        Returns:
            Raw bytes from the channel (may be empty).
        """

    @abstractmethod
    def write(self, channel: int, data: bytes) -> int:
        """Write raw bytes to an RTT down channel.

        Args:
            channel: RTT down channel index.
            data: Bytes to send.

        Returns:
            Number of bytes actually written.
        """

    @abstractmethod
    def stop_rtt(self) -> None:
        """Stop RTT on the target."""

    @abstractmethod
    def disconnect(self) -> None:
        """Disconnect from the target."""

    @abstractmethod
    def reset(self, halt: bool = False) -> None:
        """Reset the target.

        Args:
            halt: If True, halt CPU after reset.
        """

    def __enter__(self):
        return self

    def __exit__(self, exc_type, exc_val, exc_tb):
        try:
            self.stop_rtt()
        except Exception:
            pass
        try:
            self.disconnect()
        except Exception:
            pass
        return False


class JLinkTransport(RTTTransport):
    """RTT transport using pylink-square (SEGGER J-Link).

    Requires: ``pip install pylink-square>=2.0.0``
    """

    def __init__(self):
        self._jlink = None
        self._connected = False

    def connect(self, device: str, interface: str = "SWD", speed: int = 4000) -> None:
        try:
            import pylink
        except ImportError:
            raise ImportError(
                "pylink-square is required for JLinkTransport. "
                "Install with: pip install pylink-square>=2.0.0"
            )

        self._jlink = pylink.JLink()
        self._jlink.open()

        if interface.upper() == "SWD":
            self._jlink.set_tif(pylink.enums.JLinkInterfaces.SWD)
        else:
            self._jlink.set_tif(pylink.enums.JLinkInterfaces.JTAG)

        self._jlink.connect(device, speed=speed)
        self._connected = True
        logger.info("JLink connected to %s via %s at %d kHz", device, interface, speed)

    def start_rtt(self, block_address: int | None = None) -> int:
        if not self._jlink or not self._connected:
            raise RuntimeError("Not connected. Call connect() first.")

        if block_address is not None:
            self._jlink.rtt_start(block_address)
        else:
            self._jlink.rtt_start()

        # Wait for RTT to find the control block
        deadline = time.time() + 5.0
        while time.time() < deadline:
            try:
                num_up = self._jlink.rtt_get_num_up_buffers()
                if num_up > 0:
                    logger.info("RTT started: %d up channels", num_up)
                    return num_up
            except Exception:
                pass
            time.sleep(0.05)

        raise TimeoutError("RTT control block not found within 5 seconds")

    def read(self, channel: int, max_bytes: int = 4096) -> bytes:
        if not self._jlink:
            return b""
        try:
            data = self._jlink.rtt_read(channel, max_bytes)
            if data:
                return bytes(data)
            return b""
        except Exception:
            return b""

    def write(self, channel: int, data: bytes) -> int:
        if not self._jlink:
            return 0
        try:
            return self._jlink.rtt_write(channel, list(data))
        except Exception:
            return 0

    def stop_rtt(self) -> None:
        if self._jlink:
            try:
                self._jlink.rtt_stop()
            except Exception:
                pass

    def disconnect(self) -> None:
        if self._jlink:
            try:
                self._jlink.close()
            except Exception:
                pass
            self._jlink = None
            self._connected = False

    def reset(self, halt: bool = False) -> None:
        if not self._jlink:
            raise RuntimeError("Not connected")
        self._jlink.reset(halt=halt)


class ProbeRSTransport(RTTTransport):
    """RTT transport using probe-rs CLI subprocess.

    Requires: ``cargo install probe-rs-tools`` (provides ``probe-rs`` binary).

    Note: probe-rs RTT attach is text-oriented. This backend captures
    raw stdout from ``probe-rs rtt`` and treats it as binary data.
    For true binary RTT, JLinkTransport is preferred.
    """

    def __init__(self):
        self._proc: Optional[subprocess.Popen] = None
        self._chip: Optional[str] = None
        self._bin = shutil.which("probe-rs")

    def connect(self, device: str, interface: str = "SWD", speed: int = 4000) -> None:
        if not self._bin:
            raise FileNotFoundError(
                "probe-rs not found. Install with: cargo install probe-rs-tools"
            )
        self._chip = device
        logger.info("ProbeRS transport configured for chip %s", device)

    def start_rtt(self, block_address: int | None = None) -> int:
        if not self._bin or not self._chip:
            raise RuntimeError("Not connected. Call connect() first.")

        cmd = [self._bin, "rtt", "--chip", self._chip]
        if block_address is not None:
            cmd.extend(["--rtt-address", f"0x{block_address:X}"])

        self._proc = subprocess.Popen(
            cmd,
            stdout=subprocess.PIPE,
            stderr=subprocess.PIPE,
            stdin=subprocess.DEVNULL,
        )

        # Give it time to attach
        time.sleep(1.0)
        if self._proc.poll() is not None:
            stderr = self._proc.stderr.read().decode("utf-8", errors="replace") if self._proc.stderr else ""
            raise RuntimeError(f"probe-rs rtt exited immediately: {stderr}")

        logger.info("probe-rs RTT attached to %s", self._chip)
        return 1  # probe-rs doesn't report channel count easily

    def read(self, channel: int, max_bytes: int = 4096) -> bytes:
        if not self._proc or not self._proc.stdout:
            return b""
        try:
            import select
            ready, _, _ = select.select([self._proc.stdout], [], [], 0.0)
            if ready:
                return self._proc.stdout.read1(max_bytes)
            return b""
        except Exception:
            return b""

    def write(self, channel: int, data: bytes) -> int:
        # probe-rs CLI doesn't support writing to down channels via rtt subcommand
        logger.warning("ProbeRSTransport does not support RTT write")
        return 0

    def stop_rtt(self) -> None:
        if self._proc and self._proc.poll() is None:
            self._proc.terminate()
            try:
                self._proc.wait(timeout=5)
            except subprocess.TimeoutExpired:
                self._proc.kill()
                self._proc.wait(timeout=2)
        self._proc = None

    def disconnect(self) -> None:
        self.stop_rtt()
        self._chip = None

    def reset(self, halt: bool = False) -> None:
        if not self._bin or not self._chip:
            raise RuntimeError("Not connected")
        cmd = [self._bin, "reset", "--chip", self._chip]
        if halt:
            cmd.append("--halt")
        subprocess.run(cmd, capture_output=True, timeout=30)
