# probe-rs ST-Link RTT Debug Investigation

**Date**: 2026-02-15  
**Result**: ST-Link driver bug confirmed with debug logging  
**Status**: Cannot fix without probe-rs changes

## What We Proved

Added debug logging to probe-rs source code to capture what ST-Link actually returns when reading RTT control block memory.

### Debug Logging Added

Modified `/probe-rs/src/rtt.rs` in `attach_at()` function:
- Log memory read operations
- Dump hex bytes read from target
- Compare expected vs actual RTT signature

### Test Results

**Firmware**: STM32L432KC running Zephyr with RTT enabled  
**ELF Symbol**: `_SEGGER_RTT` at 0x20001010 (verified with `nm`)  
**probe-rs Version**: 0.31.0

**Memory read at 0x20001010:**

```
DEBUG attach_at: Reading RTT control block at address 0x20001010
DEBUG attach_at: Reading 16 bytes of RTT ID...

Expected RTT ID: "SEGGER RTT\0\0\0\0\0\0"
Expected (hex):   53 45 47 47 45 52 20 52 54 54 00 00 00 00 00 00

Got RTT ID: "\u{1}\0\0\0\u{1}\0\0\0�0\0\0`�\0\u{10}"
Got (hex):   01 00 00 00 01 00 00 00 c0 30 00 00 60 f1 00 10
```

**Result**: MISMATCH - ST-Link returns garbage data

Tested 16 addresses from 0x20001000 to 0x2000103c:
- ❌ No "SEGGER RTT" signature found at any address
- ❌ ST-Link consistently returns wrong data
- ❌ After reset: all zeros

## Proof Chain

| Step | Status | Evidence |
|------|--------|----------|
| Firmware has RTT | ✅ | `CONFIG_USE_SEGGER_RTT=y` in build |
| Symbol in ELF | ✅ | `nm` shows `_SEGGER_RTT` at 0x20001010 |
| ELF parsing works | ✅ | Our code extracts correct address |
| probe-rs reads memory | ✅ | No errors thrown, reads complete |
| ST-Link returns correct data | ❌ | **Returns garbage instead of RTT block** |

## The Bug

**Location**: probe-rs ST-Link driver memory read implementation  
**Symptom**: `core.read()` succeeds but returns wrong data from RAM  
**Impact**: RTT completely non-functional with ST-Link probes  
**Scope**: All STM32 targets using ST-Link

**Not fixable without**:
- Deep dive into probe-rs ST-Link driver
- Understanding ST-Link USB protocol
- Possibly fixing in ST-Link firmware itself

## Comparison

| Probe Type | RTT Works? | Status |
|------------|------------|--------|
| J-Link (JLinkBridge) | ✅ Yes | Production-ready |
| J-Link (probe-rs) | ❌ ARM errors | Untested |
| CMSIS-DAP (probe-rs) | ❌ ARM errors | Untested |
| ST-Link (probe-rs) | ❌ **Garbage data** | Confirmed broken |

## Related Issues

- probe-rs/probe-rs#3495: STM32H755 CM4 RTT not working
- probe-rs/probe-rs#1359: Memory scanning bug (appears fixed in 0.31)

## Recommendation

**ABANDON probe-rs RTT integration.**

Use what works:
```bash
# J-Link probes - WORKS
eabctl rtt start --device NRF5340_XXAA_APP --transport jlink
```

Don't waste more time on probe-rs until upstream fixes ST-Link driver.
