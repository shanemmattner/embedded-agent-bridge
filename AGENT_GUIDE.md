# Embedded Agent Bridge (EAB) - Agent Guide

A file-based interface for LLM agents to interact with ESP32 devices reliably.

## Quick Start

```bash
# Start the daemon (auto-detects ESP32)
cd /tmp/embedded-agent-bridge
python3 -m eab --port auto --base-dir /tmp/eab-session
```

## File Interface

All interaction happens through files in the base directory:

| File | Read/Write | Purpose |
|------|------------|---------|
| `latest.log` | Read | All serial output with timestamps |
| `alerts.log` | Read | Filtered alerts (crashes, errors, boot events) |
| `status.json` | Read | Connection state, counters, health |
| `cmd.txt` | Write | Send commands to device |

## Reading Device Output

### Check Recent Output
```bash
tail -50 /tmp/eab-session/latest.log
```

### Check for Errors/Crashes
```bash
cat /tmp/eab-session/alerts.log
```

### Check Connection Status
```bash
cat /tmp/eab-session/status.json
```

Example status.json:
```json
{
  "session": {
    "id": "serial_2025-12-11_08-25-03",
    "started": "2025-12-11T08:25:03",
    "uptime_seconds": 120
  },
  "connection": {
    "port": "/dev/cu.usbmodem5B140841231",
    "baud": 115200,
    "status": "connected",
    "reconnects": 0
  },
  "counters": {
    "lines_logged": 500,
    "bytes_received": 35000,
    "commands_sent": 5,
    "alerts_triggered": 3
  },
  "patterns": {
    "MEMORY": 10,
    "BOOT": 1
  }
}
```

## Sending Commands

### Regular Commands (sent to device)
```bash
# Send a command to the device's serial console
printf 'help' > /tmp/eab-session/cmd.txt

# Send multiple commands
printf 'status\nmem' > /tmp/eab-session/cmd.txt
```

### Special Commands (handled by EAB)

Special commands start with `!` and are processed by EAB, not sent to device:

```bash
# Reset the ESP32 (via DTR/RTS)
printf '!RESET' > /tmp/eab-session/cmd.txt

# Soft reset
printf '!RESET:soft_reset' > /tmp/eab-session/cmd.txt

# Enter bootloader mode
printf '!BOOTLOADER' > /tmp/eab-session/cmd.txt

# Get chip info via esptool
printf '!CHIP_INFO' > /tmp/eab-session/cmd.txt

# Flash firmware
printf '!FLASH:/path/to/firmware.bin' > /tmp/eab-session/cmd.txt

# Erase flash
printf '!ERASE' > /tmp/eab-session/cmd.txt
```

## Alert Patterns

EAB automatically detects and logs these patterns to `alerts.log`:

| Pattern | Meaning |
|---------|---------|
| `ERROR` | ESP-IDF error log (E (timestamp)) |
| `CRASH` | Guru Meditation, Backtrace, panic |
| `MEMORY` | Heap info, out of memory, alloc failed |
| `WATCHDOG` | Task watchdog, interrupt watchdog |
| `BOOT` | Reset reason, boot mode |
| `WIFI` | WiFi disconnection, failures |
| `BLE` | BLE errors |

## Automatic Recovery

EAB monitors for crashes and can automatically recover:

1. **Crash Detection**: Guru Meditation, panics, watchdog triggers
2. **Boot Loop Detection**: Too many reboots in short time
3. **Stuck Detection**: No output for 2+ minutes
4. **Auto Recovery**: Resets chip to restore operation

## Best Practices for Agents

### 1. Always Check Status First
```bash
# Before sending commands, verify connection
cat /tmp/eab-session/status.json | grep '"status"'
```

### 2. Wait for Command Results
```bash
# Send command
printf 'mem' > /tmp/eab-session/cmd.txt
# Wait a moment
sleep 1
# Check output
tail -20 /tmp/eab-session/latest.log
```

### 3. Monitor for Crashes
```bash
# Check if any crashes occurred
grep -i "crash\|panic\|guru" /tmp/eab-session/alerts.log
```

### 4. Reset if Stuck
```bash
# If device seems unresponsive
printf '!RESET' > /tmp/eab-session/cmd.txt
sleep 3
tail -30 /tmp/eab-session/latest.log
```

### 5. Use grep for Specific Output
```bash
# Find specific log entries
grep "wifi" /tmp/eab-session/latest.log
grep "heap" /tmp/eab-session/latest.log
```

## Troubleshooting

### Device Not Found
```bash
# List available ports
python3 -m eab --list
```

### Port In Use
EAB uses file locking. Check for other processes:
```bash
lsof /dev/cu.usbmodem*
```

### Device Stuck in Bootloader
```bash
printf '!RESET' > /tmp/eab-session/cmd.txt
```

### No Output After Flash
```bash
# Reset after flashing
printf '!RESET' > /tmp/eab-session/cmd.txt
sleep 3
tail -50 /tmp/eab-session/latest.log
```

## Command Line Options

```bash
python3 -m eab [options]

Options:
  --port, -p      Serial port (default: auto)
  --baud, -b      Baud rate (default: 115200)
  --base-dir, -d  Directory for log files (default: /var/run/eab/serial)
  --list, -l      List available serial ports
```

## Example Agent Workflow

```bash
# 1. Start monitoring (in background or separate terminal)
cd /tmp/embedded-agent-bridge
python3 -m eab --port auto --base-dir /tmp/eab-session &

# 2. Wait for connection
sleep 3

# 3. Verify connected
cat /tmp/eab-session/status.json | grep status

# 4. Send a command
printf 'help' > /tmp/eab-session/cmd.txt
sleep 1

# 5. Read response
tail -30 /tmp/eab-session/latest.log

# 6. Check for any errors
cat /tmp/eab-session/alerts.log

# 7. If needed, reset device
printf '!RESET' > /tmp/eab-session/cmd.txt

# 8. Flash new firmware
printf '!FLASH:/path/to/firmware.bin' > /tmp/eab-session/cmd.txt
sleep 30
tail -50 /tmp/eab-session/latest.log
```

## Log Format

Logs use grep-friendly format with timestamps:

```
[HH:MM:SS.mmm] <original line from device>
[HH:MM:SS.mmm] >>> CMD: <command sent>
[HH:MM:SS.mmm] [EAB] <EAB status message>
```

Example:
```
[08:25:03.214] I (13329) audio_rec: VAD started
[08:25:04.000] >>> CMD: help
[08:25:04.100] Available commands:
[08:25:25.661] [EAB] OK: Device reset
[08:25:25.683] rst:0x1 (POWERON),boot:0x8 (SPI_FAST_FLASH_BOOT)
```
