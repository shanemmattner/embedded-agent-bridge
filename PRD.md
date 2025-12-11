# Product Requirements Document: Embedded Agent Bridge

**Version:** 1.0
**Date:** 2025-12-11
**Status:** Draft

## Executive Summary

Embedded Agent Bridge is a lightweight, reliable daemon system that enables AI agents (Claude Code, GPT, etc.) to interact with microcontrollers through file-based interfaces. The system prioritizes reliability, simplicity, and comprehensive logging to make embedded debugging accessible to LLMs without complex protocol implementations.

### Core Philosophy

> **"Fire and forget reliability with session-level logging that captures everything."**

The daemon should be something you start once and trust completely. It handles reconnection, error recovery, and logging automatically. The LLM interacts through simple file reads/writes, never worrying about serial port management, buffer overflows, or connection state.

## Problem Statement

### Current Pain Points

1. **Serial port fragility**: Direct serial access from scripts is unreliable. Ports disconnect, buffers overflow, multiple processes conflict.

2. **LLM context pollution**: Streaming serial output directly to an LLM wastes context on noise. Important events get buried.

3. **No persistent history**: When debugging, you often need "what happened 5 minutes ago?" but serial output is gone.

4. **Bidirectional complexity**: Sending commands while reading output requires careful coordination that's easy to break.

5. **No correlation**: Events from serial, GDB, and other tools aren't correlated. Hard to answer "what was the device doing when GDB hit this breakpoint?"

### What Existing Tools Miss

| Tool | Strength | Gap |
|------|----------|-----|
| **ChatDBG** | LLM controls debugger | No embedded/serial focus |
| **MCP GDB Server** | MCP protocol | No serial, no embedded helpers |
| **ESP-IDF Monitor** | Good for humans | Not agent-friendly |
| **pySerial scripts** | Simple | No reliability, no logging |

## Target Users

1. **AI Agents** (Primary): Claude Code, custom LLM agents, automation scripts
2. **Embedded Developers**: Using AI assistants for debugging
3. **CI/CD Systems**: Automated hardware testing

## Requirements

### Core Requirements

#### R1: Reliability First

| ID | Requirement | Priority |
|----|-------------|----------|
| R1.1 | Daemon must auto-reconnect on port disconnect | P0 |
| R1.2 | Daemon must handle USB replug gracefully | P0 |
| R1.3 | Daemon must never crash on malformed serial data | P0 |
| R1.4 | Daemon must survive for days without intervention | P0 |
| R1.5 | Memory usage must stay constant (no leaks) | P0 |
| R1.6 | CPU usage < 1% when idle | P1 |

#### R2: Session Logging

| ID | Requirement | Priority |
|----|-------------|----------|
| R2.1 | All serial data logged with millisecond timestamps | P0 |
| R2.2 | Logs persisted to disk immediately (no buffering loss) | P0 |
| R2.3 | Session logs named with start timestamp | P0 |
| R2.4 | Configurable log rotation (size or time based) | P1 |
| R2.5 | Compressed archive of old sessions | P2 |
| R2.6 | Searchable log format (grep-friendly) | P0 |

#### R3: Agent Interface

| ID | Requirement | Priority |
|----|-------------|----------|
| R3.1 | Read current output via single file read | P0 |
| R3.2 | Send commands via single file write | P0 |
| R3.3 | Get statistics via JSON file | P0 |
| R3.4 | Important events in separate alerts file | P0 |
| R3.5 | Command acknowledgment with echo | P1 |
| R3.6 | Support for binary data (hex encoding) | P2 |

#### R4: Pattern Detection

| ID | Requirement | Priority |
|----|-------------|----------|
| R4.1 | Configurable alert patterns (regex) | P0 |
| R4.2 | Built-in patterns: ERROR, FAIL, DISCONNECT, TIMEOUT, CRASH, panic, assert | P0 |
| R4.3 | Pattern matches logged to separate alerts file | P0 |
| R4.4 | Pattern count statistics | P1 |
| R4.5 | Configurable actions on pattern match | P2 |

#### R8: Testability

| ID | Requirement | Priority |
|----|-------------|----------|
| R8.1 | All core functions must be unit testable without hardware | P0 |
| R8.2 | Serial port abstraction layer for mock injection | P0 |
| R8.3 | File system abstraction for testing file operations | P0 |
| R8.4 | Test coverage > 80% for core daemon logic | P0 |
| R8.5 | Integration tests with mock serial port | P1 |
| R8.6 | Stress tests for reconnection logic | P1 |
| R8.7 | Memory leak detection in test suite | P2 |

### Development Methodology

**Test-First Development (TDD)**

All features must be developed using test-first methodology:

1. **Write failing test first** that defines expected behavior
2. **Implement minimum code** to make the test pass
3. **Refactor** while keeping tests green
4. **Commit** test and implementation together

