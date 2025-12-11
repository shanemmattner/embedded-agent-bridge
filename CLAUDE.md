# Embedded Agent Bridge (EAB)

ESP32 serial communication daemon. **ALWAYS use eab-control for ALL ESP32 operations.**

## CRITICAL RULES FOR AGENTS

1. **NEVER use esptool directly** - Use `eab-control flash` instead
2. **NEVER use pio device monitor** - Use `eab-control tail` instead
3. **NEVER access the serial port directly** - EAB manages the port
4. **Port busy errors?** Run `eab-control flash` - it handles port release automatically

## Quick Reference

```bash
# Check status (ALWAYS do this first)
~/tools/embedded-agent-bridge/eab-control status

# View serial output
~/tools/embedded-agent-bridge/eab-control tail 50

# Send command to device
~/tools/embedded-agent-bridge/eab-control send "i"

# Flash firmware (handles EVERYTHING automatically)
~/tools/embedded-agent-bridge/eab-control flash /path/to/project

# Reset device
~/tools/embedded-agent-bridge/eab-control reset
```

## Flashing Firmware

**ONLY use eab-control flash:**

```bash
# Flash ESP-IDF project (auto-detects chip, pauses daemon, flashes, resumes)
~/tools/embedded-agent-bridge/eab-control flash /path/to/esp-idf-project

# Erase flash first if corrupted
~/tools/embedded-agent-bridge/eab-control erase
~/tools/embedded-agent-bridge/eab-control flash /path/to/project
```

The flash command:
1. Automatically pauses daemon and releases the serial port
2. Detects chip type from build config
3. Flashes bootloader, partition table, and app
4. Resumes daemon and shows boot output

**If you see "port is busy" anywhere, you did something wrong. Use eab-control.**

## Fixing Boot Loops

If device shows `invalid header: 0xffffffff` or watchdog resets:

```bash
~/tools/embedded-agent-bridge/eab-control flash /path/to/working/project
```

## Monitoring Device

```bash
# Last N lines of output
~/tools/embedded-agent-bridge/eab-control tail 50

# Watch for specific pattern (blocks until found or timeout)
~/tools/embedded-agent-bridge/eab-control wait "Ready" 30

# View crash/error alerts only
~/tools/embedded-agent-bridge/eab-control alerts
```

## Status JSON

Check `/tmp/eab-session/status.json` for:
- `connection.status`: "connected", "reconnecting", "disconnected"
- `health.status`: "healthy", "idle", "stuck", "disconnected"
- `health.idle_seconds`: Seconds since last serial activity
- `health.usb_disconnects`: Count of USB disconnect events

## Pre-Flight Check

Before flashing, run preflight to verify everything is ready:

```bash
~/tools/embedded-agent-bridge/eab-control preflight
```

This checks:
- Daemon is running
- Port is detected
- Device is connected
- Health status is good

## All Commands

```
eab-control status      # Check daemon and device status
eab-control preflight   # Verify ready to flash (run before flashing!)
eab-control tail [N]    # Show last N lines (default 50)
eab-control alerts [N]  # Show last N alerts (default 20)
eab-control send <text> # Send text to device
eab-control reset       # Reset ESP32
eab-control flash <dir> # Flash ESP-IDF project
eab-control erase       # Erase entire flash
eab-control wait <pat>  # Wait for pattern in output
```

## Troubleshooting

| Problem | Solution |
|---------|----------|
| "port is busy" | Use `eab-control flash` instead of esptool |
| No output | Run `eab-control status` then `eab-control reset` |
| Boot loop | Run `eab-control flash /path/to/working/project` |
| Daemon not running | Run `eab-control start` |
| Flash failed | Run `eab-control preflight` to diagnose |
| USB disconnected | Check cable, run `eab-control status` |

## ESPTool Wrapper (System Protection)

An esptool wrapper script is included that intercepts direct esptool calls and
redirects agents to use eab-control instead. This prevents "port busy" errors.

To enable system-wide protection, add to PATH before the real esptool:
```bash
export PATH="$HOME/tools/embedded-agent-bridge:$PATH"
```

The wrapper will:
1. Detect if EAB daemon is managing the port
2. Block write operations that would conflict
3. Display helpful instructions pointing to eab-control
4. Pass through non-conflicting operations to real esptool

## Typical Workflow

```bash
# 1. Check status first
eab-control status

# 2. Run preflight before flashing
eab-control preflight

# 3. Flash your project
eab-control flash /path/to/project

# 4. Monitor output
eab-control tail 50
```
