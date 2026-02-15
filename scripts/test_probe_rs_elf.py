#!/usr/bin/env python3
"""
Test probe-rs native RTT with ELF symbol reading.

This tests the new elf_path parameter that reads the _SEGGER_RTT symbol
from the ELF file instead of scanning RAM.

Usage:
    # With ELF file (RECOMMENDED - works with ST-Link)
    python3 test_probe_rs_elf.py --chip STM32L432KCUx --elf build/zephyr/zephyr.elf

    # Fallback to RAM scanning (may fail with ST-Link)
    python3 test_probe_rs_elf.py --chip STM32L432KCUx

    # With explicit address
    python3 test_probe_rs_elf.py --chip STM32L432KCUx --address 0x20001010
"""

import argparse
import sys
import time

try:
    from eab_probe_rs import ProbeRsSession
except ImportError:
    print("ERROR: eab_probe_rs not installed.")
    print("Run: pip install --break-system-packages eab_probe_rs-*.whl")
    sys.exit(1)


def main():
    parser = argparse.ArgumentParser(description="Test probe-rs RTT with ELF symbol reading")
    parser.add_argument("--chip", required=True, help="Target chip (e.g., STM32L432KCUx)")
    parser.add_argument("--elf", help="Path to ELF file (RECOMMENDED)")
    parser.add_argument("--address", type=lambda x: int(x, 0), help="RTT block address (hex or decimal)")
    parser.add_argument("--probe", help="Probe selector (serial/VID:PID)")
    parser.add_argument("--duration", type=int, default=10, help="Read duration in seconds")

    args = parser.parse_args()

    print(f"🔧 Connecting to {args.chip}...")
    session = ProbeRsSession(chip=args.chip, probe_selector=args.probe)

    try:
        session.attach()
        print("✓ Attached to target")

        # Start RTT with appropriate method
        if args.elf:
            print(f"📖 Reading _SEGGER_RTT symbol from ELF: {args.elf}")
            num_channels = session.start_rtt(elf_path=args.elf)
            print(f"✓ RTT started via ELF symbol - {num_channels} channels found")
        elif args.address:
            print(f"📍 Using explicit address: 0x{args.address:08x}")
            num_channels = session.start_rtt(block_address=args.address)
            print(f"✓ RTT started at address - {num_channels} channels found")
        else:
            print("🔍 Scanning RAM for RTT control block...")
            num_channels = session.start_rtt()
            print(f"✓ RTT started via RAM scan - {num_channels} channels found")

        # Read RTT data
        print(f"\n📡 Reading RTT channel 0 for {args.duration} seconds...")
        print("=" * 60)

        start_time = time.time()
        total_bytes = 0

        while time.time() - start_time < args.duration:
            data = session.rtt_read(channel=0)
            if data:
                total_bytes += len(data)
                try:
                    text = data.decode('utf-8', errors='replace')
                    print(text, end='', flush=True)
                except UnicodeDecodeError:
                    print(f"[Binary: {len(data)} bytes]", flush=True)
            time.sleep(0.01)  # 10ms poll interval

        print("\n" + "=" * 60)
        print(f"✓ Read {total_bytes} bytes total")

    except Exception as e:
        print(f"\n❌ Error: {e}")
        return 1
    finally:
        session.detach()
        print("✓ Detached")

    return 0


if __name__ == "__main__":
    sys.exit(main())
