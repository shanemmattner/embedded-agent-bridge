# EAB Live Demo — Presenter Guide

**Hardware:** nRF5340 DK connected via USB to Mac Studio
**Dashboard:** http://192.168.0.19:8050
**EAB plotter (WebSocket):** http://192.168.0.19:8080

---

## Before You Start

Confirm everything is running:
```bash
ps aux | grep -E "eabctl|JLink" | grep -v grep
# Should show: python -m eab (daemon) + JLinkRTTLoggerExe (RTT bridge)

ls -la /tmp/eab-devices/default/
# Should show: rtt-raw.log, latest.log, status.json, events.jsonl
```

Start dashboard (if not already running):
```bash
cd ~/Desktop/embedded-agent-bridge/docs/presentation
python demo_dashboard.py
# Open: http://192.168.0.19:8050
```

---

## Demo 1: Core EAB Workflow (5 min)
**Story:** AI agents can't hold serial ports open. EAB solves this.

### Terminal 1 — run the scripted demo
```bash
cd ~/Desktop/embedded-agent-bridge/docs/presentation
python demo_run.py
```
Press **Enter** between each step.

**What it shows:**
1. `eabctl start` — daemon grabs the serial port, holds it forever
2. `eabctl rtt start` — J-Link RTT bridge starts, Zephyr boot logs flow
3. BLE advertising — agent reads state from files, never holds any session
4. DWT watchpoint — `sensor_counter` watched without halting CPU
5. `fault null` — inject a NULL pointer dereference
6. `fault-analyze` — GDB reads CFSR/HFSR/stacked PC, generates `ai_prompt`
7. Board reset — clean boot confirmed

**Key talking points:**
- Every command returns JSON → agent-parseable, no TTY
- Files in `/tmp/eab-devices/default/` are the interface
- Flash → daemon auto-pauses, resumes after. No monitor killed.

---

## Demo 2: BLE Central + Live Data (5 min)
**Story:** When a central connects, DATA packets flow. Dashboard graphs light up.

### Terminal 1 — start the dashboard
```bash
python demo_dashboard.py
# Navigate to http://192.168.0.19:8050
```

### Terminal 2 — BLE scan (show the device advertising)
```bash
python bleak_central.py --scan
# Shows: ★ EAB-Peripheral  [AA:BB:CC:DD:EE:FF]  -45 dBm
```

### Terminal 2 — connect and stream data
```bash
python bleak_central.py
# Connects, subscribes to notifications
# DATA packets: counter=N temp=XX.XX — printed live
# Dashboard temperature graph + counter graph start updating
```

### Terminal 3 — watch RTT side-by-side
```bash
tail -f /tmp/eab-devices/default/rtt-raw.log
# Shows DATA: lines appearing in sync with bleak_central.py output
```

**Key talking points:**
- `bleak_central.py` is the BLE stack on the Mac — it's what a robot/phone would be
- RTT is the firmware side — you can see the same data in two places simultaneously
- The EAB daemon + RTT bridge run independently, they don't know about bleak
- Agent workflow: start BLE test → watch RTT for expected DATA pattern → assert

---

## Demo 3: DWT Non-Halting Watchpoint (3 min)
**Story:** GDB watchpoints halt the CPU → BLE drops. DWT doesn't.

### Terminal 1 — arm the watchpoint, stream changes
```bash
eabctl --base-dir /tmp/eab-devices/default \
  dwt watch \
  --device NRF5340_XXAA_APP \
  --symbol sensor_counter \
  --elf ~/zephyrproject/build/zephyr/zephyr.elf
# Streams JSONL when sensor_counter changes — no halt
```

### Terminal 2 — in parallel, connect BLE (so counter increments)
```bash
python bleak_central.py
# With BLE connected, sensor_counter increments with each notification
```

**Key talking points:**
- Cortex-M33 has 4 DWT comparators — hardware feature, not software polling
- ~100Hz sampling via J-Link — low latency, no CPU impact
- Use case: BLE connection interval drifting → watch conn_interval live
- Alternative: `eabctl dwt halt --condition "abs(new-prev)/prev > 0.20"` — halt only on >20% spike

---

## Demo 4: EAB Plotter — WebSocket Real-Time Chart (bonus, 2 min)
**Story:** EAB has a built-in uPlot WebSocket plotter for raw RTT metrics.

### Terminal 1
```bash
cd ~/Desktop/embedded-agent-bridge/docs/presentation
python start_plotter.py
# Open: http://192.168.0.19:8080
```
*Requires BLE central connected for DATA: lines to appear in the chart.*

---

## If Things Go Wrong

### RTT log is empty / stale
```bash
eabctl --base-dir /tmp/eab-devices/default rtt stop
sleep 1
eabctl --base-dir /tmp/eab-devices/default rtt start --device NRF5340_XXAA_APP --transport jlink
tail -f /tmp/eab-devices/default/rtt-raw.log
```

### Board not responding
```bash
/Applications/SEGGER/JLink_V918/JLinkExe -device NRF5340_XXAA_APP -if SWD -speed 4000 -autoconnect 1 -CommanderScript /dev/stdin <<'EOF'
r
g
exit
EOF
```

### Daemon not running
```bash
eabctl --base-dir /tmp/eab-devices/default start \
  --port /dev/cu.usbmodem0010500636591
```

### BLE not found by bleak
```bash
# Check nRF is advertising:
eabctl --base-dir /tmp/eab-devices/default rtt tail 5
# Should show: [BLE] ADVERTISING interval=100ms

# If not, reset the board:
eabctl --base-dir /tmp/eab-devices/default reset --chip nrf5340
```

---

## Key URLs
| What | URL |
|------|-----|
| Plotly Dash dashboard | http://192.168.0.19:8050 |
| EAB uPlot plotter | http://192.168.0.19:8080 |
| Session dir | /tmp/eab-devices/default/ |
| GitHub | github.com/shanemmattner/embedded-agent-bridge |

## Key Files
| File | Contents |
|------|----------|
| `rtt-raw.log` | Raw RTT from JLinkRTTLogger |
| `latest.log` | Serial UART output |
| `alerts.log` | Crashes, errors |
| `events.jsonl` | Structured event stream |
| `status.json` | Daemon health |
| `rtt.jsonl` | Parsed RTT events |
