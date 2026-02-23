# USB Port Mapping — Apple Silicon Mac

Definitive mapping of USB serial ports to dev boards. macOS names `/dev/cu.usbmodem*` ports based on either the USB **serial number** or the **locationID** (physical USB port). Ports with serial-based names are stable across re-enumeration. Location-based names change if you move the cable to a different port.

## Current Mapping (Feb 2026)

| Device | Port | Naming Basis | USB Serial | VID:PID | USB Location |
|--------|------|-------------|------------|---------|-------------|
| **ESP32-C6** | `/dev/cu.usbmodem101` | locationID | `F0:F5:BD:01:88:2C` | `303a:1001` | `0x00100000` (direct) |
| **STM32L4** (STLINK_V3 VCP) | `/dev/cu.usbmodem1102` | locationID | `004F00463234510333353533` | `0483:3754` | `0x01100000` (direct) |
| **ESP32-P4** | `/dev/cu.usbmodem83101` | locationID | `60:55:F9:FA:FF:19` | `303a:1001` | `0x08310000` (via USB hub) |
| **STM32-N6** (STLink V2) | `/dev/cu.usbmodem83403` | locationID | `066EFF494851877267042838` | `0483:374b` | `0x08340000` (via USB hub) |
| **nRF5340** (J-Link) | `/dev/cu.usbmodem0010500636593` | serial | `001050063659` | `1366:1061` | `0x08330000` (via USB hub) |
| **MCXN947** (MCU-LINK) | `/dev/cu.usbmodemI2WZW2OTY3RUW3` | serial | `I2WZW2OTY3RUW` | `1fc9:0143` | `0x02100000` (direct) |
| **C2000** (XDS110) | `/dev/cu.usbmodemCL3910781` | serial | `CL391078` | `0451:bef3` | `0x03100000` (direct) |
| **ESP32-S3** (CH340) | `/dev/cu.usbmodem5B140925971` | serial | `5B14092597` | `1a86:55d3` | `0x08320000` (via USB hub) |

## How macOS Names USB Serial Ports

macOS creates `/dev/cu.usbmodem<HINT><INTERFACE>` where:

- **HINT** = USB serial number (if device provides one with alphanumeric chars), OR
- **HINT** = locationID hex digits (if serial is MAC-address format like `F0:F5:BD:...`)
- **INTERFACE** = USB interface number (1, 3, 4, etc.)

### Stable ports (serial-based names)
These survive re-enumeration — the name comes from the device serial burned into hardware:
- `cu.usbmodem0010500636593` — J-Link serial `001050063659` + interface 3
- `cu.usbmodemI2WZW2OTY3RUW3` — MCU-LINK serial + interface 3
- `cu.usbmodemCL3910781` — XDS110 serial + interface 1
- `cu.usbmodem5B140925971` — CH340 serial + interface 1

### Unstable ports (location-based names)
These change if you move the USB cable to a different physical port:
- `cu.usbmodem101` — ESP32-C6 (locationID `0x00100000`, interface 1)
- `cu.usbmodem1102` — STM32L4 STLINK_V3 (locationID `0x01100000`, interface 2)
- `cu.usbmodem83101` — ESP32-P4 (locationID `0x08310000` via hub, interface 1)
- `cu.usbmodem83403` — STM32-N6 STLink V2 (locationID `0x08340000` via hub, interface 3)

## Identifying Boards After Re-Enumeration

If ports shift (e.g., after replug), use this to re-identify:

```bash
# Quick: list all USB devices with serial numbers
ioreg -p IOUSB -l -w0 | grep -E '"USB (Serial Number|Product Name)"' | paste - -

# Map locationID to port name (locationID hex digits → port name digits)
# 0x00100000 → 101
# 0x01100000 → 1102
# 0x08310000 → 83101
# 0x08340000 → 83403

# Multi-probe disambiguation (ESP32-C6 and ESP32-P4 share VID:PID 303a:1001)
# ALWAYS use `adapter serial <SERIAL>` with OpenOCD to target the right board
```

## ESP32 Multi-Probe Disambiguation

ESP32-C6 and ESP32-P4 both use VID:PID `303a:1001`. OpenOCD will grab whichever it finds first unless you specify:

```bash
# ESP32-C6
openocd -f board/esp32c6-builtin.cfg -c "adapter serial F0:F5:BD:01:88:2C" ...

# ESP32-P4
openocd -f board/esp32p4-builtin.cfg -c "adapter serial 60:55:F9:FA:FF:19" ...
```

## STM32 Probe Situation

- **ST-Link V3** (`0483:3754`, serial `004F00...`) — INVISIBLE to libusb on macOS Apple Silicon due to eUSB2 repeater issue. macOS CDC ACM driver claims the VCP interface. See `macos-flash-troubleshooting.md`.
- **ST-Link V2** (`0483:374b`, serial `066EFF...`) — Works with st-flash, OpenOCD, probe-rs.
- **Workaround**: Flash STM32L4 using `st-flash` which routes through the V2 probe.

## USB Hub Topology

Boards connected via Anker 332 USB-C hub (serial `7423J07`) at locationID `0x08100000`:
- ESP32-P4 (`0x08310000`)
- ESP32-S3 (`0x08320000`)
- nRF5340 J-Link (`0x08330000`)
- STM32-N6 STLink V2 (`0x08340000`)

Boards connected directly to Mac USB ports:
- ESP32-C6 (`0x00100000`)
- STM32L4 STLINK_V3 (`0x01100000`)
- MCXN947 MCU-LINK (`0x02100000`)
- C2000 XDS110 (`0x03100000`)
