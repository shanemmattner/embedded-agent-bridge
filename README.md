# Embedded Agent Bridge

AI agent bridge for embedded systems debugging. Enables LLM agents (Claude Code, ChatGPT, etc.) to interact with embedded hardware through serial monitors, GDB debuggers, OpenOCD/JTAG interfaces, and more.

## Vision

Embedded debugging is hard. You're juggling:
- Serial monitor output
- GDB sessions
- OpenOCD/JTAG connections
- Logic analyzer traces
- Oscilloscope readings
- Datasheet lookups

What if an AI agent could help? Not just answer questions, but actually **control the debugger**, **read serial output**, **set breakpoints**, and **correlate events** across all these interfaces?

That's what Embedded Agent Bridge enables.

## Architecture

```
┌─────────────────┐     ┌─────────────────┐     ┌─────────────────┐
│   AI Agent      │     │  Agent Bridge   │     │   Hardware      │
│  (Claude Code)  │     │                 │     │                 │
│                 │     │  ┌───────────┐  │     │  ┌───────────┐  │
│  Read files ◄───┼─────┼──┤ Serial    ├──┼─────┼──┤ ESP32     │  │
│  Write cmds ────┼─────┼──► Daemon    │  │     │  │ STM32     │  │
│                 │     │  └───────────┘  │     │  │ nRF52     │  │
│                 │     │                 │     │  └───────────┘  │
│                 │     │  ┌───────────┐  │     │                 │
│                 │◄────┼──┤ GDB       ├──┼─────┼──► JTAG/SWD    │
│                 │────►┼──► Daemon    │  │     │                 │
│                 │     │  └───────────┘  │     │                 │
│                 │     │                 │     │                 │
│                 │     │  ┌───────────┐  │     │                 │
│                 │◄────┼──┤ OpenOCD   ├──┼─────┼──► Debug Probe  │
│                 │────►┼──► Bridge    │  │     │                 │
│                 │     │  └───────────┘  │     │                 │
└─────────────────┘     └─────────────────┘     └─────────────────┘
```

## Core Components

### 1. Serial Monitor Daemon
Background process that captures serial output and enables command injection.

**Current implementation:**
- Daemon: `python3 -m eab` (`eab/daemon.py`)
- Recommended wrapper: `eab-control` (bash) + `eabctl` (Python, JSON-friendly)

**Session files (default `/tmp/eab-session/`):**
- `latest.log` - Captured output (timestamped)
- `cmd.txt` - Command queue (append one command per line)
- `alerts.log` - Pattern-matched important events
- `events.jsonl` - JSONL system events (pause/resume, flash, alerts, commands)
- `data.bin` - High-speed raw data stream (optional)
- `status.json` - Connection + health status (for agents)

**Features:**
- Auto-detect USB serial ports
- Timestamped logging
- Pattern detection (DISCONNECT, ERROR, TIMEOUT, etc.)
- Bidirectional communication
- Statistics tracking

### 2. USB-JTAG + GDB (EAB-managed)
EAB includes an **OpenOCD + GDB** control surface via `eabctl` so you can keep chip/debug interaction inside EAB.

**Start OpenOCD (ESP32-S3 built-in USB Serial/JTAG defaults):**
```bash
./eabctl openocd start --chip esp32s3 --vid 0x303a --pid 0x1001
```

**Send an OpenOCD command (via telnet port, default 4444):**
```bash
./eabctl openocd cmd --command "targets"
```

**Run one-shot GDB commands against the OpenOCD GDB server (default :3333):**
```bash
./eabctl gdb --chip esp32s3 --cmd "monitor reset halt" --cmd "bt"
```

**Stop OpenOCD:**
```bash
./eabctl openocd stop
```

**Notes:**
- This is a minimal bridge (OpenOCD lifecycle + batch GDB commands). A persistent MI wrapper can be added later.
- If OpenOCD exits immediately, check `/tmp/eab-session/openocd.err` and ensure the device exposes USB-JTAG.

### 3. Flash Operations (Chip-Agnostic)
EAB provides chip-agnostic flash commands that work with ESP32, STM32, and other supported chips.

