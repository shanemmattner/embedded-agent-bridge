#!/usr/bin/env python3
"""
Embedded Agent Bridge - Serial Daemon

A reliable serial daemon with file-based agent interface.
Designed for LLM agents to interact with embedded devices.

Usage:
    python -m serial.daemon --port /dev/ttyUSB0 --baud 115200
    python -m serial.daemon --port auto --base-dir /var/run/eab/serial
"""

import argparse
import signal
import sys
import os
from typing import Optional

from .implementations import RealSerialPort, RealFileSystem, RealClock, ConsoleLogger
from .reconnection import ReconnectionManager
from .session_logger import SessionLogger
from .pattern_matcher import PatternMatcher, AlertLogger
from .status_manager import StatusManager
from .interfaces import ConnectionState
from .device_control import DeviceController, strip_ansi
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
        base_dir: str = "/var/run/eab/serial",
        auto_detect: bool = True,
    ):
        self._port = port
        self._baud = baud
        self._base_dir = base_dir
        self._auto_detect = auto_detect
        self._running = False

        # Create real implementations
        self._serial = RealSerialPort()
        self._fs = RealFileSystem()
        self._clock = RealClock()
        self._logger = ConsoleLogger()

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

        # Command file path
        self._cmd_path = os.path.join(base_dir, "cmd.txt")
        self._cmd_mtime = 0.0

        # Pause file path - write seconds to this file to pause daemon
        self._pause_path = os.path.join(base_dir, "pause.txt")
        self._paused = False
        self._pause_start_time: Optional[float] = None
        self._original_port: Optional[str] = None  # Track original port for resume

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

    def _resolve_port(self) -> str:
        """Resolve 'auto' to actual port."""
        if self._port.lower() == "auto" and self._auto_detect:
            ports = RealSerialPort.list_ports()

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

            # Search for ESP32-like devices
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
                        self._logger.info(f"Auto-detected ESP32 port: {p.device} ({p.description})")
                        return p.device

            self._logger.warning("No ESP32 serial port found")
            return self._port
        return self._port

    def _on_reconnect(self) -> None:
        """Called when reconnection succeeds."""
        self._status_manager.record_reconnect()
        self._logger.info("Reconnected to device")

    def _on_disconnect(self) -> None:
        """Called when disconnect detected."""
        self._status_manager.set_connection_state(ConnectionState.RECONNECTING)
        self._status_manager.record_usb_disconnect()
        self._logger.warning("Connection lost")

    def _on_flash_start(self) -> None:
        """Called when flash operation starts (need to release port)."""
        self._status_manager.set_connection_state(ConnectionState.DISCONNECTED)
        self._logger.info("Flash starting, releasing port...")

    def _on_flash_end(self, success: bool) -> None:
        """Called when flash operation ends."""
        if success:
            self._status_manager.set_connection_state(ConnectionState.CONNECTED)
            self._logger.info("Flash complete, port reacquired")
        else:
            self._logger.error("Flash failed")

    def _on_chip_state_change(self, old_state: ChipState, new_state: ChipState) -> None:
        """Called when chip state changes."""
        self._logger.info(f"Chip state: {old_state.value} -> {new_state.value}")
        # Log to session
        self._session_logger.log_line(f"[EAB] Chip state: {new_state.value}")

    def _on_crash_detected(self, line: str) -> None:
        """Called when a crash is detected."""
        self._logger.error(f"Crash detected!")
        # Log to alerts
        self._session_logger.log_line(f"[EAB] CRASH DETECTED: {line[:100]}")

    def start(self, force: bool = False) -> bool:
        """Start the daemon. Returns True if started successfully.

        Args:
            force: If True, kill any existing daemon first
        """
        self._logger.info(f"Starting Embedded Agent Bridge Serial Daemon")
        self._logger.info(f"Port: {self._reconnection._port_name}, Baud: {self._baud}")
        self._logger.info(f"Base directory: {self._base_dir}")

        port_name = self._reconnection._port_name

        # Singleton enforcement - only one daemon per machine
        self._singleton = SingletonDaemon(logger=self._logger)
        if not self._singleton.acquire(kill_existing=force, port=port_name, base_dir=self._base_dir):
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
            return False

        # Connect to serial port
        if not self._reconnection.connect():
            self._logger.error("Failed to connect to serial port")
            self._port_lock.release()
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
        self._status_manager.set_connection_state(ConnectionState.CONNECTED)

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

                # Check connection
                if not self._reconnection.check_and_reconnect():
                    self._clock.sleep(0.1)
                    continue

                # Read serial data
                data = self._serial.read_line()
                if data:
                    try:
                        line = data.decode("utf-8", errors="replace").strip()
                        if line:
                            self._process_line(line)
                    except Exception as e:
                        self._logger.error(f"Error processing line: {e}")

                # Check for commands
                self._check_commands()

                # Update status periodically
                now = self._clock.timestamp()
                if now - last_status_update >= status_update_interval:
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
        available_ports = [p.device for p in RealSerialPort.list_ports()]

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
                    self._paused = False
                    self._pause_start_time = None
                    self._original_port = None
                    return

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

        # Reconnect to serial port
        if self._reconnection.connect():
            self._status_manager.set_connection_state(ConnectionState.CONNECTED)
            self._logger.info("Resumed successfully - serial port reconnected")
            self._session_logger.log_line(f"[EAB] RESUMED - connected to {port_name}")
        else:
            self._logger.warning("Resume: reconnection pending, will retry...")
            self._status_manager.set_connection_state(ConnectionState.RECONNECTING)
            self._session_logger.log_line("[EAB] RESUME - reconnection pending")

        self._paused = False
        self._pause_start_time = None
        self._original_port = None

    def _process_line(self, line: str) -> None:
        """Process a received line."""
        # Log the line
        self._session_logger.log_line(line)
        self._status_manager.record_line()
        byte_count = len(line)
        self._status_manager.record_bytes(byte_count)
        self._status_manager.record_activity(byte_count)

        # Feed to chip recovery for state monitoring
        self._chip_recovery.process_line(line)

        # Check for patterns
        matches = self._pattern_matcher.check_line(line)
        for match in matches:
            self._alert_logger.log_alert(match)
            self._status_manager.record_alert(match.pattern)

        # Print to console (strip ANSI for cleaner output)
        print(strip_ansi(line))

    def _check_commands(self) -> None:
        """Check for commands in the command file."""
        try:
            if not self._fs.file_exists(self._cmd_path):
                return

            mtime = self._fs.get_mtime(self._cmd_path)
            if mtime <= self._cmd_mtime:
                return

            self._cmd_mtime = mtime
            content = self._fs.read_file(self._cmd_path).strip()

            if not content:
                return

            # Clear the file
            self._fs.write_file(self._cmd_path, "")

            # Send each command
            for line in content.split("\n"):
                cmd = line.strip()
                if cmd:
                    self._send_command(cmd)

        except Exception as e:
            self._logger.error(f"Error checking commands: {e}")

    def _send_command(self, cmd: str) -> None:
        """Send a command to the device (or handle special ! commands)."""
        self._logger.info(f"Sending command: {cmd}")
        self._session_logger.log_command(cmd)
        self._status_manager.record_command()

        # Check for special commands (!RESET, !FLASH, etc.)
        if self._device_controller.is_special_command(cmd):
            result = self._device_controller.handle_command(cmd)
            self._logger.info(f"Special command result: {result}")
            # Log result to session
            self._session_logger.log_line(f"[EAB] {result}")
            return

        # Regular command - send to device
        data = (cmd + "\n").encode()
        self._serial.write(data)

    def stop(self) -> None:
        """Stop the daemon gracefully, leaving chip in good state."""
        self._logger.info("Stopping daemon...")
        self._running = False

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


