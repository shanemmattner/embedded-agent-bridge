---
name: embedded-agent-bridge
description: >
  Managing embedded hardware (ESP32, STM32, nRF5340/Zephyr) through the EAB daemon, eabctl CLI, and JLinkBridge Python API.
  Use when the user asks to interact with microcontrollers, flash firmware, read serial
  output, debug crashes, send commands to devices, or manage hardware daemons.
---

# Embedded Agent Bridge (EAB)

EAB runs a background daemon that manages the serial port, so you never need to hold open
an interactive session. All interaction is through `eabctl` CLI commands and session files.

## Quick Start

```bash
# Ensure eabctl is in PATH (install if needed: pip install -e /path/to/embedded-agent-bridge)
which eabctl || pip install -e .

# One-liner: start daemon and see what the device is printing
eabctl start --port auto && eabctl tail 20 --json
```

## Architecture

```
You (agent) ──eabctl──► EAB Daemon ──serial──► Hardware (ESP32/STM32)
                              │
                              ▼
                    /tmp/eab-session/
                    ├── latest.log     (serial output)
                    ├── alerts.log     (crashes, errors)
                    ├── events.jsonl   (structured events)
                    ├── status.json    (connection state)
                    └── cmd.txt        (command queue)

RTT path (Python API):
Agent ──JLinkBridge──► JLinkRTTLogger ──SWD──► nRF5340/Zephyr
                              │
                              ▼
                    /tmp/eab-session/
                    ├── rtt-raw.log  (raw JLinkRTTLogger output)
                    ├── rtt.log      (cleaned text)
                    ├── rtt.jsonl    (structured records)
                    └── rtt.csv      (DATA key=value rows)
```

## Essential Commands

### Always use `--json` for machine-parseable output

```bash
eabctl status --json          # Connection health, counters, port info
eabctl tail 50 --json         # Last 50 lines of serial output
eabctl alerts 20 --json       # Last 20 alert lines (crashes, errors)
eabctl events 50 --json       # Last 50 structured events
eabctl send "help" --json     # Send command to device
eabctl diagnose --json        # Full health check with recommendations
```

### Daemon lifecycle

```bash
eabctl start --port /dev/cu.usbmodem101    # Start daemon on specific port
eabctl start --port auto                    # Auto-detect USB serial port
eabctl stop                                 # Stop daemon
eabctl status --json                        # Check if running
```

### Flashing firmware

```bash
# Flash binary or ELF (STM32 ELF auto-converted to .bin)
eabctl flash firmware.bin --chip esp32c6 --port /dev/cu.usbmodem101
eabctl flash firmware.elf --chip stm32l4

# Flash ESP-IDF project directory
eabctl flash /path/to/esp-idf-project --chip esp32c6

# Erase flash (fixes corrupted firmware)
eabctl erase --chip stm32l4

# Reset device
eabctl reset --chip esp32c6
```

### Port control (CRITICAL for hardware commands)

```bash
# Pause daemon to release serial port (required before chip-info, manual flash, etc.)
eabctl pause 60               # Pause for 60 seconds
eabctl resume                  # Resume early

# flash/erase/reset handle pause/resume automatically
# chip-info does NOT — you must pause first
```

### Waiting for output

```bash
eabctl wait "Ready" --timeout 30         # Wait for regex in serial output
eabctl wait-event --type alert --timeout 10  # Wait for structured event
```

### GDB + OpenOCD (debug bridge)

```bash
eabctl openocd start --chip esp32c6      # Start OpenOCD
eabctl gdb --chip esp32c6 --cmd "bt" --cmd "info registers"
eabctl openocd stop
```

### High-speed data streaming

```bash
eabctl stream start --mode raw --chunk 16384 --marker "===DATA_START==="
eabctl recv-latest --bytes 65536 --out data.bin
eabctl stream stop
```

## Supported Chips

| Family | Variants | Flash Tool | Debug |
|--------|----------|-----------|-------|
| ESP32 | esp32, esp32s3, esp32c3, esp32c6 | esptool | OpenOCD (ESP build) |
| STM32 | stm32l4, stm32f4, stm32h7, stm32g4, stm32mp1 | st-flash | OpenOCD + ST-Link |
| nRF (Zephyr) | nrf5340, nrf52840 | west flash / J-Link | J-Link SWD + RTT |
| RP2040 (Zephyr) | rp2040 | west flash / picotool | — |

