#!/usr/bin/env python3
"""
EAB BLE Central — Live Demo Client
====================================
Connects to the nRF5340 EAB-Peripheral, subscribes to sensor notifications,
and prints live DATA packets to the terminal.

When connected, the firmware emits:
    DATA: counter=N temp=XX.XX notify_count=N

These appear in RTT (rtt-raw.log) and flow to the Plotly Dash dashboard.

Usage:
    python bleak_central.py              # auto-scan for EAB-Peripheral
    python bleak_central.py --addr AA:BB:CC:DD:EE:FF  # connect directly
    python bleak_central.py --scan      # scan and list devices only
"""

from __future__ import annotations

import argparse
import asyncio
import json
import struct
import sys
import time
from datetime import datetime

try:
    from bleak import BleakClient, BleakScanner
    from bleak.backends.characteristic import BleakGATTCharacteristic
except ImportError:
    print("ERROR: bleak not installed. Run: pip install bleak")
    sys.exit(1)

# ---------------------------------------------------------------------------
# GATT UUIDs (from nrf-ble-peripheral firmware)
# ---------------------------------------------------------------------------

SERVICE_UUID  = "eab20001-0000-1000-8000-00805f9b34fb"
NOTIFY_UUID   = "eab20002-0000-1000-8000-00805f9b34fb"  # notify: DATA packets
CONTROL_UUID  = "eab20003-0000-1000-8000-00805f9b34fb"  # write: 0x01=fast 0x02=slow 0x03=off
STATUS_UUID   = "eab20004-0000-1000-8000-00805f9b34fb"  # read: status

DEVICE_NAME   = "EAB-Peripheral"

# ---------------------------------------------------------------------------
# Terminal colors
# ---------------------------------------------------------------------------

RESET  = "\033[0m"
BOLD   = "\033[1m"
DIM    = "\033[2m"
RED    = "\033[91m"
GREEN  = "\033[92m"
YELLOW = "\033[93m"
BLUE   = "\033[94m"
CYAN   = "\033[96m"
GRAY   = "\033[90m"


def ts() -> str:
    return datetime.now().strftime("%H:%M:%S.%f")[:-3]


def parse_notify(data: bytearray) -> dict:
    """Parse the EAB notify packet.

    Firmware sends a raw struct OR prints DATA: lines via RTT.
    Try to decode as little-endian int32 counter + float temp.
    Fall back to raw hex if format doesn't match.
    """
    if len(data) >= 8:
        try:
            counter = struct.unpack_from("<i", data, 0)[0]
            temp    = struct.unpack_from("<f", data, 4)[0]
            return {"counter": counter, "temp": round(temp, 2), "raw": data.hex()}
        except Exception:
            pass
    return {"raw": data.hex(), "len": len(data)}


# ---------------------------------------------------------------------------
# Main client
# ---------------------------------------------------------------------------

