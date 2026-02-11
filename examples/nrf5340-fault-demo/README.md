# nRF5340 Fault Demo

Multi-threaded Zephyr firmware with injectable Cortex-M33 faults for demonstrating `eabctl fault-analyze`.

## Threads

| Thread | Stack | Period | Purpose |
|--------|-------|--------|---------|
| sensor | 1024B | 500ms | Fake temp readings (DATA lines) |
| blinker | 512B | 1s | LED toggle + heartbeat |
| monitor | 1024B | 5s | Uptime stats |

## Shell Commands (via RTT)

```
fault null       — NULL pointer dereference  → DACCVIOL
fault divzero    — Integer divide by zero    → DIVBYZERO
fault unaligned  — Unaligned 32-bit access   → UNALIGNED
fault undef      — Undefined instruction     → UNDEFINSTR
fault overflow   — Stack overflow recursion  → STKOF
fault bus        — Bad peripheral address    → PRECISERR
```

## Build & Flash

```bash
west build -b nrf5340dk/nrf5340/cpuapp examples/nrf5340-fault-demo
west flash
```

## Demo Walkthrough

```bash
# 1. Start RTT
python3 -c "
from eab.jlink_bridge import JLinkBridge
b = JLinkBridge('/tmp/eab-session')
b.start_rtt(device='NRF5340_XXAA_APP')
"

# 2. See threads running
eabctl tail 20

# 3. Inject a fault (type into RTT shell)
#    fault null

# 4. Wait for crash
eabctl wait "FATAL ERROR" --timeout 30

# 5. Diagnose
eabctl fault-analyze --device NRF5340_XXAA_APP --json

# 6. Or with symbols
eabctl fault-analyze --device NRF5340_XXAA_APP --elf build/zephyr/zephyr.elf
```
