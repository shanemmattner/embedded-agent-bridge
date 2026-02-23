# Embedded Agent Bridge (EAB)

Background daemons bridging AI coding agents to debuggers and embedded hardware (ESP32, STM32, nRF, NXP MCX via serial, RTT, J-Link, OpenOCD). **ALWAYS use eabctl for ALL hardware operations.**

## CRITICAL RULES FOR AGENTS

1. **NEVER use esptool/JLinkExe/openocd directly** - Use `eabctl` instead
2. **NEVER use pio device monitor** - Use `eabctl tail` instead
3. **NEVER access serial ports or debug probes directly** - EAB manages all hardware interfaces
4. **Port busy errors?** Run `eabctl flash` - it handles port release automatically
5. **Before flashing, check `docs/usb-port-mapping.md`** - Ports shift on USB re-enumeration
6. **ESP32 multi-probe: ALWAYS use `adapter serial`** - ESP32-C6 and P4 share VID:PID `303a:1001`
7. **ST-Link V3 invisible on macOS** - See `docs/macos-flash-troubleshooting.md` for workarounds

## Quick Reference

```bash
# Check status (ALWAYS do this first)
eabctl status
eabctl status --json   # machine-parseable

# View serial output
eabctl tail 50
eabctl tail 50 --json  # machine-parseable

# Send command to device
eabctl send "i"

# Flash firmware (handles EVERYTHING automatically)
eabctl flash /path/to/project

# Reset device
eabctl reset

# Fault analysis (Cortex-M crash decode)
eabctl fault-analyze --device NRF5340_XXAA_APP --json
eabctl fault-analyze --device MCXN947 --probe openocd --chip mcxn947 --json

# DWT profiling (function/region performance measurement)
eabctl profile-function --function main --device NRF5340_XXAA_APP --elf build/zephyr/zephyr.elf
eabctl profile-region --start 0x1000 --end 0x1100 --device NRF5340_XXAA_APP
eabctl dwt-status --device NRF5340_XXAA_APP --json

# RTT (Real-Time Transfer) streaming
# J-Link transport (subprocess-based, background logging)
eabctl rtt start --device NRF5340_XXAA_APP --transport jlink
eabctl rtt stop
eabctl rtt status --json
eabctl rtt tail 100

# probe-rs transport (native Rust extension, all probe types)
# Supports ST-Link, CMSIS-DAP, J-Link, ESP USB-JTAG
eabctl rtt start --device STM32L476RG --transport probe-rs
eabctl rtt start --device STM32L476RG --transport probe-rs --probe-selector "0483:374b"

# Note: probe-rs transport does not yet support background logging daemon
# Use for testing connectivity and firmware RTT setup verification
```

## Flashing Firmware

**ONLY use eabctl flash:**

```bash
# Flash ESP-IDF project (auto-detects chip, pauses daemon, flashes, resumes)
eabctl flash /path/to/esp-idf-project

# Erase flash first if corrupted
eabctl erase
eabctl flash /path/to/project
```

The flash command:
1. Automatically pauses daemon and releases the serial port
2. Detects chip type from build config
3. For ESP32 USB-JTAG ports: uses **OpenOCD JTAG** (not esptool) — much more reliable
4. Flashes bootloader, partition table, and app
5. Resumes daemon and shows boot output

**ESP32-C6 USB-JTAG Note:** The built-in USB-Serial/JTAG peripheral is unreliable
for large serial transfers (esptool drops at ~50KB+). EAB auto-detects USB-JTAG
ports and flashes via OpenOCD's `program_esp` command using the JTAG transport,
which is 100% reliable. Requires Espressif OpenOCD (installed with ESP-IDF).

**NEVER use `idf.py flash` or `esptool.py` directly.** Use `eabctl flash`.
**If you see "port is busy" anywhere, you did something wrong. Use eabctl.**

```bash
# Zephyr targets (uses west flash)
eabctl flash --chip nrf5340 --runner jlink
eabctl flash --chip mcxn947 --runner openocd
```

## Fixing Boot Loops

If device shows `invalid header: 0xffffffff` or watchdog resets:

```bash
eabctl flash /path/to/working/project
```

## Monitoring Device

```bash
# Last N lines of output
eabctl tail 50

# Watch for specific pattern (blocks until found or timeout)
eabctl wait "Ready" 30

# View crash/error alerts only
eabctl alerts
eabctl alerts --json   # machine-parseable
```

## Payload Capture (Base64/WAV/etc.)

If the device outputs base64 between markers and you need a clean extract:

```bash
eabctl capture-between "===WAV_START===" "===WAV_END===" out.wav --decode-base64
```

## DWT Profiling (Cortex-M Performance Measurement)

