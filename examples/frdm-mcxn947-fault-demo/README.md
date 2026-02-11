# FRDM-MCXN947 Fault Demo

Multi-threaded Zephyr firmware with injectable Cortex-M33 faults for the NXP FRDM-MCXN947 board. Trigger a crash via button press or shell command, then diagnose it with `eabctl fault-analyze`.

## What it does

Three background threads run continuously to simulate a real application:

| Thread | Stack | Period | Purpose |
|--------|-------|--------|---------|
| sensor | 1024B | 500ms | Simulated temperature readings (DATA lines) |
| blinker | 512B | 1s | LED toggle + heartbeat |
| monitor | 1024B | 5s | Uptime stats |

## Triggering faults

### Buttons (FRDM-MCXN947)

| Button | Fault | CFSR/HFSR bit |
|--------|-------|---------------|
| SW2 | NULL pointer dereference | DACCVIOL |
| SW3 | Invalid peripheral read (0x5FFF0000) | PRECISERR |

### Shell commands (via UART console)

```
fault null       — NULL pointer dereference  → DACCVIOL
fault divzero    — Integer divide by zero    → DIVBYZERO
fault unaligned  — Unaligned 32-bit access   → UNALIGNED
fault undef      — Undefined instruction     → UNDEFINSTR
fault overflow   — Stack overflow recursion  → STKOF
fault bus        — Bad peripheral address    → PRECISERR
```

## Requirements

- FRDM-MCXN947 board
- [Zephyr SDK](https://docs.zephyrproject.org/latest/develop/getting_started/)
- OpenOCD (for fault analysis via CMSIS-DAP / MCU-Link on-board probe)

## Build and flash

```bash
west build -b frdm_mcxn947/mcxn947/cpu0 examples/frdm-mcxn947-fault-demo
west flash --runner linkserver
```

## Demo walkthrough

```bash
# 1. Open serial console (MCU-Link virtual COM port)
#    The board enumerates a USB-CDC serial port when connected

# 2. Trigger a fault — press SW2 on the board, or type into UART shell:
#    fault null

# 3. Analyze fault registers via OpenOCD + CMSIS-DAP
eabctl fault-analyze --device MCXN947 --probe openocd --chip mcxn947

# 4. Or with ELF symbols for better backtraces
eabctl fault-analyze --device MCXN947 --probe openocd --chip mcxn947 \
    --elf build/zephyr/zephyr.elf

# 5. JSON output for agent consumption
eabctl fault-analyze --device MCXN947 --probe openocd --chip mcxn947 --json
```

## Key differences from nRF5340 demo

| | nRF5340 DK | FRDM-MCXN947 |
|---|---|---|
| Console | SEGGER RTT | UART over USB-CDC |
| Shell | RTT channel 1 | UART shell |
| Buttons | 4 (sw0-sw3) | 2 (SW2, SW3) |
| Bus fault addr | 0x50FF0000 | 0x5FFF0000 |
| Debug probe | J-Link | OpenOCD + CMSIS-DAP |
| Board target | nrf5340dk/nrf5340/cpuapp | frdm_mcxn947/mcxn947/cpu0 |
| Flash runner | jlink | linkserver |