## Common Workflows

### 1. Start fresh session (recommended: `--port auto`)

```bash
eabctl start --port auto    # Auto-detect is the easiest default
eabctl status --json        # Verify connected — check health.status and connection.status
eabctl tail 20 --json       # See what device is printing
```

### 2. Send command and check response

```bash
eabctl send "help" --json
sleep 1
eabctl tail 10 --json       # Read response
```

### 3. Flash and verify

```bash
eabctl flash firmware.bin --chip esp32c6 --json
eabctl wait "Ready" --timeout 15
eabctl tail 20 --json       # Verify boot output
```

### 4. Diagnose problems

```bash
eabctl diagnose --json       # Automated health check
eabctl alerts 20 --json      # Recent crashes/errors
eabctl events 50 --json      # Daemon lifecycle events
```

### 5. Debug with GDB

```bash
eabctl openocd start --chip stm32l4
eabctl gdb --chip stm32l4 --cmd "monitor reset halt" --cmd "bt" --cmd "info registers"
eabctl openocd stop
```

### 6. RTT streaming (nRF5340 / Zephyr)

```python
from eab.jlink_bridge import JLinkBridge
bridge = JLinkBridge('/tmp/eab-session')
bridge.start_rtt(device='NRF5340_XXAA_APP')
# Read: rtt.log, rtt.jsonl, rtt.csv
bridge.stop_rtt()
```

## Critical Rules

1. **Always use `--json`** — Parse structured output, don't regex human-readable text. Key fields: `health.status`, `connection.status`, `daemon.is_alive`
2. **Pause before chip-info** — `eabctl pause 30 && eabctl chip-info --chip esp32c6 && eabctl resume`
3. **Don't hold serial ports open** — Never use `minicom`, `screen`, or `pyserial` directly; use eabctl
4. **Check status first** — Before any operation, run `eabctl status --json` to verify daemon is running
5. **STM32 needs .bin, not .elf** — `eabctl flash` handles this automatically (converts ELF to binary)
6. **ESP32 handles .elf natively** — esptool accepts ELF files directly
7. **Read session files directly** when eabctl is too slow — `latest.log`, `alerts.log`, `events.jsonl` are plain text

## Troubleshooting

| Symptom | Cause | Fix |
|---------|-------|-----|
| `eabctl: command not found` | Not in PATH | `pip install -e /path/to/embedded-agent-bridge` or activate venv |
| "Daemon not running" | No daemon started | `eabctl start --port auto` |
| "Port busy" / "Resource busy" | Another process has serial port | `eabctl pause 60` or kill conflicting process |
| Boot loop (WATCHDOG in alerts) | Corrupted firmware | `eabctl erase --chip <chip> && eabctl flash firmware.bin --chip <chip>` |
| Flash succeeds but no output | Wrong baud rate or firmware crash | Check `eabctl tail 20`, try `eabctl reset` |
| "objcopy not found" | ARM toolchain missing (STM32 ELF) | `brew install --cask gcc-arm-embedded` |
| chip-info fails | Daemon fighting for port | `eabctl pause 30` first, then `eabctl chip-info` |
| OpenOCD "unknown target" | Need ESP-specific OpenOCD build | Install espressif/openocd-esp32, not homebrew openocd |

## Session Directory

Default: `/tmp/eab-session/` (override with `--base-dir`)

| File | Format | Contents |
|------|--------|----------|
| `latest.log` | Text | `[HH:MM:SS.mmm] <serial line>` |
| `alerts.log` | Text | Filtered crashes, errors, watchdog |
| `events.jsonl` | JSONL | `{"type": "...", "timestamp": "...", "data": {...}}` |
| `status.json` | JSON | Connection state, counters, patterns |
| `cmd.txt` | Text | Command queue (append to send) |
| `data.bin` | Binary | High-speed stream data |
| `rtt-raw.log` | Text | Raw JLinkRTTLogger output |
| `rtt.log` | Text | Cleaned RTT text, ANSI stripped |
| `rtt.jsonl` | JSONL | Structured RTT records |
| `rtt.csv` | CSV | DATA key=value rows |

## Reference

- Full agent guide: `AGENT_GUIDE.md` (detailed workflows, special commands, file interface)
- Binary protocol: `PROTOCOL.md` (high-speed framing format)
- CLI help: `eabctl --help` and `eabctl <command> --help`