Profile function execution time and cycle counts using ARM Cortex-M DWT (Data Watchpoint and Trace) hardware. Requires J-Link debug probe and pylink-square package (`pip install embedded-agent-bridge[jlink]`).

### Profile a Function

Measure execution time of a specific function by name:

```bash
# Profile function by name (auto-detects CPU frequency)
eabctl profile-function --function main --device NRF5340_XXAA_APP --elf build/zephyr/zephyr.elf

# Override CPU frequency if auto-detection fails
eabctl profile-function --function sensor_read --device NRF5340_XXAA_APP --elf build/zephyr/zephyr.elf --cpu-freq 128000000

# JSON output for machine parsing
eabctl profile-function --function main --device NRF5340_XXAA_APP --elf build/zephyr/zephyr.elf --json
```

### Profile an Address Region

Measure execution time between two addresses:

```bash
# Profile specific address range
eabctl profile-region --start 0x1000 --end 0x1100 --device NRF5340_XXAA_APP

# With explicit CPU frequency
eabctl profile-region --start 0x1000 --end 0x1100 --device NRF5340_XXAA_APP --cpu-freq 128000000

# JSON output
eabctl profile-region --start 0x1000 --end 0x1100 --device NRF5340_XXAA_APP --json
```

### Check DWT Status

Display current DWT register state:

```bash
# Human-readable status
eabctl dwt-status --device NRF5340_XXAA_APP

# JSON output
eabctl dwt-status --device NRF5340_XXAA_APP --json
```

### CPU Frequency Defaults

The profiler auto-detects CPU frequency for common chips:

| Device | CPU Frequency | Override Flag |
|--------|---------------|---------------|
| nRF5340 | 128 MHz | `--cpu-freq 128000000` |
| nRF52840 | 64 MHz | `--cpu-freq 64000000` |
| MCXN947 | 150 MHz | `--cpu-freq 150000000` |
| STM32F4 | 168 MHz | `--cpu-freq 168000000` |
| STM32H7 | 480 MHz | `--cpu-freq 480000000` |

Use `--cpu-freq` to override auto-detection or support unlisted devices.

## Supported Hardware

| Family | Variants | Debug Probe | Flash Tool |
|--------|----------|-------------|------------|
| ESP32 | esp32, esp32s3, esp32c3, esp32c6 | OpenOCD (ESP) | OpenOCD JTAG (USB-JTAG) / esptool (UART) |
| STM32 | stm32l4, stm32f4, stm32h7, stm32g4 | OpenOCD + ST-Link | st-flash |
| nRF | nRF5340 | J-Link SWD | west flash (Zephyr) |
| NXP MCX | MCXN947 | OpenOCD CMSIS-DAP | west flash (Zephyr) |
| C2000 | F28003x, F28004x | XDS110 | CCS / eabctl flash |

## GDB Debugging (ESP32-C6)

The ESP32-C6 has a built-in USB-JTAG that supports full GDB debugging via OpenOCD.
Requires the **Espressif OpenOCD** fork (installed with ESP-IDF at `~/.espressif/tools/openocd-esp32/`).

```bash
# Start OpenOCD (runs as a server on port 3333)
~/.espressif/tools/openocd-esp32/*/openocd-esp32/bin/openocd -f board/esp32c6-builtin.cfg

# In another terminal, connect GDB
~/.espressif/tools/riscv32-esp-elf-gdb/*/riscv32-esp-elf-gdb/bin/riscv32-esp-elf-gdb build/app.elf
(gdb) target remote :3333
(gdb) mon reset halt
(gdb) info registers
(gdb) continue

# Quick register dump (no GDB needed)
openocd -f board/esp32c6-builtin.cfg -c "init" -c "halt" -c "reg" -c "shutdown"

# Flash via JTAG (what eabctl uses internally)
openocd -f board/esp32c6-builtin.cfg -c "program_esp app.bin 0x10000 verify" -c "reset run" -c "shutdown"
```

ESP32-C6 supports 4 hardware breakpoints, 4 watchpoints, and full CSR/debug register access.

## C2000 Development (TI Microcontrollers)

EAB supports TI C2000 microcontrollers (F28003x, F28004x) via XDS110 debug probe and CCS Scripting Server.

### Building C2000 Firmware

**Prerequisites (one-time setup):**

```bash
# 1. Pull Docker image (~2GB)
docker pull whuzfb/ccstudio:20.2-ubuntu24.04

# 2. Clone C2000Ware SDK (required by firmware, sparse checkout ~50MB)
cd /tmp
git clone --depth=1 --filter=blob:none --sparse \
  https://github.com/TexasInstruments/c2000ware-core-sdk.git
cd c2000ware-core-sdk
git sparse-checkout set device_support/f28003x driverlib/f28003x
git checkout
```

**Build firmware:**

