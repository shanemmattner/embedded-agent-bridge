# ESP32-C6 Apptrace Blocker

**Date**: 2026-02-15
**Status**: ✅ RESOLVED - Apptrace initialization working with reset sequence

## ✅ Solution Found

**Root Cause**: RISC-V ESP chips (C6, C3, H2, C5) must boot AFTER OpenOCD connects so firmware can advertise apptrace control block via semihosting during startup.

**The Fix** (from [OpenOCD issue #188](https://github.com/espressif/openocd-esp32/issues/188) and [ESP-IDF issue #18213](https://github.com/espressif/esp-idf/issues/18213)):

```bash
# 1. Start OpenOCD
~/.espressif/tools/openocd-esp32/v0.12.0-esp32-20241016/openocd-esp32/bin/openocd \
  -f board/esp32c6-builtin.cfg -l /tmp/openocd.log &

# 2. Reset chip AFTER OpenOCD connects (critical for RISC-V targets)
echo "reset run" | nc localhost 4444

# 3. Wait 5 seconds for firmware to boot and advertise control block
sleep 5

# 4. Start apptrace
echo "esp apptrace start file:///tmp/apptrace.log 0 0 10 0 0" | nc localhost 4444
```

**Result**: ✅ Apptrace initialization succeeds
```
Total trace memory: 16384 bytes
Open file /tmp/apptrace.log
App trace params: from 1 cores, size 0 bytes, stop_tmo 10 s, poll period 0 ms, wait_rst 0, skip 0 bytes
Connect targets...
[esp32c6] Target halted, PC=0x40804694, debug_reason=00000000
Targets connected.
```

**Official Documentation**: [OpenOCD Troubleshooting FAQ - RISC-V Apptrace](https://github.com/espressif/openocd-esp32/wiki/Troubleshooting-FAQ#failed-to-start-application-level-tracing-on-riscv-chip)

**Next Steps**: Debug firmware to verify data capture (currently 0 bytes written, likely firmware not resuming or not reaching trace write loop).

---

## What Works ✅

1. **Firmware built successfully**:
   - Location: `examples/esp32c6-apptrace-test/build/eab-test-firmware.bin` (149KB)
   - Config: `CONFIG_APPTRACE_ENABLE=y`, `CONFIG_APPTRACE_DEST_JTAG=y`
   - Includes: `esp_app_trace.h`, `esp_apptrace_write()`, `esp_apptrace_flush()`

2. **Firmware flashed via OpenOCD JTAG**:
   ```bash
   ~/.espressif/tools/openocd-esp32/v0.12.0-esp32-20241016/openocd-esp32/bin/openocd \
     -f board/esp32c6-builtin.cfg \
     -c "program_esp build/bootloader/bootloader.bin 0x0 verify" \
     -c "program_esp build/partition_table/partition-table.bin 0x8000 verify" \
     -c "program_esp build/eab-test-firmware.bin 0x10000 verify" \
     -c "reset run" -c "shutdown"
   ```
   **Result**: All 3 partitions verified successfully

3. **OpenOCD connects to ESP32-C6**:
   ```
   Info : esp_usb_jtag: serial (F0:F5:BD:01:88:2C)
   Info : JTAG tap: esp32c6.tap0 tap/device found: 0x0000dc25
   Info : Listening on port 4444 for telnet connections
   ```

## What Fails ❌

### Apptrace Start Command

**Command**:
```bash
telnet localhost 4444
esp apptrace start file:///tmp/apptrace.log 0 0 1 0 0
```

**Error**:
```
/Users/shane/.espressif/tools/openocd-esp32/v0.12.0-esp32-20241016/openocd-esp32/bin/../share/openocd/scripts/target/esp_common.cfg:9: Error:
Failed to get max trace block size!
Failed to init cmd ctx (-4)!
```

### Attempts Made

1. ❌ Halt CPU first: `halt` then `esp apptrace start` - same error
2. ❌ Resume CPU: `resume` - no change
3. ❌ Serial output check - port busy (can't verify firmware booted)

## Suspected Root Causes

1. **Version mismatch**: ESP-IDF 5.4 vs OpenOCD v0.12.0-esp32-20241016
   - Apptrace protocol may have changed
   - Command syntax may be different for ESP32-C6

2. **Firmware-side issue**:
   - Apptrace buffer not initialized correctly
   - `esp_apptrace_host_is_connected()` may not work with this OpenOCD version
   - Missing `esp_apptrace_init()` call (if required)

3. **USB-JTAG conflict**:
   - `CONFIG_ESP_CONSOLE_USB_SERIAL_JTAG=y` may conflict with OpenOCD
   - Serial console and JTAG debug both use the same USB interface
   - OpenOCD may lock out serial port access

4. **ESP32-C6 specific**:
   - Newer chip, less mature apptrace support
   - May need newer OpenOCD or different board config

## Next Steps to Unblock

### Option 1: Check ESP-IDF Examples (5 min)

```bash
cd ~/esp/esp-idf/examples/system/app_trace_basic
cat README.md
cat pytest_app_trace_basic.py  # See actual test commands
```

Look for:
- Exact `esp apptrace` command syntax
- Any ESP32-C6 specific notes
- OpenOCD version requirements

### Option 2: Try ESP32-S3 (30 min)

ESP32-S3 has more mature apptrace support. Test with that chip first to validate the approach.

### Option 3: Disable USB-JTAG Console (15 min)

Edit `sdkconfig.defaults`:
```
# Disable USB-JTAG console (conflicts with OpenOCD)
CONFIG_ESP_CONSOLE_USB_SERIAL_JTAG=n

# Use UART console instead (requires external USB-UART on GPIO16/17)
CONFIG_ESP_CONSOLE_UART=y
CONFIG_ESP_CONSOLE_UART_NUM=0
```

Rebuild and reflash, then retry apptrace.

### Option 4: Search ESP-IDF Forums (10 min)

Search terms:
- "esp32-c6 apptrace failed to get max trace block size"
- "esp32 apptrace openocd version"
- "esp_apptrace init cmd ctx"

Check:
- https://github.com/espressif/esp-idf/issues
- https://github.com/espressif/openocd-esp32/issues
- ESP32 forums

### Option 5: Simplify Firmware (20 min)

Remove complexity, test with ESP-IDF's exact app_trace_basic example:

```bash
cd ~/esp/esp-idf/examples/system/app_trace_basic
idf.py set-target esp32c6
idf.py build
# Flash via OpenOCD JTAG
# Test apptrace
```

If it works: compare configs to find what's different.
If it fails: confirms ESP32-C6 + OpenOCD v0.12.0 incompatibility.

## Alternative Approaches

### Plan B: Use System View Instead

ESP-IDF has SystemView tracing which might work better:
```
CONFIG_APPTRACE_SV_ENABLE=y
CONFIG_APPTRACE_DEST_JTAG=y
```

SystemView has better OpenOCD integration and documentation.

### Plan C: Use ESP-IDF Monitor

ESP-IDF's `idf.py monitor` has built-in support for apptrace:
```bash
idf.py -p /dev/tty.usbmodem101 monitor
# Then in monitor: "apptrace start"
```

This might bypass OpenOCD entirely.

### Plan D: Defer ESP32 Apptrace

- Mark issue #105 as blocked
- Document the blocker
- Move to other EAB features
- Revisit when ESP-IDF/OpenOCD versions mature

## Time Spent

- Phase 1 (Firmware): 1.5 hours
- Phase 2 (Debugging): 1 hour
- **Total**: 2.5 hours

## Decision Point

**Recommendation**: Try Options 1, 3, and 5 (total ~40 min). If still blocked, defer to Plan D and document thoroughly so work isn't repeated.

The probe-rs RTT investigation wasted ~14 hours across 2 attempts. Don't repeat that mistake - timebox this investigation and move on if it doesn't work quickly.