def main():
    parser = argparse.ArgumentParser(
        description="Embedded Agent Bridge - Serial Daemon",
        formatter_class=argparse.RawDescriptionHelpFormatter,
        epilog="""
Examples:
  python -m serial.daemon --port /dev/ttyUSB0
  python -m serial.daemon --port auto --baud 115200
  python -m serial.daemon --port /dev/cu.usbmodem123 --base-dir ./eab
        """,
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
        default="/var/run/eab/serial",
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

    args = parser.parse_args()

    if args.list:
        print("Available serial ports:")
        for p in RealSerialPort.list_ports():
            print(f"  {p.device}")
            print(f"    Description: {p.description}")
            print(f"    HWID: {p.hwid}")
            print()
        return

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
        return

    if args.stop:
        from .singleton import kill_existing_daemon
        existing = check_singleton()
        if existing and existing.is_alive:
            print(f"Stopping EAB daemon (PID {existing.pid})...")
            if kill_existing_daemon():
                print("Daemon stopped")
            else:
                print("Failed to stop daemon")
                sys.exit(1)
        else:
            print("No EAB daemon is running")
        return

    if args.pause:
        existing = check_singleton()
        if not existing or not existing.is_alive:
            print("No EAB daemon is running")
            sys.exit(1)

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
        return

    # Helper to get daemon info for commands that need it
    def get_daemon_info():
        existing = check_singleton()
        if not existing or not existing.is_alive:
            print("No EAB daemon is running")
            sys.exit(1)
        return existing

    if args.cmd:
        existing = get_daemon_info()
        cmd_path = os.path.join(existing.base_dir, "cmd.txt")
        with open(cmd_path, "w") as f:
            f.write(args.cmd + "\n")
        print(f"Command sent: {args.cmd}")
        return

    if args.reset:
        existing = get_daemon_info()
        cmd_path = os.path.join(existing.base_dir, "cmd.txt")
        with open(cmd_path, "w") as f:
            f.write("!RESET\n")
        print("Reset command sent")
        return

    if args.logs is not None:
        existing = get_daemon_info()
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
        return

    if args.alerts is not None:
        existing = get_daemon_info()
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
        return

    if args.wait_for:
        import time
        import re
        existing = get_daemon_info()
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
                            sys.exit(0)
                    initial_pos = f.tell()
            except FileNotFoundError:
                pass
            time.sleep(0.1)

        print(f"Timeout waiting for pattern '{args.wait_for}'")
        sys.exit(1)

    daemon = SerialDaemon(
        port=args.port,
        baud=args.baud,
        base_dir=args.base_dir,
    )

    # Handle signals
    def signal_handler(sig, frame):
        daemon.stop()
        sys.exit(0)

    signal.signal(signal.SIGINT, signal_handler)
    signal.signal(signal.SIGTERM, signal_handler)

    if daemon.start(force=args.force):
        daemon.run()
    else:
        sys.exit(1)


if __name__ == "__main__":
    main()
