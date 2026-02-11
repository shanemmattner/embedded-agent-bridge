# Embedded Agent Bridge (EAB) - Agent Guide

A daemon and Python API for LLM agents to interact with embedded devices (ESP32, STM32, nRF5340/Zephyr) reliably.

## Quick Reference (TL;DR)

```bash
# Check device status
eabctl status

# Machine-parseable status (for agents)
eabctl status --json

# View serial output
eabctl tail 50

# Machine-parseable tail (for agents)
eabctl tail 50 --json

# View recent system events (daemon lifecycle, pause/resume, flash, alerts)
eabctl events 50

# Send command to device
eabctl send "help"

# Start high-speed data streaming (arm on marker)
eabctl stream start --mode raw --chunk 16384 --marker "===DATA_START===" --no-patterns --truncate

# Stop high-speed streaming
eabctl stream stop

# Fetch last 64KB of streamed data
eabctl recv-latest --bytes 65536 --out latest.bin

# Reset device
eabctl reset

# Flash firmware (auto-detects chip, handles everything)
eabctl flash /path/to/project

# Erase flash (for corrupted firmware)
eabctl erase
```

## The eabctl Script

The `eabctl` script is the primary interface. It handles serial port management, daemon control, and all ESP32 operations automatically.

### All Available Commands

```
Daemon Commands:
  start       Start the daemon now
  stop        Stop the daemon
  restart     Restart the daemon
  status      Show daemon status
  diagnose    Automated health checks (add --json for agents)
  logs        Show daemon logs (stdout/stderr)
  enable      Enable auto-start at login
  disable     Disable auto-start

Port Control:
  pause [N]   Pause for N seconds (default 120) to release serial port
  resume      Resume from pause early

Device Control:
  reset       Reset the ESP32 device
  cmd <cmd>   Send special command (e.g., '!CHIP_INFO', '!BOOTLOADER')

Flashing (handles pause/resume automatically):
  flash <dir>      Flash ESP-IDF project (auto-detects chip, finds binaries)
  flash <file>     Flash single binary file
  build-flash <dir> Build ESP-IDF project and flash
  erase            Erase entire flash
  chip-info        Get chip ID and flash info
  read-mac         Read MAC address

Backup/Restore:
  backup [file] [size]  Backup flash to file (default 4MB)
  restore <file>        Restore flash from backup

Serial Communication:
  send <text>     Send text to device (e.g., 'r' to record)
  monitor         Live serial output (Ctrl+C to exit)

Log Viewing:
  tail [N]    Show last N lines from serial log (default 50)
  alerts [N]  Show last N alert lines (default 20)
  events [N]  Show last N JSON events (default 50)
  wait <pat>  Wait for log line matching pattern
  wait-event  Wait for event in events.jsonl
  capture-between <start> <end> <out> [--decode-base64]  Capture payload between markers

Data Streaming (high-speed):
  stream start|stop   Enable/disable raw data streaming to data.bin
  recv --offset N --length M [--out file] [--base64]
  recv-latest --bytes N [--out file] [--base64]
```

## Common Agent Workflows

### 1. Check if Device is Working

```bash
# Get daemon and device status
eabctl status

# View recent serial output
eabctl tail 30
```

### 2. Send Commands to Device

```bash
# Send a single character command
eabctl send "i"

# Send longer text
eabctl send "help"

# Wait for specific output pattern
eabctl wait "Ready" 30

# Wait for a system event (example: command sent)
eabctl wait-event --type command_sent --timeout 10
```

### 3. Fix Boot Loop / Corrupted Firmware

If the device is stuck in a boot loop (showing watchdog resets, "invalid header", etc.):

```bash
# Option 1: Flash a known-good ESP-IDF project
eabctl flash /path/to/working/project

# Option 2: Erase and start fresh
eabctl erase
eabctl flash /path/to/project

# Option 3: Restore from backup
eabctl restore backup.bin
```

### 4. Flash New Firmware

```bash
# Flash an ESP-IDF project (auto-detects everything)
eabctl flash /path/to/esp-idf-project

# The command will:
# 1. Auto-detect serial port from daemon
# 2. Pause daemon to release port
# 3. Find bootloader, partition table, and app binaries
# 4. Auto-detect chip type (ESP32, ESP32-S3, etc.)
# 5. Flash all components at correct addresses
# 6. Resume daemon
# 7. Show boot output
```

### 5. Build and Flash

```bash
# Build the project first, then flash
eabctl build-flash /path/to/project
```

### 6. Backup Before Risky Operations

```bash
# Create backup of current flash
eabctl backup my_backup.bin

# Later, restore if needed
eabctl restore my_backup.bin
```

### 7. Debug Connection Issues

```bash
# Check chip info
eabctl chip-info

# Read MAC address
eabctl read-mac

# Check alerts for crashes/errors
eabctl alerts 20

# Check daemon events for reconnect/pause/flash
eabctl events 20

# Run automated diagnostics (human or JSON)
eabctl diagnose
eabctl diagnose --json
```

### 8. RTT Streaming (nRF5340 / Zephyr)

RTT uses Python API (no eabctl commands yet):

```python
from eab.jlink_bridge import JLinkBridge

bridge = JLinkBridge('/tmp/eab-session')
status = bridge.start_rtt(device='NRF5340_XXAA_APP')
# Check status.running, status.num_up_channels

# Read processed output
# /tmp/eab-session/rtt.log — cleaned text
# /tmp/eab-session/rtt.jsonl — structured records
# /tmp/eab-session/rtt.csv — DATA records

bridge.stop_rtt()
```

## Event Stream (Non-Blocking IPC)

