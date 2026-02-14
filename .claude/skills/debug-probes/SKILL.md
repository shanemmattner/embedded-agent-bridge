---
name: debug-probes
description: >
  Debug probe selection, usage patterns, and troubleshooting for ARM Cortex-M targets.
  Covers J-Link, probe-rs, OpenOCD, CMSIS-DAP probes. RTT binary capture, nRF5340
  recovery, throughput optimization, and common pitfalls.
---

# Debug Probes for Embedded Development

## Probe Selection

| Probe | USB Speed | RTT Throughput | Price | Best For |
|-------|-----------|----------------|-------|----------|
| J-Link OB (on DK boards) | Full Speed (12 Mbit) | ~150 KB/s | Free (on-board) | Quick dev, no purchase needed |
| J-Link EDU Mini | Full Speed (12 Mbit) | ~150 KB/s | ~$20 | Budget external probe |
| J-Link EDU | Hi-Speed (480 Mbit) | ~800 KB/s | ~$60 | Serious RTT streaming |
| J-Link PLUS | Hi-Speed (480 Mbit) | ~800 KB/s | ~$500 | Commercial/production |
| CMSIS-DAP v2 (WCH-Link, picoLink) | Full Speed | N/A (no RTT) | $2-15 | Flashing only |
| Black Magic Probe | Full Speed | N/A (GDB native) | ~$75 | GDB without server |

**Key insight:** RTT throughput is bottlenecked by USB speed, NOT SWD clock.
- USB Full Speed (12 Mbit): ~150 KB/s = ~74 kHz @ 16-bit samples
- USB Hi-Speed (480 Mbit): ~800 KB/s = ~400 kHz @ 16-bit samples
- SWD clock (4-50 MHz) has negligible effect on sustained throughput

## Transport Backends

### J-Link (pylink-square) — Primary

Best for: RTT, binary streaming, Cortex-M debugging with SEGGER tools.

```python
from eab.rtt_transport import JLinkTransport

transport = JLinkTransport()
transport.connect(device="NRF5340_XXAA_APP", interface="SWD", speed=4000)
transport.start_rtt()

# Binary-clean read — returns raw bytes, no text interpretation
data = transport.read(channel=1, max_bytes=4096)

transport.stop_rtt()
transport.disconnect()
```

**Device strings:** `NRF5340_XXAA_APP`, `NRF52840_XXAA`, `MCXN947`, `STM32L476RG`

### probe-rs — Secondary

Best for: Open-source workflows, Rust toolchains, flashing without SEGGER license.

```bash
# Flash
probe-rs run --chip nRF5340_xxAA_APP target/thumbv7em-none-eabihf/release/app

# RTT attach (text mode)
probe-rs rtt --chip nRF5340_xxAA_APP

# Reset
probe-rs reset --chip nRF5340_xxAA_APP
```

```python
from eab.rtt_transport import ProbeRSTransport

transport = ProbeRSTransport()
transport.connect(device="nRF5340_xxAA_APP")
transport.start_rtt()
data = transport.read(channel=1)
```

### OpenOCD — Tertiary

Best for: ESP32, NXP MCX, chips without J-Link support.

```bash
# ESP32-C6 via built-in USB-JTAG
~/.espressif/tools/openocd-esp32/*/openocd-esp32/bin/openocd -f board/esp32c6-builtin.cfg

# NXP MCXN947 via CMSIS-DAP
openocd -f interface/cmsis-dap.cfg -f target/mcxn9xx.cfg
```

## RTT Binary Capture

High-throughput binary data streaming from target to host via RTT.

### Quick Start

```python
from eab.rtt_binary import RTTBinaryCapture
from eab.rtt_transport import JLinkTransport

capture = RTTBinaryCapture(
    transport=JLinkTransport(),
    device="NRF5340_XXAA_APP",
    channels=[1],           # RTT channel for binary data
    sample_rate=10000,       # Hz (for metadata, not enforced)
    sample_width=2,          # bytes per sample (int16)
    output_path="capture.rttbin",
)
capture.start()
# ... device streams data on RTT channel 1 ...
capture.stop()

# Convert
data = capture.to_numpy()   # dict[channel, np.ndarray]
capture.to_csv("capture.csv")
```

### CLI

```bash
eabctl rtt-capture start --device NRF5340_XXAA_APP --channel 1 \
  --sample-rate 10000 --sample-width 2 --output capture.rttbin
eabctl rtt-capture stop
eabctl rtt-capture convert capture.rttbin --format csv --output capture.csv
eabctl rtt-capture info capture.rttbin
```

### File Format (.rttbin)

64-byte self-describing header + variable-length frames:
- Header: magic "RTTB", version, sample_width, sample_rate, timestamp_hz, channel_mask
- Frame: 4B timestamp + 1B channel + 2B length + payload (7 bytes overhead)

### Firmware Side (Zephyr)

```c
#include <SEGGER_RTT.h>

// Configure channel 1 with large buffer, non-blocking
static char rtt_buf[16384];
SEGGER_RTT_ConfigUpBuffer(1, "BinaryData", rtt_buf, sizeof(rtt_buf),
                          SEGGER_RTT_MODE_NO_BLOCK_SKIP);

// Write raw binary samples
int16_t samples[512];
SEGGER_RTT_Write(1, samples, sizeof(samples));
```

