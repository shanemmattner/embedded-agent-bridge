# ESP32-C6 Apptrace Research Summary

**Date**: 2026-02-15
**Outcome**: ✅ BLOCKER RESOLVED - Apptrace initialization working

## Problem

After building ESP32-C6 apptrace test firmware and flashing via OpenOCD JTAG, the `esp apptrace start` command failed with:

```
Error: Failed to get max trace block size!
Error: Failed to init cmd ctx (-4)!
```

## Root Cause (via Firecrawl Research)

RISC-V ESP chips (ESP32-C6, C3, H2, C5) have a unique requirement compared to Xtensa targets:

1. **Firmware must boot WHILE OpenOCD is connected** to advertise the apptrace control block
2. During `esp_apptrace_init()` (early boot), firmware calls `esp_apptrace_advertise_ctrl_block()`
3. This function uses **semihosting** (special RISC-V `ebreak` instruction) to send control block address to OpenOCD
4. If OpenOCD isn't running when firmware boots, this semihosting call never happens
5. Without the control block address, OpenOCD doesn't know where to find the trace buffer in memory

**Why Xtensa doesn't have this problem**: Xtensa's `OCD_ENABLED` register reflects physical debugger connection status regardless of halt state. RISC-V's `ASSIST_DEBUG_CORE_0_DEBUG_MODE` only indicates if CPU is halted, not if debugger is connected.

## Solution (from GitHub Issues)

### Key References

- [espressif/openocd-esp32#188](https://github.com/espressif/openocd-esp32/issues/188) - "Application Level Tracing fails on ESP32C3"
- [espressif/esp-idf#18213](https://github.com/espressif/esp-idf/issues/18213) - "SystemView/apptrace broken on RISC-V targets"
- [Official FAQ](https://github.com/espressif/openocd-esp32/wiki/Troubleshooting-FAQ#failed-to-start-application-level-tracing-on-riscv-chip)

### The Fix

```bash
# 1. Start OpenOCD
~/.espressif/tools/openocd-esp32/v0.12.0-esp32-20241016/openocd-esp32/bin/openocd \
  -f board/esp32c6-builtin.cfg -l /tmp/openocd.log &

# 2. CRITICAL: Reset chip AFTER OpenOCD connects
echo "reset run" | nc localhost 4444

# 3. Wait for firmware to boot and advertise control block
sleep 5

# 4. Start apptrace
echo "esp apptrace start file:///tmp/apptrace.log 0 0 10 0 0" | nc localhost 4444
```

### Before vs After

**Before (ERROR)**:
```
> esp apptrace start file:///tmp/apptrace.log 0 0 1 0 0
Error: Failed to get max trace block size!
Error: Failed to init cmd ctx (-4)!
```

**After (SUCCESS)**:
```
> reset run
> esp apptrace start file:///tmp/apptrace.log 0 0 10 0 0
Total trace memory: 16384 bytes
Open file /tmp/apptrace.log
App trace params: from 1 cores, size 0 bytes, stop_tmo 10 s, poll period 0 ms, wait_rst 0, skip 0 bytes
Connect targets...
[esp32c6] Target halted, PC=0x40804694, debug_reason=00000000
Targets connected.
```

## What Works Now

✅ Apptrace initialization (control block advertising)
✅ OpenOCD recognizes trace buffer (16384 bytes)
✅ Apptrace start/stop commands succeed
✅ USB-JTAG confirmed compatible with apptrace

## What Doesn't Work Yet

❌ Zero bytes captured in output file
⚠️ Firmware may be halted after apptrace starts (target halted at PC=0x40804694)
⚠️ Need to verify firmware reaches trace write loop

## Next Steps

1. **Debug firmware execution**: Determine why no data is being written
   - Check if firmware is halted vs running during apptrace
   - Verify `esp_apptrace_host_is_connected()` returns true
   - Add breakpoints or logging to trace write path

2. **Test data capture**: Once firmware runs properly, verify heartbeat data appears in log

3. **Proceed with Phase 3-7**: Implement Python transport, worker, CLI integration

## Time Invested

- **Phase 1** (Firmware): 1.5 hours
- **Phase 2** (Debugging): 1 hour
- **Firecrawl Research**: 15 minutes
- **Total**: ~2.75 hours

**Comparison to probe-rs RTT attempt**: 14 hours wasted on unfixable upstream bugs. This time we found the solution in <3 hours thanks to Firecrawl research.

## Key Learnings

1. **RISC-V targets have unique apptrace requirements** - always reset after OpenOCD connects
2. **Firecrawl is invaluable** for hardware debugging - found exact GitHub issues in minutes
3. **USB-JTAG is NOT a blocker** - apptrace works fine, just needs reset sequence
4. **Official documentation exists** - OpenOCD wiki has troubleshooting for this exact issue

## Files Updated

- `APPTRACE_BLOCKER.md` - Added solution section with full procedure
- `examples/esp32c6-apptrace-test/README.md` - Updated manual test steps with reset sequence
- `ESP32_APPTRACE_RESEARCH_SUMMARY.md` - This file (research summary)