**Testability Architecture**

The daemon must be designed for testability from the start:

```python
# Bad: Hard-coded dependencies (untestable)
class SerialDaemon:
    def __init__(self):
        self.serial = serial.Serial("/dev/ttyUSB0", 115200)

# Good: Dependency injection (testable)
class SerialDaemon:
    def __init__(self, serial_port: SerialPortInterface, file_system: FileSystemInterface):
        self.serial = serial_port
        self.fs = file_system
```

**Mock Interfaces**

| Component | Interface | Mock |
|-----------|-----------|------|
| Serial port | `SerialPortInterface` | `MockSerialPort` |
| File system | `FileSystemInterface` | `MockFileSystem` |
| Time/Clock | `ClockInterface` | `MockClock` |
| Logging | `LoggerInterface` | `MockLogger` |

**Test Categories**

| Category | Scope | Hardware Required |
|----------|-------|-------------------|
| Unit tests | Individual functions | No |
| Integration tests | Component interaction | No (mocks) |
| System tests | Full daemon behavior | No (mocks) |
| Hardware tests | Real device interaction | Yes |

### Extended Requirements

#### R5: Multi-Tool Correlation (Phase 2)

| ID | Requirement | Priority |
|----|-------------|----------|
| R5.1 | Common timestamp format across all bridges | P1 |
| R5.2 | Unified event log combining serial + GDB + OpenOCD | P2 |
| R5.3 | "What was happening at timestamp X?" query | P2 |

#### R6: GDB Bridge (Phase 2)

| ID | Requirement | Priority |
|----|-------------|----------|
| R6.1 | GDB MI protocol wrapper | P1 |
| R6.2 | Command file interface (same pattern as serial) | P1 |
| R6.3 | Hardware-specific helpers (show-gpio, show-i2c) | P1 |
| R6.4 | Breakpoint management | P2 |
| R6.5 | Core dump analysis | P2 |

#### R7: OpenOCD Bridge (Phase 3)

| ID | Requirement | Priority |
|----|-------------|----------|
| R7.1 | Flash operations | P2 |
| R7.2 | Reset control | P2 |
| R7.3 | Memory read/write | P2 |

## Architecture

### File-Based Interface

```
/var/run/eab/                    # Runtime directory
├── serial/
│   ├── config.json              # Port, baud, patterns config
│   ├── status.json              # Connection state, uptime
│   ├── latest.log               # Current session log (append)
│   ├── cmd.txt                  # Command input (write to send)
│   ├── alerts.log               # Pattern-matched events only
│   └── stats.json               # Counters, metrics
├── gdb/                         # Same pattern
│   ├── config.json
│   ├── status.json
│   ├── output.log
│   ├── cmd.txt
│   └── stats.json
└── sessions/                    # Historical logs
    ├── serial_2025-12-11_01-30-00.log.gz
    ├── serial_2025-12-11_08-45-00.log.gz
    └── ...
```

### Daemon Lifecycle

```
                    ┌─────────────────┐
                    │     START       │
                    └────────┬────────┘
                             │
                    ┌────────▼────────┐
                    │  Load Config    │
                    └────────┬────────┘
                             │
              ┌──────────────▼──────────────┐
              │      Find/Connect Port      │◄──────┐
              └──────────────┬──────────────┘       │
                             │                      │
                    ┌────────▼────────┐             │
                    │  Start Session  │             │
                    │  (new log file) │             │
                    └────────┬────────┘             │
                             │                      │
         ┌───────────────────▼───────────────────┐  │
         │              MAIN LOOP                │  │
         │  ┌─────────────────────────────────┐  │  │
         │  │ 1. Read serial data             │  │  │
         │  │ 2. Timestamp and log            │  │  │
         │  │ 3. Check patterns → alerts      │  │  │
         │  │ 4. Check cmd.txt → send         │  │  │
         │  │ 5. Update stats                 │  │  │
         │  └─────────────────────────────────┘  │  │
         └───────────────────┬───────────────────┘  │
                             │                      │
                    ┌────────▼────────┐             │
                    │  Disconnect?    ├─────────────┘
                    │  (auto-retry)   │  Yes, wait & retry
                    └────────┬────────┘
                             │ No (SIGTERM)
                    ┌────────▼────────┐
                    │  Clean Shutdown │
                    │  Archive logs   │
                    └─────────────────┘
```

### Log Format

