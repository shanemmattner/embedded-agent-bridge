#!/usr/bin/env python3
"""Live hardware test: Binary RTT capture end-to-end.

Proves the full EAB binary RTT pipeline works on real hardware:
1. JLinkTransport connects and reads RTT
2. BinaryWriter captures frames to .rttbin
3. BinaryReader reads them back with verified integrity
4. Converters produce CSV and numpy arrays
5. High-throughput stress test validates sustained performance
6. RTTBinaryCapture high-level API works end-to-end

Requirements:
  - J-Link probe connected to target (on-board or external)
  - Target running firmware that outputs on RTT (any channel)
  - pip install embedded-agent-bridge[jlink]

Usage:
    python3 rtt_live_test.py
    python3 rtt_live_test.py --device NRF52840_XXAA --channel 0
    python3 rtt_live_test.py --channel 1 --sample-width 2  # binary int16 data
"""

import argparse
import sys
import time
from pathlib import Path

try:
    from eab.rtt_transport import JLinkTransport
    from eab.rtt_binary import BinaryWriter, BinaryReader, RTTBinaryCapture, MAGIC, VERSION
    from eab.rtt_convert import to_csv
except ImportError:
    print("ERROR: pip install embedded-agent-bridge[jlink]")
    raise SystemExit(1)


passed = 0
failed = 0


def header(name):
    print(f"\n{'='*60}")
    print(f"  {name}")
    print(f"{'='*60}")


def result(ok, msg=""):
    global passed, failed
    if ok:
        passed += 1
        print(f"  PASS {msg}")
    else:
        failed += 1
        print(f"  FAIL {msg}")


def test_transport_connect(device, speed, channel):
    """Connect via JLinkTransport, start RTT, read data."""
    header("TEST 1: Transport connect + RTT read")

    transport = JLinkTransport()
    transport.connect(device, "SWD", speed)
    print(f"  Connected to {device}")

    num_up = transport.start_rtt()
    print(f"  RTT started: {num_up} up channels")
    assert num_up >= 1, f"Expected >=1 up channels, got {num_up}"

    total = 0
    chunks = 0
    t0 = time.monotonic()
    while time.monotonic() - t0 < 2.0:
        data = transport.read(channel, 4096)
        if data:
            total += len(data)
            chunks += 1
        else:
            time.sleep(0.01)

    throughput = total / 2
    print(f"  Read {total:,} bytes in {chunks} chunks (2s)")
    print(f"  Throughput: {throughput/1024:.1f} KB/s")

    transport.stop_rtt()
    transport.disconnect()
    result(total > 0, f"({total:,} bytes)")
    return total


def test_capture_to_rttbin(device, speed, channel, sample_width, output_dir):
    """Capture live RTT to .rttbin file."""
    header("TEST 2: Live capture to .rttbin (3s)")

    rttbin_path = output_dir / "live_capture.rttbin"

    transport = JLinkTransport()
    transport.connect(device, "SWD", speed)
    transport.start_rtt()

    writer = BinaryWriter(
        rttbin_path,
        channels=[channel],
        sample_width=sample_width,
        sample_rate=0,
        timestamp_hz=1000,
    )

    total_bytes = 0
    frame_count = 0
    t0 = time.monotonic()

    while time.monotonic() - t0 < 3.0:
        data = transport.read(channel, 4096)
        if data:
            elapsed_ms = int((time.monotonic() - t0) * 1000)
            writer.write_frame(channel, data, timestamp=elapsed_ms)
            total_bytes += len(data)
            frame_count += 1
        else:
            time.sleep(0.005)

    writer.close()
    transport.stop_rtt()
    transport.disconnect()

    file_size = rttbin_path.stat().st_size
    overhead = file_size - total_bytes - 64
    print(f"  Captured {total_bytes:,} bytes in {frame_count} frames")
    print(f"  File: {file_size:,} bytes ({overhead/max(frame_count,1):.1f} B/frame overhead)")

    result(frame_count > 0 and file_size > 64)
    return rttbin_path, total_bytes, frame_count


