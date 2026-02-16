#!/usr/bin/env python3
"""
ESP32 Family Test Module

Tests ESP32-C6, ESP32-P4, ESP32-S3 devices independently.
Each test is isolated and can run standalone.

Usage:
    python3 tests/test_esp32.py --chip esp32c6
    python3 tests/test_esp32.py --chip esp32p4 --duration 30
    python3 tests/test_esp32.py --port /dev/cu.usbmodem101
    python3 tests/test_esp32.py --chip esp32c6 --json
"""

import argparse
import json
import subprocess
import time
from pathlib import Path
from typing import Dict, Optional


class ESP32Test:
    """Isolated test for a single ESP32 device"""

    def __init__(self, chip: str, port: str, firmware_dir: str):
        self.chip = chip
        self.port = port
        self.firmware_dir = Path(firmware_dir)
        self.metrics = {
            "chip": chip,
            "port": port,
            "firmware": str(firmware_dir),
            "flash_success": False,
            "boot_success": False,
            "bytes_received": 0,
            "lines_received": 0,
            "errors": [],
        }

    def flash(self) -> bool:
        """Flash firmware to device"""
        try:
            cmd = ["eabctl", "flash", "--port", self.port, str(self.firmware_dir)]
            result = subprocess.run(cmd, capture_output=True, text=True, timeout=120)
            self.metrics["flash_success"] = result.returncode == 0
            if not self.metrics["flash_success"]:
                self.metrics["errors"].append(f"Flash failed: {result.stderr[:200]}")
            return self.metrics["flash_success"]
        except Exception as e:
            self.metrics["errors"].append(f"Flash exception: {str(e)}")
            return False

    def wait_boot(self, timeout: int = 10) -> bool:
        """Wait for device to boot and output data"""
        try:
            # Wait for device to appear in eabctl devices
            time.sleep(2)

            # Try to tail output
            cmd = ["eabctl", "tail", "10"]
            result = subprocess.run(cmd, capture_output=True, text=True, timeout=timeout)

            if result.returncode == 0 and result.stdout.strip():
                self.metrics["boot_success"] = True
                self.metrics["lines_received"] = len([l for l in result.stdout.split("\n") if l.strip()])
                self.metrics["bytes_received"] = len(result.stdout)
                return True
            else:
                self.metrics["errors"].append(f"No boot output: {result.stderr[:200]}")
                return False
        except Exception as e:
            self.metrics["errors"].append(f"Boot wait exception: {str(e)}")
            return False

    def collect_data(self, duration: int = 30) -> Dict:
        """Collect debug data for specified duration"""
        try:
            # Collect output
            cmd = ["eabctl", "tail", "200"]
            result = subprocess.run(cmd, capture_output=True, text=True, timeout=duration + 5)

            if result.returncode == 0:
                lines = [l for l in result.stdout.split("\n") if l.strip()]
                self.metrics["lines_received"] = len(lines)
                self.metrics["bytes_received"] = len(result.stdout)

                # Save to file
                output_file = f"/tmp/eab-test-{self.chip}.log"
                Path(output_file).write_text(result.stdout)
                self.metrics["output_file"] = output_file

        except Exception as e:
            self.metrics["errors"].append(f"Data collection exception: {str(e)}")

        return self.metrics

    def run_full_test(self, duration: int = 30) -> Dict:
        """Run complete test sequence"""
        print(f"\n{'='*70}")
        print(f"ESP32 Test: {self.chip}")
        print(f"{'='*70}\n")

        print(f"📦 Device: {self.chip}")
        print(f"   Port: {self.port}")
        print(f"   Firmware: {self.firmware_dir}")
        print()

        # Flash
        print("🔧 Flashing firmware...")
        if not self.flash():
            print("❌ Flash failed")
            return self.metrics

        print("✅ Flash successful")
        print()

        # Wait for boot
        print("🚀 Waiting for boot...")
        if not self.wait_boot():
            print("❌ Boot failed")
            return self.metrics

        print("✅ Boot successful")
        print()

        # Collect data
        print(f"📊 Collecting data ({duration}s)...")
        self.collect_data(duration)
        print(f"✅ Collected {self.metrics['lines_received']} lines ({self.metrics['bytes_received']} bytes)")
        if "output_file" in self.metrics:
            print(f"   Saved to: {self.metrics['output_file']}")
        print()

        return self.metrics


def get_firmware_dir(chip: str) -> Optional[str]:
    """Get firmware directory for chip type"""
    mapping = {
        "esp32c6": "examples/esp32c6-apptrace-test",
        "esp32p4": "examples/esp32p4-stress-test",
        "esp32s3": "examples/esp32s3-debug-full",
    }
    return mapping.get(chip)


def main():
    parser = argparse.ArgumentParser(description="Test ESP32 family devices")
    parser.add_argument("--chip", required=True, choices=["esp32c6", "esp32p4", "esp32s3"],
                        help="Chip type")
    parser.add_argument("--port", help="Serial port (auto-detect if not specified)")
    parser.add_argument("--duration", type=int, default=30, help="Data collection duration (seconds)")
    parser.add_argument("--json", action="store_true", help="Output results as JSON")
    args = parser.parse_args()

    # Auto-detect port if not specified
    if not args.port:
        from device_discovery import discover_devices
        devices = discover_devices(chip_filter=args.chip)
        if not devices:
            print(f"❌ No {args.chip} device found")
            return 1
        args.port = devices[0]["port"]

    # Get firmware directory
    firmware_dir = get_firmware_dir(args.chip)
    if not firmware_dir:
        print(f"❌ Unknown chip type: {args.chip}")
        return 1

    # Run test
    test = ESP32Test(args.chip, args.port, firmware_dir)
    results = test.run_full_test(args.duration)

    # Output
    if args.json:
        print(json.dumps(results, indent=2))
    else:
        print(f"\n{'='*70}")
        print("Test Summary")
        print(f"{'='*70}\n")
        print(f"Flash: {'✅' if results['flash_success'] else '❌'}")
        print(f"Boot: {'✅' if results['boot_success'] else '❌'}")
        print(f"Data: {results['lines_received']} lines, {results['bytes_received']} bytes")
        if results['errors']:
            print(f"\nErrors:")
            for err in results['errors']:
                print(f"  - {err}")
        print()

    return 0 if results['boot_success'] else 1


if __name__ == "__main__":
    exit(main())
