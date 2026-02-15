# eab-probe-rs: Native probe-rs RTT Transport

Rust extension for [Embedded Agent Bridge (EAB)](https://github.com/shanemmattner/embedded-agent-bridge) that provides binary RTT (Real-Time Transfer) access via the probe-rs library.

## Why This Exists

EAB originally supported RTT only through SEGGER J-Link probes via the `pylink-square` Python library. This Rust extension adds probe-agnostic RTT support — works with **any probe-rs-compatible debug probe**:

- **ST-Link** (built into STM32 Nucleo/Discovery boards)
- **CMSIS-DAP** (OpenOCD, pyOCD, cheap $3 probes)
- **J-Link** (SEGGER probes — still works!)
- **ESP USB JTAG** (built into ESP32-C3/C6/S3)

The key difference from the existing `ProbeRSTransport` (which spawns `probe-rs rtt` as a subprocess):

| Approach | Binary RTT | Bidirectional | Speed | Status |
|---|---|---|---|---|
| `JLinkTransport` (pylink) | ✅ Yes | ✅ Yes | Fast | Works, J-Link only |
| `ProbeRSTransport` (subprocess) | ❌ Text only | ❌ Read-only | Slow | Limited |
| **`ProbeRsNativeTransport`** (this) | **✅ Yes** | **✅ Yes** | **Fast** | **New** |

## Architecture

```
Python (EAB)
    ↓ import eab_probe_rs
PyO3 bindings (this crate)
    ↓ probe-rs Rust API
probe-rs library
    ↓ USB/debug protocol
ST-Link / CMSIS-DAP / J-Link / ESP JTAG
    ↓ SWD/JTAG
Target MCU (STM32, nRF, ESP32, RP2040, etc.)
```

## Building

### Prerequisites

- Rust toolchain (`rustup` or Homebrew)
- Python 3.9+ with `pip`
- `maturin` (Rust→Python build tool)

```bash
# Install maturin
cargo install maturin
# or: pip install maturin

# Build and install the extension (development mode)
cd eab-probe-rs
maturin develop --release

# The extension is now importable:
python3 -c "from eab_probe_rs import ProbeRsSession; print('✓ Installed')"
```

### For Production

```bash
# Build a wheel
maturin build --release

# Install the wheel
pip install target/wheels/eab_probe_rs-*.whl
```

## Usage from Python

### Standalone

```python
from eab_probe_rs import ProbeRsSession

# Connect to a chip
session = ProbeRsSession(chip="STM32L476RG")
session.attach()

# Start RTT
num_channels = session.start_rtt()
print(f"Found {num_channels} RTT up channels")

# Read binary data from channel 0
while True:
    data = session.rtt_read(channel=0)
    if data:
        print(f"Received {len(data)} bytes: {data[:16].hex()}")

# Write to down channel
session.rtt_write(channel=0, data=b"command\n")

# Cleanup
session.detach()
```

### Via EAB

```python
from eab.rtt_transport import ProbeRsNativeTransport

transport = ProbeRsNativeTransport()
transport.connect("STM32L476RG")
num_up = transport.start_rtt()

data = transport.read(channel=0)
transport.write(channel=0, b"test")

transport.disconnect()
```

### Via EAB CLI

```bash
# Start RTT logging via probe-rs
eabctl rtt start --device STM32L476RG --transport probe-rs

# Read RTT output
eabctl rtt tail 50

# Stop RTT
eabctl rtt stop
```

## Firmware Side (Target Code)

Your embedded firmware needs to initialize the RTT control block. Example for Zephyr RTOS:

```c
#include <SEGGER_RTT.h>

// In prj.conf:
// CONFIG_USE_SEGGER_RTT=y
// CONFIG_SEGGER_RTT_BUFFER_SIZE_UP=4096

void main(void) {
    // Write text to channel 0 (stdio)
    SEGGER_RTT_WriteString(0, "Hello from target!\n");

    // Write binary data to channel 1
    uint16_t samples[512];
    SEGGER_RTT_Write(1, samples, sizeof(samples));
}
```

For bare-metal STM32, add `SEGGER_RTT.c` and `SEGGER_RTT.h` to your project (available in J-Link SDK or Zephyr source).

## Supported Chips

probe-rs supports **700+ chips**. Check the full list:

```bash
probe-rs chip list
```

Common families:
- STM32 (all families: F0, F1, F4, F7, G0, G4, H7, L0, L4, L5, U5, WB, WL)
- nRF (nRF51, nRF52, nRF53, nRF91)
- RP2040 (Raspberry Pi Pico)
- ESP32-C3/C6/H2/S2/S3 (RISC-V and Xtensa)
- NXP (i.MX RT, LPC, Kinetis, MCX)
- Microchip SAM (SAMD, SAME, SAMV)
- GigaDevice GD32 (all families)

## Troubleshooting

### ImportError: No module named 'eab_probe_rs'

The extension wasn't built. Run:

```bash
cd eab-probe-rs
maturin develop --release
```

### RuntimeError: No debug probes found

Check USB connection:

```bash
# List connected probes
probe-rs list
```

Expected output:
```
[0]: STLink V2-1 -- 0483:374b:... (ST-LINK)
```

If empty, check:
- USB cable connected?
- Target powered?
- USB permissions (Linux: udev rules)

### RuntimeError: Failed to attach to chip 'XYZ'

The chip name doesn't match probe-rs's database. Find the correct name:

```bash
probe-rs chip list | grep -i stm32l4
```

Example: `"stm32l476rg"` → `"STM32L476RG"` (case-insensitive, but use exact match)

### RuntimeError: RTT control block not found

Firmware doesn't have RTT enabled. Ensure:

1. `SEGGER_RTT.c` linked into firmware
2. RTT buffer allocated (check `.map` file for `_SEGGER_RTT` symbol)
3. Firmware actually calls `SEGGER_RTT_Write()` or `SEGGER_RTT_printf()`

## Performance

Measured on STM32L476RG via ST-Link V2-1 (USB Full Speed):

| Metric | Value |
|--------|-------|
| RTT read throughput | ~150 KB/s (USB bottleneck) |
| Max sample rate (int16) | ~74 kHz |
| Latency (read call) | <1 ms |
| CPU overhead (target) | ~1 µs per write |

For higher throughput, use a USB Hi-Speed probe (J-Link EDU: ~800 KB/s).

## License

MIT (same as Embedded Agent Bridge)

## Credits

- **probe-rs**: https://probe.rs/
- **PyO3**: https://pyo3.rs/
- **SEGGER RTT**: RTT protocol originally by SEGGER (BSD-licensed source)