```
# Session header
================================================================================
SESSION: serial_2025-12-11_01-30-00
PORT: /dev/cu.usbmodem5B140841231
BAUD: 115200
STARTED: 2025-12-11T01:30:00.000000
================================================================================

# Log entries (grep-friendly, parseable)
[01:30:00.123] I (12345) MAIN: Starting application
[01:30:00.456] I (12346) BLE: Initializing NimBLE
[01:30:01.789] I (12789) BLE: Advertising started
[01:30:15.234] >>> CMD: AT+RST                           # Commands marked with >>>
[01:30:15.567] OK
[01:30:45.890] E (45890) BLE: Connection timeout         # Errors easily grep-able
[01:30:45.891] !!! ALERT [TIMEOUT]: E (45890) BLE: Connection timeout

# Session footer
================================================================================
SESSION ENDED: 2025-12-11_02-45-00
DURATION: 1h 15m 00s
LINES LOGGED: 12,345
ALERTS: 3
COMMANDS SENT: 7
================================================================================
```

### Stats JSON

```json
{
  "session": {
    "id": "serial_2025-12-11_01-30-00",
    "started": "2025-12-11T01:30:00.000000",
    "uptime_seconds": 4500
  },
  "connection": {
    "port": "/dev/cu.usbmodem5B140841231",
    "baud": 115200,
    "status": "connected",
    "reconnects": 0
  },
  "counters": {
    "lines_logged": 12345,
    "bytes_received": 567890,
    "commands_sent": 7,
    "alerts_triggered": 3
  },
  "patterns": {
    "ERROR": 2,
    "TIMEOUT": 1,
    "DISCONNECT": 0,
    "CRASH": 0
  },
  "last_updated": "2025-12-11T02:45:00.000000"
}
```

## Agent Interaction Examples

### Example 1: Read Latest Output

```python
# Agent simply reads the log file
output = read_file("/var/run/eab/serial/latest.log", last=100)
```

### Example 2: Send Command

```python
# Agent writes to command file
write_file("/var/run/eab/serial/cmd.txt", "AT+RST\n")
# Daemon picks it up within 100ms, sends to device, logs response
```

### Example 3: Check for Problems

```python
# Agent reads alerts file for important events only
alerts = read_file("/var/run/eab/serial/alerts.log")
if "DISCONNECT" in alerts:
    # Handle disconnect
```

### Example 4: Get Statistics

```python
# Agent reads stats for metrics
stats = json.loads(read_file("/var/run/eab/serial/stats.json"))
print(f"Uptime: {stats['session']['uptime_seconds']}s")
print(f"Reconnects: {stats['connection']['reconnects']}")
```

## Implementation Plan

### Phase 1: Rock-Solid Serial Daemon (Week 1-2)

1. **Refactor existing daemon**
   - Add auto-reconnection
   - Add session-based logging
   - Add log rotation
   - Add proper signal handling

2. **Test reliability**
   - 24-hour stress test
   - USB disconnect/reconnect
   - High-speed data bursts
   - Memory leak check

3. **Documentation**
   - Usage examples
   - Configuration reference
   - Troubleshooting guide

### Phase 2: GDB Bridge (Week 3-4)

1. **GDB MI protocol wrapper**
2. **Same file interface pattern**
3. **ESP32/STM32 hardware helpers**
4. **Correlation with serial logs**

### Phase 3: Integration & Polish (Week 5-6)

1. **Unified installer**
2. **Systemd service files**
3. **MCP server wrapper (optional)**
4. **CI/CD examples**

## Success Metrics

1. **Reliability**: 99.9% uptime over 7-day test
2. **Performance**: < 1% CPU, < 20MB RAM
3. **Latency**: Command → device < 100ms
4. **Adoption**: Used in 3+ real debugging sessions

## Risks & Mitigations

| Risk | Impact | Mitigation |
|------|--------|------------|
| Serial port permissions on Linux | Medium | Document udev rules |
| macOS security restrictions | Medium | Document entitlements |
| Log disk space exhaustion | Medium | Rotation + alerts |
| Race conditions on file access | Low | Atomic writes, file locking |

## Open Questions

1. Should we support Windows? (Complexity vs market)
2. Binary protocol support (Modbus, proprietary)?
3. Multiple simultaneous serial ports?
4. Web UI for log viewing?

## References

### Related Projects
- [ChatDBG](https://github.com/plasma-umass/ChatDBG) - AI debugging for GDB/LLDB
- [MCP GDB Server](https://playbooks.com/mcp/signal-slot-gdb) - MCP protocol for GDB
- [LDB Debugger](https://github.com/FloridSleeves/LLMDebugger) - LLM runtime debugging

### Research Papers
- [ChatDBG: Augmenting Debugging with LLMs](https://arxiv.org/abs/2403.16354)
- [Securing LLM-Generated Embedded Firmware](https://arxiv.org/abs/2509.09970)

### Standards
- [Model Context Protocol](https://modelcontextprotocol.io/)
- [GDB MI Protocol](https://sourceware.org/gdb/current/onlinedocs/gdb.html/GDB_002fMI.html)
