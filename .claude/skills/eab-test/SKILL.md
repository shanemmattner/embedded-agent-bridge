---
name: eab-regression-test
description: >
  Run EAB regression tests against real hardware. Covers unit tests, daemon lifecycle,
  serial I/O, flash (ESP32 + STM32), debug bridge, and known regression checks.
  Use when testing EAB changes before committing or merging.
---

# EAB Regression Testing

Automated test plan for verifying EAB against real hardware. Run this before any merge.

## Hardware Setup

Detect what's connected before starting:

```bash
ls /dev/cu.usb*
ioreg -p IOUSB -l | grep "USB Product Name"
```

| Board | USB Descriptor | Port (typical) |
|-------|---------------|----------------|
| ESP32-C6 DevKit | USB JTAG_serial debug unit | `/dev/cu.usbmodem1101` |
| STM32L4 + ST-Link | STM32 STLink | `/dev/cu.usbmodem21403` |
| nRF5340 DK | J-Link OB | `/dev/cu.usbmodemXXXX` |

Set these variables for the test run:

```bash
ESP_PORT=/dev/cu.usbmodem1101
STM_PORT=/dev/cu.usbmodem21403
ESP_FW=examples/esp32c6-test-firmware/build/eab-test-firmware.elf
```

## Prerequisites

```bash
which eabctl || pip install -e .
which esptool.py       # ESP32 flash
which st-flash         # STM32 flash
which arm-none-eabi-objcopy  # STM32 ELF conversion
which openocd          # Debug bridge
```

## Test Execution Order

Run tests in this exact order. Each section depends on the previous.

---

## 1. Unit Tests (no hardware)

```bash
python3 -m pytest eab/tests/ tests/ -v --tb=short
```

**Pass criteria:**
- 260+ tests pass (197 unit + 66 integration)
- `test___main___executes_daemon_main` may fail (known pre-existing issue — ignore it)
- Zero NEW failures

---

## 1b. RTT / J-Link Tests (no hardware)

```bash
python3 -m pytest tests/test_jlink_bridge.py tests/test_jlink_rtt.py tests/test_rtt_stream.py -v --tb=short
```

**Pass criteria:** All tests pass. These test JLinkBridge, JLinkRTTManager, and RTTStreamProcessor with mocked subprocesses.

---

## 2. Daemon Lifecycle

### 2.1 Start (auto-detect)

```bash
eabctl start --port auto --json
```

**Check:** `"started": true`, PID returned, `log_path` exists.

### 2.2 Status (running)

```bash
eabctl status --json
```

**Check:** `daemon.is_alive == true`, `connection.status == "connected"`, `health.status == "healthy"`.

### 2.3 Stop

```bash
eabctl stop --json
```

**Check:** `"stopped": true`.

### 2.4 Stop when already stopped

```bash
eabctl stop --json
```

**Check:** Exit code 1, `"stopped": false`.

### 2.5 Start (explicit port)

```bash
eabctl start --port $ESP_PORT --json
```

**Check:** `"started": true`, port matches `$ESP_PORT`.

---

## 3. Serial I/O

Daemon must be running on ESP32 port for these tests.

### 3.1 Tail output

```bash
eabctl tail 20 --json
```

**Check:** `lines` array returned. Each line has `timestamp`, `content`, `raw` fields.

### 3.2 Positional vs flag syntax

```bash
eabctl tail 10 --json       # Positional
eabctl tail -n 10 --json    # Flag
eabctl tail --json           # Default (50)
```

**Check:** All three return valid JSON with `lines` array.

### 3.3 Alerts

```bash
eabctl alerts 20 --json
```

**Check:** Returns JSON with `lines` array (may be empty).

### 3.4 Send command + read response

```bash
eabctl send "help" --json
sleep 2
eabctl tail 10 --json
```

**Check:** Send returns `"command": "help"`. Tail shows device help menu.

### 3.5 Events

```bash
eabctl events 10 --json
```

**Check:** `events` array with `type`, `timestamp`, `sequence` fields.

### 3.6 Wait for pattern

```bash
eabctl send "help" --json
eabctl wait "help" --timeout 5 --json
```

**Check:** Returns success within timeout.

### 3.7 Diagnose

```bash
eabctl diagnose --json
```

**Check:** `"healthy": true`. All checks show `"status": "ok"`.

Stop daemon: `eabctl stop`

---

## 4. Port Control

### 4.1 Pause and resume

```bash
eabctl start --port $ESP_PORT
sleep 2
eabctl pause 30 --json
eabctl status --json           # Should show disconnected/paused
eabctl resume --json
sleep 2
eabctl status --json           # Should show connected again
eabctl stop
```

**Check:** Pause releases port. Resume reconnects. Status reflects both states.

---

## 5. Flash — ESP32

### 5.1 Flash ELF

```bash
eabctl flash $ESP_FW --chip esp32c6 --port $ESP_PORT --json
```

**Check:**
- `"success": true`
- `"tool": "esptool.py"`
- NO `"converted_from"` field (ESP32 handles ELF natively)
- Address is `"0x10000"` (NOT `"esptool.py"` — regression 10.2)
- stdout contains "Hash of data verified"

