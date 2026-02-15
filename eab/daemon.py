#!/usr/bin/env python3
"""
Embedded Agent Bridge - Serial Daemon

A reliable serial daemon with file-based agent interface.
Designed for LLM agents to interact with embedded devices.

Usage:
    python3 -m eab --port /dev/ttyUSB0 --baud 115200
    python3 -m eab --port auto --base-dir /tmp/eab-devices/default
"""

import argparse
import signal
import sys
import os
import json
import base64
import re
from typing import Optional

from .implementations import RealSerialPort, RealFileSystem, RealClock, ConsoleLogger
from .command_file import append_command, drain_commands
from .reconnection import ReconnectionManager
from .session_logger import SessionLogger, LogRotationConfig
from .pattern_matcher import PatternMatcher, AlertLogger
from .status_manager import StatusManager
from .event_emitter import EventEmitter
from .data_stream import DataStreamWriter
from .reset_reason import ResetReasonTracker
from .interfaces import (
    ClockInterface,
    ConnectionState,
    FileSystemInterface,
    LoggerInterface,
    SerialPortInterface,
)
from .device_control import DeviceController
from .log_sanitize import sanitize_serial_bytes
from .port_lock import PortLock, find_port_users, list_all_locks
from .chip_recovery import ChipRecovery, ChipState
from .singleton import SingletonDaemon, check_singleton


