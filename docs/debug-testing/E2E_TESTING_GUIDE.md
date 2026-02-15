# End-to-End Testing Guide
**Debug-Full Examples - Complete Validation Procedure**

## Overview

This guide provides a complete, repeatable procedure for building, flashing, testing, and validating all 5 debug-full firmware examples.

## Prerequisites

### Required Tools
- [ ] ESP-IDF (for ESP32-C6, ESP32-S3)
- [ ] Zephyr SDK + west (for nRF5340, MCXN947, STM32L4)
- [ ] eabctl (EAB CLI tool)
- [ ] esptool (ESP32 flashing)
- [ ] J-Link Software (for nRF5340)
- [ ] probe-rs or OpenOCD (for MCXN947, STM32L4)

### Required Hardware
- [ ] ESP32-C6 DevKit
- [ ] ESP32-S3 DevKit
- [ ] nRF5340 DK
- [ ] FRDM-MCXN947
- [ ] Nucleo-L432KC (STM32L4)

## Phase 1: Environment Setup

### ESP-IDF Setup
```bash
# If not installed, install ESP-IDF
git clone --recursive https://github.com/espressif/esp-idf.git
cd esp-idf
./install.sh esp32c6,esp32s3
. ./export.sh

# Verify
idf.py --version
```

### Zephyr Setup
```bash
# If not installed, install Zephyr
west init ~/zephyrproject
cd ~/zephyrproject
west update
west zephyr-export
pip install -r ~/zephyrproject/zephyr/scripts/requirements.txt

# Verify
west --version
```

## Phase 2: Build All Examples

### Automated Build (Recommended)
```bash
cd /path/to/embedded-agent-bridge
./scripts/build-all-debug-examples.sh
```

### Manual Build

#### ESP32-C6 Debug Full
```bash
cd examples/esp32c6-debug-full
. $IDF_PATH/export.sh
idf.py build
```

**Expected Output:**
- `build/esp32c6-debug-full.bin`
- `build/esp32c6-debug-full.elf`
- `build/bootloader/bootloader.bin`
- `build/partition_table/partition-table.bin`

#### ESP32-S3 Debug Full
```bash
cd examples/esp32s3-debug-full
. $IDF_PATH/export.sh
idf.py build
```

#### nRF5340 Debug Full
```bash
cd examples/nrf5340-debug-full
west build -b nrf5340dk/nrf5340/cpuapp
```

**Expected Output:**
- `build/zephyr/zephyr.elf`
- `build/zephyr/zephyr.bin`
- `build/zephyr/zephyr.hex`

#### MCXN947 Debug Full
```bash
cd examples/mcxn947-debug-full
west build -b frdm_mcxn947
```

#### STM32L4 Debug Full
```bash
cd examples/stm32l4-debug-full
west build -b nucleo_l432kc
```

## Phase 3: Flash Firmware

### ESP32-C6
```bash
# Using EAB (recommended)
eabctl flash examples/esp32c6-debug-full

# Or using idf.py
cd examples/esp32c6-debug-full
idf.py flash monitor
```

### ESP32-S3
```bash
eabctl flash examples/esp32s3-debug-full
```

### nRF5340
```bash
eabctl flash --chip nrf5340 --runner jlink
```

### MCXN947
```bash
cd examples/mcxn947-debug-full
west flash --runner openocd
```

### STM32L4
```bash
cd examples/stm32l4-debug-full
west flash --runner openocd
```

## Phase 4: Functionality Testing

### ESP32-C6 / ESP32-S3 Test Procedure

#### 1. Monitor Output
```bash
eabctl tail 100
```

**Expected Boot Output:**
```
I (XXX) debug_full: ========================================
I (XXX) debug_full: ESP32-C6 Debug Full Example
I (XXX) debug_full: ========================================
I (XXX) debug_full: Features enabled:
I (XXX) debug_full:   - SystemView task tracing
I (XXX) debug_full:   - Heap allocation tracking
I (XXX) debug_full:   - Coredump generation
I (XXX) debug_full:   - Task watchdog
I (XXX) debug_full: ========================================
I (XXX) debug_full: All tasks created. Ready for debugging!
```

