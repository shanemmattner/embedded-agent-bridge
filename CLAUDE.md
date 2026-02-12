# Embedded Agent Bridge (EAB)

Background daemons bridging AI coding agents to debuggers and embedded hardware (ESP32, STM32, nRF, NXP MCX via serial, RTT, J-Link, OpenOCD). **ALWAYS use eabctl for ALL hardware operations.**

## CRITICAL RULES FOR AGENTS

1. **NEVER use esptool/JLinkExe/openocd directly** - Use `eabctl` instead
2. **NEVER use pio device monitor** - Use `eabctl tail` instead
3. **NEVER access serial ports or debug probes directly** - EAB manages all hardware interfaces
4. **Port busy errors?** Run `eabctl flash` - it handles port release automatically

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

# RTT (Python API — no CLI command yet)
# from eab.rtt import JLinkBridge
# bridge = JLinkBridge(device="NRF5340_XXAA_APP", rtt_port=0)
# bridge.start(); bridge.stop()
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
3. Flashes bootloader, partition table, and app
4. Resumes daemon and shows boot output

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
| ESP32 | esp32, esp32s3, esp32c3, esp32c6 | OpenOCD (ESP) | esptool |
| STM32 | stm32l4, stm32f4, stm32h7, stm32g4 | OpenOCD + ST-Link | st-flash |
| nRF | nRF5340 | J-Link SWD | west flash (Zephyr) |
| NXP MCX | MCXN947 | OpenOCD CMSIS-DAP | west flash (Zephyr) |

## Diagnostics

```bash
eabctl diagnose
eabctl diagnose --json
```

## Status JSON

Check `/tmp/eab-session/status.json` for:
- `connection.status`: "connected", "reconnecting", "disconnected"
- `health.status`: "healthy", "idle", "stuck", "disconnected"
- `health.idle_seconds`: Seconds since last serial activity
- `health.usb_disconnects`: Count of USB disconnect events

## Event Stream (JSONL)

Check `/tmp/eab-session/events.jsonl` for non-blocking system events:
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
```

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
