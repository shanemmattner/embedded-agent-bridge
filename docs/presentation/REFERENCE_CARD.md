# Embedded Agent Bridge — Reference Card
**github.com/shanemmattner/embedded-agent-bridge**

```
pip install -e .    eabctl start --port auto    eabctl rtt start --device NRF5340_XXAA_APP
```

---

## Architecture

```
Agent (Claude / Cursor / Copilot)
  │
  ├─ eabctl ──► Serial Daemon ──UART──► Any MCU
  │               │
  │               └── /tmp/eab-devices/default/
  │                     latest.log   cmd.txt   alerts.log   events.jsonl   status.json
  │
  ├─ eabctl rtt ──► JLink/probe-rs ──SWD/RTT──► Zephyr log output
  │                                               rtt.log  rtt.jsonl  rtt.csv
  │
  ├─ eabctl fault-analyze ──GDB──► Cortex-M fault registers
  │                                 CFSR decoded + stacked PC + ai_prompt
  │
  └─ eabctl dwt watch ──DWT ──────► Non-halting variable watchpoints (4 comparators)
                                     JSONL stream, no CPU halt, BLE-safe
```

---

## Key Commands

### Daemon
```bash
eabctl start --port auto              # start (auto-detect USB serial)
eabctl start --port /dev/cu.usbmodem101
eabctl stop
eabctl status --json
eabctl diagnose --json                # full health check
```

### Read / Send
```bash
eabctl tail 50 --json                 # last 50 lines of serial output
eabctl send "kernel threads" --json   # send command to device
eabctl alerts 20 --json              # crashes / errors
eabctl events 50 --json              # event stream
```

### RTT (Zephyr / bare-metal)
```bash
eabctl rtt start --device NRF5340_XXAA_APP --transport jlink
eabctl rtt start --device STM32L476RG  --transport probe-rs
eabctl rtt tail 50 --json
eabctl rtt stop
# Output: /tmp/eab-devices/default/rtt.log  rtt.jsonl  rtt.csv
```

### DWT Non-Halting Watchpoints
```bash
# Watch by ELF symbol — streams changes, no halt
eabctl dwt watch --device NRF5340_XXAA_APP \
    --symbol conn_interval --elf zephyr.elf

# Conditional halt — stop only when value spikes >20%
eabctl dwt halt --device NRF5340_XXAA_APP \
    --symbol conn_interval --elf zephyr.elf \
    --condition "abs(new-prev)/prev > 0.20"

eabctl dwt list      # show active comparators
eabctl dwt clear     # release all
```

### Full JTAG / GDB
```bash
eabctl openocd start --chip nrf5340
eabctl gdb --chip nrf5340 --cmd "monitor reset halt" --cmd "bt" --json
eabctl openocd stop

# Flash (auto-pauses daemon, resumes after)
eabctl flash zephyr.elf --chip nrf5340
eabctl reset --chip nrf5340
eabctl chip-info --chip nrf5340
```

### Fault Analysis
```bash
# Auto-triggered on crash pattern, or run manually
eabctl fault-analyze --device NRF5340_XXAA_APP --rtt-context 100 --json
# Returns: CFSR/HFSR decoded, stacked PC, last N RTT lines, ai_prompt field
```

### Hardware-in-the-Loop Regression
```bash
eabctl regression --suite tests/hw/ --json   # run suite (exit 0=pass, 1=fail)
eabctl regression --test tests/hw/smoke.yaml
```

### Anomaly Detection
```bash
eabctl anomaly record  --device NRF5340_XXAA_APP --duration 60 --output baseline.json
eabctl anomaly compare --device NRF5340_XXAA_APP --baseline baseline.json --json
eabctl anomaly watch   --device NRF5340_XXAA_APP --metric bt_notification_interval_ms \
    --threshold 2.5sigma
```

### MCP Server (Claude Desktop / Cursor)
```bash
pip install embedded-agent-bridge[mcp]
eabmcp   # stdio transport
# Config: {"mcpServers": {"eab": {"command": "eabmcp"}}}
# Tools: get_status  read_rtt  send_command  fault_analyze
#        flash_firmware  reset_device  run_regression  get_alerts
```

---

## Session Files

| File | Contents |
|------|----------|
| `latest.log` | Timestamped serial output |
| `cmd.txt` | Command queue (daemon reads + sends) |
| `alerts.log` | Crashes, errors, watchdog resets |
| `events.jsonl` | Structured event stream |
| `status.json` | Connection + health status |
| `rtt.log` | RTT output (timestamped) |
| `rtt.jsonl` | RTT structured events |
| `rtt.csv` | RTT metrics in CSV |
| `baselines/*.json` | Anomaly detection baselines |

All files live in `/tmp/eab-devices/<device>/` (configurable with `--base-dir`)

---

## Supported Hardware

nRF5340 · ESP32 (S3/C3/C6/P4) · STM32 (H7/F4/G4/L4/N6) · MCXN947 · TI C2000 · Any UART device

**Debug probes:** J-Link · ST-Link · CMSIS-DAP · ESP USB-JTAG · XDS110

---

*All commands support `--json`. Designed for LLM agents: no TTY, no interactive sessions, no port conflicts.*
