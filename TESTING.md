# EAB Regression Testing Guide

Run these tests before merging any change to the EAB codebase. Unit tests run without hardware. E2E tests require two boards connected.

## Required Hardware

| Board | Connection | Port (typical) |
|-------|-----------|----------------|
| ESP32-C6 DevKit | USB Serial/JTAG | `/dev/cu.usbmodem101` |
| STM32L4 + ST-Link | USB ST-Link | `/dev/cu.usbmodem21403` |
| nRF5340 DK | J-Link SWD | Detected by `JLinkExe` |
| FRDM-MCXN947 | OpenOCD CMSIS-DAP | Detected by `openocd` |

Adjust port paths to match your setup. Run `eabctl start --port auto` or `ls /dev/cu.usb*` to discover ports.

## Prerequisites

```bash
cd /path/to/embedded-agent-bridge
pip install -e .
which eabctl           # Must be in PATH
which esptool.py       # For ESP32 flash tests
which st-flash         # For STM32 flash tests
which arm-none-eabi-objcopy  # For STM32 ELF conversion tests
which openocd          # For debug bridge tests
which JLinkGDBServerCLExe  # For J-Link debug/RTT (from SEGGER J-Link Software Pack)
which west              # For Zephyr flash tests
```

## Test Firmware

Build the ESP32-C6 test firmware before running E2E tests:

```bash
cd examples/esp32c6-test-firmware
idf.py build
cd ../..
```

For STM32, use any valid ELF or binary targeting the chip. A minimal blinky works.

---

## 1. Unit Tests (no hardware)

```bash
python3 -m pytest tests/ -v
```

**Expected:** All tests pass (341+/343). 2 pre-existing known failures (`test_daemon_main_accepts_argv` annotation check, `test___main___executes_daemon_main`). Zero NEW failures.

### What the unit tests cover

- CLI entry points (`eab --help`, `eabctl --help`, `--version`)
- Argument parsing: positional, flag, and default forms for `tail`, `alerts`, `events`
- Package structure (pyproject.toml, entry points, module existence)
- Module importability (`eab.control`, `eab.daemon`)

---

## 2. E2E Tests — Daemon Lifecycle

These tests verify the daemon starts, connects, and stops cleanly.

### 2.1 Start daemon (auto-detect)

```bash
eabctl start --port auto --json
```

**Verify:**
- `"started": true`
- A PID is returned
- Daemon log exists at the returned `log_path`

### 2.2 Check status

```bash
eabctl status --json
```

**Verify:**
- `daemon.is_alive: true`
- `connection.status: "connected"`
- `health.status: "healthy"`
- Port matches the connected device

### 2.3 Start daemon (explicit port)

```bash
eabctl stop
eabctl start --port /dev/cu.usbmodem101 --json
```

**Verify:** Same as 2.1 but port matches the explicit value.

### 2.4 Stop daemon

```bash
eabctl stop --json
```

**Verify:**
- `"stopped": true`
- `eabctl status --json` shows `daemon.running: false`

### 2.5 Stop when not running

```bash
eabctl stop --json
```

**Verify:** Returns error with `"stopped": false` and message "Daemon not running". Exit code 1.

---

## 3. E2E Tests — Serial I/O

Start daemon before these tests: `eabctl start --port <esp32-port>`

### 3.1 Read serial output

```bash
eabctl tail 20 --json
```

**Verify:**
- Returns JSON with `lines` array
- Each line has `timestamp`, `content`, `raw` fields
- Content shows device output (heartbeats, boot messages)

### 3.2 Positional vs flag syntax

```bash
# All three forms should return the same structure
eabctl tail 10 --json       # Positional
eabctl tail -n 10 --json    # Flag
eabctl tail --json           # Default (50 lines)
```

**Verify:** All three return valid JSON with `lines` array. Positional and flag return 10 lines (or fewer if log is short).

### 3.3 Read alerts

```bash
eabctl alerts 20 --json
```

**Verify:** Returns JSON with `lines` array. May be empty if no crashes/errors detected.

### 3.4 Send command and read response

```bash
eabctl send "help" --json
sleep 2
eabctl tail 10 --json
```

