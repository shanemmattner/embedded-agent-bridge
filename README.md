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
  ├──eabctl──► fault-analyze ──GDB──► Cortex-M registers (any probe)
  │
  └──eabctl──► DSS Transport ──JTAG/XDS110──► TI C2000
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

That's it. Your agent reads files and calls CLI commands. No custom protocol, no interactive sessions.

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

**RTT (Real-Time Transfer)**
- **J-Link transport**: JLinkRTTLogger subprocess with background logging, multi-format output (rtt.log, rtt.jsonl, rtt.csv)
- **probe-rs transport**: Native Rust extension (PyO3) for probe-agnostic RTT (ST-Link, CMSIS-DAP, J-Link, ESP USB-JTAG)
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

**C2000 DSS Transport**
- Persistent JTAG session via TI CCS scripting (Python API)
- Fast memory read/write (~1-5ms per read vs ~50ms with DSLite)
- ERAD profiler, DLOG buffer capture, register decode
- Trace export to Perfetto JSON (ERAD spans, DLOG tracks, log events)
- Variable streaming from live C2000 targets

**ML Inference Benchmarking**
- INT8 TFLite Micro with CMSIS-NN backend on Cortex-M33 and Cortex-M55
- DWT hardware cycle counter profiling (zero-overhead, exact cycle counts)
- Automated `bench_capture` regression step parses `[ML_BENCH]` output lines
- Cross-board comparison: sine, person_detect, micro_speech, exoboot_gait models
- STM32N6 SRAM boot automation (GDB load for boards without on-chip flash)
- Example firmware: `mcxn947-ml-bench/`, `stm32n6-ml-bench/`, `stm32n6-npu-bench/`, `stm32n6-gait-bench/`

**Zephyr RTOS Support**
- `west flash` integration for Zephyr targets
- Chip profiles for nRF5340, MCXN947, RP2040, STM32N6
- Board detection from CMakeCache.txt
- STM32N6 SRAM boot via `sram_boot` regression step

**Hardware-in-the-Loop Regression Testing**
- Define tests in YAML — flash, reset, send commands, assert log output, check variables
- `eabctl regression --suite tests/hw/ --json` runs a full suite with pass/fail JSON output
- Setup/teardown phases, variable assertions (expect_eq/gt/lt), fault checking
- ML benchmark steps: `bench_capture` (parse inference metrics), `sram_boot` (STM32N6 SRAM load)
- CI-friendly: exit code 0 = all pass, 1 = any fail
- Steps shell out to `eabctl --json` for full isolation

**HIL pytest Plugin**
- Write hardware-in-the-loop tests as normal `pytest` functions with fixtures and `assert`
- `hil_device` fixture manages device lifecycle (flash, reset, teardown)
- RTT output captured per-test, attached to pytest report on failure
- `--hil-device`, `--hil-chip`, `--hil-probe` CLI options; tests auto-skip without hardware
- `hil_central` fixture for second BLE central device

**BLE Hardware-in-the-Loop**
- Second nRF5340 DK as BLE central controlled via RTT shell (`BleCentral`)
- Multi-device YAML regression: `devices: {peripheral: ..., central: ...}` 
- New YAML steps: `ble_scan`, `ble_connect`, `ble_subscribe`, `ble_write`, `expect_notify`
- Full BLE end-to-end test: peripheral advertises → central connects → notifications flow → writes

**DWT Non-Halting Watchpoints**
- Program Cortex-M DWT comparators to watch memory addresses without halting the CPU
- Stream JSONL events when watched variables change (at ~100Hz polling via J-Link)
- ELF symbol resolution — watch `conn_interval` by name, not address
- Conditional halting watchpoints via GDB Python (e.g. halt only when value changes >20%)
- `eabctl dwt watch/halt/list/clear` subcommands; all 4 comparators on Cortex-M33

**Debug Monitor Mode**
- Non-halting breakpoints for BLE firmware — debug handler runs as Cortex-M exception
- BLE Link Layer keeps running at high priority; GATT callbacks debuggable without disconnect
- `eabctl debug-monitor enable --device NRF5340_XXAA_APP [--priority 3]`
- DEMCR register control (MON_EN bit 16); integrates with regression YAML flash step
- `eabctl preflight --ble-safe` warns when BLE build + halt-mode debugging detected