def test_read_back(rttbin_path, expected_bytes, expected_frames, channel, sample_width):
    """Read .rttbin back and verify integrity."""
    header("TEST 3: Read back + verify integrity")

    with BinaryReader(rttbin_path) as reader:
        assert reader.version == VERSION
        assert reader.sample_width == sample_width
        assert reader.timestamp_hz == 1000
        print(f"  Header: v{reader.version}, {reader.sample_width}B samples, "
              f"ts={reader.timestamp_hz} Hz")

        frames = reader.read_all()
        total = sum(len(p) for _, _, p in frames)
        print(f"  Frames: {len(frames)} (expected {expected_frames})")
        print(f"  Payload: {total:,} bytes (expected {expected_bytes:,})")

        ok = (len(frames) == expected_frames and total == expected_bytes)

        # Verify timestamps are monotonic
        timestamps = [ts for ts, _, _ in frames]
        monotonic = all(timestamps[i] >= timestamps[i-1] for i in range(1, len(timestamps)))
        print(f"  Timestamps: {timestamps[0]} → {timestamps[-1]} ms (monotonic: {monotonic})")
        ok = ok and monotonic

        # Verify channel
        channels = set(ch for _, ch, _ in frames)
        print(f"  Channels: {channels}")
        ok = ok and (channels == {channel})

    result(ok)


def test_convert_csv(rttbin_path, output_dir):
    """Convert .rttbin to CSV."""
    header("TEST 4: Convert to CSV")

    csv_path = output_dir / "live_capture.csv"
    to_csv(rttbin_path, csv_path)

    lines = csv_path.read_text().strip().split("\n")
    print(f"  CSV: {len(lines)-1} data rows")
    print(f"  Header: {lines[0]}")

    ok = (lines[0] == "timestamp,channel,payload_hex,payload_length" and len(lines) > 1)
    result(ok)


def test_convert_numpy(rttbin_path, channel, sample_width):
    """Convert .rttbin to numpy arrays."""
    header("TEST 5: Convert to numpy")

    try:
        import numpy as np
        from eab.rtt_convert import to_numpy
    except ImportError:
        print("  SKIP (numpy not installed)")
        return

    data = to_numpy(rttbin_path, sample_width=sample_width)

    if channel in data:
        arr = data[channel]
        print(f"  Channel {channel}: {len(arr):,} samples, dtype={arr.dtype}")
        print(f"  Range: [{arr.min()}, {arr.max()}], mean={arr.mean():.1f}")
        result(len(arr) > 0)
    else:
        print(f"  Channel {channel} not in result (got: {list(data.keys())})")
        result(False)


def test_stress(device, speed, channel, output_dir):
    """High-throughput stress test with microsecond timestamps."""
    header("TEST 6: Stress test (5s, tight loop)")

    rttbin_path = output_dir / "stress_capture.rttbin"

    transport = JLinkTransport()
    transport.connect(device, "SWD", speed)
    transport.start_rtt()

    writer = BinaryWriter(
        rttbin_path,
        channels=[channel],
        sample_width=1,
        sample_rate=0,
        timestamp_hz=1_000_000,
    )

    total_bytes = 0
    frame_count = 0
    empty_reads = 0
    t0 = time.monotonic()

    while time.monotonic() - t0 < 5.0:
        data = transport.read(channel, 8192)
        if data:
            elapsed_us = int((time.monotonic() - t0) * 1_000_000)
            writer.write_frame(channel, data, timestamp=elapsed_us)
            total_bytes += len(data)
            frame_count += 1
        else:
            empty_reads += 1
            time.sleep(0.001)

    elapsed = time.monotonic() - t0
    writer.close()
    transport.stop_rtt()
    transport.disconnect()

    throughput = total_bytes / elapsed
    print(f"  Duration: {elapsed:.2f}s")
    print(f"  Data: {total_bytes:,} bytes ({total_bytes/1024:.1f} KB)")
    print(f"  Throughput: {throughput/1024:.1f} KB/s")
    print(f"  Frames: {frame_count:,}, empty reads: {empty_reads:,}")

    # Verify round-trip
    with BinaryReader(rttbin_path) as reader:
        frames = reader.read_all()
        readback = sum(len(p) for _, _, p in frames)
        ok = (readback == total_bytes)
        if frames:
            span_us = frames[-1][0] - frames[0][0]
            print(f"  Timestamp span: {span_us/1e6:.2f}s")

    print(f"  Round-trip: {'OK' if ok else 'MISMATCH'}")
    result(ok)


