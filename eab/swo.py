"""SWO (Serial Wire Output) capture and ITM decoding for ARM Cortex-M.

Provides:
- SWOCapture: Captures SWO data via J-Link or OpenOCD
- ITMDecoder: Decodes ITM stimulus port packets
- ExceptionTracer: Logs interrupt entry/exit with timing

SWO uses Manchester or UART encoding on the SWO pin (TRACEDATA0 on nRF5340).
The TPIU (Trace Port Interface Unit) must be configured for SWO mode.

ITM Packet Format:
- Sync: 0x00 (delimiter)
- Stimulus Port: [header byte][1-4 data bytes]
  - Header: bits[7:3]=port, bits[2:0]=size-1
  - Channel 0: printf/text output
  - Channel 1-31: custom data channels
- Hardware Source: DWT counters, exception trace, etc.
- Timestamp: Relative or absolute timing packets

Architecture:
    SWOCapture manages background processes (JLinkSWOViewerCLExe or OpenOCD)
    ITMDecoder parses raw SWO bytes into structured ITM packets
    ExceptionTracer subscribes to exception packets and logs events
"""

from __future__ import annotations

import asyncio
import json
import logging
import os
import signal
import subprocess
import time
from dataclasses import dataclass
from enum import IntEnum
from pathlib import Path
from typing import IO, Any, Callable, Optional

logger = logging.getLogger(__name__)


# =============================================================================
# ITM Packet Types and Constants
# =============================================================================

class ITMPacketType(IntEnum):
    """ITM packet types per ARM CoreSight spec."""
    SYNC = 0           # Synchronization packet (0x00)
    OVERFLOW = 1       # Buffer overflow marker
    TIMESTAMP = 2      # Local or global timestamp
    EXTENSION = 3      # Extension packet
    STIMULUS = 4       # Stimulus port data (channels 0-31)
    HARDWARE = 5       # Hardware source (DWT, exception trace)


class ExceptionEvent(IntEnum):
    """Exception trace event types."""
    ENTER = 1    # Exception entry
    EXIT = 2     # Exception exit
    RETURN = 3   # Exception return


# ITM channel 0 is typically used for printf/text output
ITM_PRINTF_CHANNEL = 0

# Hardware source packet IDs
HW_EVENT_COUNTER_WRAP = 0x01
HW_PC_SAMPLE = 0x02
HW_DATA_TRACE = 0x04
HW_EXCEPTION_TRACE = 0x08


# =============================================================================
# Data Classes
# =============================================================================

@dataclass(frozen=True)
class ITMPacket:
    """Parsed ITM packet."""
    packet_type: ITMPacketType
    timestamp: Optional[int] = None
    channel: Optional[int] = None  # For STIMULUS packets
    data: Optional[bytes] = None
    exception_num: Optional[int] = None  # For HARDWARE exception trace
    exception_event: Optional[ExceptionEvent] = None
    raw: Optional[bytes] = None


@dataclass(frozen=True)
class ExceptionTrace:
    """Exception trace record with timing."""
    exception_num: int
    event: ExceptionEvent
    timestamp: Optional[int]
    elapsed_us: Optional[float] = None


@dataclass(frozen=True)
class SWOStatus:
    """SWO capture status."""
    running: bool
    pid: Optional[int]
    device: Optional[str]
    swo_freq: Optional[int]
    cpu_freq: Optional[int]
    log_path: str
    bin_path: str
    last_error: Optional[str] = None


# =============================================================================
# ITM Decoder
# =============================================================================

