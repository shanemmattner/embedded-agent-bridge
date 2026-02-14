# nRF5340 Fault Demo

Multi-threaded Zephyr firmware with injectable Cortex-M33 faults. Trigger a crash via button press or shell command, then diagnose it with `eabctl fault-analyze`.

## What it does

Three background threads run continuously to simulate a real application:

| Thread | Stack | Period | Purpose |
|--------|-------|--------|---------|
| sensor | 1024B | 500ms | Simulated temperature readings (DATA lines) |
| blinker | 512B | 1s | LED toggle + heartbeat |
| monitor | 1024B | 5s | Uptime stats |

## Triggering faults

### Buttons (nRF5340 DK)

| Button | Fault | CFSR/HFSR bit |
|--------|-------|---------------|
| 1 | NULL pointer dereference | DACCVIOL |
| 2 | Divide by zero | DIVBYZERO |
| 3 | Stack overflow (recursion) | STKOF |
| 4 | Invalid peripheral read | PRECISERR |

### Shell commands (via RTT channel 1)

```
fault null       — NULL pointer dereference  → DACCVIOL
fault divzero    — Integer divide by zero    → DIVBYZERO
fault unaligned  — Unaligned 32-bit access   → UNALIGNED
fault undef      — Undefined instruction     → UNDEFINSTR
fault overflow   — Stack overflow recursion  → STKOF
fault bus        — Bad peripheral address    → PRECISERR
```

## Requirements

- nRF5340 DK
- [Zephyr SDK](https://docs.zephyrproject.org/latest/develop/getting_started/)
- [J-Link Software Pack](https://www.segger.com/downloads/jlink/) (for RTT and `eabctl fault-analyze`)

## Build and flash

```bash
west build -b nrf5340dk/nrf5340/cpuapp examples/nrf5340-fault-demo
west flash
```

## Demo walkthrough

```bash
# 1. Start RTT to see thread output
python3 -c "
from eab.jlink_bridge import JLinkBridge
b = JLinkBridge('/tmp/eab-devices/default')
b.start_rtt(device='NRF5340_XXAA_APP')
"

# 2. Verify threads are running
eabctl tail 20

# 3. Trigger a fault — press Button 1 on the DK, or type into RTT shell:
#    fault null

# 4. Wait for the crash
eabctl wait "FATAL ERROR" --timeout 30

# 5. Analyze fault registers
eabctl fault-analyze --device NRF5340_XXAA_APP --json

# 6. Or with ELF symbols for better backtraces
eabctl fault-analyze --device NRF5340_XXAA_APP --elf build/zephyr/zephyr.elf
```

## Expected output

```
============================================================
CORTEX-M ANALYSIS
============================================================

FAULT REGISTERS:
  CFSR   = 0x00000002
  HFSR   = 0x40000000
  MMFAR  = 0x00000000
  BFAR   = 0x00000000
  SFSR   = 0x00000000
  SFAR   = 0x00000000

DECODED FAULTS:
  - DACCVIOL: Data access violation
  - FORCED: Forced hard fault (escalated from configurable fault)

SUGGESTIONS:
  - Fault address is 0x00000000 — likely a NULL pointer dereference
  - Hard fault was escalated from a configurable fault — check CFSR for root cause
```