#### 2. Test Status Command
```bash
eabctl send "status"
sleep 2
eabctl tail 10
```

**Expected Output:**
```
I (XXX) debug_full: === System Status ===
I (XXX) debug_full: Free heap: XXXXX bytes
I (XXX) debug_full: Min free heap: XXXXX bytes
I (XXX) debug_full: Active tasks: X
```

#### 3. Test Heap Tracing
```bash
# Start heap tracing
eabctl send "heap_start"
sleep 2
eabctl tail 5

# Let it run for 10 seconds
sleep 10

# Stop and dump heap trace
eabctl send "heap_stop"
sleep 3
eabctl tail 50
```

**Expected Output:**
```
I (XXX) debug_full: Heap tracing started
...
I (XXX) debug_full: Heap tracing stopped
128 allocations trace (128 entry buffer)
...allocation details...
```

#### 4. Test Coredump Generation
```bash
# Trigger NULL pointer fault
eabctl send "fault_null"
sleep 5
eabctl tail 100
```

**Expected Output:**
```
E (XXX) debug_full: Triggering NULL pointer fault...
Guru Meditation Error: Core 0 panic'ed (Load access fault)
...
Coredump saved to flash
```

**Verify Coredump:**
```bash
cd examples/esp32c6-debug-full
idf.py coredump-info
```

#### 5. Test Watchdog (Optional - Will Reset Device)
```bash
eabctl send "wdt_test"
# Device will reset after ~10 seconds
```

### nRF5340 / MCXN947 / STM32L4 Test Procedure

#### 1. Start RTT
```bash
eabctl rtt start --device NRF5340_XXAA_APP --transport jlink
sleep 2
eabctl rtt tail 100
```

**Expected Boot Output:**
```
[00:00:00.000,000] <inf> debug_full: ========================================
[00:00:00.001,000] <inf> debug_full: nRF5340 Debug Full Example
[00:00:00.002,000] <inf> debug_full: ========================================
[00:00:00.003,000] <inf> debug_full: Features enabled:
[00:00:00.004,000] <inf> debug_full:   - CTF task tracing via RTT
[00:00:00.005,000] <inf> debug_full:   - Shell commands (type 'help')
[00:00:00.006,000] <inf> debug_full:   - Coredump generation
[00:00:00.007,000] <inf> debug_full:   - MPU stack guard
[00:00:00.008,000] <inf> debug_full: ========================================
```

#### 2. Test Shell Commands
```bash
# List all threads
eabctl send "kernel threads"
sleep 2
eabctl rtt tail 30

# Show stack usage
eabctl send "kernel stacks"
sleep 2
eabctl rtt tail 30

# System uptime
eabctl send "kernel uptime"
sleep 2
eabctl rtt tail 10

# Custom status
eabctl send "status"
sleep 2
eabctl rtt tail 10
```

**Expected Output:**
```
uart:~$ kernel threads
Scheduler: 2500 since last call
Threads:
 0x20000a00 compute
        options: 0x0, priority: 7 timeout: 0
        state: pending
        stack size 2048, unused 1624, usage 424 / 2048 (20 %)
...
```

#### 3. Test Fault Injection
```bash
# Trigger NULL pointer fault
eabctl send "fault null"
sleep 3
eabctl rtt tail 50
```

**Expected Output:**
```
[00:00:10.000,000] <inf> debug_full: Triggering NULL pointer fault...
[00:00:10.100,000] <err> os: ***** MPU FAULT *****
[00:00:10.100,000] <err> os: Faulting instruction address: 0x000xxxxx
...
[00:00:10.150,000] <err> os: ***** Coredump *****
```

## Phase 5: Trace Capture & Analysis

