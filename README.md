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

**Files:**
- `serial_daemon.py` - Main daemon
- `esp32_latest.log` - Captured output (agent reads this)
- `esp32_cmd.txt` - Command injection (agent writes here)
- `esp32_alerts.log` - Pattern-matched important events
- `esp32_stats.json` - Statistics and metrics

**Features:**
- Auto-detect USB serial ports
- Timestamped logging
- Pattern detection (DISCONNECT, ERROR, TIMEOUT, etc.)
- Bidirectional communication
- Statistics tracking

### 2. GDB Bridge (Planned)
Daemon that wraps GDB and exposes it via file-based interface.

**Capabilities:**
- Execute GDB commands (`bt`, `p variable`, `c`, `b main.c:50`)
- Custom hardware-aware commands (`show-i2c`, `show-gpio`)
- Parse MI protocol output into readable format
- Correlate with serial output

### 3. OpenOCD Bridge (Planned)
Interface to OpenOCD for flash/debug operations.

**Capabilities:**
- Flash firmware
- Reset target
- Read/write memory
- Control execution

### 4. ESP-IDF Integration (Planned)
Build and flash integration for ESP32 development.

**Capabilities:**
- `idf.py build`
- `idf.py flash`
- `idf.py monitor` (via serial daemon)

## Usage Patterns

### Pattern 1: Daemon + File Polling
Agent runs daemon in background, reads output files.

```bash
# Start daemon
python3 serial_daemon.py --port /dev/cu.usbmodem... &

# Agent reads output
cat esp32_latest.log

# Agent sends command
echo "AT+RST" > esp32_cmd.txt
```

### Pattern 2: Timed Capture
Agent runs tool for fixed duration, captures output.

```bash
# Capture 5 seconds of output
python3 read_uart.py /dev/cu.usbmodem 5 > output.txt
```

### Pattern 3: MCP Server (Future)
Full MCP protocol integration for Claude Code.

```json
{
  "mcpServers": {
    "embedded-bridge": {
      "command": "python3",
      "args": ["mcp_server.py"]
    }
  }
}
```

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
- [ ] Reconnection handling
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

# Install dependencies
pip install pyserial

# Run serial daemon
python3 serial_daemon.py --port /dev/cu.usbmodem...
```

## Contributing

This is a private repository under active development. Contact the maintainers for access.

## License

Proprietary - Circuit Synth