class ITMDecoder:
    """Decodes ITM stimulus port packets from raw SWO data.

    Handles synchronization, packet framing, and multi-byte data extraction.
    Supports channels 0-31, hardware source packets, and timestamp packets.
    """

    def __init__(self):
        self._buf = bytearray()
        self._last_timestamp: Optional[int] = None
        self._sync_count = 0  # Track consecutive sync bytes for resync

    def feed(self, data: bytes) -> list[ITMPacket]:
        """Feed raw SWO bytes and return decoded packets.

        Args:
            data: Raw SWO bytes from capture source

        Returns:
            List of decoded ITMPacket objects
        """
        self._buf.extend(data)
        packets: list[ITMPacket] = []

        while len(self._buf) > 0:
            pkt = self._parse_next_packet()
            if pkt is None:
                break
            packets.append(pkt)

        return packets

    def _parse_next_packet(self) -> Optional[ITMPacket]:
        """Parse the next packet from buffer. Returns None if incomplete."""
        if len(self._buf) == 0:
            return None

        header = self._buf[0]

        # Sync packet: 0x00 (or multiple consecutive for resync)
        if header == 0x00:
            self._buf.pop(0)
            self._sync_count += 1
            if self._sync_count >= 5:  # 5+ consecutive syncs = lost sync recovery
                logger.debug("ITM sync recovery after %d sync bytes", self._sync_count)
                self._sync_count = 0
            return ITMPacket(packet_type=ITMPacketType.SYNC, raw=bytes([0x00]))

        self._sync_count = 0  # Reset sync counter on non-sync byte

        # ITM packet classification per ARM CoreSight spec:
        # Bits [2:0] encode the packet type and size
        # Bits [7:3] encode source/channel for data packets
        
        ss = header & 0b11  # Size/type field in bits [1:0]
        
        # Synchronization and Overflow (ss == 0b00 and special header values)
        if ss == 0b00:
            # Sync is 0x00 (handled above)
            # Overflow is 0x70
            if header == 0x70:
                self._buf.pop(0)
                return ITMPacket(packet_type=ITMPacketType.OVERFLOW, raw=bytes([0x70]))
            # Timestamp packets also have ss == 0b00 in many cases
            # Check bits [7:4]
            if (header & 0xF0) in (0xC0, 0xD0):  # Local timestamp
                return self._parse_timestamp_packet()
            if (header & 0xF0) in (0x90, 0xB0):  # Global timestamp
                return self._parse_global_timestamp_packet()
            # Other 0b00 patterns are reserved/invalid
            logger.warning("Unknown ITM packet header: 0x%02X", header)
            self._buf.pop(0)
            return None
        
        # Protocol packet (ss == 0b11)
        if ss == 0b11:
            # Extension packet (header == 0x08)
            if header == 0x08:
                return self._parse_extension_packet()
            # Hardware source packets (bits [7:4] = 0x0 to 0x7)
            if (header & 0xF0) < 0x80:
                return self._parse_hardware_packet()
            # Reserved
            logger.warning("Unknown protocol packet: 0x%02X", header)
            self._buf.pop(0)
            return None
        
        # Instrumentation packet (ss == 0b01 or 0b10)
        # These are stimulus port packets (channel 0-31)
        if ss in (0b01, 0b10):
            return self._parse_stimulus_packet()
        
        # Should not reach here
        logger.warning("Unknown ITM packet header: 0x%02X", header)
        self._buf.pop(0)
        return None

    def _parse_stimulus_packet(self) -> Optional[ITMPacket]:
        """Parse stimulus port packet (channel 0-31 data)."""
        if len(self._buf) < 1:
            return None

        header = self._buf[0]
        ss = header & 0b11  # Size field: 01 = 1 byte, 10 = 2 bytes, 11 = 4 bytes (but 11 is protocol)
        
        # Payload size based on ss field
        if ss == 0b01:
            payload_size = 1
        elif ss == 0b10:
            payload_size = 2
        else:
            # ss == 0b11 should be handled as protocol packet, not stimulus
            # This should not happen if caller checks correctly
            logger.warning("Invalid stimulus packet ss=0b11")
            self._buf.pop(0)
            return None

        # Channel encoded in bits [7:3]
        channel = (header >> 3) & 0x1F

        if len(self._buf) < 1 + payload_size:
            return None  # Wait for complete packet

        raw = bytes(self._buf[: 1 + payload_size])
        data = bytes(self._buf[1: 1 + payload_size])
        del self._buf[: 1 + payload_size]

        return ITMPacket(
            packet_type=ITMPacketType.STIMULUS,
            channel=channel,
            data=data,
            timestamp=self._last_timestamp,
            raw=raw,
        )

    def _parse_hardware_packet(self) -> Optional[ITMPacket]:
        """Parse hardware source packet (DWT, exception trace).
        
        Hardware packets always have ss=11 (bits [1:0] = 0b11).
        The discriminator is in bits [7:4].
        For exception trace (discriminator = 0x1), payload is 2 bytes:
        - Byte 1: exception number (0-511)
        - Byte 2: event type (bits [1:0])
        """
        if len(self._buf) < 1:
            return None

        header = self._buf[0]
        
        # Hardware source packet discriminator in bits [7:4]
        hw_source = (header >> 4) & 0x0F

        # Exception trace: discriminator = 0x1, fixed 2-byte payload
        if hw_source == 0x1:
            if len(self._buf) < 3:  # Header + 2 payload bytes
                return None
            
            raw = bytes(self._buf[:3])
            exception_num = self._buf[1]
            event_type = self._buf[2] & 0x03
            del self._buf[:3]

            try:
                event = ExceptionEvent(event_type)
            except ValueError:
                event = None

            return ITMPacket(
                packet_type=ITMPacketType.HARDWARE,
                exception_num=exception_num,
                exception_event=event,
                data=bytes([exception_num, event_type]),
                timestamp=self._last_timestamp,
                raw=raw,
            )

        # Other hardware source packets (variable payload size)
        # For now, consume 2 bytes (header + 1 payload) as minimum
        if len(self._buf) < 2:
            return None
        
        raw = bytes(self._buf[:2])
        payload = bytes(self._buf[1:2])
        del self._buf[:2]
        
        return ITMPacket(
            packet_type=ITMPacketType.HARDWARE,
            data=payload,
            timestamp=self._last_timestamp,
            raw=raw,
        )

    def _parse_timestamp_packet(self) -> Optional[ITMPacket]:
        """Parse local timestamp packet (variable-length continuation format)."""
        if len(self._buf) < 1:
            return None

        header = self._buf[0]
        timestamp = 0
        offset = 1

        # Continuation byte format: bit 7 = 1 for more bytes
        while offset < len(self._buf):
            byte = self._buf[offset]
            timestamp |= (byte & 0x7F) << (7 * (offset - 1))
            offset += 1
            if (byte & 0x80) == 0:  # No continuation bit
                break

        if offset == 1 or (offset < len(self._buf) and (self._buf[offset - 1] & 0x80)):
            return None  # Incomplete timestamp

        raw = bytes(self._buf[:offset])
        del self._buf[:offset]

        self._last_timestamp = timestamp

        return ITMPacket(
            packet_type=ITMPacketType.TIMESTAMP,
            timestamp=timestamp,
            raw=raw,
        )

    def _parse_global_timestamp_packet(self) -> Optional[ITMPacket]:
        """Parse global timestamp packet (GTS1 or GTS2)."""
        # Similar to local timestamp but with different header encoding
        # For simplicity, treat as local timestamp (decoder extension point)
        return self._parse_timestamp_packet()

    def _parse_extension_packet(self) -> Optional[ITMPacket]:
        """Parse extension packet."""
        if len(self._buf) < 2:
            return None

        # Extension packets have variable length; for now, consume 2 bytes
        raw = bytes(self._buf[:2])
        del self._buf[:2]

        return ITMPacket(
            packet_type=ITMPacketType.EXTENSION,
            raw=raw,
        )

    def reset(self) -> None:
        """Reset decoder state (e.g., on target reset or resync)."""
        self._buf.clear()
        self._last_timestamp = None
        self._sync_count = 0


