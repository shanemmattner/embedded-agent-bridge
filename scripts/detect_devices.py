#!/usr/bin/env python3
"""
Device Detection for EAB
Automatically identifies which USB port belongs to which development board

Usage:
    python3 detect_devices.py                 # Print table
    python3 detect_devices.py --json          # Output JSON
    python3 detect_devices.py --device esp32c6  # Find specific device
"""

import json
import subprocess
import re
import sys
from pathlib import Path
from typing import Dict, List, Optional

class DeviceDetector:
    """Detects and identifies connected development boards"""

    def __init__(self):
        self.devices = []

    def scan_ports(self) -> List[str]:
        """Find all USB serial ports"""
        ports = []
        for pattern in ["/dev/cu.usbmodem*", "/dev/cu.usbserial*", "/dev/cu.SLAB*",
                        "/dev/ttyUSB*", "/dev/ttyACM*"]:
            ports.extend(Path("/dev").glob(pattern.replace("/dev/", "")))
        return [str(p) for p in sorted(ports)]

    def detect_esp32(self, port: str) -> Optional[Dict]:
        """Try to identify ESP32 board using esptool"""
        try:
            result = subprocess.run(
                ["esptool", "--port", port, "chip_id"],
                capture_output=True,
                text=True,
                timeout=5
            )
            output = result.stdout + result.stderr

            if "Detecting chip type" in output:
                chip_match = re.search(r"Chip is (ESP32[-\w]+)", output)
                mac_match = re.search(r"MAC: ([\w:]+)", output)

                chip = chip_match.group(1) if chip_match else "ESP32"
                chip_lower = chip.lower().replace("-", "")

                return {
                    "device_type": chip_lower,
                    "chip": chip_lower,
                    "family": "esp32",
                    "serial": mac_match.group(1) if mac_match else None,
                    "transport": "uart",
                    "flash_tool": "esptool"
                }
        except (subprocess.TimeoutExpired, FileNotFoundError, Exception):
            pass
        return None

    def detect_jlink(self, port: str) -> Optional[Dict]:
        """Try to identify J-Link connected board"""
        # J-Link doesn't use serial ports directly, but we can check for
        # nRF5340 DK which has USB CDC
        # This is a heuristic - not perfect
        try:
            # Try to read device descriptor
            import serial
            ser = serial.Serial(port, timeout=0.1)
            ser.close()

            # Check if it's likely an nRF5340 based on USB VID/PID
            # This would require pyserial or libusb binding
            # For now, return None and rely on other methods
        except:
            pass
        return None

    def detect_via_usb_ids(self, port: str) -> Optional[Dict]:
        """Identify device via USB vendor/product IDs"""
        try:
            # On macOS, use system_profiler
            result = subprocess.run(
                ["system_profiler", "SPUSBDataType"],
                capture_output=True,
                text=True,
                timeout=5
            )
            output = result.stdout

            # Find the section for this port
            port_name = Path(port).name
            lines = output.split("\n")

            device_section = []
            in_section = False
            for line in lines:
                if port_name in line or f"usbmodem" in line:
                    in_section = True
                if in_section:
                    device_section.append(line)
                    if line.strip() and not line.startswith(" "):
                        break

            device_text = "\n".join(device_section)

            # Identify by vendor
            if "Espressif" in device_text or "10C4" in device_text:  # Espressif or Silicon Labs
                return {
                    "device_type": "esp32_unknown",
                    "chip": "unknown",
                    "family": "esp32",
                    "transport": "uart",
                    "flash_tool": "esptool"
                }
            elif "SEGGER" in device_text or "1366" in device_text:
                # Could be nRF5340 with J-Link OB
                return {
                    "device_type": "nrf5340",
                    "chip": "nrf5340",
                    "family": "nordic",
                    "transport": "jlink",
                    "flash_tool": "west flash --runner jlink"
                }
            elif "STMicroelectronics" in device_text or "0483" in device_text:
                return {
                    "device_type": "stm32_unknown",
                    "chip": "unknown",
                    "family": "stm32",
                    "transport": "serial",
                    "flash_tool": "openocd or st-flash"
                }
            elif "NXP" in device_text or "1FC9" in device_text:
                return {
                    "device_type": "nxp_unknown",
                    "chip": "unknown",
                    "family": "nxp",
                    "transport": "serial",
                    "flash_tool": "openocd"
                }

        except (subprocess.TimeoutExpired, FileNotFoundError):
            pass
        return None

    def detect_device(self, port: str) -> Dict:
        """Detect device type for a single port"""
        info = {
            "port": port,
            "device_type": "unknown",
            "chip": "unknown",
            "family": "unknown",
            "serial": None,
            "transport": "unknown",
            "flash_tool": "unknown"
        }

        # Try ESP32 detection (most reliable)
        esp_info = self.detect_esp32(port)
        if esp_info:
            info.update(esp_info)
            return info

        # Try USB ID detection
        usb_info = self.detect_via_usb_ids(port)
        if usb_info:
            info.update(usb_info)
            return info

        return info

    def scan_all(self) -> List[Dict]:
        """Scan all ports and detect devices"""
        ports = self.scan_ports()
        self.devices = []

        for port in ports:
            device_info = self.detect_device(port)
            self.devices.append(device_info)

        return self.devices

    def find_device(self, device_type: str) -> Optional[Dict]:
        """Find first device of specified type"""
        for device in self.devices:
            if device["device_type"] == device_type or device["chip"] == device_type:
                return device
        return None

    def get_port_for_device(self, device_type: str) -> Optional[str]:
        """Get port for specified device type"""
        device = self.find_device(device_type)
        return device["port"] if device else None


def print_table(devices: List[Dict]):
    """Print devices in table format"""
    print(f"{'PORT':<40} {'DEVICE TYPE':<20} {'CHIP':<15} {'FLASH TOOL':<20}")
    print(f"{'-'*40} {'-'*20} {'-'*15} {'-'*20}")
    for device in devices:
        print(f"{device['port']:<40} {device['device_type']:<20} {device['chip']:<15} {device['flash_tool']:<20}")


def print_summary(devices: List[Dict]):
    """Print device summary"""
    print("\n=== Summary ===")
    print(f"Total devices: {len(devices)}")
    print(f"ESP32 devices: {sum(1 for d in devices if d['family'] == 'esp32')}")
    print(f"Nordic devices: {sum(1 for d in devices if d['family'] == 'nordic')}")
    print(f"STM32 devices: {sum(1 for d in devices if d['family'] == 'stm32')}")
    print(f"NXP devices: {sum(1 for d in devices if d['family'] == 'nxp')}")
    print(f"Unknown devices: {sum(1 for d in devices if d['device_type'] == 'unknown')}")


def main():
    import argparse

    parser = argparse.ArgumentParser(description="Detect connected development boards")
    parser.add_argument("--json", action="store_true", help="Output JSON")
    parser.add_argument("--device", type=str, help="Find specific device type")
    parser.add_argument("--port-only", action="store_true", help="Output only port (with --device)")
    args = parser.parse_args()

    detector = DeviceDetector()
    devices = detector.scan_all()

    if args.device:
        device = detector.find_device(args.device)
        if device:
            if args.port_only:
                print(device["port"])
            elif args.json:
                print(json.dumps(device, indent=2))
            else:
                print(f"Found {args.device}: {device['port']}")
            sys.exit(0)
        else:
            print(f"Device {args.device} not found", file=sys.stderr)
            sys.exit(1)
    elif args.json:
        print(json.dumps(devices, indent=2))
    else:
        print_table(devices)
        print_summary(devices)


if __name__ == "__main__":
    main()
