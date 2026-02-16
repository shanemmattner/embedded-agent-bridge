#!/usr/bin/env python3
"""
Main Test Orchestrator

Discovers connected devices and runs isolated tests for each.
Aggregates results into a comprehensive report.

Usage:
    python3 tests/run_all_tests.py
    python3 tests/run_all_tests.py --devices esp32c6,nrf5340
    python3 tests/run_all_tests.py --duration 60 --json
"""

import argparse
import json
import sys
from pathlib import Path
from typing import List, Dict

# Add tests directory to path
sys.path.insert(0, str(Path(__file__).parent))

from device_discovery import discover_devices
from test_esp32 import ESP32Test, get_firmware_dir as get_esp32_firmware
from test_nrf import nRF5340Test


def run_esp32_test(chip: str, port: str, duration: int) -> Dict:
    """Run ESP32 family test"""
    firmware_dir = get_esp32_firmware(chip)
    if not firmware_dir:
        return {"chip": chip, "error": "Unknown chip type"}

    test = ESP32Test(chip, port, firmware_dir)
    return test.run_full_test(duration)


def run_nrf_test(duration: int) -> Dict:
    """Run nRF5340 test"""
    test = nRF5340Test()
    return test.run_full_test(duration)


def main():
    parser = argparse.ArgumentParser(description="Run all hardware tests")
    parser.add_argument("--devices", help="Comma-separated list of devices to test (e.g., esp32c6,nrf5340)")
    parser.add_argument("--duration", type=int, default=30, help="Data collection duration per device (seconds)")
    parser.add_argument("--json", action="store_true", help="Output results as JSON")
    args = parser.parse_args()

    # Discover devices
    print("🔍 Discovering connected devices...")
    all_devices = discover_devices()
    print(f"   Found {len(all_devices)} devices")
    print()

    # Filter devices if specified
    if args.devices:
        device_filter = set(args.devices.split(","))
        test_devices = [d for d in all_devices if d["chip"] in device_filter]
    else:
        test_devices = all_devices

    if not test_devices:
        print("❌ No devices to test")
        return 1

    # Run tests
    results = []

    for device in test_devices:
        chip = device["chip"]
        port = device["port"]

        # Skip unknown chips
        if chip == "unknown":
            print(f"⏭️  Skipping unknown device at {port}")
            continue

        print(f"\n{'='*70}")
        print(f"Testing: {chip} at {port}")
        print(f"{'='*70}")

        try:
            # ESP32 family
            if chip in ["esp32c6", "esp32p4", "esp32s3"]:
                result = run_esp32_test(chip, port, args.duration)
                results.append(result)

            # nRF5340
            elif chip == "nrf5340":
                result = run_nrf_test(args.duration)
                results.append(result)

            # Others not yet implemented
            else:
                print(f"⏭️  Test not yet implemented for {chip}")
                results.append({
                    "chip": chip,
                    "port": port,
                    "error": "Test not implemented"
                })

        except Exception as e:
            print(f"❌ Test failed: {e}")
            results.append({
                "chip": chip,
                "port": port,
                "error": str(e)
            })

    # Summary
    print(f"\n{'='*70}")
    print("Test Summary")
    print(f"{'='*70}\n")

    passed = 0
    failed = 0

    for result in results:
        chip = result.get("chip", "unknown")
        if "error" in result:
            print(f"❌ {chip}: {result['error']}")
            failed += 1
        elif result.get("boot_success") or result.get("rtt_start_success"):
            print(f"✅ {chip}: {result.get('lines_received', 0)} lines collected")
            passed += 1
        else:
            print(f"❌ {chip}: Test failed")
            failed += 1

    print()
    print(f"Passed: {passed}/{len(results)}")
    print(f"Failed: {failed}/{len(results)}")
    print()

    # JSON output
    if args.json:
        output_file = "/tmp/eab-test-results.json"
        with open(output_file, "w") as f:
            json.dump({"results": results, "summary": {"passed": passed, "failed": failed}}, f, indent=2)
        print(f"💾 Results saved to: {output_file}")

    return 0 if failed == 0 else 1


if __name__ == "__main__":
    exit(main())
