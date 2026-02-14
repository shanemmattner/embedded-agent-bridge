# Embedded Agent Bridge

[![License: MIT](https://img.shields.io/badge/License-MIT-blue.svg)](LICENSE)
[![Python 3.9+](https://img.shields.io/badge/Python-3.9+-green.svg)](https://python.org)
[![CI](https://github.com/shanemmattner/embedded-agent-bridge/actions/workflows/ci.yml/badge.svg)](https://github.com/shanemmattner/embedded-agent-bridge/actions/workflows/ci.yml)
[![Lint](https://github.com/shanemmattner/embedded-agent-bridge/actions/workflows/lint.yml/badge.svg)](https://github.com/shanemmattner/embedded-agent-bridge/actions/workflows/lint.yml)

Background daemons that manage serial ports, GDB, and OpenOCD so LLM agents (Claude Code, Cursor, Copilot, etc.) can interact with embedded hardware without hanging or wasting context tokens. The agent pings the daemon for data through a simple CLI and file interface instead of trying to hold open interactive sessions directly.

```
Agent ──eabctl──► Serial Daemon ──UART──► ESP32 / STM32
  │
  ├──Python API──► JLinkBridge ──SWD/RTT──► nRF5340 / Zephyr targets
  │
  └──eabctl──► fault-analyze ──GDB──► Cortex-M registers (any probe)
```

## Quick Start

```bash
pip install embedded-agent-bridge   # or: git clone + pip install -e .

# Start the serial daemon (auto-detects USB serial ports)
eabctl start --port auto

# Now any agent can:
eabctl tail 50 --json              # Read serial output
eabctl send "AT+RST" --json        # Send commands to device
eabctl status --json               # Check connection health
eabctl flash fw.bin --chip esp32s3  # Flash firmware
eabctl diagnose --json             # Full health check
```

That's it. Your agent reads files and calls CLI commands. No MCP server, no custom protocol, no interactive sessions.

## Why

LLM agents work in a read/write/run loop. Embedded dev requires persistent sessions — a serial monitor that stays open, a GDB connection, a JTAG interface. When an agent tries to run `minicom` or `screen` directly, it either blocks forever, loses state when it closes the session to read output, or fights another tool for the port.

EAB turns these interactive sessions into file I/O and CLI calls. The agent reads `latest.log` instead of holding open minicom, and writes to `cmd.txt` instead of fighting for the serial port.

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
- Automatic ELF-to-binary conversion for STM32 (st-flash requires .bin)
- ESP32 and STM32 (ST-Link) support built-in

**ESP-IDF Integration**
- `eab-flash` wrapper: auto-pauses daemon, flashes, daemon resumes
- Works with `idf.py flash` and `esptool` directly

**RTT (Real-Time Transfer) via J-Link**
- JLinkRTTLogger subprocess management via JLinkBridge facade
- RTTStreamProcessor with multi-format output (rtt.log, rtt.jsonl, rtt.csv)
- Log rotation, boot/reset detection
- Real-time plotter (browser-based uPlot + WebSocket, parses `DATA: key=value` from RTT stream)

**Cortex-M Fault Analysis**
- `eabctl fault-analyze` reads fault registers (CFSR, HFSR, BFAR, MMFAR, SFSR, SFAR) via GDB
- Decodes fault bits to human-readable descriptions
- Stacked PC extraction for crash location
- Works with any debug probe (J-Link or OpenOCD/CMSIS-DAP)

**Debug Probe Abstraction**
- Pluggable probe backends: J-Link (via JLinkGDBServer), OpenOCD (CMSIS-DAP, ST-Link)
- Probe registry with auto-detection
- Backward-compatible with legacy JLinkBridge API

**Zephyr RTOS Support**
- `west flash` integration for Zephyr targets
- Chip profiles for nRF5340, MCXN947, RP2040
- Board detection from CMakeCache.txt

**Agent-Friendly Design**
- All output in files — agents read with `cat`, `tail`, or their native file tools
- `--json` flag on every command for structured output
- No interactive sessions, no stdin, no TTY requirements
- Session directory (`/tmp/eab-devices/<device>/`) is the single source of truth

## Usage

### Agent reads serial output and sends commands

```bash
eabctl tail 50 --json        # Last 50 lines of serial output
eabctl send "help" --json    # Send command to device
eabctl events 20 --json      # Recent system events
eabctl diagnose --json       # Full health check
```

### Agent flashes firmware

```bash
# ESP32 — esptool handles ELF and binary natively
eabctl flash firmware.bin --chip esp32s3 --port /dev/cu.usbserial-0001

# STM32 — ELF files auto-converted to binary via arm-none-eabi-objcopy
eabctl flash firmware.elf --chip stm32l4
eabctl flash firmware.bin --chip stm32l4 --address 0x08004000

# ESP-IDF projects (handles daemon pause/resume automatically)
eab-flash -p /dev/cu.usbmodem1101
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
| `rtt-raw.log` | Raw RTT output (unprocessed) |
| `rtt.log` | Timestamped RTT output |
| `rtt.csv` | RTT data in CSV format |
| `rtt.jsonl` | RTT structured events |

## Platform Support

| Platform | Status | Notes |
|----------|--------|-------|
| **macOS** | Tested | Primary development platform |
| **Linux** | Expected to work | Same APIs (fcntl, pyserial), not yet tested |
| **Windows** | Expected to work | File locking migrated to `portalocker`. Not yet tested. |

## Supported Hardware

- **ESP32** family (S3, C3, C6) — serial + USB-JTAG + ESP-IDF flash
- **STM32** family (H7, F4, G4, L4, MP1) — serial + ST-Link + OpenOCD
- **nRF5340** (Zephyr) — J-Link SWD + RTT + fault analysis
- **FRDM-MCXN947** (Zephyr) — OpenOCD CMSIS-DAP + fault analysis
- **Zephyr RTOS targets** — any board with J-Link or OpenOCD support
- **Any UART device** — the serial daemon works with anything that shows up as `/dev/tty*` or `/dev/cu.*`

## Roadmap

- [x] Serial monitor daemon with auto-reconnection
- [x] Pattern detection and alerting
- [x] ESP-IDF flash integration
- [x] OpenOCD + GDB bridge (batch commands)
- [x] Chip-agnostic flash/erase/reset
- [x] Automatic ELF-to-binary conversion for STM32
- [x] Claude Code agent skill (`.claude/skills/eab/SKILL.md`)
- [x] Zephyr RTOS support ([#60](https://github.com/shanemmattner/embedded-agent-bridge/issues/60), [#62](https://github.com/shanemmattner/embedded-agent-bridge/issues/62))
- [x] RTT via J-Link ([#55](https://github.com/shanemmattner/embedded-agent-bridge/issues/55), [#62](https://github.com/shanemmattner/embedded-agent-bridge/issues/62))
- [x] Cortex-M fault analysis ([#68](https://github.com/shanemmattner/embedded-agent-bridge/issues/68))
- [x] Debug probe abstraction ([#69](https://github.com/shanemmattner/embedded-agent-bridge/issues/69))
- [x] Windows compatibility — portalocker ([#61](https://github.com/shanemmattner/embedded-agent-bridge/issues/61))
- [ ] Multiple simultaneous port support
- [ ] GDB MI protocol wrapper (persistent debugging sessions)
- [ ] MCP server (for agents that support it)
- [ ] Cross-tool event correlation
- [ ] Power profiling integration

## Documentation

- [Agent Skill](.claude/skills/eab/SKILL.md) — Drop-in skill for Claude Code (follows [Agent Skills](https://agentskills.io) standard)
- [Agent Guide](AGENT_GUIDE.md) — Detailed instructions for LLM agents (also serves as `llms.txt`)
- [Protocol](PROTOCOL.md) — Binary framing format for high-speed streaming
- [Plotter Guide](docs/plotter.md) — Real-time data visualization
- [Examples](examples/) — Test firmware and usage examples
- [CLI Reference](#cli-reference) — Full command documentation

## CLI Reference

### All commands use `eabctl`

```bash
# Daemon lifecycle
eabctl start --port auto             # Start daemon (auto-detect port)
eabctl start --port /dev/cu.usbmodem101  # Start on specific port
eabctl stop                          # Stop daemon
eabctl status --json                 # Connection + health status

# Serial output and commands
eabctl tail 50 --json                # Recent serial output
eabctl send "command" --json         # Send command to device
eabctl alerts 20 --json              # Recent crashes/errors
eabctl events 50 --json              # Recent events
eabctl diagnose --json               # Full diagnostic report

# Port control
eabctl pause 60                      # Pause daemon for 60s (release port)
eabctl resume                        # Resume early

# Flash, erase, reset
eabctl flash fw.elf --chip stm32l4   # Flash (ELF auto-converted to .bin)
eabctl flash fw.bin --chip esp32s3   # Flash binary
eabctl erase --chip stm32l4          # Erase flash
eabctl reset --chip stm32l4          # Hardware reset
eabctl chip-info --chip esp32s3      # Chip information

# Debug bridge
eabctl openocd start --chip esp32s3  # Start OpenOCD
eabctl gdb --chip esp32s3 --cmd "bt" # Run GDB commands
eabctl openocd stop                  # Stop OpenOCD

# Fault analysis
eabctl fault-analyze --device NRF5340_XXAA_APP --json
eabctl fault-analyze --device MCXN947 --probe openocd --chip mcxn947 --json

# RTT (Python API — no CLI yet)
# from eab.rtt import JLinkBridge
# bridge = JLinkBridge(device="NRF5340_XXAA_APP", rtt_port=0)
# bridge.start(); bridge.stop()
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

# Dependencies: pyserial, portalocker
# Optional: J-Link Software Pack (for RTT), openocd, gdb, west (for Zephyr), websockets (for plotter)
```

## Contributing

Contributions welcome. Open an issue or PR.

## License

MIT