class SerialDaemon:
    """
    Main serial daemon that ties all components together.

    Components:
    - ReconnectionManager: Handles port connection/reconnection
    - SessionLogger: Writes timestamped logs
    - PatternMatcher: Detects alert patterns
    - AlertLogger: Writes alerts to separate file
    - StatusManager: Writes status.json for agents
    """

    def __init__(
        self,
        port: str,
        baud: int = 115200,
        base_dir: str = "/tmp/eab-devices/default",
        auto_detect: bool = True,
        *,
        serial_port: Optional[SerialPortInterface] = None,
        filesystem: Optional[FileSystemInterface] = None,
        clock: Optional[ClockInterface] = None,
        logger: Optional[LoggerInterface] = None,
        log_max_size_mb: int = 100,
        log_max_files: int = 5,
        log_compress: bool = True,
        device_name: str = "",
    ):
        self._port = port
        self._baud = baud
        self._base_dir = base_dir
        self._auto_detect = auto_detect
        self._running = False
        self._device_name = device_name

        # Implementations (allow injection for tests)
        self._serial = serial_port or RealSerialPort()
        self._fs = filesystem or RealFileSystem()
        self._clock = clock or RealClock()
        self._logger = logger or ConsoleLogger()

        # Ensure base directory exists
        self._fs.ensure_dir(base_dir)

        # Create components
        self._reconnection = ReconnectionManager(
            serial_port=self._serial,
            clock=self._clock,
            logger=self._logger,
            port_name=self._resolve_port(),
            baud=baud,
            on_reconnect=self._on_reconnect,
            on_disconnect=self._on_disconnect,
        )

        self._session_logger = SessionLogger(
            filesystem=self._fs,
            clock=self._clock,
            base_dir=base_dir,
            rotation_config=LogRotationConfig(
                max_size_bytes=log_max_size_mb * 1_000_000,
                max_files=log_max_files,
                compress=log_compress,
            ),
        )

        self._pattern_matcher = PatternMatcher(
            clock=self._clock,
            load_defaults=True,
        )

        self._alert_logger = AlertLogger(
            filesystem=self._fs,
            clock=self._clock,
            alerts_path=os.path.join(base_dir, "alerts.log"),
        )

        self._status_manager = StatusManager(
            filesystem=self._fs,
            clock=self._clock,
            status_path=os.path.join(base_dir, "status.json"),
        )

        self._events = EventEmitter(
            filesystem=self._fs,
            clock=self._clock,
            events_path=os.path.join(base_dir, "events.jsonl"),
        )

        self._reset_tracker = ResetReasonTracker(
            clock=self._clock,
        )

        # Command file path
        self._cmd_path = os.path.join(base_dir, "cmd.txt")
        self._cmd_mtime = 0.0

        # Stream config path (high-speed data mode)
        self._stream_path = os.path.join(base_dir, "stream.json")
        self._stream_mtime = 0.0
        self._stream_enabled = False
        self._stream_active = False
        self._stream_mode = "raw"
        self._stream_chunk_size = 16384
        self._stream_marker: Optional[str] = None
        self._stream_pattern_matching = True
        self._data_stream = DataStreamWriter(
            filesystem=self._fs,
            clock=self._clock,
            data_path=os.path.join(base_dir, "data.bin"),
        )

        # Pause file path - write seconds to this file to pause daemon
        self._pause_path = os.path.join(base_dir, "pause.txt")
        self._paused = False
        self._pause_start_time: Optional[float] = None
        self._original_port: Optional[str] = None  # Track original port for resume

        # File transfer guardrails (prevents false crash/watchdog detection on base64 payload lines)
        self._file_transfer_active = False
        self._file_transfer_in_data = False

        # Device controller for special commands (!RESET, !FLASH, etc.)
        self._device_controller = DeviceController(
            serial_port=self._serial,
            port_name=self._resolve_port(),
            baud=baud,
            logger=self._logger,
            on_flash_start=self._on_flash_start,
            on_flash_end=self._on_flash_end,
        )

        # Port lock to prevent contention
        self._port_lock: Optional[PortLock] = None

        # Singleton enforcement (one daemon per machine)
        self._singleton: Optional[SingletonDaemon] = None

        # Chip recovery for automatic crash handling
        self._chip_recovery = ChipRecovery(
            reset_callback=self._device_controller.reset,
            logger=self._logger,
            boot_loop_threshold=5,
            stuck_timeout=120.0,  # 2 minutes without output = stuck
            crash_recovery_delay=2.0,
            max_recovery_attempts=3,
        )
        self._chip_recovery.set_callbacks(
            on_state_change=self._on_chip_state_change,
            on_crash_detected=self._on_crash_detected,
        )
        self._auto_recovery = True  # Enable automatic recovery

    def _emit_event(self, event_type: str, data: Optional[dict] = None, level: str = "info") -> None:
        try:
            self._events.emit(event_type, data=data or {}, level=level)
        except Exception as e:
            self._logger.debug(f"Event emit failed: {e}")

    def _resolve_port(self) -> str:
        """Resolve 'auto' to an actual serial port.

        If multiple candidates match, attempt to probe each candidate using
        `esptool` to find an Espressif bootloader-capable port. This helps on
        dual-interface USB devices (e.g. FTDI dual channels) where only one of
        the exposed serial ports is wired to UART0.
        """
        if self._port.lower() == "auto" and self._auto_detect:
            ports = self._serial.list_ports()

            # ESP32 USB identifiers (prioritized)
            esp32_patterns = [
                # Native USB (ESP32-S2, S3, C3, C6, P4)
                "usbmodem",
                # CP210x (most common ESP32 dev boards)
                "cp210",
                "silicon_labs",
                "silabs",
                # CH340/CH341 (cheap ESP32 boards)
                "ch340",
                "ch341",
                "wch",
                # FTDI (some dev boards)
                "ftdi",
                "ft232",
                # Generic USB serial
                "usbserial",
                "usb",
            ]

            # Collect candidates in priority order.
            candidates: list[str] = []
            for pattern in esp32_patterns:
                for p in ports:
                    device_lower = p.device.lower()
                    desc_lower = p.description.lower()
                    hwid_lower = p.hwid.lower()

                    if (pattern in device_lower or
                        pattern in desc_lower or
                        pattern in hwid_lower):
                        # Skip Bluetooth and debug ports
                        if "bluetooth" in desc_lower or "debug-console" in device_lower:
                            continue
                        candidates.append(p.device)

            # De-duplicate while preserving order.
            unique_candidates: list[str] = []
            seen: set[str] = set()
            for dev in candidates:
                if dev in seen:
                    continue
                seen.add(dev)
                unique_candidates.append(dev)

            if not unique_candidates:
                self._logger.warning("No ESP32 serial port found")
                return self._port

            if len(unique_candidates) == 1:
                chosen = unique_candidates[0]
                self._logger.info(f"Auto-detected ESP32 port: {chosen}")
                return chosen

            # Multiple candidates: try probing with esptool (fast, reliable).
            try:
                import shutil
                import subprocess

                esptool = shutil.which("esptool") or shutil.which("esptool.py")
                if esptool:
                    for dev in unique_candidates:
                        try:
                            self._logger.info(f"Probing candidate port with esptool: {dev}")
                            result = subprocess.run(
                                [esptool, "--port", dev, "chip-id"],
                                capture_output=True,
                                text=True,
                                timeout=10,
                            )
                            combined = (result.stdout or "") + "\n" + (result.stderr or "")
                            if result.returncode == 0 and "ESP32" in combined:
                                self._logger.info(f"Auto-detected ESP32 port via probe: {dev}")
                                return dev
                        except Exception as e:
                            self._logger.debug(f"Probe failed for {dev}: {e}")
            except Exception:
                pass

            # Fallback heuristic: choose the candidate with the highest numeric suffix.
            try:
                import re

                def score(dev: str) -> tuple[int, str]:
                    m = re.search(r"(\\d+)$", dev)
                    return (int(m.group(1)) if m else -1, dev)

                chosen = max(unique_candidates, key=score)
            except Exception:
                chosen = unique_candidates[0]

            self._logger.warning(
                "Multiple candidate ports matched; falling back to: "
                f"{chosen} (candidates={unique_candidates})"
            )
            return chosen

        return self._port

    def _on_reconnect(self) -> None:
        """Called when reconnection succeeds."""
        self._status_manager.record_reconnect()
        self._logger.info("Reconnected to device")
        self._emit_event("reconnect", {"port": self._reconnection._port_name})

    def _on_disconnect(self) -> None:
        """Called when disconnect detected."""
        self._status_manager.set_connection_state(ConnectionState.RECONNECTING)
        self._status_manager.record_usb_disconnect()
        self._logger.warning("Connection lost")
        self._emit_event("disconnect", {"port": self._reconnection._port_name}, level="warn")

    def _on_flash_start(self) -> None:
        """Called when flash operation starts (need to release port)."""
        self._status_manager.set_connection_state(ConnectionState.DISCONNECTED)
        self._logger.info("Flash starting, releasing port...")
        self._emit_event("flash_start", {"port": self._reconnection._port_name})

    def _on_flash_end(self, success: bool) -> None:
        """Called when flash operation ends."""
        if success:
            self._status_manager.set_connection_state(ConnectionState.CONNECTED)
            self._logger.info("Flash complete, port reacquired")
            self._emit_event("flash_end", {"success": True, "port": self._reconnection._port_name})
        else:
            self._logger.error("Flash failed")
            self._emit_event("flash_end", {"success": False, "port": self._reconnection._port_name}, level="error")

    def _on_chip_state_change(self, old_state: ChipState, new_state: ChipState) -> None:
        """Called when chip state changes."""
        self._logger.info(f"Chip state: {old_state.value} -> {new_state.value}")
        # Log to session
        self._session_logger.log_line(f"[EAB] Chip state: {new_state.value}")
        self._emit_event(
            "chip_state",
            {"from": old_state.value, "to": new_state.value},
        )

    def _on_crash_detected(self, line: str) -> None:
        """Called when a crash is detected."""
        self._logger.error(f"Crash detected!")
        # Log to alerts
        self._session_logger.log_line(f"[EAB] CRASH DETECTED: {line[:100]}")
        self._emit_event("crash_detected", {"line": line[:200]}, level="error")

    def start(self, force: bool = False) -> bool:
        """Start the daemon. Returns True if started successfully.

        Args:
            force: If True, kill any existing daemon first
        """
        self._logger.info(f"Starting Embedded Agent Bridge Serial Daemon")
        self._logger.info(f"Port: {self._reconnection._port_name}, Baud: {self._baud}")
        self._logger.info(f"Base directory: {self._base_dir}")
        self._emit_event(
            "daemon_starting",
            {
                "port": self._reconnection._port_name,
                "baud": self._baud,
                "base_dir": self._base_dir,
                "pid": os.getpid(),
            },
        )

        port_name = self._reconnection._port_name

        # Singleton enforcement - one daemon per device (or one global if no device_name)
        self._singleton = SingletonDaemon(logger=self._logger, device_name=self._device_name)
        if not self._singleton.acquire(kill_existing=force, port=port_name, base_dir=self._base_dir):
            self._emit_event("daemon_start_failed", {"reason": "singleton"})
            return False

        # Check for port contention BEFORE connecting
        self._logger.info(f"Checking for port contention...")
        existing_users = find_port_users(port_name)
        if existing_users:
            self._logger.warning(f"Port {port_name} may be in use by other processes:")
            for user in existing_users:
                self._logger.warning(f"  PID {user['pid']}: {user['name']}")

        # Check existing EAB locks
        existing_locks = list_all_locks()
        for lock in existing_locks:
            if lock.port == port_name:
                self._logger.warning(
                    f"Port {port_name} locked by EAB PID {lock.pid} "
                    f"({lock.process_name}) since {lock.started}"
                )

        # Try to acquire our own lock
        self._port_lock = PortLock(port_name, logger=self._logger)
        if not self._port_lock.acquire(timeout=0, force=True):
            self._logger.error(f"Could not acquire lock for {port_name}")
            owner = self._port_lock.get_owner()
            if owner:
                self._logger.error(
                    f"Port locked by PID {owner.pid} ({owner.process_name})"
                )
            self._emit_event("daemon_start_failed", {"reason": "port_lock", "port": port_name}, level="error")
            return False
        self._emit_event("port_lock_acquired", {"port": port_name})

        # Connect to serial port
        if not self._reconnection.connect():
            self._logger.error("Failed to connect to serial port")
            self._port_lock.release()
            self._emit_event("daemon_start_failed", {"reason": "connect_failed", "port": port_name}, level="error")
            return False

        # Generate session ID
        session_id = self._clock.now().strftime("serial_%Y-%m-%d_%H-%M-%S")

        # Start session
        self._session_logger.start_session(
            port=self._reconnection._port_name,
            baud=self._baud,
        )

        self._status_manager.start_session(
            session_id=session_id,
            port=self._reconnection._port_name,
            baud=self._baud,
        )
        
        # Reset pattern counts for fresh session
        self._pattern_matcher.reset_counts()
        
        self._status_manager.set_connection_state(ConnectionState.CONNECTED)
        self._status_manager.set_stream_state(
            enabled=self._stream_enabled,
            active=self._stream_active,
            mode=self._stream_mode,
            chunk_size=self._stream_chunk_size,
            marker=self._stream_marker,
            pattern_matching=self._stream_pattern_matching,
        )
        self._events.set_session_id(session_id)
        self._emit_event(
            "daemon_started",
            {
                "session_id": session_id,
                "port": self._reconnection._port_name,
                "baud": self._baud,
                "base_dir": self._base_dir,
                "pid": os.getpid(),
            },
        )

        # Clear command file
        self._fs.write_file(self._cmd_path, "")

        self._running = True
        self._logger.info("Daemon started successfully")
        self._logger.info(f"Command file: {self._cmd_path}")

        return True

    def run(self) -> None:
        """Main daemon loop."""
        last_status_update = 0.0
        status_update_interval = 1.0  # Update status every second

        while self._running:
            try:
                # Check for pause request
                if self._check_pause():
                    continue

                # Check for stream config updates
                self._check_stream_config()

                # Check connection
                if not self._reconnection.check_and_reconnect():
                    self._clock.sleep(0.1)
                    continue

                # High-speed data mode (raw)
                if self._stream_enabled and self._stream_active and self._stream_mode == "raw":
                    chunk = self._serial.read_bytes(self._stream_chunk_size)
                    if chunk:
                        meta = self._data_stream.append(chunk)
                        self._status_manager.record_bytes(len(chunk))
                        self._status_manager.record_activity(len(chunk))
                        self._emit_event("data_chunk", meta)
                    else:
                        # Avoid busy spin when no data
                        self._clock.sleep(0.0005)
                # High-speed data mode (base64 lines)
                elif self._stream_enabled and self._stream_active and self._stream_mode == "base64":
                    data = self._serial.read_line()
                    if data:
                        try:
                            line = sanitize_serial_bytes(data)
                            if line:
                                try:
                                    raw = base64.b64decode(line, validate=True)
                                except Exception:
                                    raw = b""
                                if raw:
                                    meta = self._data_stream.append(raw)
                                    self._status_manager.record_bytes(len(raw))
                                    self._status_manager.record_activity(len(raw))
                                    self._emit_event("data_chunk", meta)
                        except Exception as e:
                            self._logger.error(f"Error processing base64 stream: {e}")
                    else:
                        self._clock.sleep(0.0005)
                else:
                    # Read serial data line-by-line
                    data = self._serial.read_line()
                    if data:
                        try:
                            line = sanitize_serial_bytes(data)
                            if line:
                                self._process_line(line)
                        except Exception as e:
                            self._logger.error(f"Error processing line: {e}")

                # Check for commands
                self._check_commands()

                # Update status periodically
                now = self._clock.timestamp()
                if now - last_status_update >= status_update_interval:
                    # Update reset statistics before writing status
                    self._status_manager.set_reset_statistics(self._reset_tracker.get_statistics())
                    self._status_manager.update()
                    last_status_update = now

                    # Check if chip needs recovery (automatic recovery)
                    if self._auto_recovery and self._chip_recovery.needs_recovery():
                        self._logger.warning("Chip needs recovery, performing automatic recovery...")
                        self._chip_recovery.perform_recovery()

                # Small sleep to prevent CPU spinning
                if not self._serial.bytes_available():
                    self._clock.sleep(0.001)

            except Exception as e:
                self._logger.error(f"Error in main loop: {e}")
                self._clock.sleep(0.1)

    def _check_pause(self) -> bool:
        """Check for pause request. Returns True if paused (caller should continue loop).

        Edge cases handled:
        - Port disappears during pause (USB unplugged)
        - Port changes during pause (different device)
        - Rapid pause/resume cycles
        - esptool holding port briefly after flash
        """
        try:
            if not self._fs.file_exists(self._pause_path):
                if self._paused:
                    # Pause file removed (early resume), resume now
                    self._resume_from_pause()
                return False

            content = self._fs.read_file(self._pause_path).strip()
            if not content:
                if self._paused:
                    self._resume_from_pause()
                return False

            # Parse pause duration
            try:
                pause_until = float(content)
            except ValueError:
                # Invalid content, remove file
                self._fs.write_file(self._pause_path, "")
                if self._paused:
                    self._resume_from_pause()
                return False

            now = self._clock.timestamp()
            if now >= pause_until:
                # Pause expired, remove file and resume
                self._fs.write_file(self._pause_path, "")
                if self._paused:
                    self._resume_from_pause()
                return False

            # We should be paused
            if not self._paused:
                remaining = int(pause_until - now)
                self._logger.info(f"PAUSING for {remaining}s - releasing serial port for flashing...")

                # Store original port name for later verification
                self._original_port = self._reconnection._port_name
                self._pause_start_time = now

                self._reconnection.disconnect()
                if self._port_lock:
                    self._port_lock.release()
                    self._port_lock = None
                self._status_manager.set_connection_state(ConnectionState.DISCONNECTED)

                # Log to session for agent visibility
                self._session_logger.log_line(f"[EAB] PAUSED - port {self._original_port} released for flashing")
                self._emit_event(
                    "paused",
                    {"port": self._original_port, "pause_until": pause_until},
                )

                self._paused = True

            # Sleep while paused (check more frequently near end of pause for responsiveness)
            remaining = pause_until - now
            sleep_time = 0.5 if remaining > 5 else 0.1
            self._clock.sleep(sleep_time)
            return True

        except Exception as e:
            self._logger.error(f"Error checking pause: {e}")
            return False

    def _resume_from_pause(self) -> None:
        """Resume from paused state - re-acquire lock and reconnect.

        Handles edge cases:
        - Port disappeared (USB unplugged)
        - Port changed (different device now)
        - esptool still holding port briefly
        - Port name changed after ESP32 reset
        """
        pause_duration = 0
        if self._pause_start_time:
            pause_duration = int(self._clock.timestamp() - self._pause_start_time)

        self._logger.info(f"Resuming from pause (was paused {pause_duration}s)...")

        # Check if original port still exists
        port_name = self._reconnection._port_name
        original_port = self._original_port or port_name

        # Give esptool/other tools time to release port (common race condition)
        self._clock.sleep(0.5)

        # Check if port exists using available ports list
        available_ports = [p.device for p in self._serial.list_ports()]

        if original_port not in available_ports:
            self._logger.warning(f"Original port {original_port} no longer exists!")
            self._logger.info(f"Available ports: {available_ports}")

            # Try to auto-detect a new ESP32 port
            if self._auto_detect:
                new_port = self._resolve_port()
                if new_port != self._port and new_port in available_ports:
                    self._logger.info(f"Auto-detected new port: {new_port}")
                    self._reconnection._port_name = new_port
                    port_name = new_port
                else:
                    self._logger.warning("No ESP32 port found, will retry on next loop...")
                    self._status_manager.set_connection_state(ConnectionState.RECONNECTING)
                    self._session_logger.log_line("[EAB] RESUME FAILED - port disappeared, waiting for reconnect")
                    self._emit_event(
                        "resume_failed",
                        {"reason": "port_disappeared", "original_port": original_port},
                        level="warn",
                    )
                    self._paused = False
                    self._pause_start_time = None
                    self._original_port = None
                    return 0

        # Re-acquire port lock with extended retries (esptool can hold port for a bit)
        self._port_lock = PortLock(port_name, logger=self._logger)

        lock_acquired = False
        for attempt in range(10):  # Extended retries for esptool cleanup
            if self._port_lock.acquire(timeout=0, force=True):
                lock_acquired = True
                break
            self._logger.warning(f"Port lock retry {attempt + 1}/10 (esptool may still be releasing)...")
            self._clock.sleep(0.5)

        if not lock_acquired:
            self._logger.error("Failed to re-acquire port lock after pause")
            # Check who's holding the port
            port_users = find_port_users(port_name)
            if port_users:
                for user in port_users:
                    self._logger.warning(f"  Port held by PID {user['pid']}: {user['name']}")
            # Continue anyway, reconnection may still work
            self._emit_event(
                "resume_lock_failed",
                {"port": port_name, "users": port_users},
                level="warn",
            )

        # Reconnect to serial port
        if self._reconnection.connect():
            self._status_manager.set_connection_state(ConnectionState.CONNECTED)
            self._logger.info("Resumed successfully - serial port reconnected")
            self._session_logger.log_line(f"[EAB] RESUMED - connected to {port_name}")
            self._emit_event(
                "resumed",
                {"port": port_name, "pause_duration_s": pause_duration},
            )
        else:
            self._logger.warning("Resume: reconnection pending, will retry...")
            self._status_manager.set_connection_state(ConnectionState.RECONNECTING)
            self._session_logger.log_line("[EAB] RESUME - reconnection pending")
            self._emit_event(
                "resume_pending",
                {"port": port_name, "pause_duration_s": pause_duration},
                level="warn",
            )

        self._paused = False
        self._pause_start_time = None
        self._original_port = None

    def _process_line(self, line: str) -> None:
        """Process a received line."""
        # Track file transfer mode (serial file download protocol).
        if "===FILE_START===" in line:
            self._file_transfer_active = True
            self._file_transfer_in_data = False
        elif self._file_transfer_active and "===DATA===" in line:
            self._file_transfer_in_data = True
        elif self._file_transfer_active and "===FILE_END===" in line:
            self._file_transfer_active = False
            self._file_transfer_in_data = False

        # If we're inside the DATA section and this line looks like pure base64 payload,
        # skip chip health/pattern processing to avoid accidental substring matches (e.g. "WDT").
        suppress_health = False
        if self._file_transfer_in_data:
            payload = line.strip()
            if payload and re.fullmatch(r"[A-Za-z0-9+/=]{20,}", payload):
                suppress_health = True

        # Check for stream marker to enable high-speed mode.
        if (
            self._stream_enabled
            and not self._stream_active
            and self._stream_marker
            and self._stream_marker in line
        ):
            self._stream_active = True
            self._status_manager.set_stream_state(
                enabled=self._stream_enabled,
                active=self._stream_active,
                mode=self._stream_mode,
                chunk_size=self._stream_chunk_size,
                marker=self._stream_marker,
                pattern_matching=self._stream_pattern_matching,
            )
            self._emit_event(
                "stream_started",
                {
                    "marker": self._stream_marker,
                    "mode": self._stream_mode,
                    "chunk_size": self._stream_chunk_size,
                },
            )

        # Log the line
        self._session_logger.log_line(line)
        self._status_manager.record_line()
        byte_count = len(line)
        self._status_manager.record_bytes(byte_count)
        self._status_manager.record_activity(byte_count)

        # Feed to chip recovery for state monitoring (unless this is base64 payload data)
        if not suppress_health:
            self._chip_recovery.process_line(line)

        # Check for reset reasons
        if not suppress_health:
            reset_event = self._reset_tracker.check_line(line)
            if reset_event:
                # Emit event for reset detection
                self._emit_event(
                    "reset_detected",
                    {
                        "reason": reset_event.reason,
                        "timestamp": reset_event.timestamp.isoformat(),
                        "raw_line": reset_event.raw_line[:200],
                    },
                    level="info" if not self._reset_tracker.is_unexpected_reset(reset_event.reason) else "warn",
                )
                
                # Alert on unexpected resets
                if self._reset_tracker.is_unexpected_reset(reset_event.reason):
                    self._logger.warning(f"Unexpected reset: {reset_event.reason}")

        # Check for patterns
        if self._stream_pattern_matching and not suppress_health:
            matches = self._pattern_matcher.check_line(line)
            for match in matches:
                self._alert_logger.log_alert(match)
                self._status_manager.record_alert(match.pattern)
                self._emit_event(
                    "alert",
                    {"pattern": match.pattern, "line": line[:200]},
                    level="warn",
                )

        # Print to console (line already sanitized/ANSI-stripped)
        print(line)

    def _check_commands(self) -> None:
        """Check for commands in the command file."""
        try:
            if not self._fs.file_exists(self._cmd_path):
                return 0

            mtime = self._fs.get_mtime(self._cmd_path)
            if mtime <= self._cmd_mtime:
                return 0

            commands = drain_commands(self._cmd_path)
            # Update mtime after truncation so we don't spin on our own clear.
            try:
                self._cmd_mtime = self._fs.get_mtime(self._cmd_path)
            except Exception:
                self._cmd_mtime = mtime

            for cmd in commands:
                self._send_command(cmd)

        except Exception as e:
            self._logger.error(f"Error checking commands: {e}")

    def _check_stream_config(self) -> None:
        """Check for high-speed stream configuration changes."""
        try:
            if not self._fs.file_exists(self._stream_path):
                if self._stream_enabled:
                    self._stream_enabled = False
                    self._stream_active = False
                    self._stream_marker = None
                    self._status_manager.set_stream_state(
                        enabled=False,
                        active=False,
                        mode=self._stream_mode,
                        chunk_size=self._stream_chunk_size,
                        marker=self._stream_marker,
                        pattern_matching=self._stream_pattern_matching,
                    )
                    self._emit_event("stream_disabled", {})
                return 0

            mtime = self._fs.get_mtime(self._stream_path)
            if mtime <= self._stream_mtime:
                return 0
            self._stream_mtime = mtime

            raw = self._fs.read_file(self._stream_path)
            cfg = json.loads(raw or "{}")

            enabled = bool(cfg.get("enabled", False))
            mode = str(cfg.get("mode", self._stream_mode or "raw")).lower()
            if mode not in {"raw", "base64"}:
                mode = "raw"
            chunk_size = int(cfg.get("chunk_size", self._stream_chunk_size) or self._stream_chunk_size)
            if chunk_size <= 0:
                chunk_size = 16384
            marker = cfg.get("marker")
            if marker is not None:
                marker = str(marker)

            pattern_matching = bool(cfg.get("pattern_matching", True))
            truncate = bool(cfg.get("truncate", False))

            if truncate:
                self._data_stream.truncate()
                self._emit_event("stream_truncated", {})

            self._stream_enabled = enabled
            self._stream_mode = mode
            self._stream_chunk_size = chunk_size
            self._stream_marker = marker
            self._stream_pattern_matching = pattern_matching
            if enabled:
                self._stream_active = False if marker else True
            else:
                self._stream_active = False

            self._status_manager.set_stream_state(
                enabled=self._stream_enabled,
                active=self._stream_active,
                mode=self._stream_mode,
                chunk_size=self._stream_chunk_size,
                marker=self._stream_marker,
                pattern_matching=self._stream_pattern_matching,
            )

            self._emit_event(
                "stream_config",
                {
                    "enabled": self._stream_enabled,
                    "active": self._stream_active,
                    "mode": self._stream_mode,
                    "chunk_size": self._stream_chunk_size,
                    "marker": self._stream_marker,
                    "pattern_matching": self._stream_pattern_matching,
                    "truncate": truncate,
                },
            )

            if self._stream_enabled and not self._stream_active and self._stream_marker:
                self._emit_event(
                    "stream_armed",
                    {"marker": self._stream_marker, "mode": self._stream_mode},
                )
            elif self._stream_enabled and self._stream_active:
                self._emit_event(
                    "stream_active",
                    {"mode": self._stream_mode, "chunk_size": self._stream_chunk_size},
                )
        except Exception as e:
            self._logger.error(f"Error checking stream config: {e}")

    def _send_command(self, cmd: str) -> None:
        """Send a command to the device (or handle special ! commands)."""
        self._logger.info(f"Sending command: {cmd}")
        self._session_logger.log_command(cmd)
        self._status_manager.record_command()
        self._emit_event(
            "command_sent",
            {"command": cmd, "special": self._device_controller.is_special_command(cmd)},
        )

        # Check for special commands (!RESET, !FLASH, etc.)
        if self._device_controller.is_special_command(cmd):
            result = self._device_controller.handle_command(cmd)
            self._logger.info(f"Special command result: {result}")
            # Log result to session
            self._session_logger.log_line(f"[EAB] {result}")
            self._emit_event("command_result", {"command": cmd, "result": result})
            return 0

        # Regular command - send to device
        data = (cmd + "\n").encode()
        self._serial.write(data)

    def stop(self) -> None:
        """Stop the daemon gracefully, leaving chip in good state."""
        self._logger.info("Stopping daemon...")
        self._running = False
        self._emit_event("daemon_stopping", {"pid": os.getpid()})

        # Perform clean shutdown to ensure chip is in good state
        try:
            self._chip_recovery.clean_shutdown()
        except Exception as e:
            self._logger.error(f"Error during chip cleanup: {e}")

        # End session
        self._session_logger.end_session()
        self._status_manager.set_connection_state(ConnectionState.DISCONNECTED)
        self._status_manager.update()

        # Disconnect
        self._reconnection.disconnect()

        # Release port lock
        if self._port_lock:
            self._port_lock.release()

        # Release singleton lock
        if self._singleton:
            self._singleton.release()

        self._logger.info("Daemon stopped")
        self._emit_event("daemon_stopped", {"pid": os.getpid()})