**Flash firmware:**
```bash
# ESP32
./eabctl flash firmware.bin --chip esp32s3 --port /dev/cu.usbserial-0001 --address 0x10000

# STM32
./eabctl flash firmware.bin --chip stm32l4 --address 0x08004000
```

**Erase flash:**
```bash
./eabctl erase --chip stm32l4
./eabctl erase --chip esp32s3 --port /dev/cu.usbserial-0001
```

**Get chip info:**
```bash
./eabctl chip-info --chip stm32l4 --json
./eabctl chip-info --chip esp32s3 --port /dev/cu.usbserial-0001
```

**Hardware reset:**
```bash
./eabctl reset --chip stm32l4
```

### 4. STM32 + ST-Link Integration
Full support for STM32 development with ST-Link debugging.

**Start OpenOCD with ST-Link:**
```bash
./eabctl openocd start --chip stm32l4
```

**GDB debugging:**
```bash
./eabctl gdb --chip stm32l4 --cmd "monitor reset halt" --cmd "bt"
```

**Flash firmware workflow:**
```bash
# Check chip connection
./eabctl chip-info --chip stm32l4

# Flash bootloader + app
./eabctl flash bootloader.bin --chip stm32l4 --address 0x08000000
./eabctl flash app.bin --chip stm32l4 --address 0x08004000

# Reset and run
./eabctl reset --chip stm32l4
```

### 5. ESP-IDF Integration

The `eab-flash` wrapper enables seamless flashing while EAB daemon is running.

**The Problem:** EAB holds the serial port open for monitoring, which blocks `esptool`/`idf.py flash` from accessing the device.

**The Solution:** `eab-flash` automatically pauses EAB, flashes, and EAB auto-resumes.

#### Basic Usage

```bash
# Flash ESP-IDF project (from project directory)
./eab-flash

# Flash specific project
./eab-flash --project /path/to/esp-idf-project

# Flash to specific port
./eab-flash -p /dev/cu.usbmodem1101

# Use esptool directly
./eab-flash --esptool -p /dev/ttyUSB0 write_flash 0x0 firmware.bin

# Longer pause duration (default 60s)
./eab-flash --pause-duration 120

# Dry run - see what would happen without actually flashing
./eab-flash --dry-run -p /dev/cu.usbmodem1101

# Verbose mode for debugging
./eab-flash --verbose -p /dev/cu.usbmodem1101
```

#### How It Works

1. Detects if EAB daemon is running
2. Sends pause command (EAB releases serial port)
3. Waits for port release confirmation (with timeout)
4. Sources ESP-IDF environment and runs `idf.py flash` or `esptool`
5. EAB auto-resumes after pause expires

#### Command-Line Options

| Option | Description |
|--------|-------------|
| `--esptool` | Use esptool directly instead of idf.py flash |
| `--project`, `-C DIR` | Specify ESP-IDF project directory |
| `--pause-duration N` | Pause EAB for N seconds (default: 60) |
| `--dry-run` | Show what would be executed without running |
| `--verbose`, `-v` | Enable verbose output for debugging |
| `--version`, `-V` | Show version information |
| `--help`, `-h` | Show help message |

All other arguments (like `-p PORT`, `-b BAUD`) are passed through to `idf.py flash` or `esptool`.

#### Exit Codes

| Code | Meaning |
|------|---------|
| 0 | Flash completed successfully |
| 1 | Argument or validation error |
| 2 | Environment error (Python/ESP-IDF not found) |
| 3 | EAB communication error |
| * | Exit code from esptool/idf.py (passed through) |

#### Environment Variables

| Variable | Description | Default |
|----------|-------------|---------|
| `IDF_PATH` | Path to ESP-IDF installation | `$HOME/esp/esp-idf` |
| `EAB_SESSION_DIR` | EAB session directory | `/tmp/eab-session` |

#### Error Scenarios and Edge Cases

**Flash fails:**
- EAB will still auto-resume after the pause expires
- Error message will indicate the exit code from esptool/idf.py
- Check device connection and port availability