**Verify:**
- Send returns `"command": "help"` and `"queued_to"` path
- Tail shows the device's help menu in output (commands like `help`, `status`, `info`, etc.)

### 3.5 Events stream

```bash
eabctl events 10 --json
```

**Verify:**
- Returns JSON with `events` array
- Events have `type`, `timestamp`, `sequence` fields
- Types include: `daemon_started`, `command_sent`, `alert`, etc.

### 3.6 Wait for pattern

```bash
eabctl send "help" --json
eabctl wait "help" --timeout 5 --json
```

**Verify:** Returns success within timeout. If device doesn't echo "help", use a pattern that appears in heartbeat output.

### 3.7 Diagnose

```bash
eabctl diagnose --json
```

**Verify:**
- `"healthy": true`
- Checks array includes: `daemon`, `status_json`, `connection`, `health`, `boot_loop`
- All checks show `"status": "ok"`
- `recommendations` is empty when healthy

Stop daemon after serial tests: `eabctl stop`

---

## 4. E2E Tests — Port Control

### 4.1 Pause and resume

```bash
eabctl start --port <esp32-port>
eabctl pause 30 --json
eabctl status --json          # Should show paused state
eabctl resume --json
eabctl status --json          # Should show connected again
eabctl stop
```

**Verify:**
- Pause returns success
- Status during pause shows the port is released
- Resume returns success
- Status after resume shows reconnected

---

## 5. E2E Tests — Flash (ESP32)

### 5.1 Flash ELF file

```bash
eabctl flash examples/esp32c6-test-firmware/build/eab-test-firmware.elf \
  --chip esp32c6 --port <esp32-port> --json
```

**Verify:**
- `"success": true`
- `"tool": "esptool.py"`
- NO `"converted_from"` field (ESP32 handles ELF natively)
- Address is `"0x10000"` (default for ESP32 app partition)
- esptool output shows "Hash of data verified"

### 5.2 Flash binary file

```bash
# Extract binary first
esptool.py --chip esp32c6 elf2image examples/esp32c6-test-firmware/build/eab-test-firmware.elf
eabctl flash examples/esp32c6-test-firmware/build/eab-test-firmware.bin \
  --chip esp32c6 --port <esp32-port> --json
```

**Verify:** Same as 5.1 — `"success": true`, correct address.

### 5.3 Verify boot after flash

```bash
eabctl start --port <esp32-port>
sleep 3
eabctl tail 20 --json
eabctl stop
```

**Verify:** Device boots and shows expected output (heartbeats, help menu).

### 5.4 Erase flash

```bash
eabctl erase --chip esp32c6 --port <esp32-port> --json
```

**Verify:** `"success": true`. Device will not boot after erase (expected).

### 5.5 Flash after erase (recovery)

```bash
eabctl flash examples/esp32c6-test-firmware/build/eab-test-firmware.elf \
  --chip esp32c6 --port <esp32-port> --json
```

**Verify:** Flash succeeds and device boots again.

---

## 6. E2E Tests — Flash (STM32)

### 6.1 Flash ELF with auto-conversion

```bash
eabctl flash <stm32-firmware>.elf --chip stm32l4 --json
```

**Verify:**
- `"success": true`
- `"converted_from": "elf"` — confirms ELF-to-binary conversion happened
- `"firmware"` shows original .elf path (not temp .bin)
- `"tool": "st-flash"`
- `"command"` array shows a temp `.bin` file was passed to st-flash
- stderr shows "Flash written and verified!"

### 6.2 Flash binary (no conversion)

```bash
arm-none-eabi-objcopy -O binary <stm32-firmware>.elf /tmp/test.bin
eabctl flash /tmp/test.bin --chip stm32l4 --json
```

**Verify:**
- `"success": true`
- NO `"converted_from"` field
- Same md5 checksum as the ELF-converted binary from 6.1

### 6.3 Verify vector table via GDB

```bash
eabctl openocd start --chip stm32l4 --json
eabctl gdb --chip stm32l4 --cmd "x/4x 0x08000000" --json
eabctl openocd stop --json
```