### ESP32-C6 / ESP32-S3 SystemView Trace

#### Capture Trace
```bash
# Start apptrace capture (run in separate terminal)
$IDF_PATH/tools/esp_app_trace/sysviewtrace_proc.py /dev/ttyACM0 -o /tmp/esp32-trace.svdat

# Or use EAB
eabctl trace start --source rtt -o /tmp/esp32-trace.rttbin --device ESP32C6
sleep 15
eabctl trace stop
```

#### Export to Perfetto
```bash
# Convert SystemView to Perfetto JSON
$IDF_PATH/tools/esp_app_trace/sysviewtrace_proc.py /tmp/esp32-trace.svdat -p -o /tmp/esp32-trace.json

# Or use EAB
eabctl trace export -i /tmp/esp32-trace.rttbin -o /tmp/esp32-trace.json
```

#### Visualize
1. Open https://ui.perfetto.dev
2. Click "Open trace file"
3. Select `/tmp/esp32-trace.json`
4. Verify timeline shows:
   - Multiple tasks (cmd, compute, io, alloc)
   - Task switching events
   - CPU utilization
   - Custom event markers

### nRF5340 / MCXN947 / STM32L4 CTF Trace

#### Capture Trace
```bash
# Start CTF trace capture via RTT
eabctl trace start --source rtt -o /tmp/nrf5340-trace.rttbin --device NRF5340_XXAA_APP

# Let it run for 15 seconds
sleep 15

# Stop capture
eabctl trace stop
```

#### Export to Perfetto
```bash
# Using EAB
eabctl trace export -i /tmp/nrf5340-trace.rttbin -o /tmp/nrf5340-trace.json

# Or using babeltrace
babeltrace /tmp/nrf5340-trace.rttbin --format json -o /tmp/nrf5340-trace.json
```

#### Visualize
1. Open https://ui.perfetto.dev
2. Click "Open trace file"
3. Select `/tmp/nrf5340-trace.json`
4. Verify timeline shows:
   - Multiple threads (compute, io, alloc)
   - Thread scheduling
   - Custom trace events
   - System work queue activity

## Phase 6: Automated Regression Testing

### Create Test YAML

#### ESP32-C6 Test (examples/esp32c6_debug_full.yaml)
```yaml
name: ESP32-C6 Debug Full Validation
device: esp32c6
chip: esp32c6
timeout: 120

setup:
  - flash:
      firmware: examples/esp32c6-debug-full

steps:
  - reset: {}
  - wait:
      pattern: "Ready for debugging"
      timeout: 10
  - send:
      text: "status"
  - wait:
      pattern: "Free heap"
      timeout: 5
  - send:
      text: "heap_start"
  - sleep: 5
  - send:
      text: "heap_stop"
  - wait:
      pattern: "allocations trace"
      timeout: 5

teardown:
  - reset: {}
```

#### nRF5340 Test (examples/nrf5340_debug_full.yaml)
```yaml
name: nRF5340 Debug Full Validation
device: nrf5340
chip: nrf5340
timeout: 120

setup:
  - flash:
      firmware: examples/nrf5340-debug-full
      runner: jlink

steps:
  - reset: {}
  - wait:
      pattern: "Ready for debugging"
      timeout: 10
  - send:
      text: "kernel threads"
  - wait:
      pattern: "compute"
      timeout: 5
  - send:
      text: "status"
  - wait:
      pattern: "Uptime"
      timeout: 5

teardown:
  - reset: {}
```

### Run Regression Tests
```bash
# Run single test
eabctl regression --test tests/hw/esp32c6_debug_full.yaml --json

# Run all debug tests
eabctl regression --suite tests/hw/ --filter "*debug_full*" --json

# Cross-platform matrix
eabctl regression --suite tests/hw/ --filter "*debug_full*" --matrix --json
```

## Phase 7: Validation Checklist

### Per-Platform Validation