# =============================================================================
# Exception Tracer
# =============================================================================

class ExceptionTracer:
    """Logs interrupt entry/exit with timing from ITM exception trace packets."""

    def __init__(self, log_path: Optional[Path] = None):
        self._log_path = log_path
        self._log_f: Optional[IO] = None
        self._exception_stack: dict[int, int] = {}  # exception_num → entry_timestamp
        self._traces: list[ExceptionTrace] = []

    def feed(self, packet: ITMPacket) -> Optional[ExceptionTrace]:
        """Process an ITM packet and return exception trace if applicable.

        Args:
            packet: Decoded ITM packet

        Returns:
            ExceptionTrace if packet is an exception event, else None
        """
        if packet.packet_type != ITMPacketType.HARDWARE:
            return None
        if packet.exception_num is None or packet.exception_event is None:
            return None

        exception_num = packet.exception_num
        event = packet.exception_event
        timestamp = packet.timestamp

        elapsed_us = None

        if event == ExceptionEvent.ENTER:
            self._exception_stack[exception_num] = timestamp or 0
        elif event == ExceptionEvent.EXIT:
            entry_ts = self._exception_stack.pop(exception_num, None)
            if entry_ts is not None and timestamp is not None:
                elapsed_us = float(timestamp - entry_ts)

        trace = ExceptionTrace(
            exception_num=exception_num,
            event=event,
            timestamp=timestamp,
            elapsed_us=elapsed_us,
        )

        self._traces.append(trace)
        self._write_trace(trace)

        return trace

    def _write_trace(self, trace: ExceptionTrace) -> None:
        """Append exception trace to log file."""
        if self._log_path is None:
            return

        try:
            if self._log_f is None or self._log_f.closed:
                self._log_f = open(self._log_path, "a", encoding="utf-8", buffering=1)

            event_str = trace.event.name.lower()
            ts_str = f"{trace.timestamp}" if trace.timestamp is not None else "None"
            elapsed_str = f"{trace.elapsed_us:.2f}" if trace.elapsed_us is not None else "N/A"

            line = f"[{ts_str}] Exception {trace.exception_num:3d} {event_str:6s} elapsed={elapsed_str} µs\n"
            self._log_f.write(line)
        except OSError as e:
            logger.warning("Failed to write exception trace: %s", e)

    def get_traces(self) -> list[ExceptionTrace]:
        """Return all collected exception traces."""
        return self._traces.copy()

    def reset(self) -> None:
        """Clear exception stack and traces."""
        self._exception_stack.clear()
        self._traces.clear()

    def close(self) -> None:
        """Close log file handle."""
        if self._log_f and not self._log_f.closed:
            try:
                self._log_f.close()
            except OSError:
                pass
        self._log_f = None


