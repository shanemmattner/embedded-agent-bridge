# Embedded Agent Bridge

[![License: MIT](https://img.shields.io/badge/License-MIT-blue.svg)](LICENSE)
[![Python 3.9+](https://img.shields.io/badge/Python-3.9+-green.svg)](https://python.org)

**Let AI agents debug your embedded hardware.**

AI coding agents (Claude Code, Cursor, Copilot) are great at writing firmware — but they can't use your debugger. They can't hold open a serial monitor, step through GDB, or flash your board. They get stuck, timeout, or just guess.

EAB fixes this. It runs background daemons that manage serial ports, GDB, and OpenOCD, then exposes everything through simple CLI calls and files that any agent can read and write. Your agent reads `latest.log` instead of trying to hold open minicom. It writes to `cmd.txt` instead of fighting for the serial port.

```
┌─────────────────┐     ┌─────────────────┐     ┌─────────────────┐
│   AI Agent      │     │  Agent Bridge   │     │   Hardware      │
│  (Claude Code,  │     │                 │     │                 │
│   Cursor, etc.) │     │  Serial Daemon  │     │  ESP32 / STM32  │
│                 │     │  GDB Bridge     │     │  nRF52 / RP2040 │
│  Read files  ◄──┼─────┤  OpenOCD Bridge ├─────┤  Any UART/JTAG  │
│  Write cmds  ───┼─────►               │     │  device         │
└─────────────────┘     └─────────────────┘     └─────────────────┘
```

## Quick Start

```bash
pip install embedded-agent-bridge   # or: git clone + pip install -e .

# Start the serial daemon (auto-detects USB serial ports)
eab --port auto &

# Now any agent can:
eabctl tail -n 50            # Read serial output
eabctl send "AT+RST"         # Send commands to device
eabctl status --json         # Check connection health
eabctl flash fw.bin --chip esp32s3   # Flash firmware
```

That's it. Your agent reads files and calls CLI commands. No MCP server, no custom protocol, no interactive sessions.

## The Problem

LLM-based coding agents operate in a **read file / write file / run command** loop. Embedded debugging requires **persistent interactive sessions** — a serial monitor that stays open, a GDB session you step through, an OpenOCD connection managing JTAG.

These two models are fundamentally incompatible. When an agent tries to run `minicom` or `screen`, it either:
- Blocks forever (can't read output while session is open)
- Loses context (closes the session to read, loses state)
- Fights for the port (another tool already has it open)

EAB bridges this gap by turning interactive sessions into file I/O and CLI calls.

## Features

**Serial Monitor Daemon**
- Auto-detect USB serial ports
- Timestamped logging to `latest.log`
- Pattern detection (crashes, errors, disconnects) → `alerts.log`
- Bidirectional communication via `cmd.txt` queue
- Auto-reconnection on disconnect
- Pause/resume for flashing (port sharing)
- JSON event stream (`events.jsonl`) for structured agent consumption

**GDB + OpenOCD Bridge**
- Start/stop OpenOCD from CLI (`eabctl openocd start --chip esp32s3`)
- One-shot GDB commands (`eabctl gdb --cmd "bt" --cmd "info registers"`)
- Chip-agnostic flash, erase, reset, chip-info commands
- ESP32 and STM32 (ST-Link) support built-in

**ESP-IDF Integration**
- `eab-flash` wrapper: auto-pauses daemon, flashes, daemon resumes
- Works with `idf.py flash` and `esptool` directly

**Agent-Friendly Design**
- All output in files — agents read with `cat`, `tail`, or their native file tools
- `--json` flag on every command for structured output
- No interactive sessions, no stdin, no TTY requirements
- Session directory (`/tmp/eab-session/`) is the single source of truth

## Usage

### Agent reads serial output and sends commands

```bash
eabctl tail -n 50 --json     # Last 50 lines of serial output
eabctl send "help"            # Send command to device
eabctl events -n 20 --json   # Recent system events
eabctl diagnose --json        # Full health check
```

### Agent flashes firmware

```bash
# Chip-agnostic
eabctl flash firmware.bin --chip esp32s3 --port /dev/cu.usbserial-0001

# ESP-IDF projects (handles daemon pause/resume automatically)
eab-flash -p /dev/cu.usbmodem1101

# STM32 via ST-Link
eabctl flash app.bin --chip stm32l4 --address 0x08004000
```

### Agent uses GDB

```bash
eabctl openocd start --chip esp32s3
eabctl gdb --chip esp32s3 --cmd "monitor reset halt" --cmd "bt"
eabctl openocd stop
```

### Session files (what agents actually read)

| File | Contents |
|------|----------|
| `latest.log` | Timestamped serial output |
| `cmd.txt` | Command queue (append to send) |
| `alerts.log` | Pattern-matched events (crashes, errors) |
| `events.jsonl` | Structured event stream |
| `status.json` | Connection and health status |
| `data.bin` | High-speed raw data (optional) |

## Comparison

| Feature | ChatDBG | MCP GDB Server | EAB |
|---------|---------|----------------|-----|
| Serial/UART monitoring | No | No | Yes |
| GDB integration | Yes | Yes | Yes |
| OpenOCD/JTAG | No | No | Yes |
| Flash firmware | No | No | Yes |
| ESP-IDF integration | No | No | Yes |
| Pattern/crash detection | No | No | Yes |
| Works with any LLM agent | No | Claude only | Yes |

## Supported Hardware

- **ESP32** family (S3, C3, C6) — serial + USB-JTAG + ESP-IDF flash
- **STM32** family (H7, F4, G4, L4, MP1) — serial + ST-Link + OpenOCD
- **Any UART device** — the serial daemon works with anything that shows up as `/dev/tty*` or `/dev/cu.*`

## Roadmap

- [x] Serial monitor daemon with auto-reconnection
- [x] Pattern detection and alerting
- [x] ESP-IDF flash integration
- [x] OpenOCD + GDB bridge (batch commands)
- [x] Chip-agnostic flash/erase/reset
- [ ] GDB MI protocol wrapper (persistent debugging sessions)
- [ ] Multiple simultaneous port support
- [ ] MCP server (for agents that support it)
- [ ] Cross-tool event correlation
- [ ] Power profiling integration

## Documentation

- [Agent Guide](AGENT_GUIDE.md) — Detailed instructions for LLM agents (also serves as `llms.txt`)
- [Protocol](PROTOCOL.md) — Binary framing format for high-speed streaming
- [CLI Reference](#cli-reference) — Full command documentation

## CLI Reference

### Daemon

```bash
eab --port auto                # Start daemon (auto-detect port)
eab --port auto --force        # Kill existing daemon and start fresh
eab --status                   # Check if daemon is running
eab --stop                     # Stop daemon
eab --pause 60                 # Pause daemon for 60s (release port)
eab --logs 50                  # View last 50 log lines
eab --alerts 20                # View last 20 alerts
eab --wait-for "BOOT" --wait-timeout 30   # Wait for pattern
```

### Controller (eabctl)

```bash
eabctl status --json           # Connection + health status
eabctl tail -n 50 --json       # Recent serial output
eabctl send "command" --json   # Send command to device
eabctl events -n 50 --json     # Recent events
eabctl diagnose --json         # Full diagnostic report
eabctl flash fw.bin --chip esp32s3   # Flash firmware
eabctl erase --chip stm32l4         # Erase flash
eabctl reset --chip stm32l4         # Hardware reset
eabctl chip-info --chip esp32s3     # Chip information
eabctl openocd start --chip esp32s3  # Start OpenOCD
eabctl gdb --chip esp32s3 --cmd "bt" # Run GDB commands
```

## Related Projects

- [ChatDBG](https://github.com/plasma-umass/ChatDBG) — AI debugging for GDB/LLDB (75K+ downloads)
- [probe-rs](https://probe.rs/) — Rust debugging toolkit for ARM
- [pyOCD](https://pyocd.io/) — Python debugger for ARM Cortex-M
- [OpenOCD](https://openocd.org/) — Open On-Chip Debugger

## Installation

```bash
# From PyPI (coming soon)
pip install embedded-agent-bridge

# From source
git clone https://github.com/shanemmattner/embedded-agent-bridge.git
cd embedded-agent-bridge
pip install -e .

# Dependencies: just pyserial
# Optional: openocd, gdb (for debug bridge features)
```

## Contributing

Contributions welcome. Open an issue or PR.

## License

MIT