```bash
# From examples/c2000-stress-test directory
./docker-build.sh
```

The Docker build:
- Uses pre-configured CCS 20.2 with C2000 compiler
- Mounts C2000Ware SDK from `/tmp/c2000ware-core-sdk`
- Imports project via Docker image entrypoint
- Builds firmware to `Debug/launchxl_ex1_f280039c_demo.out`
- No local CCS installation needed
- Works in CI/CD pipelines

**Output:** `Debug/<project>.out` (COFF/ELF binary ready to flash)

### Flashing C2000 Firmware

```bash
# Flash via EAB (auto-detects XDS110, uses CCS DSS transport)
eabctl flash examples/c2000-stress-test

# Or manually via CCS debugger GUI
```

### Live Debug Access

C2000 supports live variable access via CCS Scripting Server (persistent debug session):

```bash
# Read variables during execution
eabctl c2000 read-vars --vars error_count,heap_free

# Stream variables to file
eabctl c2000 stream-vars --vars sensor_data --rate 100

# Trace execution with ERAD profiler
eabctl c2000 trace start --buffer-size 1024
```

### Hardware Support

- **F28003x**: LAUNCHXL-F280039C dev kit
- **Debug Probe**: XDS110 (onboard USB-JTAG)
- **Transport**: CCS DSS (Debug Server Scripting) for live memory access
- **Throughput**: ~31 KB/s (bulk reads), ~12 Hz (DLOG snapshots)

### Known Limitations

- Requires CCS installed locally OR Docker for builds
- Flash via CCS GUI or eabctl (no standalone flash tool)
- DSS transport requires Node.js for CCS scripting client

See `examples/c2000-stress-test/README.md` for complete build and test documentation.

## Diagnostics

```bash
eabctl diagnose
eabctl diagnose --json
```

## Status JSON

Check `/tmp/eab-devices/<device>/status.json` for:
- `connection.status`: "connected", "reconnecting", "disconnected"
- `health.status`: "healthy", "idle", "stuck", "disconnected"
- `health.idle_seconds`: Seconds since last serial activity
- `health.usb_disconnects`: Count of USB disconnect events

## Event Stream (JSONL)

Check `/tmp/eab-devices/<device>/events.jsonl` for non-blocking system events:
- daemon_starting/daemon_started/daemon_stopped
- command_sent/command_result
- paused/resumed/flash_start/flash_end
- alert/crash_detected

## Pre-Flight Check

Before flashing, run preflight to verify everything is ready:

```bash
eabctl preflight
```

This checks:
- Daemon is running
- Port is detected
- Device is connected
- Health status is good

## Trace Capture (Perfetto Integration)

Capture device output to `.rttbin` and export to Perfetto JSON for visualization. Works with **any board** — not just J-Link/RTT.

```bash
# RTT capture (nRF5340 via J-Link — original mode)
eabctl trace start --source rtt -o /tmp/trace.rttbin --device NRF5340_XXAA_APP

# Serial capture (any board with an EAB daemon running)
eabctl trace start --source serial --trace-dir /tmp/eab-devices/esp32 -o /tmp/trace.rttbin
eabctl trace start --source serial --trace-dir /tmp/eab-devices/nrf5340 -o /tmp/trace.rttbin

# Auto-derive device dir from --device name (NRF5340_XXAA_APP → /tmp/eab-devices/nrf5340/)
eabctl trace start --source serial --device NRF5340_XXAA_APP -o /tmp/trace.rttbin

# Logfile replay (tail any text file)
eabctl trace start --source logfile --logfile /path/to/old.log -o /tmp/trace.rttbin

# Stop capture
eabctl trace stop

# Export to Perfetto JSON (works with any source)
eabctl trace export -i /tmp/trace.rttbin -o /tmp/trace.json
# Open trace.json in https://ui.perfetto.dev
```

All sources write the same `.rttbin` format. The serial/logfile modes tail the log file and write each line as a frame with wall-clock timestamps. Log rotation (file truncation) is handled gracefully.

## All Commands

```
eabctl status              # Check daemon and device status
eabctl preflight           # Verify ready to flash (run before flashing!)
eabctl tail [N]            # Show last N lines (default 50)
eabctl alerts [N]          # Show last N alerts (default 20)
eabctl events [N]          # Show last N JSON events (default 50)
eabctl send <text>         # Send text to device
eabctl reset               # Reset ESP32
eabctl flash <dir>         # Flash ESP-IDF project
eabctl erase               # Erase entire flash
eabctl wait <pat>          # Wait for pattern in output
eabctl wait-event          # Wait for event in events.jsonl
eabctl stream ...          # High-speed data stream (data.bin)
eabctl recv ...            # Read bytes from data.bin
eabctl fault-analyze       # Decode Cortex-M fault registers via GDB
eabctl profile-function    # Profile function execution time (J-Link + DWT)
eabctl profile-region      # Profile address region execution time (J-Link + DWT)
eabctl dwt-status          # Display DWT register state
eabctl trace start         # Start trace capture (rtt/serial/logfile → .rttbin)
eabctl trace stop          # Stop active trace capture
eabctl trace export        # Export .rttbin to Perfetto JSON
eabctl regression          # Run hardware-in-the-loop regression tests
```

