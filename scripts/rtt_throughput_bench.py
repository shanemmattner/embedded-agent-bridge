#!/usr/bin/env python3
"""RTT throughput benchmark — measure sustained binary RTT speed.

Connects to a target via J-Link, reads RTT data as fast as possible,
and reports throughput statistics. Works with any firmware that outputs
data on an RTT channel (text or binary).

Usage:
    python3 rtt_throughput_bench.py
    python3 rtt_throughput_bench.py --device NRF52840_XXAA --channel 0
    python3 rtt_throughput_bench.py --duration 30 --channel 1

Requires: pip install embedded-agent-bridge[jlink]
"""

import argparse
import sys
import time

try:
    from eab.rtt_transport import JLinkTransport
except ImportError:
    print("ERROR: pip install embedded-agent-bridge[jlink]")
    raise SystemExit(1)


def run_benchmark(device: str, channel: int, duration: float,
                  speed: int, serial_no: int | None):
    transport = JLinkTransport()

    connect_kwargs = {}
    if serial_no:
        connect_kwargs["serial_no"] = serial_no

    print(f"Connecting to {device} via J-Link SWD @ {speed} kHz...")
    transport.connect(device, "SWD", speed, **connect_kwargs)

    num_up = transport.start_rtt()
    print(f"RTT started: {num_up} up channel(s)")

    if channel >= num_up:
        print(f"ERROR: Channel {channel} not available (only {num_up} channels)")
        transport.stop_rtt()
        transport.disconnect()
        return

    print(f"Reading channel {channel} for {duration:.0f}s...\n")

    total_bytes = 0
    total_chunks = 0
    empty_reads = 0
    max_chunk = 0
    interval_bytes = 0
    last_report = time.monotonic()
    t0 = time.monotonic()

    try:
        while time.monotonic() - t0 < duration:
            data = transport.read(channel, 8192)
            if data:
                n = len(data)
                total_bytes += n
                total_chunks += 1
                interval_bytes += n
                if n > max_chunk:
                    max_chunk = n
            else:
                empty_reads += 1
                time.sleep(0.001)

            # Report every second
            now = time.monotonic()
            if now - last_report >= 1.0:
                elapsed = now - t0
                interval_rate = interval_bytes / (now - last_report)
                avg_rate = total_bytes / elapsed
                print(f"  [{elapsed:5.1f}s] {interval_rate/1024:7.1f} KB/s "
                      f"(avg {avg_rate/1024:.1f} KB/s, "
                      f"{total_bytes/1024:.0f} KB total)")
                interval_bytes = 0
                last_report = now

    except KeyboardInterrupt:
        print("\n  (interrupted)")

    elapsed = time.monotonic() - t0
    transport.stop_rtt()
    transport.disconnect()

    # Summary
    avg_throughput = total_bytes / elapsed if elapsed > 0 else 0
    print(f"\n{'='*50}")
    print(f"RTT Throughput Benchmark Results")
    print(f"{'='*50}")
    print(f"  Device:       {device}")
    print(f"  Channel:      {channel}")
    print(f"  Duration:     {elapsed:.2f}s")
    print(f"  Total data:   {total_bytes:,} bytes ({total_bytes/1024:.1f} KB)")
    print(f"  Throughput:   {avg_throughput/1024:.1f} KB/s")
    print(f"  Chunks:       {total_chunks:,} (avg {total_bytes/max(total_chunks,1):.0f} B)")
    print(f"  Max chunk:    {max_chunk:,} bytes")
    print(f"  Empty reads:  {empty_reads:,}")

    if avg_throughput > 0:
        for width, label in [(1, "uint8"), (2, "int16"), (4, "int32")]:
            rate = avg_throughput / width
            print(f"  → {rate/1000:.1f} kHz @ {label}")

    print(f"{'='*50}")


def main():
    parser = argparse.ArgumentParser(
        description="Measure RTT throughput from a J-Link debug probe.",
        formatter_class=argparse.RawDescriptionHelpFormatter,
        epilog="""
Examples:
  %(prog)s                                    # nRF5340, channel 0, 10s
  %(prog)s --channel 1 --duration 30          # binary channel, 30s
  %(prog)s --device NRF52840_XXAA             # different target
  %(prog)s --serial 801052657                 # specific J-Link probe
""")
    parser.add_argument("--device", default="NRF5340_XXAA_APP",
                        help="J-Link device name (default: NRF5340_XXAA_APP)")
    parser.add_argument("--channel", type=int, default=0,
                        help="RTT channel to read (default: 0)")
    parser.add_argument("--duration", type=float, default=10.0,
                        help="Test duration in seconds (default: 10)")
    parser.add_argument("--speed", type=int, default=4000,
                        help="SWD clock speed in kHz (default: 4000)")
    parser.add_argument("--serial", type=int, default=None,
                        help="J-Link serial number (for multi-probe setups)")
    args = parser.parse_args()

    run_benchmark(args.device, args.channel, args.duration,
                  args.speed, args.serial)


if __name__ == "__main__":
    main()
