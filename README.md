# Embedded Agent Bridge

[![License: MIT](https://img.shields.io/badge/License-MIT-blue.svg)](LICENSE)
[![Python 3.9+](https://img.shields.io/badge/Python-3.9+-green.svg)](https://python.org)

Background daemons that manage serial ports, GDB, and OpenOCD so LLM agents (Claude Code, Cursor, Copilot, etc.) can interact with embedded hardware without hanging or wasting context tokens. The agent pings the daemon for data through a simple CLI and file interface instead of trying to hold open interactive sessions directly.

```
┌─────────────────┐     ┌─────────────────────┐     ┌─────────────────┐
│   AI Agent      │     │   Agent Bridge       │     │   Hardware      │
│  (Claude Code,  │     │                      │     │                 │
│   Cursor, etc.) │     │  Serial Daemon ──────┼────►│  ESP32 / STM32  │
│                 │     │  GDB + OpenOCD ──────┼────►│  (UART / JTAG)  │
│  Read files  ◄──┼─────┤                      │     │                 │
│  Write cmds  ───┼─────►  JLinkBridge ────────┼────►│  nRF5340 /      │
│  Python API  ───┼─────►  (RTT + SWO + GDB)   │     │  Zephyr (SWD)   │
└─────────────────┘     └─────────────────────┘     └─────────────────┘
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

**RTT (Real-Time Transfer) via J-Link**
- JLinkRTTLogger subprocess for native J-Link DLL speed (no pylink dependency)
- RTTStreamProcessor: ANSI stripping, line framing, log format auto-detection (Zephyr, ESP-IDF, nRF SDK)
- Multi-format output: `rtt.log` (cleaned text), `rtt.jsonl` (structured records), `rtt.csv` (DATA key=value rows)
- Log rotation (5MB cap, 3 backups)
- Boot/reset detection across all platforms
- JLinkBridge facade managing RTT, SWO, and GDB Server subprocesses

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
| `rtt-raw.log` | Raw JLinkRTTLogger output (unprocessed) |
| `rtt.log` | Cleaned RTT text with ANSI stripped |
| `rtt.csv` | DATA key=value records as CSV columns |
| `rtt.jsonl` | Structured RTT records (one JSON per line) |

## Platform Support

| Platform | Status | Notes |
|----------|--------|-------|
| **macOS** | Tested | Primary development platform |
| **Linux** | Expected to work | Same APIs (fcntl, pyserial), not yet tested |
| **Windows** | Not supported | File locking uses `fcntl` (Unix-only). Contributions welcome. |

## Supported Hardware

- **ESP32** family (S3, C3, C6) — serial + USB-JTAG + ESP-IDF flash
- **STM32** family (H7, F4, G4, L4, MP1) — serial + ST-Link + OpenOCD
- **nRF5340** (nRF Connect SDK / Zephyr) — J-Link SWD + RTT
- **Zephyr RTOS targets** — any board with J-Link support (nRF, STM32, ESP32, RP2040)
- **Any UART device** — the serial daemon works with anything that shows up as `/dev/tty*` or `/dev/cu.*`

## Roadmap

- [x] Serial monitor daemon with auto-reconnection
- [x] Pattern detection and alerting
- [x] ESP-IDF flash integration
- [x] OpenOCD + GDB bridge (batch commands)
- [x] Chip-agnostic flash/erase/reset
- [x] Automatic ELF-to-binary conversion for STM32
- [x] Claude Code agent skill (`.claude/skills/eab/SKILL.md`)
- [x] Zephyr RTOS support ([#62](https://github.com/shanemmattner/embedded-agent-bridge/pull/62))
- [ ] Multiple simultaneous port support
- [ ] GDB MI protocol wrapper (persistent debugging sessions)
- [ ] MCP server (for agents that support it)
- [ ] Cross-tool event correlation
- [ ] Power profiling integration

## Documentation

- [Agent Skill](.claude/skills/eab/SKILL.md) — Drop-in skill for Claude Code (follows [Agent Skills](https://agentskills.io) standard)
- [Agent Guide](AGENT_GUIDE.md) — Detailed instructions for LLM agents (also serves as `llms.txt`)
- [Protocol](PROTOCOL.md) — Binary framing format for high-speed streaming
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
```

## RTT (Python API)

RTT features use the Python API directly (no eabctl CLI commands yet):

```python
from eab.jlink_bridge import JLinkBridge

bridge = JLinkBridge('/tmp/eab-session')
bridge.start_rtt(device='NRF5340_XXAA_APP')
# Data streams to: rtt.log, rtt.jsonl, rtt.csv
bridge.stop_rtt()
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
# Optional: J-Link Software Pack (for RTT features)
# Optional: openocd, gdb (for debug bridge features)
```

## Contributing

Contributions welcome. Open an issue or PR.

## License

MIT