def main(argv: Optional[list[str]] = None) -> int:
    """Entry point for the EAB daemon CLI.

    Args:
        argv: Command-line arguments (defaults to sys.argv[1:])

    Returns:
        Exit code (0 for success, 1 for error)
    """
    parser = argparse.ArgumentParser(
        description="Embedded Agent Bridge - Serial Daemon",
        formatter_class=argparse.RawDescriptionHelpFormatter,
        epilog="""
Examples:
  python3 -m eab --port /dev/ttyUSB0
  python3 -m eab --port auto --baud 115200
  python3 -m eab --port /dev/cu.usbmodem123 --base-dir /tmp/eab-devices/default
        """,
    )

    parser.add_argument(
        "--version",
        action="version",
        version="%(prog)s 1.0.0 (embedded-agent-bridge)",
    )
    parser.add_argument(
        "--port", "-p",
        default="auto",
        help="Serial port (default: auto-detect)",
    )
    parser.add_argument(
        "--baud", "-b",
        type=int,
        default=115200,
        help="Baud rate (default: 115200)",
    )
    parser.add_argument(
        "--base-dir", "-d",
        default="/tmp/eab-devices/default",
        help="Base directory for logs and status files",
    )
    parser.add_argument(
        "--list", "-l",
        action="store_true",
        help="List available serial ports and exit",
    )
    parser.add_argument(
        "--force", "-f",
        action="store_true",
        help="Kill any existing daemon and take over",
    )
    parser.add_argument(
        "--status", "-s",
        action="store_true",
        help="Show status of existing daemon and exit",
    )
    parser.add_argument(
        "--stop",
        action="store_true",
        help="Stop any running daemon and exit",
    )
    parser.add_argument(
        "--pause",
        type=int,
        metavar="SECONDS",
        help="Pause daemon for N seconds (releases serial port for flashing)",
    )
    parser.add_argument(
        "--cmd",
        type=str,
        metavar="COMMAND",
        help="Send a command to the device via cmd.txt (use ! prefix for special commands)",
    )
    parser.add_argument(
        "--reset",
        action="store_true",
        help="Reset the ESP32 device (sends !RESET command)",
    )
    parser.add_argument(
        "--logs",
        type=int,
        nargs="?",
        const=50,
        metavar="LINES",
        help="Show last N lines from session log (default: 50)",
    )
    parser.add_argument(
        "--wait-for",
        type=str,
        metavar="PATTERN",
        help="Wait for a line matching pattern in log (exits when found)",
    )
    parser.add_argument(
        "--wait-timeout",
        type=int,
        default=30,
        metavar="SECONDS",
        help="Timeout for --wait-for (default: 30s)",
    )
    parser.add_argument(
        "--alerts",
        type=int,
        nargs="?",
        const=20,
        metavar="LINES",
        help="Show last N alert lines (default: 20)",
    )
    parser.add_argument(
        "--log-max-size",
        type=int,
        default=100,
        metavar="MB",
        help="Max log size in MB before rotation (default: 100)",
    )
    parser.add_argument(
        "--log-max-files",
        type=int,
        default=5,
        metavar="COUNT",
        help="Max rotated log files to keep (default: 5)",
    )
    parser.add_argument(
        "--no-log-compress",
        action="store_true",
        help="Disable compression of rotated logs",
    )
    parser.add_argument(
        "--device-name",
        default="",
        help="Device name for per-device singleton (e.g., esp32, nrf5340)",
    )

    args = parser.parse_args(argv)

    if args.list:
        print("Available serial ports:")
        for p in RealSerialPort.list_ports():
            print(f"  {p.device}")
            print(f"    Description: {p.description}")
            print(f"    HWID: {p.hwid}")
            print()
        return 0

    if args.status:
        existing = check_singleton()
        if existing:
            print(f"EAB Daemon Status:")
            print(f"  Running: {existing.is_alive}")
            print(f"  PID: {existing.pid}")
            print(f"  Port: {existing.port}")
            print(f"  Base dir: {existing.base_dir}")
            print(f"  Started: {existing.started}")
        else:
            print("No EAB daemon is running")
        return 0

    if args.stop:
        from .singleton import kill_existing_daemon
        existing = check_singleton()
        if existing and existing.is_alive:
            print(f"Stopping EAB daemon (PID {existing.pid})...")
            if kill_existing_daemon():
                print("Daemon stopped")
                return 0
            else:
                print("Failed to stop daemon")
                return 1
        else:
            print("No EAB daemon is running")
        return 0

    if args.pause:
        existing = check_singleton()
        if not existing or not existing.is_alive:
            print("No EAB daemon is running")
            return 1

        import time
        pause_seconds = args.pause
        pause_until = time.time() + pause_seconds
        pause_path = os.path.join(existing.base_dir, "pause.txt")

        print(f"Pausing EAB daemon for {pause_seconds} seconds...")
        print(f"Serial port will be released for flashing.")

        # Write pause file
        with open(pause_path, "w") as f:
            f.write(str(pause_until))

        # Wait a moment for daemon to release port
        time.sleep(1.0)
        print(f"Port released. You have {pause_seconds - 1} seconds to flash.")
        print(f"Daemon will auto-resume when pause expires.")
        print(f"To resume early: rm {pause_path}")
        return 0

    # Helper to get daemon info for commands that need it
    def get_daemon_info():
        existing = check_singleton()
        if not existing or not existing.is_alive:
            print("No EAB daemon is running")
            return None
        return existing

    if args.cmd:
        existing = get_daemon_info()
        if not existing:
            return 1
        cmd_path = os.path.join(existing.base_dir, "cmd.txt")
        append_command(cmd_path, args.cmd)
        print(f"Command sent: {args.cmd}")
        return 0

    if args.reset:
        existing = get_daemon_info()
        if not existing:
            return 1
        cmd_path = os.path.join(existing.base_dir, "cmd.txt")
        append_command(cmd_path, "!RESET")
        print("Reset command sent")
        return 0

    if args.logs is not None:
        existing = get_daemon_info()
        if not existing:
            return 1
        log_path = os.path.join(existing.base_dir, "latest.log")
        try:
            import subprocess
            result = subprocess.run(
                ["tail", f"-{args.logs}", log_path],
                capture_output=True,
                text=True
            )
            print(result.stdout)
        except FileNotFoundError:
            print(f"Log file not found: {log_path}")
        return 0

    if args.alerts is not None:
        existing = get_daemon_info()
        if not existing:
            return 1
        alerts_path = os.path.join(existing.base_dir, "alerts.log")
        try:
            import subprocess
            result = subprocess.run(
                ["tail", f"-{args.alerts}", alerts_path],
                capture_output=True,
                text=True
            )
            if result.stdout.strip():
                print(result.stdout)
            else:
                print("No alerts recorded")
        except FileNotFoundError:
            print("No alerts log file")
        return 0

    if args.wait_for:
        import time
        import re
        existing = get_daemon_info()
        if not existing:
            return 1
        log_path = os.path.join(existing.base_dir, "latest.log")
        pattern = re.compile(args.wait_for)

        start_time = time.time()
        timeout = args.wait_timeout

        # Get initial file size to only read new lines
        try:
            with open(log_path, "r") as f:
                f.seek(0, 2)  # Seek to end
                initial_pos = f.tell()
        except FileNotFoundError:
            initial_pos = 0

        print(f"Waiting for pattern '{args.wait_for}' (timeout: {timeout}s)...")

        while time.time() - start_time < timeout:
            try:
                with open(log_path, "r") as f:
                    f.seek(initial_pos)
                    for line in f:
                        if pattern.search(line):
                            print(f"MATCH: {line.strip()}")
                            return 0
                    initial_pos = f.tell()
            except FileNotFoundError:
                pass
            time.sleep(0.1)

        print(f"Timeout waiting for pattern '{args.wait_for}'")
        return 1

    daemon = SerialDaemon(
        port=args.port,
        baud=args.baud,
        base_dir=args.base_dir,
        log_max_size_mb=args.log_max_size,
        log_max_files=args.log_max_files,
        log_compress=not args.no_log_compress,
        device_name=args.device_name,
    )

    # Handle signals
    def signal_handler(sig, frame):
        daemon.stop()
        raise SystemExit(0)

    signal.signal(signal.SIGINT, signal_handler)
    signal.signal(signal.SIGTERM, signal_handler)

    if daemon.start(force=args.force):
        daemon.run()
        return 0
    else:
        return 1


if __name__ == "__main__":
    sys.exit(main())