**Ctrl+C during flash:**
- Safe to abort; EAB pause timer continues independently
- EAB will auto-resume when the pause expires
- To resume EAB immediately: `rm /tmp/eab-session/pause.txt`

**Port still busy after pause:**
- The script waits up to 10 seconds for port release
- If timeout occurs, it proceeds with flash attempt anyway
- Check for other processes using the port with `lsof /dev/cu.usbmodem*`

**ESP-IDF not found:**
- Set `IDF_PATH` environment variable to your ESP-IDF location
- Or source `export.sh` manually before running `eab-flash`

**Multiple devices connected:**
- Use `-p PORT` to specify the exact port
- Without `-p`, idf.py/esptool may select wrong device

**Concurrent eab-flash calls:**
- Only one flash operation at a time is safe
- The pause file mechanism doesn't support concurrent access

#### Manual Pause (For Other Tools)

If you need to use other flash tools that `eab-flash` doesn't support:

```bash
# Pause EAB for 60 seconds
python3 -m eab --pause 60

# EAB releases port immediately
# Flash with any tool you want
esptool.py ...
platformio run --target upload
make flash

# EAB auto-resumes when pause expires
# Or resume early by removing pause file:
rm /tmp/eab-session/pause.txt
```

## Usage Patterns

### Pattern 1: Daemon + File Polling
Agent runs daemon in background, reads output files.

```bash
# Start daemon
python3 -m eab --port auto --base-dir /tmp/eab-session &

# Agent reads output
cat /tmp/eab-session/latest.log

# Agent sends command
./eabctl send "AT+RST"

# Agent tails events (non-blocking)
./eabctl events -n 50 --json
```

### Pattern 2: Timed Capture
Agent runs tool for fixed duration, captures output.

```bash
# Capture 5 seconds of output
python3 read_uart.py /dev/cu.usbmodem 5 > output.txt
```

### Pattern 3: JSON CLI (Recommended)
Prefer simple CLI calls + `--json` instead of loading an MCP skill.

```bash
./eabctl status --json
./eabctl tail -n 50 --json
./eabctl send "help" --json
./eabctl send "help" --await-event --json
./eabctl wait-event --type command_sent --timeout 10 --json
./eabctl stream start --mode raw --chunk 16384 --marker "===DATA_START===" --no-patterns --truncate --json
./eabctl recv-latest --bytes 65536 --out latest.bin --json
./eabctl diagnose --json
```

## Binary Framing (Optional, Custom Firmware Only)

High‑speed streaming can use a simple binary framing format when you control
the firmware. See `PROTOCOL.md` for proposed defaults.

Stock firmware does **not** require framing and continues to work with the
standard line‑based log mode.

## Comparison with Existing Tools

| Feature | ChatDBG | MCP GDB | Embedded Agent Bridge |
|---------|---------|---------|----------------------|
| GDB integration | Yes | Yes | Yes |
| Serial/UART | No | No | **Yes** |
| OpenOCD/JTAG | No | No | **Planned** |
| ESP-IDF integration | No | No | **Yes** |
| Pattern detection | No | No | **Yes** |
| Hardware-specific helpers | No | No | **Yes** |
| Embedded-first design | No | No | **Yes** |

## Related Projects and Research

### AI-Assisted Debugging Tools

