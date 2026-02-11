# EAB RTT Plotter — Agent Guide

## Architecture

```
┌─────────────┐     ┌──────────────────┐     ┌──────────────┐
│  nRF5340    │◄───►│ JLinkGDBServer   │     │  Browser     │
│  (target)   │     │  :2331 (GDB)     │     │  :8080 (WS)  │
└─────────────┘     │  :2332 (SWO)     │     └──────┬───────┘
                    │  :2333 (Telnet)  │            │
                    └──────┬───────────┘            │
                           │                        │
                    ┌──────▼───────────┐     ┌──────▼───────┐
                    │ JLinkRTTClient   │     │ plotter      │
                    │  → rtt.log       │     │ server.py    │
                    │  → stdout:19021  │────►│  :8080       │
                    └──────────────────┘     └──────────────┘
```

### Port Map

| Port  | Service              | Protocol |
|-------|----------------------|----------|
| 2331  | JLinkGDBServer GDB   | GDB RSP  |
| 2332  | JLinkGDBServer SWO   | Raw      |
| 2333  | JLinkGDBServer Telnet| Telnet   |
| 19021 | JLinkRTTClient       | Telnet   |
| 8080  | Plotter HTTP + WS    | HTTP/WS  |

## Quick Start

```bash
# Direct Telnet mode (default, recommended)
eabctl rtt plot

# File-tail fallback (pre-recorded logs, SWO, etc.)
eabctl rtt plot --log-path /tmp/eab-session/rtt.log

# Custom ports
eabctl rtt plot --port 9090 --telnet-port 19021
```

## "No Data in Plotter" Diagnostic Flowchart

```
1. Is the browser connected?
   → Check top-right badge: "connected" (green) vs "disconnected" (red)
   → If disconnected: Is the plotter server running? Check terminal.

2. Is there a status banner?
   → "GDB server died" → GDB server crashed. Check step 3.
   → "RTT Telnet connect failed" → RTT Client not running. Check step 4.

3. Is GDB server running?
   → eabctl jlink gdb-status
   → If not running: eabctl jlink gdb-start --device NRF5340_XXAA_APP
   → Health monitor will attempt auto-restart if base_dir was provided.

4. Is RTT Client running?
   → eabctl rtt status
   → If not running: eabctl rtt start --device NRF5340_XXAA_APP
   → RTT Client connects to GDB server, so GDB must be up first.

5. Is the target outputting DATA: lines?
   → eabctl rtt tail -n 20
   → If no DATA: lines: firmware isn't printing RTT data.
   → Format: DATA: key1=1.23 key2=4.56

6. Still nothing?
   → Kill everything and restart:
     eabctl rtt stop
     eabctl jlink gdb-stop
     eabctl rtt start --device NRF5340_XXAA_APP
     eabctl rtt plot
```

## Common Failure Modes

| Symptom | Root Cause | Fix |
|---------|-----------|-----|
| Browser shows "disconnected" | Plotter server not running | Start `eabctl rtt plot` |
| "RTT Telnet connect failed" in banner | JLinkRTTClient not running or crashed | `eabctl rtt start --device ...` |
| "GDB server died" in banner | JLinkGDBServer crashed | Auto-restarts if base_dir set; else `eabctl jlink gdb-start` |
| Connected but 0/s data rate | Target not printing DATA: lines | Check firmware RTT output |
| Data appears then stops | GDB server died mid-stream | Check banner; health monitor handles this |
| Buffer grew, plotter froze (old bug) | No-newline data filled buffer | Fixed: 64KB buffer cap with discard |

## Key Insight

**GDB server is the critical dependency — check it first.**

The data flow chain is: Target → GDBServer → RTTClient → Plotter.
If GDB server dies, everything downstream goes silent. The health monitor
(active in Telnet mode with base_dir) checks every 5s and attempts auto-restart.
