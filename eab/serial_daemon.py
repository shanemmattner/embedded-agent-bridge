#!/usr/bin/env python3
"""
Serial Monitor Daemon for ESP32 BLE Debugging

Captures serial output from ESP32 and logs to file with timestamps.
Run this in a terminal to capture logs during BLE testing.

Usage:
    python3 serial_monitor_daemon.py [--port /dev/cu.usbmodem...] [--output esp32_log.txt]
"""

import serial
import serial.tools.list_ports
import sys
import os
import argparse
from datetime import datetime
import signal
import time
import json
from collections import deque

# Default settings
DEFAULT_PORT = "/dev/cu.usbmodem5B140841231"
DEFAULT_BAUD = 115200
# Fixed output location for easy access from Claude Code
LOG_DIR = os.path.dirname(os.path.abspath(__file__))
LATEST_LOG = os.path.join(LOG_DIR, "esp32_latest.log")
CMD_FILE = os.path.join(LOG_DIR, "esp32_cmd.txt")
STATS_FILE = os.path.join(LOG_DIR, "esp32_stats.json")
ALERTS_FILE = os.path.join(LOG_DIR, "esp32_alerts.log")
DEFAULT_OUTPUT = LATEST_LOG  # Always write to fixed location

# Patterns to watch for (will be logged to alerts file)
ALERT_PATTERNS = [
    "DISCONNECT", "ERROR", "FAIL", "TIMEOUT", "CRASH",
    "assert", "panic", "abort", "GAP_EVENT", "GATT"
]

