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
| [stm32l4-sensor-node](stm32l4-sensor-node/) | Nucleo-L432KC | Zephyr | UART (ST-Link VCP) | ST-Link | Sensor network node |
| [mcxn947-sensor-node](mcxn947-sensor-node/) | FRDM-MCXN947 | Zephyr | UART (USB-CDC) | CMSIS-DAP | Sensor network node |
| [esp32c6-ble-gateway](esp32c6-ble-gateway/) | ESP32-C6 | ESP-IDF + NimBLE | USB Serial + BLE | USB-JTAG | BLE peripheral + UART bridge |
| [nrf5340-ble-hub](nrf5340-ble-hub/) | nRF5340 DK | Zephyr | SEGGER RTT + BLE | J-Link | BLE central + UART aggregator |

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
| stm32l4-sensor-node | `nucleo_l432kc` | `jlink` (default) |
| mcxn947-sensor-node | `frdm_mcxn947/mcxn947/cpu0` | `linkserver` |
| nrf5340-ble-hub | `nrf5340dk/nrf5340/cpuapp` | `jlink` (default) |

## Multi-Board Sensor Network Demo

A networked sensor demo showcasing EAB's multi-board monitoring. Four dev kits work together — two sensor nodes feed data through a BLE gateway to a central hub, which outputs aggregated `DATA` lines via RTT for the EAB plotter.

### Topology

```
STM32L4 ──UART──> nRF5340 <──BLE──> ESP32-C6 <──UART── MCXN947
(sensor)          (hub)              (gateway)           (sensor)
```

- **STM32L4** reads internal temp + VREFINT, sends JSON over USART1
- **MCXN947** reads ADC + button states, sends JSON over LPUART2
- **ESP32-C6** collects MCXN947 data via UART, advertises combined payload via BLE
- **nRF5340** receives STM32 via UART + ESP32 via BLE, outputs aggregated DATA via RTT

### Wiring

```
STM32 PA9  (TX) ──> nRF5340 D0/P1.01 (RX)
STM32 PA10 (RX) <── nRF5340 D1/P1.02 (TX)
MCXN947 D1 (TX) ──> ESP32-C6 GPIO4   (RX)
MCXN947 D0 (RX) <── ESP32-C6 GPIO5   (TX)
All boards share common GND
```

### Build & Flash

```bash
# Sensor nodes (Zephyr)
west build -b nucleo_l432kc examples/stm32l4-sensor-node && west flash
west build -b frdm_mcxn947/mcxn947/cpu0 examples/mcxn947-sensor-node && west flash

# BLE gateway (ESP-IDF)
cd examples/esp32c6-ble-gateway && idf.py set-target esp32c6 && idf.py build flash

# BLE hub (Zephyr)
west build -b nrf5340dk/nrf5340/cpuapp examples/nrf5340-ble-hub && west flash
```

### Monitor with EAB

```bash
# Terminal 1: STM32 console (ST-Link VCP)
eabctl tail 50

# Terminal 2: ESP32-C6 console (USB Serial)
eabctl tail 50

# Terminal 3: MCXN947 console (USB-CDC)
eabctl tail 50

# Terminal 4: nRF5340 RTT (aggregated DATA)
python3 -c "
from eab.jlink_bridge import JLinkBridge
bridge = JLinkBridge('/tmp/eab-session')
bridge.start_rtt(device='NRF5340_XXAA_APP')
"
```

The nRF5340 hub outputs `DATA` lines in the RTT plotter format:

```
DATA: stm32_temp=24.5 stm32_vref=3301 nxp_adc=1234 nxp_btn=0 esp32_heap=280000 esp32_uptime=42
```

### BLE Protocol

Custom GATT service for sensor relay:

| UUID | Type | Description |
|------|------|-------------|
| `EAB10001-0000-1000-8000-00805F9B34FB` | Service | EAB Sensor Network |
| `EAB10002-0000-1000-8000-00805F9B34FB` | Characteristic (Notify) | Sensor data JSON |
| `EAB10003-0000-1000-8000-00805F9B34FB` | Characteristic (Write) | Commands from hub |
