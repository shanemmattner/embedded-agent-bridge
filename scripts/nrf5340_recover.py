#!/usr/bin/env python3
"""Recover a locked nRF5340 via CTRL-AP ERASEALL.

When APPROTECT is enabled (default when UICR is erased), the debug
AHB-APs lock and tools like JLinkExe/nrfjprog/probe-rs cannot connect.

This script uses raw SWD CORESIGHT operations to access the CTRL-AP
(which is ALWAYS accessible, even when cores are locked) and triggers
ERASEALL on both application and network cores.

Equivalent to: nrfjprog --recover (but doesn't require nrfjprog)

Usage:
    python3 nrf5340_recover.py

Requires: pylink-square
"""

import time

try:
    import pylink
except ImportError:
    print("ERROR: pip install pylink-square")
    raise SystemExit(1)


def recover_nrf5340():
    j = pylink.JLink()
    j.open()
    j.set_tif(pylink.enums.JLinkInterfaces.SWD)

    # Raw CORESIGHT — don't call connect() which fails on locked chips
    j.coresight_configure()

    dpidr = j.coresight_read(reg=0, ap=False)
    print(f"DPIDR = 0x{dpidr:08X}")

    if dpidr != 0x6BA02477:
        print("WARNING: Unexpected DPIDR. This may not be an nRF5340.")

    for ap_idx, name in [(2, "App core"), (3, "Net core")]:
        print(f"\n--- {name} (AP{ap_idx}) ---")

        # Select CTRL-AP
        j.coresight_write(reg=2, data=(ap_idx << 24), ap=False)

        # Verify AP IDR
        j.coresight_write(reg=2, data=(ap_idx << 24) | 0xF0, ap=False)
        idr = j.coresight_read(reg=3, ap=True)
        print(f"  AP IDR = 0x{idr:08X}", end="")
        if idr == 0x12880000:
            print(" (CTRL-AP OK)")
        else:
            print(" (UNEXPECTED — skipping)")
            continue

        # Switch to bank 0
        j.coresight_write(reg=2, data=(ap_idx << 24), ap=False)

        # Trigger ERASEALL (register offset 0x004 = AP reg 1)
        print("  Triggering ERASEALL...")
        j.coresight_write(reg=1, data=0x01, ap=True)

        # Wait for completion
        for i in range(60):
            time.sleep(0.5)
            status = j.coresight_read(reg=2, ap=True)
            if status == 0:
                print(f"  ERASEALL complete ({(i+1)*0.5:.1f}s)")
                break
        else:
            print("  ERASEALL timed out!")
            j.close()
            return False

    # Reset via App core CTRL-AP
    print("\nResetting chip...")
    j.coresight_write(reg=2, data=0x02000000, ap=False)
    j.coresight_write(reg=0, data=0x01, ap=True)
    time.sleep(0.1)
    j.coresight_write(reg=0, data=0x00, ap=True)

    j.close()
    print("\nRecovery complete. The chip is erased and unlocked.")
    print("You can now flash firmware normally.")
    return True


if __name__ == "__main__":
    print("nRF5340 CTRL-AP Recovery")
    print("=" * 40)
    recover_nrf5340()