#### ESP32-C6
- [ ] Firmware builds without errors
- [ ] Flashes successfully
- [ ] Boot messages appear
- [ ] All 4 tasks running (cmd, compute, io, alloc)
- [ ] `status` command works
- [ ] `heap_start` / `heap_stop` work
- [ ] `fault_null` triggers coredump
- [ ] Coredump can be decoded with `idf.py coredump-info`
- [ ] SystemView trace can be captured
- [ ] Trace exports to Perfetto JSON
- [ ] Perfetto shows task timeline

#### ESP32-S3
- [ ] Same as ESP32-C6
- [ ] Xtensa-specific features work
- [ ] Dual-core task scheduling visible in trace

#### nRF5340
- [ ] Firmware builds without errors
- [ ] Flashes successfully via J-Link
- [ ] Boot messages appear via RTT
- [ ] All 3 threads running (compute, io, alloc)
- [ ] `kernel threads` command works
- [ ] `kernel stacks` command works
- [ ] `status` command works
- [ ] `fault null` triggers MPU fault and coredump
- [ ] CTF trace can be captured via RTT
- [ ] Trace exports to Perfetto JSON
- [ ] Perfetto shows thread timeline

#### MCXN947
- [ ] Same as nRF5340
- [ ] Flashes via OpenOCD
- [ ] probe-rs transport works

#### STM32L4
- [ ] Same as nRF5340
- [ ] Flashes via OpenOCD
- [ ] Cortex-M4 specific features work

## Expected Timeline

- **Environment Setup:** 1-2 hours (one-time)
- **Build All Examples:** 30 minutes
- **Flash & Test All:** 2-3 hours
- **Trace Capture & Analysis:** 1-2 hours
- **Regression Tests:** 1 hour
- **Full Validation:** 1 day

**Total:** 1-2 days for complete end-to-end validation

## Success Criteria

✅ All 5 firmwares build successfully
✅ All 5 firmwares flash without errors
✅ All boot messages appear correctly
✅ All commands/shell work as expected
✅ Fault injection triggers coredumps
✅ Traces can be captured on all platforms
✅ Traces export to Perfetto JSON
✅ Perfetto UI shows meaningful timeline data
✅ Automated regression tests pass

## Troubleshooting

### Build Issues
- **ESP-IDF not found:** Run `. $IDF_PATH/export.sh`
- **West not found:** Run `pip install west`
- **Zephyr not found:** Set `ZEPHYR_BASE` environment variable

### Flash Issues
- **Port busy:** Stop EAB daemon first with `eabctl stop`
- **Permission denied:** Add user to dialout group or use sudo
- **Device not found:** Check USB cable and `ls /dev/cu.*`

### Runtime Issues
- **No output:** Check baud rate (115200 for ESP32, varies for Zephyr)
- **Commands don't work:** Check for typos, use `help` command
- **Coredump not saved:** Verify partition table includes coredump partition

### Trace Issues
- **No trace data:** Verify CONFIG options enabled in sdkconfig/prj.conf
- **RTT not working:** Check J-Link connection and device name
- **Export fails:** Check tool installation (sysviewtrace_proc.py, babeltrace)

## Automation Scripts

All testing can be automated using the provided scripts:

```bash
# Build all examples
./scripts/build-all-debug-examples.sh

# Run end-to-end tests
./scripts/test-debug-examples-e2e.sh

# View results
cat e2e-test-results.log
```

## Next Steps

After completing validation:
1. Document results in test log
2. Create feature comparison matrix
3. Update CLAUDE.md with debug workflows
4. Create demo videos/screenshots
5. Submit PR with all changes

## Files Created

- `scripts/build-all-debug-examples.sh` - Automated build script
- `scripts/test-debug-examples-e2e.sh` - Automated testing script
- `E2E_TEST_LOG.md` - Test execution log
- `E2E_TESTING_GUIDE.md` - This file

All procedures are documented for repeatability and continuous improvement.