- **[ChatDBG](https://github.com/plasma-umass/ChatDBG)** - AI-powered debugging assistant for GDB/LLDB/pdb. Lets you ask "why is x null?" and the LLM autonomously controls the debugger. 75,000+ downloads.
  - Paper: [ChatDBG: Augmenting Debugging with Large Language Models](https://arxiv.org/abs/2403.16354)

- **[MCP GDB Server](https://playbooks.com/mcp/signal-slot-gdb)** - MCP protocol server for GDB debugging with Claude.

- **[LDB - LLM Debugger](https://github.com/FloridSleeves/LLMDebugger)** - Tracks runtime execution block-by-block. 98.2% accuracy on GPT-4o. (ACL 2024)

### Embedded + LLM Research

- **[Securing LLM-Generated Embedded Firmware](https://arxiv.org/abs/2509.09970)** (2025) - Three-phase methodology combining LLM firmware generation with automated security validation on FreeRTOS.

- **RepairAgent** (Bouzenia et al., 2024) - LLM-based bug repair
- **AutoSD** (Kang et al., 2025) - Automated software debugging with LLMs

### Debugging Infrastructure

- **[OpenOCD](https://openocd.org/)** - Open On-Chip Debugger
- **[pyOCD](https://pyocd.io/)** - Python debugger for ARM Cortex-M
- **[probe-rs](https://probe.rs/)** - Modern Rust debugging toolkit

### MCP Protocol

- **[Model Context Protocol](https://modelcontextprotocol.io/)** - Anthropic's protocol for tool integration
- **[MCP Debugging Guide](https://modelcontextprotocol.io/legacy/tools/debugging)**

## Roadmap

### Phase 1: Serial Bridge (Current)
- [x] Basic serial monitor daemon
- [x] Timestamped logging
- [x] Pattern detection for alerts
- [x] Command injection via file
- [x] Statistics tracking
- [x] Reconnection handling
- [x] Port pause/resume for flashing (`--pause`)
- [x] Automatic crash recovery
- [x] ESP-IDF flash integration (`eab-flash`)
- [ ] Multiple port support

### Phase 2: GDB Bridge
- [ ] GDB MI protocol wrapper
- [ ] File-based command interface
- [ ] Custom ESP32/STM32 helpers
- [ ] Breakpoint management
- [ ] Variable inspection

### Phase 3: OpenOCD Integration
- [ ] Flash operations
- [ ] Reset control
- [ ] Memory read/write
- [ ] JTAG chain discovery

### Phase 4: MCP Server
- [ ] Full MCP protocol implementation
- [ ] Tool definitions for all bridges
- [ ] Claude Code integration
- [ ] Real-time streaming

### Phase 5: Advanced Features
- [ ] Cross-tool event correlation
- [ ] Crash dump analysis
- [ ] Power profiling integration
- [ ] Logic analyzer bridge

## Installation

```bash
# Clone the repo
git clone git@github.com:circuit-synth/embedded-agent-bridge.git
cd embedded-agent-bridge

# Create virtual environment (recommended)
python3 -m venv .venv
source .venv/bin/activate

# Install dependencies
pip install pyserial

# Run serial daemon
python3 -m eab --port auto --base-dir /tmp/eab-session
```

## CLI Reference

### Daemon Commands

```bash
# Start daemon (foreground)
python3 -m eab --port auto --base-dir /tmp/eab-session

# Start with force (kill existing daemon)
python3 -m eab --port auto --force

# Check daemon status
python3 -m eab --status

# Stop running daemon
python3 -m eab --stop

# Pause daemon for flashing (releases serial port)
python3 -m eab --pause 60

# Send command to device
python3 -m eab --cmd "help"

# Reset device
python3 -m eab --reset

# View recent logs
python3 -m eab --logs 50

# View alerts
python3 -m eab --alerts 20

# Wait for pattern in log
python3 -m eab --wait-for "BOOT" --wait-timeout 30
```

### Flash Wrapper (eab-flash)

```bash
# Flash ESP-IDF project (auto-detects port)
./eab-flash

# Flash to specific port
./eab-flash -p /dev/cu.usbmodem1101

# Flash specific project directory
./eab-flash --project /path/to/project

# Flash with esptool directly
./eab-flash --esptool -p /dev/ttyUSB0 write_flash 0x0 fw.bin

# Dry run to preview commands
./eab-flash --dry-run -p /dev/cu.usbmodem1101

# Verbose output for debugging
./eab-flash --verbose -p /dev/cu.usbmodem1101

# Longer pause for large firmware
./eab-flash --pause-duration 120 -p /dev/ttyUSB0

# Show version
./eab-flash --version

# Show help
./eab-flash --help
```

## Contributing

This is a private repository under active development. Contact the maintainers for access.

## License

Proprietary - Circuit Synth