Kconfig:
```
CONFIG_USE_SEGGER_RTT=y
CONFIG_SEGGER_RTT_BUFFER_SIZE_UP=4096
CONFIG_SEGGER_RTT_MODE_NO_BLOCK_SKIP=y
CONFIG_WDT_DISABLE_AT_BOOT=y  # if tight-looping
```

## nRF5340 Recovery (CRITICAL)

### How Chips Get Bricked

**NEVER run bare `erase` on nRF5340.** Erasing UICR re-enables APPROTECT, locking
both debug ports. Standard tools (JLinkExe, probe-rs, pyocd) cannot connect after this.

Dangerous commands:
- `JLinkExe` → `erase` (erases ALL flash including UICR)
- `nrfjprog --eraseall` without `--recover`
- Any tool that erases UICR without immediately reflashing

Safe alternatives:
- `west flash --runner jlink` (erases only app region, preserves UICR)
- `nrfjprog --recover` (full erase + unlock in one atomic operation)
- `eabctl flash --chip nrf5340 --runner jlink` (uses west flash internally)

### Recovery Procedure

When nRF5340 is locked (APPROTECT enabled), the CTRL-AP is still accessible
via raw CORESIGHT SWD. Use `scripts/nrf5340_recover.py`:

```bash
python3 scripts/nrf5340_recover.py
```

This:
1. Opens J-Link in raw SWD mode (no `connect()` call)
2. Uses `coresight_configure()` for raw DAP access
3. Selects CTRL-AP (AP2 for app core, AP3 for net core)
4. Triggers ERASEALL via CTRL-AP register write
5. Waits for completion, then resets chip

After recovery, flash firmware immediately:
```bash
west flash --runner jlink
```

### Manual Recovery (if script fails)

```python
import pylink
j = pylink.JLink()
j.open()
j.set_tif(pylink.enums.JLinkInterfaces.SWD)
j.coresight_configure()

# App core (AP2)
j.coresight_write(reg=2, data=0x02000000, ap=False)  # SELECT AP2
j.coresight_write(reg=1, data=0x01, ap=True)          # ERASEALL
import time; time.sleep(5)

# Net core (AP3)
j.coresight_write(reg=2, data=0x03000000, ap=False)  # SELECT AP3
j.coresight_write(reg=1, data=0x01, ap=True)          # ERASEALL
time.sleep(5)

# Reset
j.coresight_write(reg=2, data=0x02000000, ap=False)
j.coresight_write(reg=0, data=0x01, ap=True)
time.sleep(0.1)
j.coresight_write(reg=0, data=0x00, ap=True)
j.close()
```

## Throughput Optimization

### Measured Results (nRF5340 DK, J-Link OB)

| Metric | Value |
|--------|-------|
| USB speed | Full Speed (12 Mbit/s) |
| RTT throughput | 145 KB/s sustained |
| Max sample rate (int16) | ~74 kHz |
| RTT buffer (firmware) | 16 KB (non-blocking skip) |
| RTT chunk size | 512 samples = 1024 bytes |
| SWD clock effect | Negligible (USB is bottleneck) |

### To Go Faster

1. Use **J-Link EDU** (USB Hi-Speed) → ~800 KB/s → ~400 kHz @ int16
2. Use **int8** samples instead of int16 → double the sample rate
3. Apply **delta compression** on firmware side → reduce data volume
4. Use multiple RTT channels for parallel streams

### BinaryWriter/Reader Performance

- BinaryWriter: 500-12,000 MB/s (not a bottleneck)
- BinaryReader: ~4,000 MB/s (not a bottleneck)
- All bottleneck is USB transport from probe to host

## Common Pitfalls

| Problem | Cause | Fix |
|---------|-------|-----|
| nRF5340 locked after erase | UICR erased, APPROTECT re-enabled | Run `scripts/nrf5340_recover.py` |
| RTT reads return empty | RTT control block not found | Verify firmware has RTT enabled, try `start_rtt(block_address=0x20000000)` |
| Low RTT throughput | USB Full Speed probe | Use USB Hi-Speed J-Link |
| "Cannot connect to target" | APPROTECT or wrong device string | Check device string, try recovery |
| probe-rs can't find RTT | RTT block at non-default address | Pass `--rtt-scan-range` |
| JLinkExe "Could not find core" | Locked nRF5340 | Use CTRL-AP recovery, not standard connect |
| `west flash` fails | Wrong runner | Add `--runner jlink` or `--runner openocd` |

## Hardware We Have

| Board | MCU | Debug Probe | USB Speed | Notes |
|-------|-----|-------------|-----------|-------|
| nRF5340 DK | nRF5340 (Cortex-M33 @ 128 MHz) | J-Link OB | Full Speed | Primary dev board |

## Dependencies

```bash
pip install pylink-square          # J-Link transport
pip install embedded-agent-bridge  # Full EAB with RTT binary capture
cargo install probe-rs-tools       # probe-rs CLI
```
