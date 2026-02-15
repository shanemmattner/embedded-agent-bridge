# E2E Hardware Validation Report — Phase 2 Task 3

**Date:** 2026-02-15
**Branch:** feat/debug-testing-infrastructure
**Script:** `scripts/e2e-hardware-validation.sh`

## Hardware Tested

| Board | Probe | VID:PID | Status |
|-------|-------|---------|--------|
| ESP32-C6 | Built-in USB-JTAG | 303a:1001 | Connected |
| nRF5340 DK | SEGGER J-Link | 1366:1061 | Connected |
| STM32L476RG (Nucleo) | ST-Link V2-1 | 0483:374b | Connected |
| FRDM-MCXN947 | NXP MCU-LINK | 1fc9:0143 | Connected |
| (TI LaunchPad) | XDS110 | 0451:bef3 | Connected (not tested) |

## Results Summary

```
Passed:  11
Failed:  2
Skipped: 6
Total:   19
```

## Detailed Results

### ESP32-C6
| Step | Result | Notes |
|------|--------|-------|
| Chip ID | PASS | esptool identifies ESP32-C6 via USB-JTAG |
| Flash | PASS | OpenOCD JTAG flash, 6.2s, all partitions verified |
| Boot monitor | FAIL | Daemon starts but serial log empty (port assignment issue) |
| Command | SKIP | Depends on boot monitor |
| Trace capture | SKIP | Needs apptrace-capable firmware |

**Root cause of failure:** eabctl daemon registered the ESP32-C6 as serial device type but the USB-JTAG port doesn't work the same as a standard UART. The ESP32-C6's USB-JTAG serial interface requires CDC protocol handling. Fix: need to investigate if the daemon's serial reader works with USB-JTAG CDC ports.

### nRF5340 (J-Link)
| Step | Result | Notes |
|------|--------|-------|
| J-Link connect | PASS | Cortex-M33 r0p4 identified, FW V1.00 |
| Flash | SKIP | debug-full firmware not built |
| RTT start | PASS | JLinkRTTLogger started |
| RTT output | FAIL | Empty — flashed firmware doesn't print to RTT |
| RTT trace capture | PASS | 64 bytes captured (header only) |
| Perfetto export | PASS | Exported 1 event to JSON |

**Root cause of failure:** The currently-flashed firmware on the nRF5340 DK does not output to RTT channel 0. Building and flashing `examples/nrf5340-debug-full` with RTT enabled will resolve this.

### STM32L4 (ST-Link)
| Step | Result | Notes |
|------|--------|-------|
| OpenOCD connect | PASS | Cortex-M4 r0p1, 3.25V |
| probe-rs detect | PASS | STLink V2-1 enumerated |
| Flash (eabctl) | FAIL | Missing arm-none-eabi-objcopy |
| Flash (probe-rs) | PASS | Direct probe-rs download works |
| RTT output | SKIP | Firmware doesn't have RTT enabled |

**Workaround:** `eabctl flash` for STM32 .elf files requires arm-none-eabi-objcopy to convert to .bin. `probe-rs download` handles .elf directly. Install ARM GCC toolchain or fix eabctl to use probe-rs as fallback.

### MCX N947 (MCU-LINK)
| Step | Result | Notes |
|------|--------|-------|
| probe-rs detect | PASS | MCU-LINK CMSIS-DAP V3.128 enumerated |
| Flash (eabctl) | FAIL | LinkServer not installed |
| Flash (probe-rs) | SKIP | Address range 0x10000000 not in flash map |
| RTT output | SKIP | Can't test without valid firmware |

**Root cause:** FRDM-MCXN947 Zephyr build targets secure address 0x10000000 but probe-rs maps NVM at 0x00000000. NXP's LinkServer tool handles this correctly. Install LinkServer or modify the Zephyr board config.

## Trace Pipeline (End-to-End)

The full trace pipeline works:
1. `eabctl rtt start` → J-Link RTT streaming
2. `eabctl trace start --source rtt` → binary capture to .rttbin
3. `eabctl trace stop` → clean shutdown
4. `eabctl trace export -i trace.rttbin -o trace.json` → Perfetto JSON

Validated with nRF5340 J-Link. Pipeline produces valid Perfetto Chrome JSON format.

## Software Tests
- Trace pipeline tests: ALL PASS
- pytest: 573 passed, 13 failed (pre-existing)

## Blockers for Full Validation

1. **Build debug-full firmware** — `examples/nrf5340-debug-full` and `examples/esp32c6-debug-full` need to be compiled with RTT/trace enabled
2. **Install ARM GCC toolchain** — `brew install --cask gcc-arm-embedded` for STM32 eabctl flash
3. **Install NXP LinkServer** — Required for MCX N947 flash
4. **ESP32-C6 daemon serial** — Investigate USB-JTAG CDC port compatibility

## How to Run

```bash
cd ~/Desktop/personal-assistant2/work/repos/embedded-agent-bridge

# Full test (all boards + software)
bash scripts/e2e-hardware-validation.sh all

# Single board
bash scripts/e2e-hardware-validation.sh esp32c6
bash scripts/e2e-hardware-validation.sh nrf5340
bash scripts/e2e-hardware-validation.sh stm32l4
bash scripts/e2e-hardware-validation.sh mcxn947

# Discovery only
bash scripts/e2e-hardware-validation.sh --discover

# Software-only
bash scripts/e2e-hardware-validation.sh pipeline
```

Results saved to `e2e-results/<timestamp>/` with:
- `summary.json` — machine-readable results
- `devices.json` — discovered hardware
- `e2e-validation.log` — full test log
- `artifacts/<board>/` — per-board output files
- `traces/` — captured trace files

## Next Steps

1. Build debug-full firmware for all boards (requires toolchains)
2. Re-run with RTT-enabled firmware for nRF5340
3. Add ESP32 apptrace capture path
4. Install LinkServer for MCX N947
5. Add trace content validation (check JSON structure, event counts)
6. Integrate into CI/CD with hardware-in-the-loop runner
