#!/usr/bin/env python3
"""USB Board Auto-Detection for EAB.

Scans USB serial ports and identifies known dev boards by VID:PID.

Usage:
    python3 eab/auto_detect.py              # Print detected boards
    python3 eab/auto_detect.py --json       # JSON output
    python3 eab/auto_detect.py --update     # Update devices.json with detected ports
"""

import argparse
import json
import re
import subprocess
import sys
from pathlib import Path

KNOWN_BOARDS = {
    ("1fc9", "0143"): {"name": "FRDM-MCXN947", "chip": "mcxn947", "probe": "cmsis-dap"},
    ("0483", "374e"): {"name": "ST-Link V3", "chip": "stm32", "probe": "stlink"},
    ("0483", "374b"): {"name": "ST-Link V2-1", "chip": "stm32", "probe": "stlink"},
    ("1366", "1015"): {"name": "J-Link", "chip": "nrf5340", "probe": "jlink"},
    ("1366", "0105"): {"name": "J-Link OB", "chip": "nrf5340", "probe": "jlink"},
    ("303a", "1001"): {"name": "ESP32 USB-JTAG", "chip": "esp32", "probe": "esp-usb-jtag"},
    ("10c4", "ea60"): {"name": "CP2102 (ESP32)", "chip": "esp32", "probe": "uart"},
    ("0451", "bef3"): {"name": "XDS110", "chip": "c2000", "probe": "xds110"},
}


def detect_boards_pyserial():
    """Detect boards using pyserial."""
    try:
        import serial.tools.list_ports
    except ImportError:
        return None

    boards = []
    for p in serial.tools.list_ports.comports():
        vid = f"{p.vid:04x}" if p.vid else None
        pid = f"{p.pid:04x}" if p.pid else None
        if vid and pid and (vid, pid) in KNOWN_BOARDS:
            info = KNOWN_BOARDS[(vid, pid)].copy()
            info["port"] = p.device
            info["vid"] = vid
            info["pid"] = pid
            info["serial"] = p.serial_number or ""
            boards.append(info)
    return boards


def detect_boards_ioreg():
    """Fallback: detect boards via macOS ioreg."""
    try:
        out = subprocess.check_output(
            ["ioreg", "-p", "IOUSB", "-l", "-w0"],
            text=True, timeout=5
        )
    except (subprocess.SubprocessError, FileNotFoundError):
        return []

    boards = []
    current_vid = None
    current_pid = None
    current_serial = None

    for line in out.splitlines():
        m = re.search(r'"idVendor"\s*=\s*(\d+)', line)
        if m:
            current_vid = f"{int(m.group(1)):04x}"
        m = re.search(r'"idProduct"\s*=\s*(\d+)', line)
        if m:
            current_pid = f"{int(m.group(1)):04x}"
        m = re.search(r'"USB Serial Number"\s*=\s*"([^"]*)"', line)
        if m:
            current_serial = m.group(1)

        if current_vid and current_pid:
            key = (current_vid, current_pid)
            if key in KNOWN_BOARDS:
                info = KNOWN_BOARDS[key].copy()
                info["vid"] = current_vid
                info["pid"] = current_pid
                info["serial"] = current_serial or ""
                info["port"] = ""  # ioreg doesn't give port path directly
                boards.append(info)
            current_vid = None
            current_pid = None
            current_serial = None

    return boards


def detect_boards():
    """Detect connected boards, trying pyserial first then ioreg."""
    result = detect_boards_pyserial()
    if result is not None:
        return result
    return detect_boards_ioreg()


def print_table(boards):
    """Pretty-print detected boards."""
    if not boards:
        print("No known boards detected.")
        return
    print(f"{'Board':<20} {'Chip':<12} {'Probe':<12} {'Port':<30} {'Serial'}")
    print("-" * 90)
    for b in boards:
        print(f"{b['name']:<20} {b['chip']:<12} {b['probe']:<12} {b.get('port', ''):<30} {b.get('serial', '')}")
    print(f"\n{len(boards)} board(s) detected.")


def print_json(boards):
    """JSON output."""
    print(json.dumps(boards, indent=2))


def update_devices_json(boards):
    """Update devices.json with detected port paths."""
    candidates = [
        Path("/tmp/eab-devices/devices.json"),
        Path.cwd() / "devices.json",
    ]
    devices_path = None
    for c in candidates:
        if c.exists():
            devices_path = c
            break

    if not devices_path:
        print("No devices.json found. Checked:", [str(c) for c in candidates])
        return

    with open(devices_path) as f:
        devices = json.load(f)

    updated = 0
    for b in boards:
        if not b.get("port"):
            continue
        for key, dev in devices.items():
            if dev.get("chip") == b["chip"] or dev.get("name") == b["name"]:
                old_port = dev.get("port", "")
                if old_port != b["port"]:
                    dev["port"] = b["port"]
                    updated += 1
                    print(f"Updated {key}: {old_port} -> {b['port']}")

    if updated:
        with open(devices_path, "w") as f:
            json.dump(devices, f, indent=2)
        print(f"\n{updated} port(s) updated in {devices_path}")
    else:
        print("All ports already up to date.")


def main():
    parser = argparse.ArgumentParser(description="EAB USB Board Auto-Detection")
    parser.add_argument("--json", action="store_true", help="JSON output")
    parser.add_argument("--update", action="store_true", help="Update devices.json")
    args = parser.parse_args()

    boards = detect_boards()

    if args.json:
        print_json(boards)
    elif args.update:
        print_table(boards)
        print()
        update_devices_json(boards)
    else:
        print_table(boards)


if __name__ == "__main__":
    main()
