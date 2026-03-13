# Embedded Agent Bridge
## Giving AI Agents Real Embedded Hardware Access

*Shane Mattner — EE / Embedded Systems*
*github.com/shanemmattner/embedded-agent-bridge*

---

## The Problem (2 min)

**AI agents break on real hardware.**

Agents work in a `read → think → write → run` loop.
Embedded debugging requires *persistent interactive sessions*.

```bash
# What Claude/Cursor/Copilot tries:
$ minicom -D /dev/cu.usbmodem101       # blocks forever, no output
$ screen /dev/cu.usbmodem101 115200    # fights the port with the flasher
$ gdb firmware.elf                     # waits for interactive input, times out
$ JLinkRTTLogger -Device NRF5340_XXAA_APP  # subprocess, agent can't read it
```

**Result:** Agent hangs, wastes context tokens on escape sequences,
can't flash without killing its own monitor, loses state between tool calls.

---

## The Solution: Daemon + File Interface (3 min)

**Turn every interactive session into files + CLI commands.**

```
Agent ──eabctl──► Serial Daemon ──UART──► nRF5340 / ESP32 / STM32
  │
  ├──eabctl rtt──► JLink/probe-rs ──RTT──► Zephyr log output
  │
  ├──eabctl fault-analyze ──GDB/SWD──► Cortex-M registers
  │
  └──eabctl dwt watch ──DWT ──────────► Non-halting watchpoints
```

- Daemon **holds the port**. Agent never touches it.
- All output goes to **files**. Agent reads with `cat` or `eabctl tail`.
- Flash with `eabctl flash` → daemon auto-pauses, resumes after.
- All commands return **JSON**. No terminal noise in context.

---

## RTT — Real-Time Transfer (4 min)

**Problem:** Zephyr uses RTT (SEGGER) for logging, not UART. RTT requires a
persistent J-Link subprocess reading directly from MCU RAM over SWD.
An agent can't hold that subprocess open.

**EAB solution:**
```bash
# Agent starts the bridge once
eabctl rtt start --device NRF5340_XXAA_APP --transport jlink

# Then just reads files — forever, non-blocking
eabctl rtt tail 50 --json
cat /tmp/eab-devices/default/rtt.log
cat /tmp/eab-devices/default/rtt.jsonl  # structured events
```

**What's running right now on this nRF5340:**
```
[00:00:00.409] <inf> main: EAB BLE Test Peripheral starting...
[00:00:00.409] <inf> bt_hci_core: Identity: CA:4E:F7:DF:75:7C (random)
[00:00:00.411] <inf> main: [BLE] ADVERTISING interval=100ms
[00:00:00.411] <inf> main: EAB BLE Test Peripheral ready
```

Two transports supported:
- **jlink** — JLinkRTTLogger subprocess (J-Link Software Pack)
- **probe-rs** — Native Rust extension (works with ST-Link, CMSIS-DAP, J-Link)

---

## DWT — Non-Halting Watchpoints (4 min)

**Problem:** Normal GDB watchpoints halt the CPU.
For BLE firmware, halting = connection drops = test fails.

**ARM Cortex-M33 has 4 DWT comparators** (Data Watchpoint & Trace).
EAB programs them directly to watch memory without halting.

```bash
# Watch a variable by ELF symbol — no halt
eabctl dwt watch \
    --device NRF5340_XXAA_APP \
    --symbol conn_interval \
    --elf build/zephyr/zephyr.elf

# Streams JSONL events when value changes (~100Hz polling via J-Link)
# {"timestamp": "...", "label": "conn_interval", "old": 80, "new": 96}

# Conditional halt — only stop if value changes >20%
eabctl dwt halt \
    --device NRF5340_XXAA_APP \
    --symbol conn_interval \
    --elf zephyr.elf \
    --condition "abs(new-prev)/prev > 0.20"

# Status / clear
eabctl dwt list
eabctl dwt clear
```

**Use case:** BLE connection interval is drifting. Watch it live.
Agent detects anomaly. Halt only when the spike happens.

---

## Full JTAG / GDB Access (3 min)

**One-shot GDB commands** — no interactive session needed.

```bash
# Start OpenOCD (or use J-Link GDB server)
eabctl openocd start --chip nrf5340

# Run batch GDB commands — results go to stdout JSON
eabctl gdb \
    --chip nrf5340 \
    --cmd "monitor reset halt" \
    --cmd "info registers" \
    --cmd "bt" \
    --json

# Fault analysis — reads all Cortex-M fault registers
eabctl fault-analyze \
    --device NRF5340_XXAA_APP \
    --rtt-context 100 \
    --json
```

**Fault analyze output includes:**
- CFSR decoded → `UsageFault: DIVBYZERO` (human-readable)
- HFSR, BFAR, MMFAR
- Stacked PC → exact crash instruction address
- Last 100 RTT log lines before crash
- `ai_prompt` field — pre-formatted context for LLM root cause

**Agent workflow:** firmware crashes → EAB auto-detects crash pattern
→ triggers fault-analyze → passes `ai_prompt` to Claude → root cause in seconds.

---

## Live Demo (10 min)

**Hardware:** nRF5340 DK (Cortex-M33 app core + M33 network core)
**Firmware:** EAB BLE Test Peripheral — advertising, GATT services, RTT logging

```bash
# 1. Show daemon is running, board is live
eabctl status --json
eabctl rtt tail 20

# 2. Read BLE state via RTT
eabctl rtt tail 50 --json | python3 -c "import sys,json; ..."

# 3. DWT — watch connection interval variable live
eabctl dwt watch --device NRF5340_XXAA_APP \
    --symbol conn_interval --elf zephyr.elf

# 4. Trigger fault, watch EAB catch it
eabctl send "fault null"
eabctl alerts 10 --json
eabctl fault-analyze --device NRF5340_XXAA_APP --rtt-context 50 --json

# 5. Reset and verify clean boot
eabctl reset --chip nrf5340
eabctl rtt tail 20
```

---

## Why It Matters

| Pain point | EAB solution |
|------------|-------------|
| Agent blocks on minicom/screen | Daemon holds port, agent reads files |
| Flash kills serial monitor | `eabctl flash` auto-pauses daemon |
| RTT needs persistent subprocess | `eabctl rtt start` — then just read files |
| GDB needs interactive TTY | One-shot batch commands, JSON output |
| BLE debug → connection drops | DWT non-halting watchpoints |
| Crash → manual register decode | Auto fault-analyze + `ai_prompt` field |
| No HIL in CI | YAML regression suite, exit code 0/1 |

**Supported chips:** nRF5340, ESP32 (all variants), STM32, MCXN947, TI C2000, any UART device
**Agent integrations:** Claude Code skill, MCP server (Claude Desktop, Cursor, Copilot)

---

## Get Started

```bash
git clone https://github.com/shanemmattner/embedded-agent-bridge
cd embedded-agent-bridge
pip install -e .

# Plug in your board
eabctl start --port auto      # serial daemon
eabctl rtt start --device NRF5340_XXAA_APP  # RTT (nRF)

# That's it — your agent can now read hardware
eabctl tail 50 --json
eabctl rtt tail 50 --json
```

**github.com/shanemmattner/embedded-agent-bridge**
