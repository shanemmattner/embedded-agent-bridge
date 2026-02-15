# E2E Hardware Validation Report

**Last Run:** 2026-02-15 13:39 PST
**Branch:** feat/debug-testing-infrastructure
**Script:** `scripts/e2e-hardware-validation.sh`

## Results: 15 pass / 1 fail / 4 skip

| Board | Probe | Flash | Serial/RTT | Trace Capture | Perfetto Export |
|-------|-------|-------|------------|---------------|-----------------|
| ESP32-C6 | PASS | PASS | PASS | PASS (64B) | PASS |
| nRF5340 | PASS | SKIP* | PASS/FAIL** | PASS (64B) | PASS |
| STM32L4 | PASS | PASS | SKIP*** | - | - |
| MCX N947 | PASS | SKIP**** | SKIP*** | - | - |
| Trace Pipeline | - | - | - | - | PASS |
| pytest (573) | - | - | - | - | PASS |

\* nRF5340 debug-full firmware not built yet
\** RTT empty — currently flashed firmware doesn't print to RTT channel 0
\*** Firmware doesn't have RTT enabled
\**** MCX N947 requires NXP LinkServer (not installed; probe-rs has address mapping limitation)

## Bugs Found and Fixed This Session

1. **Daemon PYTHONPATH shadowing pyserial** — `eab/cli/serial/` shadowed pyserial when PYTHONPATH included `eab/cli/`. Fixed in `lifecycle_cmds.py` (commit `56565c9`).
2. **STM32 flash requiring arm-none-eabi-objcopy** — Pre-built `.bin` files exist from west builds. Script now uses `.bin` directly, no extra toolchain needed.
3. **probe-rs multi-probe selection** — With 4+ probes connected, probe-rs needs `--probe VID:PID:SERIAL` selector. Added to test script.
4. **False positive flash detection** — `grep "success"` matched `"success": false` in JSON. Fixed to check `"success": true`.

## How to Run

```bash
cd ~/Desktop/personal-assistant2/work/repos/embedded-agent-bridge

# Full validation (all boards + software tests)
bash scripts/e2e-hardware-validation.sh all

# Single board
bash scripts/e2e-hardware-validation.sh esp32c6
bash scripts/e2e-hardware-validation.sh nrf5340
bash scripts/e2e-hardware-validation.sh stm32l4
bash scripts/e2e-hardware-validation.sh mcxn947

# Discovery only (show what's connected)
bash scripts/e2e-hardware-validation.sh --discover

# Software-only (no hardware needed)
bash scripts/e2e-hardware-validation.sh pipeline
```

## Results Structure

Each run creates `e2e-results/<timestamp>/`:
```
e2e-results/20260215-133941/
├── summary.json              # Machine-readable pass/fail/skip counts
├── devices.json              # Discovered hardware
├── e2e-validation.log        # Full timestamped log
├── artifacts/
│   ├── esp32c6/
│   │   ├── chip_id.txt       # esptool output
│   │   ├── flash.txt         # Flash result JSON
│   │   ├── boot.txt          # First 50 lines of serial output
│   │   ├── cmd_status.txt    # Command response
│   │   └── export.txt        # Perfetto export result
│   ├── nrf5340/
│   │   ├── jlink_connect.txt # J-Link probe info
│   │   ├── rtt_start.txt     # RTT streaming result
│   │   ├── rtt_output.txt    # RTT log content
│   │   └── export.txt        # Perfetto export result
│   ├── stm32l4/
│   │   ├── probe_info.txt    # probe-rs device list
│   │   ├── openocd_connect.txt
│   │   └── flash.txt
│   ├── mcxn947/
│   │   └── ...
│   ├── trace-pipeline/
│   │   └── output.txt        # Software test results
│   └── pytest/
│       └── output.txt        # Full pytest output
└── traces/
    ├── esp32c6-serial.rttbin # Captured trace binary
    ├── esp32c6-trace.json    # Perfetto JSON export
    ├── nrf5340-rtt.rttbin
    └── nrf5340-trace.json
```

## Hardware Setup

### Connected Boards

| Board | Probe Type | VID:PID | Serial Port(s) |
|-------|-----------|---------|-----------------|
| ESP32-C6 DevKit | Built-in USB-JTAG | 303a:1001 | /dev/cu.usbmodem101 |
| nRF5340 DK | On-board J-Link | 1366:1061 | /dev/cu.usbmodem001050063659{1,3} |
| STM32 Nucleo-L476RG | ST-Link V2-1 | 0483:374b | /dev/cu.usbmodem83303 |
| FRDM-MCXN947 | NXP MCU-LINK | 1fc9:0143 | /dev/cu.usbmodemI2WZW2OTY3RUW3 |
| TI LaunchPad | XDS110 | 0451:bef3 | /dev/cu.usbmodemCL391078{1,4} |

### Required Tools

| Tool | Used For | Status |
|------|----------|--------|
| eabctl | Flash, daemon, trace capture/export | Installed (uv) |
| esptool | ESP32 chip identification | Installed |
| OpenOCD (esp32) | ESP32 JTAG flash | Installed (ESP-IDF) |
| OpenOCD (generic) | STM32 connection test | Installed (homebrew) |
| JLinkExe | nRF5340 connection + RTT | Installed |
| probe-rs | STM32/MCX flash + RTT | Installed (cargo) |
| pyocd | Device enumeration | Installed |
| west | Zephyr build/flash | Installed |

### Not Installed (causes SKIPs)

| Tool | Needed For | Install |
|------|-----------|---------|
| NXP LinkServer | MCX N947 flash | [nxp.com/linkserver](https://www.nxp.com/design/design-center/software/development-software/mcuxpresso-software-and-tools-/linkserver-for-microcontrollers:LINKERSERVER) |

## Known Limitations

1. **nRF5340 RTT empty**: The currently flashed firmware doesn't output to RTT. Building `examples/nrf5340-debug-full` with RTT enabled will resolve this.
2. **MCX N947 flash**: probe-rs maps NVM at 0x00000000 but Zephyr targets secure address 0x10000000. NXP LinkServer handles this correctly.
3. **eabctl flash STM32 .elf**: Requires arm-none-eabi-objcopy (not on PATH). Workaround: flash `.bin` files directly or use probe-rs fallback.
4. **ESP32-C6 trace size**: Serial log capture produces minimal data (64 bytes header). Real trace capture needs apptrace-enabled firmware.

## Trace Pipeline (Validated End-to-End)

```
eabctl rtt start → JLinkRTTLogger → rtt.log
                                       ↓
eabctl trace start --source rtt → binary .rttbin capture
                                       ↓
eabctl trace stop → clean shutdown
                                       ↓
eabctl trace export -i .rttbin -o .json → Perfetto Chrome JSON
                                       ↓
                              Open in ui.perfetto.dev
```

Validated on: ESP32-C6 (serial), nRF5340 (RTT/J-Link)
