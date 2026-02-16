#!/usr/bin/env python3
"""
Quick device verification - tests connectivity to all devices in devices.json

Usage:
    python3 scripts/verify_devices.py
    python3 scripts/verify_devices.py --devices esp32-c6,nrf5340-1
"""

import argparse
import json
import subprocess
import sys
from pathlib import Path


def run_cmd(cmd, check=False):
    """Run command and return (returncode, stdout, stderr)"""
    result = subprocess.run(cmd, capture_output=True, text=True)
    if check and result.returncode != 0:
        print(f"❌ Command failed: {' '.join(cmd)}")
        print(f"   Error: {result.stderr}")
        return None
    return result


def register_device(device):
    """Register device with eabctl"""
    cmd = [
        "eabctl", "device", "add",
        device["name"],
        "--type", "debug" if device["transport"] in ["rtt", "dss", "apptrace"] else "serial",
        "--chip", device["chip"],
        "--json"
    ]
    result = run_cmd(cmd)
    if result and result.returncode == 0:
        return json.loads(result.stdout).get("registered", False)
    return False


def check_port_exists(port):
    """Check if port device exists"""
    return Path(port).exists()


def verify_probe(device):
    """Verify debug probe connectivity"""
    probe_type = device["debug_probe"]
    chip = device["chip"]

    if probe_type == "jlink":
        # Try to connect with JLinkExe
        cmd = ["JLinkExe", "-device", chip.upper(), "-if", "SWD", "-speed", "4000", "-autoconnect", "1", "-CommandFile", "/dev/stdin"]
        # TODO: Send "exit" command via stdin
        return None  # Skip for now

    elif probe_type == "xds110":
        # C2000 XDS110 - check via DSLite or OpenOCD
        return None  # Skip for now

    elif probe_type in ["cmsis-dap", "stlink-v2", "stlink-v3"]:
        # Try probe-rs
        cmd = ["probe-rs", "list"]
        result = run_cmd(cmd)
        if result and result.returncode == 0:
            return True
        return None

    return None


def main():
    parser = argparse.ArgumentParser(description="Verify device connectivity")
    parser.add_argument("--config", default="devices.json", help="Device config path")
    parser.add_argument("--devices", help="Comma-separated device names")
    args = parser.parse_args()

    # Load config
    with open(args.config) as f:
        config = json.load(f)

    devices = config["devices"]
    if args.devices:
        filter_names = set(args.devices.split(','))
        devices = [d for d in devices if d["name"] in filter_names]

    print(f"\n{'='*70}")
    print(f"Device Verification ({len(devices)} devices)")
    print(f"{'='*70}\n")

    results = []
    for device in devices:
        name = device["name"]
        chip = device["chip"]
        port = device["port"]
        firmware = device.get("firmware", "TBD")

        print(f"📦 {name} ({chip})")

        # Check port
        port_ok = check_port_exists(port)
        status_port = "✅" if port_ok else "❌"
        print(f"   Port {port}: {status_port}")

        # Check firmware
        fw_exists = firmware != "TBD" and firmware and Path(firmware).exists()
        status_fw = "✅" if fw_exists else "⚠️"
        print(f"   Firmware: {status_fw} {firmware}")

        # Register device
        if port_ok:
            registered = register_device(device)
            status_reg = "✅" if registered else "⚠️"
            print(f"   Registration: {status_reg}")
        else:
            registered = False
            print(f"   Registration: ⏭️  (port missing)")

        # Verify probe
        # probe_ok = verify_probe(device)
        # status_probe = "✅" if probe_ok else ("⚠️" if probe_ok is None else "❌")
        # print(f"   Probe: {status_probe}")

        results.append({
            "name": name,
            "port_ok": port_ok,
            "firmware_ok": fw_exists,
            "registered": registered,
            "ready": port_ok and fw_exists and registered
        })

        print()

    # Summary
    print(f"{'='*70}")
    ready_count = sum(1 for r in results if r["ready"])
    print(f"Ready for testing: {ready_count}/{len(results)}")

    ready_devices = [r["name"] for r in results if r["ready"]]
    if ready_devices:
        print(f"\n✅ Ready: {', '.join(ready_devices)}")

    not_ready = [r["name"] for r in results if not r["ready"]]
    if not_ready:
        print(f"⚠️  Not ready: {', '.join(not_ready)}")

    print(f"{'='*70}\n")

    return 0 if ready_count > 0 else 1


if __name__ == "__main__":
    sys.exit(main())
