# Example Firmware

Test firmware for verifying EAB with real hardware. Each example targets a different platform, transport, and set of EAB features.

## Overview

| Example | Platform | Framework | Transport | Debug Probe | EAB Features |
|---------|----------|-----------|-----------|-------------|--------------|
| [esp32c6-test-firmware](esp32c6-test-firmware/) | ESP32-C6 | ESP-IDF | USB Serial | USB-JTAG | Serial daemon, shell, alerts |
| [stm32l4-test-firmware](stm32l4-test-firmware/) | STM32L476RG | Bare metal | UART (ST-Link VCP) | ST-Link | Serial daemon, flash |
| [nrf5340-test-firmware](nrf5340-test-firmware/) | nRF5340 DK | Zephyr | SEGGER RTT | J-Link | RTT bridge, real-time plotter |
| [nrf5340-fault-demo](nrf5340-fault-demo/) | nRF5340 DK | Zephyr | SEGGER RTT | J-Link | `fault-analyze`, RTT shell |
| [frdm-mcxn947-fault-demo](frdm-mcxn947-fault-demo/) | FRDM-MCXN947 | Zephyr | UART (USB-CDC) | OpenOCD / CMSIS-DAP | `fault-analyze`, UART shell |

## Architecture

```
┌─────────────────────────────────────────────────┐
│                   eabctl CLI                     │
├──────────┬──────────┬───────────┬───────────────┤
│  Serial  │   RTT    │   Flash   │ Fault Analyze │
│  daemon  │  bridge  │  (west,   │ (GDB + probe  │
│          │ (J-Link) │  esptool) │  abstraction) │
├──────────┼──────────┼───────────┼───────────────┤
│ ESP32-C6 │ nRF5340  │   All     │ nRF5340       │
│ STM32L4  │          │           │ MCXN947       │
│ MCXN947  │          │           │               │
└──────────┴──────────┴───────────┴───────────────┘
```

## Quick start

### Serial (ESP32-C6)

```bash
eabctl flash examples/esp32c6-test-firmware
eabctl tail 50
eabctl send "help"
```

### Serial (STM32L4)

```bash
eabctl flash examples/stm32l4-test-firmware --chip stm32l4
eabctl tail 50
```

### RTT (nRF5340)

Requires [J-Link Software Pack](https://www.segger.com/downloads/jlink/) (provides `JLinkRTTLogger`).

```bash
# Build and flash (requires Zephyr SDK + west)
west build -b nrf5340dk/nrf5340/cpuapp examples/nrf5340-test-firmware
west flash

# Start RTT bridge
python3 -c "
from eab.jlink_bridge import JLinkBridge
bridge = JLinkBridge('/tmp/eab-session')
st = bridge.start_rtt(device='NRF5340_XXAA_APP')
print(f'RTT running: {st.running}, channels: {st.num_up_channels}')
input('Press Enter to stop...')
bridge.stop_rtt()
"

# Output files:
#   /tmp/eab-session/rtt.log   — cleaned text log
#   /tmp/eab-session/rtt.csv   — DATA records as CSV
#   /tmp/eab-session/rtt.jsonl — structured JSON records
```

### Fault analysis (nRF5340 — J-Link)

```bash
west build -b nrf5340dk/nrf5340/cpuapp examples/nrf5340-fault-demo
west flash

# Trigger a fault (press Button 1 or use RTT shell: fault null)
# Then analyze via J-Link GDB:
eabctl fault-analyze --device NRF5340_XXAA_APP
```

### Fault analysis (FRDM-MCXN947 — OpenOCD)

Requires [OpenOCD](https://openocd.org/) (CMSIS-DAP support for the on-board MCU-Link probe).

```bash
west build -b frdm_mcxn947/mcxn947/cpu0 examples/frdm-mcxn947-fault-demo
west flash --runner linkserver

# Trigger a fault (press SW2 or use UART shell: fault null)
# Then analyze via OpenOCD + CMSIS-DAP:
eabctl fault-analyze --device MCXN947 --probe openocd --chip mcxn947
```

## Zephyr examples

Three of the five examples use [Zephyr RTOS](https://zephyrproject.org/). They follow the standard Zephyr application structure:

```
example-name/
├── CMakeLists.txt    # find_package(Zephyr), target_sources(app)
├── prj.conf          # Kconfig options
├── src/
│   └── main.c        # Application code
└── README.md
```

All Zephyr examples require a [Zephyr SDK](https://docs.zephyrproject.org/latest/develop/getting_started/) and `west` tool. Build from your Zephyr workspace root:

```bash
west build -b <board_target> /path/to/examples/<example>
west flash
```

### Board targets

| Example | Board target | Flash runner |
|---------|-------------|--------------|
| nrf5340-test-firmware | `nrf5340dk/nrf5340/cpuapp` | `jlink` (default) |
| nrf5340-fault-demo | `nrf5340dk/nrf5340/cpuapp` | `jlink` (default) |
| frdm-mcxn947-fault-demo | `frdm_mcxn947/mcxn947/cpu0` | `linkserver` |
