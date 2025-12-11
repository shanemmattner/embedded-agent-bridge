# Embedded Agent Bridge (EAB)

ESP32 serial communication daemon with agent-friendly CLI.

## Quick Start for Agents

```bash
# Check device status
~/tools/embedded-agent-bridge/eab-control status

# View serial output
~/tools/embedded-agent-bridge/eab-control tail 50

# Send command to device
~/tools/embedded-agent-bridge/eab-control send "help"

# Reset device
~/tools/embedded-agent-bridge/eab-control reset

# Flash firmware (handles everything automatically)
~/tools/embedded-agent-bridge/eab-control flash /path/to/esp-idf-project
```

## Fixing Boot Loops

If device shows `invalid header: 0xffffffff` or watchdog resets:

```bash
~/tools/embedded-agent-bridge/eab-control flash /path/to/working/project
```

Or erase and reflash:
```bash
~/tools/embedded-agent-bridge/eab-control erase
~/tools/embedded-agent-bridge/eab-control flash /path/to/project
```

## All Commands

Run `~/tools/embedded-agent-bridge/eab-control` for full help.

Key commands:
- `status` - Check daemon and device status
- `tail [N]` - Show last N lines of serial output
- `send <text>` - Send command to device
- `reset` - Reset ESP32
- `flash <dir>` - Flash ESP-IDF project (auto-detects chip)
- `erase` - Erase entire flash
- `backup [file]` - Backup flash to file
- `restore <file>` - Restore from backup

## Session Files

- `/tmp/eab-session/latest.log` - Serial output
- `/tmp/eab-session/alerts.log` - Errors/crashes
- `/tmp/eab-session/status.json` - Connection state

## Full Documentation

See `AGENT_GUIDE.md` for complete documentation.