## Regression Testing (Hardware-in-the-Loop)

Define repeatable hardware tests in YAML. Each step shells out to `eabctl --json` — same commands you'd run manually or in CI. Tests get JSON pass/fail results.

```bash
# Run all tests in a directory
eabctl regression --suite tests/hw/ --json

# Run a single test file
eabctl regression --test tests/hw/nrf5340_hello.yaml --json

# Filter by pattern
eabctl regression --suite tests/hw/ --filter "*nrf*" --json

# Override per-test timeout
eabctl regression --suite tests/hw/ --timeout 120 --json
```

### Test YAML Format

```yaml
name: nRF5340 Hello World
device: nrf5340              # EAB device name
chip: nrf5340                # for flash/debug commands
timeout: 60                  # per-test timeout (seconds)

setup:
  - flash:
      firmware: samples/hello_world
      runner: jlink

steps:
  - reset: {}
  - wait:
      pattern: "Hello from"
      timeout: 10
  - send:
      text: "status"
      await_ack: true
  - read_vars:
      elf: build/zephyr/zephyr.elf
      vars:
        - name: error_count
          expect_eq: 0
        - name: heap_free
          expect_gt: 1024
  - fault_check:
      elf: build/zephyr/zephyr.elf
      expect_clean: true

teardown:
  - reset: {}
```

### Step Types

| Step | Maps to | Key params |
|------|---------|------------|
| `flash` | `eabctl flash` | firmware, chip, runner, address |
| `reset` | `eabctl reset` | chip, method |
| `send` | `eabctl send` | text, await_ack, timeout |
| `wait` | `eabctl wait` | pattern, timeout |
| `wait_event` | `eabctl wait-event` | event_type, contains, timeout |
| `assert_log` | `eabctl wait` | pattern, timeout (alias for readability) |
| `sleep` | `time.sleep()` | seconds |
| `read_vars` | `eabctl read-vars` | elf, vars[] with expect_eq/gt/lt |
| `fault_check` | `eabctl fault-analyze` | elf, device, chip, expect_clean |

### Execution Model

- **Setup**: Runs first. Any failure → test fails immediately, skips steps.
- **Steps**: Run in order. First failure → stops, remaining steps skipped.
- **Teardown**: Always runs, even on failure. Errors logged but don't cause test failure.
- **Exit code**: 0 = all pass, 1 = any fail. JSON output includes per-step timing and details.

### Requires

`pip install pyyaml` (or `pip install embedded-agent-bridge[regression]`)

## Binary Framing (Optional)

If you can deploy custom firmware, you can use the proposed binary framing
defaults in `PROTOCOL.md` to reach high throughput. Stock firmware remains
compatible with line‑based logs.

## Troubleshooting

| Problem | Solution |
|---------|----------|
| "port is busy" | Use `eabctl flash` instead of esptool |
| No output | Run `eabctl status` then `eabctl reset` |
| Boot loop | Run `eabctl flash /path/to/working/project` |
| Daemon not running | Run `eabctl start` |
| Flash failed | Run `eabctl preflight` to diagnose |
| USB disconnected | Check cable, run `eabctl status` |
| J-Link not found | Install J-Link Software Pack from SEGGER |
| pylink not found | Install with: `pip install embedded-agent-bridge[jlink]` or `pip install pylink-square` |
| OpenOCD "unknown target" | Use chip-specific OpenOCD (espressif/openocd-esp32 for ESP32) |
| `west` not found | `pip install west` and set `ZEPHYR_BASE` |
| RTT no output | Verify J-Link connected, correct device name in `--device` flag |

## ESPTool Wrapper (System Protection)

An esptool wrapper script is included that intercepts direct esptool calls and
redirects agents to use eabctl instead. This prevents "port busy" errors.

To enable system-wide protection, add to PATH before the real esptool:
```bash
export PATH="/path/to/embedded-agent-bridge:$PATH"
```

The wrapper will:
1. Detect if EAB daemon is managing the port
2. Block write operations that would conflict
3. Display helpful instructions pointing to eabctl
4. Pass through non-conflicting operations to real esptool

## Typical Workflow

```bash
# 1. Check status first
eabctl status

# 2. Run preflight before flashing
eabctl preflight

# 3. Flash your project
eabctl flash /path/to/project

# 4. Monitor output
eabctl tail 50
```
