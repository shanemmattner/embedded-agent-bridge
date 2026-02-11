# ESP32-C6 Test Firmware (Serial)

Interactive test firmware for the EAB serial daemon. Exercises all serial monitoring features.

## What it does

- Periodic heartbeat with uptime and heap stats
- Interactive command shell over USB Serial/JTAG
- Simulated crash and error patterns for alert testing
- JSON status reporting

## Commands

| Command | Description |
|---------|-------------|
| `help` | Show available commands |
| `status` | Print device status as JSON |
| `info` | Print chip info |
| `crash` | Simulate a crash pattern (triggers EAB alerts) |
| `error` | Simulate error/warning logs |
| `echo <text>` | Echo text back |
| `reboot` | Restart device |

## Requirements

- ESP32-C6 dev board (e.g., ESP32-C6-DevKitC)
- ESP-IDF v5.x

## Build and flash

```bash
# Via EAB (recommended)
eabctl flash examples/esp32c6-test-firmware

# Or directly with ESP-IDF
cd examples/esp32c6-test-firmware
idf.py set-target esp32c6
idf.py build flash monitor
```

## Use with EAB

```bash
eabctl start              # Start serial daemon
eabctl tail 50            # View output
eabctl send "status"      # Send command
eabctl send "crash"       # Trigger alert pattern
eabctl alerts             # View detected alerts
```