class EABCentral:
    def __init__(self, addr: str | None = None):
        self.addr      = addr
        self.client    = None
        self._count    = 0
        self._start_ts = 0.0

    async def scan(self) -> list:
        """Scan for BLE devices and return list."""
        print(f"\n{CYAN}Scanning for BLE devices (5s)...{RESET}\n")
        devices = await BleakScanner.discover(timeout=5.0)
        return devices

    async def find_peripheral(self) -> str | None:
        """Scan and find EAB-Peripheral by name."""
        devices = await self.scan()
        for d in devices:
            name = d.name or ""
            if DEVICE_NAME in name or "EAB" in name:
                print(f"  {GREEN}✓{RESET}  Found: {BOLD}{name}{RESET}  [{d.address}]  RSSI={d.rssi} dBm")
                return d.address
            else:
                print(f"  {GRAY}·{RESET}  {name or '(no name)':30s} [{d.address}]  RSSI={d.rssi} dBm")
        return None

    def _on_notify(self, char: BleakGATTCharacteristic, data: bytearray):
        self._count += 1
        elapsed = time.time() - self._start_ts
        parsed = parse_notify(data)

        counter = parsed.get("counter", "?")
        temp    = parsed.get("temp", "?")
        raw     = parsed.get("raw", data.hex())

        # Color-code temperature
        if isinstance(temp, float):
            if temp > 30:
                temp_str = f"{RED}{temp:.2f}°C{RESET}"
            elif temp > 25:
                temp_str = f"{YELLOW}{temp:.2f}°C{RESET}"
            else:
                temp_str = f"{CYAN}{temp:.2f}°C{RESET}"
        else:
            temp_str = str(temp)

        rate = self._count / max(elapsed, 0.1)
        print(f"  [{ts()}]  #{self._count:4d}  "
              f"counter={BLUE}{counter}{RESET}  "
              f"temp={temp_str}  "
              f"rate={GRAY}{rate:.1f}/s{RESET}  "
              f"raw={GRAY}{raw}{RESET}")

    async def run(self):
        # Find device
        if not self.addr:
            self.addr = await self.find_peripheral()
            if not self.addr:
                print(f"\n{RED}✗  EAB-Peripheral not found.{RESET}")
                print(f"   Make sure nRF5340 is advertising.")
                print(f"   Try: eabctl rtt tail 5  →  should show ADVERTISING")
                return

        print(f"\n{CYAN}Connecting to {self.addr}...{RESET}")

        async with BleakClient(self.addr, timeout=10.0) as client:
            self.client = client
            print(f"  {GREEN}✓{RESET}  Connected!  MTU={client.mtu_size}")

            # List services
            print(f"\n  {GRAY}GATT services:{RESET}")
            for svc in client.services:
                marker = f"  {GREEN}★{RESET}" if SERVICE_UUID in str(svc.uuid).lower() else f"  {GRAY}·{RESET}"
                print(f"{marker}  {svc.uuid}  ({len(svc.characteristics)} chars)")

            # Read status characteristic
            try:
                status_val = await client.read_gatt_char(STATUS_UUID)
                print(f"\n  {CYAN}Status char:{RESET}  {status_val.hex()}  ({bytes(status_val).decode(errors='replace')})")
            except Exception as e:
                print(f"\n  {YELLOW}⚠{RESET}  Could not read status: {e}")

            # Subscribe to notifications
            print(f"\n  {CYAN}Subscribing to notifications...{RESET}")
            await client.start_notify(NOTIFY_UUID, self._on_notify)
            self._start_ts = time.time()

            # Set fast notify rate (0x01 = fast)
            try:
                await client.write_gatt_char(CONTROL_UUID, bytes([0x01]))
                print(f"  {GREEN}✓{RESET}  Control: set FAST notify rate (0x01)")
            except Exception as e:
                print(f"  {YELLOW}⚠{RESET}  Could not write control: {e}")

            print(f"\n  {BOLD}DATA packets flowing — Ctrl+C to stop{RESET}\n")
            print(f"  {'─'*72}")
            print(f"  Watch in dashboard:  {CYAN}http://192.168.0.19:8050{RESET}")
            print(f"  RTT log:             {GRAY}tail -f /tmp/eab-devices/default/rtt-raw.log{RESET}")
            print(f"  {'─'*72}\n")

            try:
                while True:
                    await asyncio.sleep(0.1)
            except (KeyboardInterrupt, asyncio.CancelledError):
                print(f"\n\n  {YELLOW}Stopping...{RESET}")
                await client.stop_notify(NOTIFY_UUID)

                # Set slow rate before disconnect
                try:
                    await client.write_gatt_char(CONTROL_UUID, bytes([0x02]))
                except Exception:
                    pass

                elapsed = time.time() - self._start_ts
                rate = self._count / max(elapsed, 0.1)
                print(f"  {GREEN}✓{RESET}  Received {self._count} notifications in {elapsed:.1f}s ({rate:.1f}/s)")
                print(f"  {GREEN}✓{RESET}  Disconnected cleanly\n")


async def scan_only():
    """Scan and print all visible BLE devices."""
    print(f"\n{CYAN}Scanning for BLE devices (8s)...{RESET}\n")
    devices = await BleakScanner.discover(timeout=8.0)
    devices.sort(key=lambda d: d.rssi or -999, reverse=True)
    print(f"  {'Name':35s} {'Address':20s} {'RSSI':>6}")
    print(f"  {'─'*63}")
    for d in devices:
        name   = d.name or "(no name)"
        marker = f"{GREEN}★ " if ("EAB" in name or DEVICE_NAME in name) else "  "
        print(f"  {marker}{name:33s} {d.address:20s} {d.rssi or 0:>5} dBm{RESET}")
    print(f"\n  {len(devices)} device(s) found\n")


if __name__ == "__main__":
    ap = argparse.ArgumentParser(description="EAB BLE Central Demo Client")
    ap.add_argument("--addr",  help="BLE address (skip scan)")
    ap.add_argument("--scan",  action="store_true", help="Scan only, don't connect")
    args = ap.parse_args()

    if args.scan:
        asyncio.run(scan_only())
    else:
        central = EABCentral(addr=args.addr)
        try:
            asyncio.run(central.run())
        except KeyboardInterrupt:
            print("\nAborted.")