**MCP Server**
- Exposes all `eabctl` commands as MCP tools for Claude Desktop, Cursor, and any MCP-aware agent
- 8 tools: `get_status`, `read_rtt`, `send_command`, `fault_analyze`, `flash_firmware`, `reset_device`, `run_regression`, `get_alerts`
- stdio transport; install with `pip install embedded-agent-bridge[mcp]`
- Add to Claude Desktop: `{"mcpServers": {"eab": {"command": "eabmcp"}}}`

**Anomaly Detection**
- Baseline recording: capture RTT metric distributions from a known-good firmware run
- Z-score comparison: detect deviations from baseline (message rates, event intervals, error counts)
- EWMA streaming: real-time sigma alerting on a rolling mean — pure Python, no numpy required
- Regression step: `anomaly_watch` with configurable sigma threshold and `fail_on_anomaly`
- Metrics extracted: BT notify count, connection interval, MTU, heap free, TX backpressure

**Fault Analysis + RTT Context**  
- `--rtt-context N` on `fault-analyze`: captures last N RTT log lines before crash timestamp
- JSON output adds `context_window` and `ai_prompt` fields for LLM root cause analysis
- Auto-trigger: crash pattern detection → automatic fault-analyze → `fault_report` event

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
| `baselines/*.json` | Anomaly detection baseline (metric stats from golden run) |

## Platform Support

| Platform | Status | Notes |
|----------|--------|-------|
| **macOS** | Tested | Primary development platform |
| **Linux** | Expected to work | Same APIs (fcntl, pyserial), not yet tested |
| **Windows** | Expected to work | File locking migrated to `portalocker`. Not yet tested. |

## Supported Hardware