def test_capture_api(device, speed, channel, sample_width, output_dir):
    """RTTBinaryCapture high-level API end-to-end."""
    header("TEST 7: RTTBinaryCapture API (3s)")

    output = output_dir / "api_capture.rttbin"

    capture = RTTBinaryCapture(
        transport=JLinkTransport(),
        device=device,
        channels=[channel],
        output_path=output,
        sample_width=sample_width,
        sample_rate=0,
        timestamp_hz=1000,
        interface="SWD",
        speed=speed,
        poll_interval=0.005,
    )

    capture.start()
    print(f"  Capture running: {capture.is_running}")
    time.sleep(3.0)
    summary = capture.stop()

    print(f"  Bytes: {summary['total_bytes']:,}")
    print(f"  Frames: {summary['total_frames']}")

    # Verify file
    with BinaryReader(output) as reader:
        frames = reader.read_all()
        total = sum(len(p) for _, _, p in frames)
        ok = (total == summary["total_bytes"] and total > 0)

    # Test CSV export
    csv_out = capture.to_csv()
    csv_lines = csv_out.read_text().strip().split("\n")
    print(f"  CSV: {len(csv_lines)-1} rows")
    ok = ok and csv_out.exists()

    result(ok)


def main():
    parser = argparse.ArgumentParser(
        description="Live hardware test for EAB binary RTT capture.",
        formatter_class=argparse.RawDescriptionHelpFormatter,
        epilog="""
Requirements:
  - J-Link connected to target (on-board DK probe or external)
  - Target running firmware that outputs on the specified RTT channel
  - For binary data tests (channel 1), use the rtt-binary-blast example firmware

Examples:
  %(prog)s                                        # defaults (nRF5340, ch0)
  %(prog)s --channel 1 --sample-width 2           # binary int16 (blast firmware)
  %(prog)s --device NRF52840_XXAA --channel 0     # different target
""")
    parser.add_argument("--device", default="NRF5340_XXAA_APP",
                        help="J-Link device name (default: NRF5340_XXAA_APP)")
    parser.add_argument("--channel", type=int, default=0,
                        help="RTT channel to test (default: 0)")
    parser.add_argument("--sample-width", type=int, default=1, choices=[1, 2, 4],
                        help="Bytes per sample for format tests (default: 1)")
    parser.add_argument("--speed", type=int, default=4000,
                        help="SWD clock speed in kHz (default: 4000)")
    parser.add_argument("--output-dir", type=Path, default=None,
                        help="Output directory (default: /tmp/rtt_live_test)")
    args = parser.parse_args()

    output_dir = args.output_dir or Path("/tmp/rtt_live_test")
    output_dir.mkdir(parents=True, exist_ok=True)

    global passed, failed

    print("=" * 60)
    print("  EAB Binary RTT Capture — Live Hardware Test")
    print(f"  Device:  {args.device}")
    print(f"  Channel: {args.channel}")
    print(f"  Output:  {output_dir}")
    print("=" * 60)

    try:
        test_transport_connect(args.device, args.speed, args.channel)
        rttbin, nbytes, nframes = test_capture_to_rttbin(
            args.device, args.speed, args.channel, args.sample_width, output_dir)
        test_read_back(rttbin, nbytes, nframes, args.channel, args.sample_width)
        test_convert_csv(rttbin, output_dir)
        test_convert_numpy(rttbin, args.channel, args.sample_width)
        test_stress(args.device, args.speed, args.channel, output_dir)
        test_capture_api(args.device, args.speed, args.channel,
                         args.sample_width, output_dir)
    except Exception as e:
        print(f"\n  FATAL: {e}")
        import traceback
        traceback.print_exc()
        failed += 1

    print(f"\n{'='*60}")
    print(f"  Results: {passed} passed, {failed} failed")
    print(f"{'='*60}")

    if output_dir.exists():
        print(f"\nOutput files:")
        for f in sorted(output_dir.iterdir()):
            print(f"  {f.name}: {f.stat().st_size:,} bytes")

    sys.exit(1 if failed > 0 else 0)


if __name__ == "__main__":
    main()