**Verify:**
- First word at 0x08000000 is a valid stack pointer (should start with `0x2000xxxx` for SRAM)
- Second word is the reset vector (should start with `0x0800xxxx` for flash)
- NOT `0x464c457f` (ELF magic — means raw ELF was written, which is the bug we fixed)

### 6.4 Flash with explicit address

```bash
eabctl flash /tmp/test.bin --chip stm32l4 --address 0x08004000 --json
```

**Verify:** `"command"` array shows `0x08004000` as the address.

### 6.5 Erase and reset

```bash
eabctl erase --chip stm32l4 --json
eabctl reset --chip stm32l4 --json
```

**Verify:** Both return success.

### 6.6 Missing toolchain error

```bash
# Temporarily hide objcopy to test error path
PATH_BACKUP=$PATH
export PATH=$(echo $PATH | tr ':' '\n' | grep -v arm-none-eabi | tr '\n' ':')
eabctl flash <stm32-firmware>.elf --chip stm32l4 --json
export PATH=$PATH_BACKUP
```

**Verify:**
- Returns error with `"error": "arm-none-eabi-objcopy not found"`
- Includes `"hint"` with installation instructions

---

## 7. E2E Tests — Debug Bridge

### 7.1 OpenOCD start/stop

```bash
eabctl openocd start --chip stm32l4 --json
eabctl openocd stop --json
```

**Verify:**
- Start returns `"running": true` with PID and port numbers (gdb: 3333, telnet: 4444)
- Stop returns `"running": false`

### 7.2 GDB one-shot commands

```bash
eabctl openocd start --chip stm32l4 --json
eabctl gdb --chip stm32l4 \
  --cmd "monitor reset halt" \
  --cmd "info registers" \
  --cmd "bt" \
  --json
eabctl openocd stop --json
```

**Verify:**
- `"success": true`
- stdout contains register dump and backtrace
- `"returncode": 0`

### 7.3 GDB memory read

```bash
eabctl openocd start --chip stm32l4 --json
eabctl gdb --chip stm32l4 --cmd "x/4x 0x08000000" --json
eabctl openocd stop --json
```

**Verify:** stdout contains memory values from flash.

---

## 8. E2E Tests — Chip Info

### 8.1 chip-info with paused daemon

```bash
eabctl start --port <esp32-port>
eabctl pause 30 --json
eabctl chip-info --chip esp32c6 --port <esp32-port> --json
eabctl resume --json
eabctl stop
```

**Verify:** Returns chip information (type, features, MAC address, flash size).

**Known issue:** Running `chip-info` without pausing the daemon first causes a port conflict. The daemon and esptool fight over the serial port.

### 8.2 chip-info without daemon

```bash
eabctl chip-info --chip esp32c6 --port <esp32-port> --json
```

**Verify:** Works when no daemon is running.

---

## 9. E2E Tests — High-Speed Streaming

Requires firmware that outputs data with markers.

### 9.1 Stream start/stop

```bash
eabctl start --port <esp32-port>
eabctl stream start --mode raw --chunk 16384 --marker "===DATA_START===" --json
eabctl stream stop --json
eabctl stop
```

**Verify:** Start and stop both return success.

### 9.2 Receive data

```bash
eabctl recv-latest --bytes 1024 --out /tmp/test-recv.bin --json
```

**Verify:** Returns byte count and output file path. File exists at specified path.

---

## 10. Regression Checks

These verify specific bugs that were fixed. If any regress, the fix was lost.

### 10.1 ELF-to-binary conversion (BUG-2)

Flash an ELF file to STM32 and verify via GDB that 0x08000000 contains a valid vector table, NOT `0x464c457f` (ELF magic bytes).

See test 6.1 and 6.3.

### 10.2 ESP32 default flash address (was defaulting to "esptool.py")

Flash to ESP32 without `--address` flag and verify the command uses `0x10000`, not `esptool.py`.

See test 5.1 — check the `"command"` array.

### 10.3 Positional args for tail/alerts/events

```bash
eabctl tail 10 --json      # Must work (positional)
eabctl tail -n 10 --json   # Must work (flag)
eabctl tail --json          # Must work (default=50)
eabctl alerts 5 --json     # Positional
eabctl events 5 --json     # Positional
```

