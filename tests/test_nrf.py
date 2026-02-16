#!/usr/bin/env python3
"""
nRF5340 Test Module

Tests nRF5340 device via J-Link RTT.

Usage:
    python3 tests/test_nrf.py --duration 30
    python3 tests/test_nrf.py --json
"""

import argparse
import json
import subprocess
import time
from pathlib import Path
from typing import Dict


class nRF5340Test:
    """Isolated test for nRF5340"""

    def __init__(self, firmware_dir: str = "examples/nrf5340-rtt-binary-blast"):
        self.chip = "NRF5340_XXAA_APP"
        self.firmware_dir = Path(firmware_dir)
        self.metrics = {
            "chip": "nrf5340",
            "firmware": str(firmware_dir),
            "flash_success": False,
            "rtt_start_success": False,
            "bytes_received": 0,
            "lines_received": 0,
            "errors": [],
        }

    def flash(self) -> bool:
        """Flash firmware via west/J-Link"""
        try:
            # Build first (if needed)
            build_cmd = ["west", "build", "-b", "nrf5340dk_nrf5340_cpuapp"]
            subprocess.run(build_cmd, cwd=self.firmware_dir, capture_output=True, timeout=120)

            # Flash
            flash_cmd = ["west", "flash", "--runner", "jlink"]
            result = subprocess.run(flash_cmd, cwd=self.firmware_dir, capture_output=True, text=True, timeout=60)

            self.metrics["flash_success"] = result.returncode == 0
            if not self.metrics["flash_success"]:
                self.metrics["errors"].append(f"Flash failed: {result.stderr[:200]}")
            return self.metrics["flash_success"]
        except Exception as e:
            self.metrics["errors"].append(f"Flash exception: {str(e)}")
            return False

    def start_rtt(self) -> bool:
        """Start RTT streaming"""
        try:
            cmd = ["eabctl", "rtt", "start", "--device", self.chip, "--transport", "jlink"]
            result = subprocess.run(cmd, capture_output=True, text=True, timeout=10)

            self.metrics["rtt_start_success"] = result.returncode == 0
            if not self.metrics["rtt_start_success"]:
                self.metrics["errors"].append(f"RTT start failed: {result.stderr[:200]}")
            return self.metrics["rtt_start_success"]
        except Exception as e:
            self.metrics["errors"].append(f"RTT start exception: {str(e)}")
            return False

    def collect_data(self, duration: int = 30) -> Dict:
        """Collect RTT data"""
        try:
            time.sleep(duration)

            # Read RTT output
            cmd = ["eabctl", "rtt", "tail", "200"]
            result = subprocess.run(cmd, capture_output=True, text=True, timeout=10)

            if result.returncode == 0:
                lines = [l for l in result.stdout.split("\n") if l.strip()]
                self.metrics["lines_received"] = len(lines)
                self.metrics["bytes_received"] = len(result.stdout)

                # Save to file
                output_file = "/tmp/eab-test-nrf5340.log"
                Path(output_file).write_text(result.stdout)
                self.metrics["output_file"] = output_file

        except Exception as e:
            self.metrics["errors"].append(f"Data collection exception: {str(e)}")

        # Stop RTT
        try:
            subprocess.run(["eabctl", "rtt", "stop"], capture_output=True, timeout=5)
        except:
            pass

        return self.metrics

    def run_full_test(self, duration: int = 30) -> Dict:
        """Run complete test sequence"""
        print(f"\n{'='*70}")
        print(f"nRF5340 Test")
        print(f"{'='*70}\n")

        print(f"📦 Device: nRF5340")
        print(f"   Firmware: {self.firmware_dir}")
        print()

        # Flash
        print("🔧 Flashing firmware...")
        if not self.flash():
            print("❌ Flash failed")
            return self.metrics

        print("✅ Flash successful")
        print()

        # Start RTT
        print("🚀 Starting RTT...")
        if not self.start_rtt():
            print("❌ RTT start failed")
            return self.metrics

        print("✅ RTT started")
        print()

        # Collect data
        print(f"📊 Collecting data ({duration}s)...")
        self.collect_data(duration)
        print(f"✅ Collected {self.metrics['lines_received']} lines ({self.metrics['bytes_received']} bytes)")
        if "output_file" in self.metrics:
            print(f"   Saved to: {self.metrics['output_file']}")
        print()

        return self.metrics


def main():
    parser = argparse.ArgumentParser(description="Test nRF5340 device")
    parser.add_argument("--duration", type=int, default=30, help="Data collection duration (seconds)")
    parser.add_argument("--json", action="store_true", help="Output results as JSON")
    args = parser.parse_args()

    # Run test
    test = nRF5340Test()
    results = test.run_full_test(args.duration)

    # Output
    if args.json:
        print(json.dumps(results, indent=2))
    else:
        print(f"\n{'='*70}")
        print("Test Summary")
        print(f"{'='*70}\n")
        print(f"Flash: {'✅' if results['flash_success'] else '❌'}")
        print(f"RTT: {'✅' if results['rtt_start_success'] else '❌'}")
        print(f"Data: {results['lines_received']} lines, {results['bytes_received']} bytes")
        if results['errors']:
            print(f"\nErrors:")
            for err in results['errors']:
                print(f"  - {err}")
        print()

    return 0 if results['rtt_start_success'] else 1


if __name__ == "__main__":
    exit(main())
