#!/usr/bin/env python3
"""
Device Discovery - Find and identify connected hardware

Scans USB ports and matches against known device signatures.
Used by all test scripts to locate target devices.

Usage:
    python3 tests/device_discovery.py
    python3 tests/device_discovery.py --chip esp32c6
    python3 tests/device_discovery.py --json
"""

import argparse
import json
import subprocess
from pathlib import Path
from typing import List, Dict, Optional


def get_serial_ports() -> List[str]:
    """Get all serial port device paths"""
    import glob
    try:
        ports = glob.glob("/dev/cu.usb*")
        return sorted(ports)
    except Exception:
        return []


def get_port_info(port: str) -> Optional[Dict]:
    """Get USB device info for a port using system_profiler"""
    try:
        # Get USB device tree
        result = subprocess.run(
            ["system_profiler", "SPUSBDataType", "-json"],
            capture_output=True,
            text=True,
            timeout=10,
        )
        if result.returncode != 0:
            return None

        data = json.loads(result.stdout)

        # Extract serial number from port path
        # e.g., /dev/cu.usbmodem101 -> look for device with location ID matching
        port_name = Path(port).name  # e.g., cu.usbmodem101

        # Search USB tree for matching device
        def search_usb_tree(items, depth=0):
            if not isinstance(items, list):
                return None
            for item in items:
                # Check if this device matches our port
                if "_name" in item:
                    # Try to match based on available info
                    product = item.get("_name", "")
                    vendor = item.get("manufacturer", "")
                    serial = item.get("serial_num", "")

                    # Return first device we find (simplified - could be more sophisticated)
                    if product or vendor or serial:
                        return {
                            "product": product,
                            "manufacturer": vendor,
                            "serial": serial,
                            "vid_pid": f"{item.get('vendor_id', 'unknown')}:{item.get('product_id', 'unknown')}",
                        }

                # Recurse into child devices
                if "_items" in item:
                    result = search_usb_tree(item["_items"], depth + 1)
                    if result:
                        return result
            return None

        # Search through all USB buses
        for bus in data.get("SPUSBDataType", []):
            if "_items" in bus:
                info = search_usb_tree(bus["_items"])
                if info:
                    return info

    except Exception as e:
        print(f"Warning: Could not get port info for {port}: {e}")

    return None


def identify_chip(port_info: Optional[Dict]) -> Optional[str]:
    """Identify chip type from USB device info"""
    if not port_info:
        return None

    product = port_info.get("product", "").lower()
    manufacturer = port_info.get("manufacturer", "").lower()
    vid_pid = port_info.get("vid_pid", "")

    # ESP32 family
    if "espressif" in manufacturer or "303a" in vid_pid:
        if "esp32c6" in product or "esp32-c6" in product:
            return "esp32c6"
        elif "esp32p4" in product or "esp32-p4" in product:
            return "esp32p4"
        elif "esp32s3" in product or "esp32-s3" in product:
            return "esp32s3"
        elif "esp32c3" in product or "esp32-c3" in product:
            return "esp32c3"
        else:
            return "esp32"  # generic

    # nRF family (SEGGER J-Link)
    elif "segger" in manufacturer or "j-link" in product:
        return "nrf5340"  # default, could inspect further

    # STM32 family (ST-Link)
    elif "stmicro" in manufacturer or "stlink" in product or "0483" in vid_pid:
        if "stlink-v3" in product:
            return "stm32l476rg"  # typical for STLINK-V3
        else:
            return "stm32"  # generic

    # NXP MCX family (CMSIS-DAP)
    elif "nxp" in manufacturer and "cmsis-dap" in product:
        return "mcxn947"

    # TI C2000 (XDS110)
    elif "texas instruments" in manufacturer and "xds110" in product:
        return "f28003x"

    return None


def discover_devices(chip_filter: Optional[str] = None) -> List[Dict]:
    """Discover all connected devices"""
    # Load known devices from config
    config_path = Path(__file__).parent.parent / "devices.json"
    if config_path.exists():
        with open(config_path) as f:
            config = json.load(f)
            known_devices = {d["port"]: d for d in config["devices"]}
    else:
        known_devices = {}

    ports = get_serial_ports()
    devices = []

    for port in ports:
        # Check if this is a known device
        if port in known_devices:
            dev = known_devices[port]
            if chip_filter and dev["chip"] != chip_filter:
                continue

            devices.append({
                "port": port,
                "chip": dev["chip"],
                "product": dev.get("product", "Unknown"),
                "manufacturer": dev.get("manufacturer", "Unknown"),
                "serial": dev.get("serial", "Unknown"),
            })
        else:
            # Try to identify unknown device
            info = get_port_info(port)
            chip = identify_chip(info)

            if chip_filter and chip != chip_filter:
                continue

            devices.append({
                "port": port,
                "chip": chip or "unknown",
                "product": info.get("product", "Unknown") if info else "Unknown",
                "manufacturer": info.get("manufacturer", "Unknown") if info else "Unknown",
                "serial": info.get("serial", "Unknown") if info else "Unknown",
            })

    return devices


def main():
    parser = argparse.ArgumentParser(description="Discover connected hardware devices")
    parser.add_argument("--chip", help="Filter by chip type (esp32c6, nrf5340, etc)")
    parser.add_argument("--json", action="store_true", help="Output as JSON")
    args = parser.parse_args()

    devices = discover_devices(args.chip)

    if args.json:
        print(json.dumps({"devices": devices}, indent=2))
    else:
        print(f"\n{'='*70}")
        print(f"Device Discovery ({len(devices)} devices)")
        print(f"{'='*70}\n")

        for dev in devices:
            print(f"📦 {dev['chip']}")
            print(f"   Port: {dev['port']}")
            print(f"   Product: {dev['product']}")
            print(f"   Manufacturer: {dev['manufacturer']}")
            print(f"   Serial: {dev['serial']}")
            print()


if __name__ == "__main__":
    main()