See test 3.2.

### 10.4 ESP32-C6 USB Serial/JTAG console

Flash the test firmware and verify serial output appears. If no output, check that `sdkconfig.defaults` has `CONFIG_ESP_CONSOLE_USB_SERIAL_JTAG=y`.

### 10.5 OpenOCD MCXN947 fault analysis

```bash
eabctl fault-analyze --device MCXN947 --probe openocd --chip mcxn947 --json
```

**Verify:** Returns valid JSON with `probe: "openocd"`. Does NOT fall back to J-Link.

---

## 11. E2E Tests — Fault Analysis

### 11.1 J-Link path (nRF5340)

```bash
eabctl fault-analyze --device NRF5340_XXAA_APP --json
```

**Verify:**
- Returns JSON with `fault_registers` object (CFSR, HFSR, BFAR, MMFAR, etc.)
- `decoded_faults` array with human-readable descriptions
- `stacked_pc` field (may be null if no fault active)
- `probe` field shows `jlink`

### 11.2 OpenOCD path (MCXN947)

```bash
eabctl fault-analyze --device MCXN947 --probe openocd --chip mcxn947 --json
```

**Verify:**
- Same JSON structure as 11.1
- `probe` field shows `openocd`

### 11.3 No active fault

If the device hasn't crashed, fault-analyze should still succeed:

**Verify:** `decoded_faults` is empty array, registers all show 0x00000000.

---

## 12. E2E Tests — RTT (nRF5340)

### 12.1 JLinkBridge start/stop

```python
from eab.rtt import JLinkBridge
bridge = JLinkBridge(device="NRF5340_XXAA_APP", rtt_port=0)
bridge.start()
import time; time.sleep(5)
bridge.stop()
```

**Verify:**
- JLinkRTTLogger process started and stopped cleanly
- `rtt.log` exists in session directory with timestamped lines
- `rtt-raw.log` exists with raw output

### 12.2 RTT output files

After running RTT for 10+ seconds with a Zephyr app that prints `DATA: key=value`:

**Verify:**
- `rtt-raw.log` — raw unprocessed output
- `rtt.log` — timestamped output
- `rtt.csv` — CSV with parsed DATA: fields
- `rtt.jsonl` — structured events

---

## 13. E2E Tests — Zephyr Flash

### 13.1 west flash (nRF5340 via J-Link)

```bash
eabctl flash --chip nrf5340 --runner jlink --json
```

**Verify:** `"success": true`, `"tool": "west"`.

### 13.2 west flash (MCXN947 via OpenOCD)

```bash
eabctl flash --chip mcxn947 --runner openocd --json
```

**Verify:** `"success": true`, `"tool": "west"`.

---

## Quick Smoke Test

Minimum viable test for a quick PR check (5 minutes):

```bash
# 1. Unit tests
python3 -m pytest tests/ -v

# 2. ESP32 flash + serial
eabctl flash examples/esp32c6-test-firmware/build/eab-test-firmware.elf \
  --chip esp32c6 --port <esp32-port> --json
eabctl start --port <esp32-port> && sleep 3
eabctl send "help" --json && sleep 2
eabctl tail 10 --json
eabctl diagnose --json
eabctl stop

# 3. STM32 flash + verify
eabctl flash <stm32>.elf --chip stm32l4 --json
# Check for "converted_from": "elf" in output

# 4. Verify no regressions
# - ESP32 flash command has "0x10000" address (not "esptool.py")
# - STM32 flash command has temp .bin path (not .elf)
# - tail/alerts/events accept positional args

# 5. Fault analysis smoke check
eabctl fault-analyze --device NRF5340_XXAA_APP --json
# Check: returns valid JSON with fault_registers
```

---

## Adding New Tests

When adding features or fixing bugs:

1. Add a unit test to `tests/test_cli_entry_points.py` for argument parsing changes
2. Add an E2E section to this document for hardware-interacting changes
3. Add a regression check (section 10) for any bug fix
4. Run the quick smoke test at minimum before merging
