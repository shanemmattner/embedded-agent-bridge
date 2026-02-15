#!/usr/bin/env python3
"""Test probe-rs RTT transport on all connected boards.

This script tests probe-rs connectivity and RTT support for each board type:
- nRF5340 (J-Link probe)
- STM32L476RG (ST-Link probe)
- MCXN947 (CMSIS-DAP probe)
- ESP32-C6 (ESP USB-JTAG probe)

Each test:
1. Connects to the board via probe-rs
2. Attempts to start RTT
3. Reads RTT data if available
4. Reports results (pass/fail with details)
"""

import sys
import time
from dataclasses import dataclass
from typing import Optional

# Test configuration for each board
@dataclass
class BoardConfig:
    name: str
    chip: str  # probe-rs chip identifier
    probe_selector: Optional[str]  # VID:PID or serial number
    probe_type: str  # For reporting


BOARDS = [
    BoardConfig(
        name="nRF5340 DK",
        chip="nRF5340_xxAA",  # probe-rs chip name (no _app suffix)
        probe_selector=None,  # Auto-detect (will use J-Link for nRF)
        probe_type="J-Link (auto-detect)",
    ),
    BoardConfig(
        name="STM32 Nucleo L476RG",
        chip="STM32L476RGTx",
        probe_selector=None,  # Auto-detect (will use ST-Link for STM32)
        probe_type="ST-Link V2-1 (auto-detect)",
    ),
    BoardConfig(
        name="FRDM-MCXN947",
        chip="MCXN947",
        probe_selector=None,  # Auto-detect (will use CMSIS-DAP for NXP)
        probe_type="CMSIS-DAP (auto-detect)",
    ),
    BoardConfig(
        name="ESP32-C6",
        chip="esp32c6",
        probe_selector=None,  # Auto-detect (will use ESP JTAG for ESP32)
        probe_type="ESP USB-JTAG (auto-detect)",
    ),
]


def test_board(config: BoardConfig) -> dict:
    """Test probe-rs RTT on a single board.

    Returns:
        dict with keys: board, probe_type, connected, rtt_available,
                       num_channels, sample_data, error
    """
    result = {
        "board": config.name,
        "chip": config.chip,
        "probe_type": config.probe_type,
        "probe_selector": config.probe_selector,
        "connected": False,
        "rtt_available": False,
        "num_channels": 0,
        "sample_data": None,
        "error": None,
    }

    try:
        from eab_probe_rs import ProbeRsSession
    except ImportError as e:
        result["error"] = f"eab_probe_rs extension not installed: {e}"
        return result

    session = None
    try:
        # Create session
        session = ProbeRsSession(chip=config.chip, probe_selector=config.probe_selector)

        # Attach to target
        session.attach()
        result["connected"] = True

        # Try to start RTT
        try:
            num_channels = session.start_rtt()
            result["rtt_available"] = True
            result["num_channels"] = num_channels

            # Read sample data (non-blocking, may be empty)
            sample = session.rtt_read(channel=0)
            if sample:
                # Try to decode as UTF-8, truncate to 100 chars
                try:
                    decoded = sample.decode('utf-8', errors='replace')[:100]
                    result["sample_data"] = decoded
                except Exception:
                    result["sample_data"] = f"<binary: {len(sample)} bytes>"

        except Exception as e:
            # RTT not available (expected if firmware doesn't have RTT)
            error_msg = str(e)
            if "RTT control block not found" in error_msg:
                result["error"] = "Firmware does not have RTT enabled (expected)"
            else:
                result["error"] = f"RTT start failed: {error_msg}"

    except Exception as e:
        result["error"] = f"Connection failed: {e}"

    finally:
        if session:
            try:
                session.detach()
            except Exception:
                pass

    return result


def print_result(result: dict):
    """Pretty-print test result."""
    print(f"\n{'=' * 70}")
    print(f"Board: {result['board']}")
    print(f"Chip: {result['chip']}")
    print(f"Probe: {result['probe_type']} ({result['probe_selector']})")
    print(f"{'=' * 70}")

    if result["connected"]:
        print("✓ Connected to target")

        if result["rtt_available"]:
            print(f"✓ RTT available ({result['num_channels']} channels)")
            if result["sample_data"]:
                print(f"✓ Sample data: {result['sample_data']}")
            else:
                print("⚠ No data available (firmware may not be outputting yet)")
        else:
            print("✗ RTT not available")
            if result["error"]:
                print(f"  {result['error']}")
    else:
        print("✗ Failed to connect")
        if result["error"]:
            print(f"  {result['error']}")


def main():
    print("=" * 70)
    print("probe-rs RTT Transport Test - All Boards")
    print("=" * 70)
    print(f"\nTesting {len(BOARDS)} boards...")

    results = []
    for config in BOARDS:
        result = test_board(config)
        results.append(result)
        print_result(result)
        time.sleep(0.5)  # Brief delay between tests

    # Summary
    print("\n" + "=" * 70)
    print("SUMMARY")
    print("=" * 70)

    connected = sum(1 for r in results if r["connected"])
    rtt_available = sum(1 for r in results if r["rtt_available"])

    print(f"Boards connected: {connected}/{len(BOARDS)}")
    print(f"RTT available: {rtt_available}/{len(BOARDS)}")

    print("\nStatus by board:")
    for r in results:
        status = "✓ PASS" if r["connected"] else "✗ FAIL"
        rtt_status = "RTT ✓" if r["rtt_available"] else "RTT ✗"
        print(f"  {status:10} {rtt_status:10} {r['board']}")

    # Exit code: 0 if all connected, 1 otherwise
    return 0 if connected == len(BOARDS) else 1


if __name__ == "__main__":
    sys.exit(main())