### 5.2 Verify boot after flash

```bash
eabctl start --port $ESP_PORT
sleep 3
eabctl tail 20 --json
eabctl stop
```

**Check:** Device boots, shows heartbeats or help menu.

### 5.3 Erase flash

```bash
eabctl erase --chip esp32c6 --port $ESP_PORT --json
```

**Check:** `"success": true`.

### 5.4 Flash after erase (recovery)

```bash
eabctl flash $ESP_FW --chip esp32c6 --port $ESP_PORT --json
```

**Check:** `"success": true`, device boots again.

---

## 6. Flash — STM32

### 6.1 Flash ELF (auto-conversion)

```bash
eabctl flash <stm32-firmware>.elf --chip stm32l4 --json
```

**Check:**
- `"success": true`
- `"converted_from": "elf"` — confirms ELF→binary conversion
- `"firmware"` shows original .elf path (not temp .bin)
- `"tool": "st-flash"`
- stderr shows "Flash written and verified!"

### 6.2 Flash binary (no conversion)

```bash
arm-none-eabi-objcopy -O binary <stm32-firmware>.elf /tmp/test.bin
eabctl flash /tmp/test.bin --chip stm32l4 --json
```

**Check:** `"success": true`, NO `"converted_from"` field.

### 6.3 Verify vector table via GDB

```bash
eabctl openocd start --chip stm32l4 --json
eabctl gdb --chip stm32l4 --cmd "x/4x 0x08000000" --json
eabctl openocd stop --json
```

**Check:**
- First word at 0x08000000 = valid stack pointer (`0x2000xxxx`)
- Second word = reset vector (`0x0800xxxx`)
- NOT `0x464c457f` (ELF magic = regression 10.1)

### 6.4 Erase and reset

```bash
eabctl erase --chip stm32l4 --json
eabctl reset --chip stm32l4 --json
```

**Check:** Both return success.

---

## 7. Debug Bridge

### 7.1 OpenOCD start/stop

```bash
eabctl openocd start --chip stm32l4 --json
eabctl openocd stop --json
```

**Check:** Start returns `"running": true` with PID. Stop returns `"running": false`.

### 7.2 GDB one-shot

```bash
eabctl openocd start --chip stm32l4 --json
eabctl gdb --chip stm32l4 --cmd "monitor reset halt" --cmd "info registers" --cmd "bt" --json
eabctl openocd stop --json
```

**Check:** `"success": true`, stdout has register dump.

---

## 8. Chip Info

### 8.1 ESP32 chip-info (daemon paused)

```bash
eabctl start --port $ESP_PORT
eabctl pause 30 --json
eabctl chip-info --chip esp32c6 --port $ESP_PORT --json
eabctl resume --json
eabctl stop
```

**Check:** Returns chip type, MAC address, flash size.

### 8.2 ESP32 chip-info (no daemon)

```bash
eabctl chip-info --chip esp32c6 --port $ESP_PORT --json
```

**Check:** Works without daemon running.

---

## 9. Regression Checks

These verify specific fixed bugs. If any fail, the fix was lost.

| ID | Bug | Test | Pass Criteria |
|----|-----|------|---------------|
| 10.1 | ELF written raw to STM32 | Test 6.3 | 0x08000000 != `0x464c457f` |
| 10.2 | ESP32 address defaulting to "esptool.py" | Test 5.1 | Address == `"0x10000"` |
| 10.3 | Positional args broken | Test 3.2 | All three tail forms work |
| 10.4 | ESP32-C6 no serial output | Test 5.2 | Heartbeats visible after flash |

---

## Quick Smoke Test (5 min)

Minimum viable check:

```bash
# Unit tests
python3 -m pytest eab/tests/ -v --tb=short

# ESP32: flash + serial
eabctl flash $ESP_FW --chip esp32c6 --port $ESP_PORT --json
eabctl start --port $ESP_PORT && sleep 3
eabctl send "help" --json && sleep 2
eabctl tail 10 --json
eabctl diagnose --json
eabctl stop

# STM32: flash + verify
eabctl flash <stm32>.elf --chip stm32l4 --json
# Check: "converted_from": "elf" present

# RTT: start + verify output (requires nRF5340 DK)
python3 -c "
from eab.jlink_bridge import JLinkBridge
b = JLinkBridge('/tmp/eab-rtt-test')
s = b.start_rtt(device='NRF5340_XXAA_APP')
print(f'RTT running: {s.running}, channels: {s.num_up_channels}')
import time; time.sleep(3)
b.stop_rtt()
"

# Regressions: ESP32 address has "0x10000", STM32 has temp .bin, positional args work
```

---

## Interpreting Results

| Result | Action |
|--------|--------|
| All pass | Safe to commit/merge |
| Unit test NEW failure | Code bug — fix before merge |
| Flash fails | Check toolchain installation, port paths, hardware connections |
| Regression check fails | Bug reintroduced — do not merge, investigate |
| Pre-existing failure only | Document it, safe to proceed |

## After Testing

```bash
eabctl stop 2>/dev/null          # Clean up daemon
eabctl openocd stop 2>/dev/null  # Clean up OpenOCD
```
