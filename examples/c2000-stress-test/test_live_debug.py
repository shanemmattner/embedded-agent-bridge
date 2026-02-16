#!/usr/bin/env python3
"""Test live debugging of C2000 via CCS Scripting persistent debug server.

Connects to the LAUNCHXL-F280039C, reads/writes variables by name and
by address, and monitors sample_count in real-time.
"""

import sys
import time
from pathlib import Path

# Add parent for imports
sys.path.insert(0, str(Path(__file__).resolve().parents[2]))

from eab.debug_probes.ccs_client import CCSDebugClient

CCXML = "/tmp/c2000ware-core-sdk/device_support/f28003x/common/targetConfigs/TMS320F280039C_LaunchPad.ccxml"
OUT_FILE = str(Path(__file__).parent / "Debug" / "launchxl_ex1_f280039c_demo.out")


def main():
    print("=== C2000 Live Debug Test ===\n")

    with CCSDebugClient(ccxml=CCXML, out_file=OUT_FILE) as client:
        # 1. Read variables by name
        print("--- Reading variables by name ---")
        te = client.read_var("test_enabled")
        sc = client.read_var("sample_count")
        st = client.read_var("samples_target")
        print(f"  test_enabled   = {te}")
        print(f"  sample_count   = {sc}")
        print(f"  samples_target = {st}")

        # 2. Read by memory address (same vars)
        print("\n--- Reading by memory address ---")
        te_mem = client.read_mem(0xA840)
        sc_mem = client.read_mem(0xA842)
        print(f"  0xA840 (test_enabled)  = {te_mem}")
        print(f"  0xA842 (sample_count)  = {sc_mem}")

        # 3. Write test_enabled = 1 to start the test
        print("\n--- Starting test (write test_enabled = 1) ---")
        client.write_var("test_enabled", 1)
        verify = client.read_var("test_enabled")
        print(f"  test_enabled = {verify} (expected 1)")

        # 4. Resume target and monitor sample_count
        print("\n--- Resuming target, monitoring sample_count for 5s ---")
        client.run()

        for i in range(5):
            time.sleep(1)
            client.halt()
            sc = client.read_var("sample_count")
            te = client.read_var("test_enabled")
            print(f"  [{i+1}s] sample_count = {sc}, test_enabled = {te}")
            if i < 4:
                client.run()

        # 5. Stop the test
        print("\n--- Stopping test (write test_enabled = 0) ---")
        client.write_var("test_enabled", 0)
        final_sc = client.read_var("sample_count")
        print(f"  Final sample_count = {final_sc}")

        # 6. Resume target (leave it running)
        client.run()
        print("\nTarget resumed. Test complete!")

    print("\n=== Done ===")


if __name__ == "__main__":
    main()
