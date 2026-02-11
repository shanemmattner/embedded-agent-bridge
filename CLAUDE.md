# Embedded Agent Bridge (EAB)

Embedded hardware daemon for serial, JTAG, and RTT. **ALWAYS use eabctl for serial/flash operations. Use JLinkBridge Python API for RTT.**

## CRITICAL RULES FOR AGENTS

1. **NEVER use esptool directly** - Use `eabctl flash` instead
2. **NEVER use pio device monitor** - Use `eabctl tail` instead
3. **NEVER access the serial port directly** - EAB manages the port
4. **Port busy errors?** Run `eabctl flash` - it handles port release automatically

## Quick Reference

```bash
# Check status (ALWAYS do this first)
eabctl status
eabctl status --json   # machine-parseable

# View serial output
eabctl tail 50
eabctl tail 50 --json  # machine-parseable

# Send command to device
eabctl send "i"

# Flash firmware (handles EVERYTHING automatically)
eabctl flash /path/to/project

# Reset device
eabctl reset
```

## Flashing Firmware

**ONLY use eabctl flash:**

```bash
# Flash ESP-IDF project (auto-detects chip, pauses daemon, flashes, resumes)
eabctl flash /path/to/esp-idf-project

# Erase flash first if corrupted
eabctl erase
eabctl flash /path/to/project
```

The flash command:
1. Automatically pauses daemon and releases the serial port
2. Detects chip type from build config
3. Flashes bootloader, partition table, and app
4. Resumes daemon and shows boot output

**If you see "port is busy" anywhere, you did something wrong. Use eabctl.**

## Fixing Boot Loops

If device shows `invalid header: 0xffffffff` or watchdog resets:

```bash
eabctl flash /path/to/working/project
```

## Monitoring Device

```bash
# Last N lines of output
eabctl tail 50

# Watch for specific pattern (blocks until found or timeout)
eabctl wait "Ready" 30

# View crash/error alerts only
eabctl alerts
eabctl alerts --json   # machine-parseable
```

## Payload Capture (Base64/WAV/etc.)

If the device outputs base64 between markers and you need a clean extract:

```bash
eabctl capture-between "===WAV_START===" "===WAV_END===" out.wav --decode-base64
```

## RTT (J-Link Real-Time Transfer)

RTT uses the Python API directly (no eabctl commands):

```python
from eab.jlink_bridge import JLinkBridge

bridge = JLinkBridge('/tmp/eab-session')
bridge.start_rtt(device='NRF5340_XXAA_APP')
# Outputs: rtt.log (cleaned text), rtt.jsonl (structured), rtt.csv (data)
bridge.stop_rtt()
```

RTT session files in `/tmp/eab-session/`:
- `rtt-raw.log` — raw JLinkRTTLogger output
- `rtt.log` — cleaned text, ANSI stripped
- `rtt.csv` — DATA key=value records as CSV
- `rtt.jsonl` — structured JSON records

Requires: J-Link Software Pack (JLinkRTTLogger must be on PATH or in /Applications/SEGGER/JLink/)

## Diagnostics

```bash
eabctl diagnose
eabctl diagnose --json
```

## Status JSON

Check `/tmp/eab-session/status.json` for:
- `connection.status`: "connected", "reconnecting", "disconnected"
- `health.status`: "healthy", "idle", "stuck", "disconnected"
- `health.idle_seconds`: Seconds since last serial activity
- `health.usb_disconnects`: Count of USB disconnect events

## Event Stream (JSONL)

Check `/tmp/eab-session/events.jsonl` for non-blocking system events:
- daemon_starting/daemon_started/daemon_stopped
- command_sent/command_result
- paused/resumed/flash_start/flash_end
- alert/crash_detected

## Pre-Flight Check

Before flashing, run preflight to verify everything is ready:

```bash
eabctl preflight
```

This checks:
- Daemon is running
- Port is detected
- Device is connected
- Health status is good

## All Commands

```
eabctl status      # Check daemon and device status
eabctl preflight   # Verify ready to flash (run before flashing!)
eabctl tail [N]    # Show last N lines (default 50)
eabctl alerts [N]  # Show last N alerts (default 20)
eabctl events [N]  # Show last N JSON events (default 50)
eabctl send <text> # Send text to device
eabctl reset       # Reset ESP32
eabctl flash <dir> # Flash ESP-IDF project
eabctl erase       # Erase entire flash
eabctl wait <pat>  # Wait for pattern in output
eabctl wait-event  # Wait for event in events.jsonl
eabctl stream ...  # High-speed data stream (data.bin)
eabctl recv ...    # Read bytes from data.bin
```

## Binary Framing (Optional)

If you can deploy custom firmware, you can use the proposed binary framing
defaults in `PROTOCOL.md` to reach high throughput. Stock firmware remains
compatible with line‑based logs.

## Troubleshooting

| Problem | Solution |
|---------|----------|
| "port is busy" | Use `eabctl flash` instead of esptool |
| No output | Run `eabctl status` then `eabctl reset` |
| Boot loop | Run `eabctl flash /path/to/working/project` |
| Daemon not running | Run `eabctl start` |
| Flash failed | Run `eabctl preflight` to diagnose |
| USB disconnected | Check cable, run `eabctl status` |

## ESPTool Wrapper (System Protection)

An esptool wrapper script is included that intercepts direct esptool calls and
redirects agents to use eabctl instead. This prevents "port busy" errors.

To enable system-wide protection, add to PATH before the real esptool:
```bash
export PATH="/path/to/embedded-agent-bridge:$PATH"
```

The wrapper will:
1. Detect if EAB daemon is managing the port
2. Block write operations that would conflict
3. Display helpful instructions pointing to eabctl
4. Pass through non-conflicting operations to real esptool

## Typical Workflow

```bash
# 1. Check status first
eabctl status

# 2. Run preflight before flashing
eabctl preflight

# 3. Flash your project
eabctl flash /path/to/project

# 4. Monitor output
eabctl tail 50
```