# =============================================================================
# SWO Capture (J-Link and OpenOCD)
# =============================================================================

def _pid_alive(pid: int) -> bool:
    try:
        os.kill(pid, 0)
        return True
    except OSError:
        return False


class SWOCapture:
    """Captures SWO data via J-Link or OpenOCD and writes to log files.

    Manages background process for SWO capture (JLinkSWOViewerCLExe or OpenOCD
    with tpiu config). Writes raw SWO data to bin file and decoded ITM text to log.
    """

    def __init__(
        self,
        base_dir: str | Path,
        decoder: Optional[ITMDecoder] = None,
        exception_tracer: Optional[ExceptionTracer] = None,
    ):
        self.base_dir = Path(base_dir)
        self.base_dir.mkdir(parents=True, exist_ok=True)

        self.pid_path = self.base_dir / "swo.pid"
        self.status_path = self.base_dir / "swo.status.json"
        self.log_path = self.base_dir / "swo.log"
        self.bin_path = self.base_dir / "swo.bin"
        self.err_path = self.base_dir / "swo.err"
        self.exceptions_path = self.base_dir / "swo_exceptions.log"

        self._decoder = decoder or ITMDecoder()
        self._exception_tracer = exception_tracer or ExceptionTracer(self.exceptions_path)

        self._log_f: Optional[IO] = None
        self._bin_f: Optional[IO] = None

    def status(self) -> SWOStatus:
        """Get current SWO capture status."""
        pid = self._read_pid(self.pid_path)
        running = bool(pid) and _pid_alive(pid)
        if pid and not running:
            self._cleanup_pid(self.pid_path)
            pid = None

        device = None
        swo_freq = None
        cpu_freq = None
        status_data = self._read_status_file(self.status_path)
        if status_data:
            device = status_data.get("device")
            swo_freq = status_data.get("swo_freq")
            cpu_freq = status_data.get("cpu_freq")

        return SWOStatus(
            running=running,
            pid=pid,
            device=device,
            swo_freq=swo_freq,
            cpu_freq=cpu_freq,
            log_path=str(self.log_path),
            bin_path=str(self.bin_path),
        )

    def start_jlink(
        self,
        device: str,
        swo_freq: int = 4000000,
        cpu_freq: int = 128000000,
        itm_port: int = 0,
    ) -> SWOStatus:
        """Start SWO capture via JLinkSWOViewerCLExe.

        Args:
            device: J-Link device string (e.g., NRF5340_XXAA_APP)
            swo_freq: SWO frequency in Hz (default 4 MHz)
            cpu_freq: CPU frequency in Hz (default 128 MHz for nRF5340)
            itm_port: ITM port number (default 0)

        Returns:
            SWOStatus with running state and process info
        """
        cur = self.status()
        if cur.running:
            return cur

        cmd = [
            "JLinkSWOViewerCLExe",
            "-device", device,
            "-itmport", str(itm_port),
            "-swofreq", str(swo_freq),
            "-cpufreq", str(cpu_freq),
        ]

        return self._start_process(
            cmd=cmd,
            device=device,
            swo_freq=swo_freq,
            cpu_freq=cpu_freq,
        )

    def start_openocd(
        self,
        telnet_port: int = 4444,
        swo_freq: int = 4000000,
        cpu_freq: int = 128000000,
    ) -> SWOStatus:
        """Start SWO capture via OpenOCD tpiu config.

        Sends OpenOCD commands to configure TPIU for SWO output. Requires
        OpenOCD to already be running with a connected target.

        Args:
            telnet_port: OpenOCD telnet port (default 4444)
            swo_freq: SWO frequency in Hz (default 4 MHz)
            cpu_freq: CPU frequency in Hz (default 128 MHz)

        Returns:
            SWOStatus with configuration status

        Note:
            This implementation is a placeholder. Full OpenOCD SWO capture
            requires tpiu config commands and port redirection, which varies
            by probe and chip. Recommended to use J-Link for SWO.
        """
        # OpenOCD SWO configuration is complex and probe-dependent.
        # For MVP, we'll just validate that OpenOCD is running and
        # return a status indicating manual configuration is needed.
        logger.warning(
            "OpenOCD SWO capture requires manual tpiu configuration. "
            "Use J-Link SWO or configure OpenOCD tpiu manually via telnet."
        )
        return SWOStatus(
            running=False,
            pid=None,
            device=None,
            swo_freq=swo_freq,
            cpu_freq=cpu_freq,
            log_path=str(self.log_path),
            bin_path=str(self.bin_path),
            last_error="OpenOCD SWO not implemented (use J-Link or manual config)",
        )

    def stop(self, timeout_s: float = 5.0) -> SWOStatus:
        """Stop SWO capture."""
        self._stop_process(self.pid_path, timeout_s)
        self._close_files()
        self._decoder.reset()
        self._exception_tracer.reset()

        status = SWOStatus(
            running=False,
            pid=None,
            device=None,
            swo_freq=None,
            cpu_freq=None,
            log_path=str(self.log_path),
            bin_path=str(self.bin_path),
        )
        self._write_status_file(self.status_path, {
            "running": False,
            "pid": None,
        })
        return status

    def tail(self, n: int = 50) -> list[str]:
        """Read last N lines from SWO log.

        Args:
            n: Number of lines to read

        Returns:
            List of lines (most recent last)
        """
        if not self.log_path.exists():
            return []

        try:
            with open(self.log_path, "r", encoding="utf-8", errors="replace") as f:
                lines = f.readlines()
            return [line.rstrip() for line in lines[-n:]]
        except OSError:
            return []

    def process_swo_data(self, data: bytes) -> None:
        """Process raw SWO data through decoder and write to logs.

        This method is called by the capture loop to decode and log ITM packets.

        Args:
            data: Raw SWO bytes from capture source
        """
        # Write raw data to bin file
        if self._bin_f is None or self._bin_f.closed:
            self._bin_f = open(self.bin_path, "ab")
        self._bin_f.write(data)
        self._bin_f.flush()  # Ensure data is written immediately

        # Decode ITM packets
        packets = self._decoder.feed(data)

        for packet in packets:
            # Write stimulus port 0 (printf) to text log
            if packet.packet_type == ITMPacketType.STIMULUS and packet.channel == ITM_PRINTF_CHANNEL:
                if packet.data:
                    self._write_log(packet.data.decode("utf-8", errors="replace"))

            # Feed to exception tracer
            trace = self._exception_tracer.feed(packet)
            if trace:
                logger.debug("Exception trace: %s", trace)

    def _write_log(self, text: str) -> None:
        """Write decoded text to SWO log file."""
        if self._log_f is None or self._log_f.closed:
            self._log_f = open(self.log_path, "a", encoding="utf-8", buffering=1)
        self._log_f.write(text)
        self._log_f.flush()  # Ensure data is written immediately

    def _close_files(self) -> None:
        """Close all file handles."""
        for f in (self._log_f, self._bin_f):
            if f and not f.closed:
                try:
                    f.close()
                except OSError:
                    pass
        self._log_f = self._bin_f = None
        self._exception_tracer.close()

    def _start_process(
        self,
        *,
        cmd: list[str],
        device: str,
        swo_freq: int,
        cpu_freq: int,
    ) -> SWOStatus:
        """Generic background process launcher for SWO capture."""
        log_f = open(self.log_path, "w", encoding="utf-8")
        err_f = open(self.err_path, "w", encoding="utf-8")

        try:
            proc = subprocess.Popen(
                cmd,
                stdin=subprocess.DEVNULL,
                stdout=log_f,
                stderr=err_f,
                cwd=str(self.base_dir),
                start_new_session=True,
            )
        finally:
            log_f.close()
            err_f.close()

        self.pid_path.write_text(str(proc.pid))

        time.sleep(0.5)
        alive = _pid_alive(proc.pid) and (proc.poll() is None)
        last_error: Optional[str] = None

        if not alive:
            try:
                err_lines = self.err_path.read_text(encoding="utf-8", errors="replace").splitlines()[-20:]
                last_error = "\n".join(err_lines).strip() or None
            except Exception:
                last_error = None
            self._cleanup_pid(self.pid_path)

        status = SWOStatus(
            running=alive,
            pid=proc.pid if alive else None,
            device=device,
            swo_freq=swo_freq,
            cpu_freq=cpu_freq,
            log_path=str(self.log_path),
            bin_path=str(self.bin_path),
            last_error=last_error,
        )

        payload = {
            "running": alive,
            "pid": proc.pid if alive else None,
            "device": device,
            "swo_freq": swo_freq,
            "cpu_freq": cpu_freq,
            "last_error": last_error,
            "timestamp": time.strftime("%Y-%m-%dT%H:%M:%S", time.localtime()),
        }
        self._write_status_file(self.status_path, payload)

        return status

    def _stop_process(self, pid_path: Path, timeout_s: float = 5.0) -> None:
        """Generic background process stopper."""
        pid = self._read_pid(pid_path)
        if not pid or not _pid_alive(pid):
            self._cleanup_pid(pid_path)
            return

        try:
            os.kill(pid, signal.SIGTERM)
        except OSError:
            pass

        deadline = time.time() + timeout_s
        while time.time() < deadline:
            if not _pid_alive(pid):
                break
            time.sleep(0.1)

        if _pid_alive(pid):
            try:
                os.kill(pid, signal.SIGKILL)
            except OSError:
                pass

        self._cleanup_pid(pid_path)

    def _read_pid(self, path: Path) -> Optional[int]:
        """Read PID from a file, return None if missing or invalid."""
        if not path.exists():
            return None
        try:
            return int(path.read_text().strip())
        except (ValueError, OSError):
            return None

    def _cleanup_pid(self, path: Path) -> None:
        """Remove a PID file if it exists."""
        try:
            path.unlink(missing_ok=True)
        except OSError:
            pass

    def _read_status_file(self, path: Path) -> Optional[dict]:
        """Read JSON status file, return None if missing or invalid."""
        if not path.exists():
            return None
        try:
            return json.loads(path.read_text(encoding="utf-8"))
        except (json.JSONDecodeError, OSError):
            return None

    def _write_status_file(self, path: Path, data: dict) -> None:
        """Write JSON status file."""
        path.write_text(json.dumps(data, indent=2, sort_keys=True))