EAB emits a JSONL event stream at:

```
/tmp/eab-session/events.jsonl
```

Each line is a JSON object with:

- `type`: daemon_starting, daemon_started, command_sent, alert, paused, resumed, flash_start, flash_end, etc.
- `sequence`: monotonic counter (per daemon lifetime)
- `timestamp`: ISO 8601
- `data`: event-specific fields (command, port, etc.)

Agents can tail this file or use:

```bash
eabctl events 50
eabctl wait-event --type command_sent --timeout 10
```

## High-Speed Data Stream

When enabled, the daemon writes raw bytes to:

```
/tmp/eab-session/data.bin
```

Enable streaming (armed on marker):

```bash
eabctl stream start --mode raw --chunk 16384 --marker "===DATA_START===" --no-patterns --truncate
```

Stop streaming:

```bash
eabctl stream stop
```

Fetch recent bytes:

```bash
eabctl recv-latest --bytes 65536 --out latest.bin
```

### Compatibility Notes

- **Stock firmware**: use line‑based logs and command queue as usual.
- **Custom firmware**: optionally enable binary framing (see `PROTOCOL.md`) for maximum throughput.
```

## Extracting Base64 Payloads (WAV, etc.)

If the device prints a base64 payload between markers (e.g. `===WAV_START===` / `===WAV_END===`),
use `capture-between` to extract *clean* payload data without timestamps or daemon messages:

```bash
# Capture base64 text payload to a file
eabctl capture-between "===WAV_START===" "===WAV_END===" out.b64

# Or decode base64 directly to bytes (e.g. WAV)
eabctl capture-between "===WAV_START===" "===WAV_END===" out.wav --decode-base64
```

## Understanding Device State

### Status JSON

```bash
cat /tmp/eab-session/status.json
```

Example output:
```json
{
  "session": {
    "id": "serial_2025-12-11_08-25-03",
    "started": "2025-12-11T08:25:03",
    "uptime_seconds": 120
  },
  "connection": {
    "port": "/dev/cu.usbmodem101",
    "baud": 115200,
    "status": "connected",
    "reconnects": 0
  },
  "counters": {
    "lines_logged": 500,
    "commands_sent": 5,
    "alerts_triggered": 3
  },
  "patterns": {
    "WATCHDOG": 10,
    "BOOT": 5
  }
}
```

**Key fields:**
- `connection.status`: "connected" or "disconnected"
- `patterns.WATCHDOG`: High count indicates boot loop
- `patterns.BOOT`: High count indicates repeated reboots

### Alert Patterns

The daemon automatically detects and logs these to `alerts.log`:

| Pattern | Meaning |
|---------|---------|
| `ERROR` | ESP-IDF error log |
| `CRASH` | Guru Meditation, Backtrace, panic |
| `MEMORY` | Heap exhaustion, alloc failed |
| `WATCHDOG` | Task/interrupt watchdog triggered |
| `BOOT` | Reset reason, boot mode |
| `WIFI` | WiFi disconnection/failures |
| `BLE` | BLE errors |

### Recognizing Boot Loops

If you see these patterns, the firmware is likely corrupted:
```
invalid header: 0xffffffff
rst:0x7 (TG0WDT_SYS_RST)
rst:0x10 (RTCWDT_RTC_RST)
```

Solution: `eabctl flash /path/to/working/project`

## File Interface (Advanced)

For direct file-based interaction:

| File | Purpose |
|------|---------|
| `/tmp/eab-session/latest.log` | All serial output with timestamps |
| `/tmp/eab-session/alerts.log` | Filtered alerts (crashes, errors) |
| `/tmp/eab-session/status.json` | Connection state, counters |
| `/tmp/eab-session/cmd.txt` | Write commands here (low-level) |

### Special Commands (via cmd.txt)

```bash
# Reset device
printf '!RESET' > /tmp/eab-session/cmd.txt

# Enter bootloader
printf '!BOOTLOADER' > /tmp/eab-session/cmd.txt

# Get chip info
printf '!CHIP_INFO' > /tmp/eab-session/cmd.txt

# Erase flash
printf '!ERASE' > /tmp/eab-session/cmd.txt
```

## Daemon Management

### Start Daemon Manually

```bash
eabctl start
```

### Auto-Start at Login

```bash
eabctl enable
```

### Check Daemon Status

```bash
eabctl status
```

### View Daemon Logs

```bash
eabctl logs
```

## Troubleshooting

### "Could not get port from daemon"

The daemon isn't running or isn't connected:
```bash
eabctl start
eabctl status
```

### Device Not Responding

```bash
# Reset the device
eabctl reset

# Check for output
eabctl tail 30
```

### Flash Operation Failed

```bash
# Check if port is in use
lsof /dev/cu.usbmodem*

# Force daemon pause
eabctl pause 120

# Try flashing manually
esptool --port /dev/cu.usbmodem* write-flash 0x0 firmware.bin

# Resume daemon
eabctl resume
```

### Boot Loop After Flash

The flash may have been partial or wrong addresses:
```bash
# Erase and reflash
eabctl erase
eabctl flash /path/to/project
```

## Log Format

All logs include timestamps:
```
[HH:MM:SS.mmm] <original line from device>
[HH:MM:SS.mmm] >>> CMD: <command sent>
[HH:MM:SS.mmm] [EAB] <EAB status message>
```

Example:
```
[08:25:03.214] I (13329) RECORDER: Initialized
[08:25:04.000] >>> CMD: i
[08:25:04.100] === Audio Recorder Info ===
[08:25:25.661] [EAB] OK: Device reset
```