- **ESP32** family (S3, C3, C6, P4) — serial + USB-JTAG + ESP-IDF flash
- **STM32** family (H7, F4, G4, L4, N6) — serial + ST-Link + OpenOCD
- **STM32N6** (Cortex-M55, Helium MVE) — SRAM boot via GDB, ML benchmarking, Neural-ART NPU evaluation
- **nRF5340** (Zephyr) — J-Link SWD + RTT + fault analysis
- **FRDM-MCXN947** (Cortex-M33, Zephyr) — OpenOCD CMSIS-DAP + fault analysis + ML benchmarking
- **TI C2000** (F28003x, F28004x) — XDS110 JTAG + CCS DSS transport
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
- [x] RTT via probe-rs (native Rust extension, all probe types) ([#117](https://github.com/shanemmattner/embedded-agent-bridge/pull/117))
- [x] Cortex-M fault analysis ([#68](https://github.com/shanemmattner/embedded-agent-bridge/issues/68))
- [x] Debug probe abstraction ([#69](https://github.com/shanemmattner/embedded-agent-bridge/issues/69))
- [x] Windows compatibility — portalocker ([#61](https://github.com/shanemmattner/embedded-agent-bridge/issues/61))
- [x] Hardware-in-the-loop regression testing ([#28](https://github.com/shanemmattner/embedded-agent-bridge/issues/28))
- [x] C2000 DSS transport (persistent JTAG via CCS scripting)
- [x] C2000 trace export (ERAD + DLOG → Perfetto JSON)
- [x] ML inference benchmarking (TFLite Micro + CMSIS-NN, DWT profiling)
- [x] Cross-board ML comparison (STM32N6 Cortex-M55 vs MCXN947 Cortex-M33)
- [x] STM32N6 SRAM boot automation
- [x] MCP server (for agents that support it)
- [x] HIL pytest plugin (`hil_device` fixture, RTT capture per test, auto-skip without hardware)
- [x] DWT non-halting watchpoints (stream events without halting CPU, ELF symbol resolution)
- [x] Debug Monitor Mode (BLE-safe non-halting breakpoints, DEMCR MON_EN)
- [x] BLE HIL steps (second nRF5340 DK as central, multi-device YAML, ble_scan/connect/notify/write)
- [x] Anomaly detection (baseline record/compare + EWMA streaming, pure Python, no numpy)
- [x] Fault analyze + RTT context window (auto-trigger on crash, ai_prompt field)
- [ ] NPU acceleration benchmarks (Neural-ART, eIQ Neutron)
- [ ] Multiple simultaneous port support
- [ ] GDB MI protocol wrapper (persistent debugging sessions)
- [ ] Cross-tool event correlation
- [ ] Power profiling integration

## Documentation

- [Agent Skill](.claude/skills/eab/SKILL.md) — Drop-in skill for Claude Code (follows [Agent Skills](https://agentskills.io) standard)
- [Agent Guide](AGENT_GUIDE.md) — Detailed instructions for LLM agents (also serves as `llms.txt`)
- [ML Benchmark Comparison](docs/ml-benchmark-comparison.md) — STM32N6 vs MCXN947 inference benchmarks
- [Regression Testing](docs/regression.md) — YAML-based hardware-in-the-loop test runner
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
eabctl fault-analyze --device NRF5340_XXAA_APP --rtt-context 100 --json
eabctl fault-analyze --device MCXN947 --probe openocd --chip mcxn947 --json

# RTT (Real-Time Transfer) streaming
# J-Link transport (subprocess-based, background logging)
eabctl rtt start --device NRF5340_XXAA_APP --transport jlink
eabctl rtt stop; eabctl rtt status --json; eabctl rtt tail 100

# probe-rs transport (native Rust extension, all probe types)
eabctl rtt start --device STM32L476RG --transport probe-rs
eabctl rtt start --device STM32L476RG --transport probe-rs --probe-selector "0483:374b"

# C2000 debug (requires CCS 2041+)
eabctl reg-read --reg IER --ccxml target.ccxml   # Read/decode C2000 register
eabctl erad-status --ccxml target.ccxml          # ERAD profiler status
eabctl stream-vars --vars error_count,heap_free --ccxml target.ccxml
eabctl dlog-capture --ccxml target.ccxml -o dlog.json  # Capture DLOG buffers
eabctl c2000-trace-export -o trace.json --erad erad.json --dlog dlog.json

# Regression testing (hardware-in-the-loop)
eabctl regression --suite tests/hw/ --json       # Run all tests in directory
eabctl regression --test tests/hw/smoke.yaml     # Run single test
eabctl regression --suite tests/hw/ --filter "*nrf*" --json  # Filter by pattern

# DWT non-halting watchpoints
eabctl dwt watch --device NRF5340_XXAA_APP --address 0x20001234 --size 4 --mode write --label "conn_interval"
eabctl dwt watch --device NRF5340_XXAA_APP --symbol conn_interval --elf build/zephyr/zephyr.elf
eabctl dwt halt --device NRF5340_XXAA_APP --symbol conn_interval --elf zephyr.elf --condition "abs(new-prev)/prev>0.20"
eabctl dwt list   # active comparators
eabctl dwt clear  # release all

# Debug monitor mode (non-halting breakpoints for BLE)
eabctl debug-monitor enable --device NRF5340_XXAA_APP --priority 3
eabctl debug-monitor disable --device NRF5340_XXAA_APP
eabctl debug-monitor status --device NRF5340_XXAA_APP --json
eabctl preflight --ble-safe  # warn if BLE build + halt-mode

# Anomaly detection
eabctl anomaly record --device NRF5340_XXAA_APP --duration 60 --output baselines/nominal.json
eabctl anomaly compare --device NRF5340_XXAA_APP --baseline baselines/nominal.json --duration 30 --json
eabctl anomaly watch --device NRF5340_XXAA_APP --metric bt_notification_interval_ms --threshold 2.5sigma

# MCP server (for Claude Desktop / Cursor)
eabmcp  # start MCP server (stdio transport)
```

## Regression Step Types

| Step | Implementation | Parameters |
|------|---------------|------------|
| `flash` | `eabctl flash` | firmware, chip, runner, address |
| `reset` | `eabctl reset` | chip, method |
| `send` | `eabctl send` | text, await_ack, timeout |
| `wait` | `eabctl tail` with pattern | pattern, timeout |
| `assert_log` | Alias for `wait` | pattern, timeout |
| `wait_event` | `eabctl wait-event` | event_type, contains, timeout |
| `sleep` | `time.sleep()` | seconds |
| `read_vars` | `eabctl read-vars` | elf, vars (name, expect_eq/gt/lt) |
| `fault_check` | `eabctl fault-analyze` | elf, expect_clean |
| `bench_capture` | Parse `[ML_BENCH]` RTT output | pattern, metrics |
| `sram_boot` | GDB load for SRAM boot | elf, load_addr |
| `ble_scan` | `BleCentral.scan()` | device, target_name, timeout |
| `ble_connect` | `BleCentral.connect()` | device, timeout |
| `ble_subscribe` | `BleCentral.subscribe_notify()` | device, char_uuid |
| `ble_write` | `BleCentral.write()` | device, char_uuid, value |
| `expect_notify` | `BleCentral.assert_notify()` | device, char_uuid, count, timeout |
| `ble_disconnect` | `BleCentral.disconnect()` | device |
| `anomaly_watch` | `eabctl anomaly watch` | device, baseline, max_sigma, duration, fail_on_anomaly |

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