class SerialMonitorDaemon:
    def __init__(self, port, baud, output_file):
        self.port = port
        self.baud = baud
        self.output_file = output_file
        self.serial = None
        self.running = False
        self.log_file = None
        self.alerts_file = None
        self.cmd_file_mtime = 0

        # Statistics
        self.stats = {
            "started": None,
            "lines_logged": 0,
            "alerts_triggered": 0,
            "commands_sent": 0,
            "errors": 0,
            "pattern_counts": {p: 0 for p in ALERT_PATTERNS}
        }

        # Circular buffer for recent lines (useful for crash analysis)
        self.recent_lines = deque(maxlen=500)

    def find_esp32_port(self):
        """Auto-detect ESP32 port if not specified"""
        ports = list(serial.tools.list_ports.comports())
        for p in ports:
            if "usbmodem" in p.device.lower() or "usb" in p.device.lower():
                print(f"Found USB device: {p.device} - {p.description}")
                if "usbmodem" in p.device.lower():
                    return p.device
        return None

    def connect(self):
        """Connect to serial port"""
        port = self.port
        if not port or not os.path.exists(port):
            detected = self.find_esp32_port()
            if detected:
                port = detected
                print(f"Auto-detected ESP32 at: {port}")
            else:
                print(f"ERROR: Port not found. Available ports:")
                for p in serial.tools.list_ports.comports():
                    print(f"  {p.device} - {p.description}")
                return False

        try:
            self.serial = serial.Serial(port, self.baud, timeout=1)
            print(f"Connected to {port} at {self.baud} baud")
            return True
        except Exception as e:
            print(f"ERROR: Could not connect to {port}: {e}")
            return False

    def start_logging(self):
        """Start logging to file"""
        if not self.output_file:
            self.output_file = LATEST_LOG

        # Truncate file at startup for fresh logs each session
        self.log_file = open(self.output_file, "w")
        self.alerts_file = open(ALERTS_FILE, "w")
        self.stats["started"] = datetime.now().isoformat()

        # Clear command file
        open(CMD_FILE, "w").close()

        print(f"Logging to: {self.output_file}")
        print(f"Alerts to: {ALERTS_FILE}")
        print(f"Commands from: {CMD_FILE}")
        print(f"Stats at: {STATS_FILE}")

        # Write header
        header = f"\n{'='*60}\n"
        header += f"ESP32 Serial Log - Started {datetime.now().isoformat()}\n"
        header += f"Port: {self.port}, Baud: {self.baud}\n"
        header += f"Command file: {CMD_FILE}\n"
        header += f"{'='*60}\n\n"
        self.log_file.write(header)
        self.log_file.flush()
        self.alerts_file.write(header)
        self.alerts_file.flush()
        print(header)

    def log_line(self, line):
        """Log a line with timestamp"""
        timestamp = datetime.now().strftime("%H:%M:%S.%f")[:-3]
        formatted = f"[{timestamp}] {line}"

        # Update stats
        self.stats["lines_logged"] += 1
        self.recent_lines.append(formatted)

        # Check for alert patterns
        for pattern in ALERT_PATTERNS:
            if pattern.upper() in line.upper():
                self.stats["pattern_counts"][pattern] += 1
                self.stats["alerts_triggered"] += 1
                if self.alerts_file:
                    self.alerts_file.write(f"[{timestamp}] [{pattern}] {line}\n")
                    self.alerts_file.flush()

        # Print to console
        print(formatted)

        # Write to file
        if self.log_file:
            self.log_file.write(formatted + "\n")
            self.log_file.flush()

        # Update stats file periodically (every 100 lines)
        if self.stats["lines_logged"] % 100 == 0:
            self.save_stats()

    def save_stats(self):
        """Save statistics to JSON file"""
        self.stats["last_updated"] = datetime.now().isoformat()
        self.stats["recent_lines_count"] = len(self.recent_lines)
        with open(STATS_FILE, "w") as f:
            json.dump(self.stats, f, indent=2)

    def check_commands(self):
        """Check for new commands in the command file"""
        try:
            if not os.path.exists(CMD_FILE):
                return

            mtime = os.path.getmtime(CMD_FILE)
            if mtime > self.cmd_file_mtime:
                self.cmd_file_mtime = mtime
                with open(CMD_FILE, "r") as f:
                    commands = f.read().strip()
                if commands:
                    # Clear the file after reading
                    open(CMD_FILE, "w").close()
                    for cmd in commands.split("\n"):
                        cmd = cmd.strip()
                        if cmd:
                            self.send_command(cmd)
        except Exception as e:
            self.log_line(f"[CMD ERROR: {e}]")

    def send_command(self, cmd):
        """Send a command to the ESP32"""
        try:
            self.log_line(f"[CMD TX] >>> {cmd}")
            self.serial.write(f"{cmd}\n".encode())
            self.stats["commands_sent"] += 1
        except Exception as e:
            self.log_line(f"[CMD ERROR: {e}]")
            self.stats["errors"] += 1

    def run(self):
        """Main loop - read serial and log"""
        self.running = True
        print("\n" + "="*60)
        print("SERIAL MONITOR RUNNING - Press Ctrl+C to stop")
        print(f"To send commands: echo 'your_command' > {CMD_FILE}")
        print("="*60 + "\n")

        last_cmd_check = 0
        try:
            while self.running:
                # Check for commands every 100ms
                now = time.time()
                if now - last_cmd_check > 0.1:
                    self.check_commands()
                    last_cmd_check = now

                if self.serial and self.serial.in_waiting:
                    try:
                        line = self.serial.readline()
                        if line:
                            decoded = line.decode('utf-8', errors='replace').strip()
                            if decoded:
                                self.log_line(decoded)
                    except Exception as e:
                        self.log_line(f"[READ ERROR: {e}]")
                        self.stats["errors"] += 1
                else:
                    # Small sleep to prevent CPU spinning
                    time.sleep(0.001)
        except KeyboardInterrupt:
            print("\n\nStopping...")
        finally:
            self.stop()

    def stop(self):
        """Clean shutdown"""
        self.running = False

        # Save final stats
        self.save_stats()

        if self.serial:
            self.serial.close()
            print("Serial port closed")
        if self.log_file:
            footer = f"\n{'='*60}\n"
            footer += f"Log ended: {datetime.now().isoformat()}\n"
            footer += f"Lines logged: {self.stats['lines_logged']}\n"
            footer += f"Alerts triggered: {self.stats['alerts_triggered']}\n"
            footer += f"Commands sent: {self.stats['commands_sent']}\n"
            footer += f"{'='*60}\n"
            self.log_file.write(footer)
            self.log_file.close()
            print(f"Log saved to: {self.output_file}")
        if self.alerts_file:
            self.alerts_file.close()
            print(f"Alerts saved to: {ALERTS_FILE}")
        print(f"Stats saved to: {STATS_FILE}")


def main():
    parser = argparse.ArgumentParser(description="ESP32 Serial Monitor Daemon")
    parser.add_argument("--port", "-p", default=DEFAULT_PORT,
                        help=f"Serial port (default: {DEFAULT_PORT})")
    parser.add_argument("--baud", "-b", type=int, default=DEFAULT_BAUD,
                        help=f"Baud rate (default: {DEFAULT_BAUD})")
    parser.add_argument("--output", "-o", default=None,
                        help="Output log file (default: timestamped file)")
    parser.add_argument("--list", "-l", action="store_true",
                        help="List available serial ports and exit")

    args = parser.parse_args()

    if args.list:
        print("Available serial ports:")
        for p in serial.tools.list_ports.comports():
            print(f"  {p.device}")
            print(f"    Description: {p.description}")
            print(f"    HWID: {p.hwid}")
            print()
        return

    daemon = SerialMonitorDaemon(args.port, args.baud, args.output)

    if not daemon.connect():
        sys.exit(1)

    daemon.start_logging()

    # Handle signals for clean shutdown
    def signal_handler(sig, frame):
        daemon.stop()
        sys.exit(0)
    signal.signal(signal.SIGINT, signal_handler)
    signal.signal(signal.SIGTERM, signal_handler)

    daemon.run()


if __name__ == "__main__":
    main()
