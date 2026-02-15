# probe-rs Native RTT Testing Guide

This guide covers end-to-end testing of the probe-rs native RTT transport.

## Prerequisites

### 1. Build and Install Extension

```bash
cd eab-probe-rs
PYO3_USE_ABI3_FORWARD_COMPATIBILITY=1 maturin build --release
pip install target/wheels/eab_probe_rs-*.whl
```

Verify installation:
```bash
python3 -c "from eab_probe_rs import ProbeRsSession; print('OK')"
```

### 2. Hardware Setup

**Supported probes:**
- ST-Link (STM32 Discovery/Nucleo boards)
- CMSIS-DAP (NXP MCX, Microchip SAM, Nordic DK)
- J-Link (SEGGER debuggers, Nordic DKs)
- ESP USB-JTAG (ESP32-C3/C6/S3 built-in)

**Supported targets:**
- STM32 (all families: F0, F4, G4, H7, L4, MP1, etc.)
- nRF52, nRF53, nRF91
- ESP32-C3, ESP32-C6, ESP32-S3
- NXP Kinetis, LPC, i.MX RT
- And 800+ more chips supported by probe-rs

Connect your board via debug probe (SWD/JTAG pins or built-in debugger).

### 3. RTT-Enabled Firmware

Your firmware **must** initialize RTT for this test to work.

#### Zephyr (nRF5340, STM32, etc.)

Add to `prj.conf`:
```ini
CONFIG_CONSOLE=y
CONFIG_RTT_CONSOLE=y
CONFIG_USE_SEGGER_RTT=y
CONFIG_LOG=y
CONFIG_LOG_BACKEND_RTT=y
```

Build and flash:
```bash
west build -b nrf5340dk_nrf5340_cpuapp samples/hello_world
west flash --runner jlink
```

#### STM32 (bare metal)

Add SEGGER RTT library to your project:
```c
#include "SEGGER_RTT.h"

void main(void) {
    SEGGER_RTT_ConfigUpBuffer(0, "Terminal", NULL, 0, SEGGER_RTT_MODE_NO_BLOCK_SKIP);

    while (1) {
        SEGGER_RTT_printf(0, "Hello from STM32! Counter: %d\n", counter++);
        HAL_Delay(1000);
    }
}
```

#### ESP-IDF (ESP32-C6)

RTT is available via esp-idf-rtt component.

## Unit Tests (No Hardware)

Run mocked tests that verify API behavior:

```bash
cd /path/to/embedded-agent-bridge
python3 -m pytest tests/test_rtt_transport.py::TestProbeRsNativeTransport -v
```

Expected: 7 tests pass (mocked, no hardware required).

## Python API Test (Hardware Required)

Test direct Python API with real hardware:

```python
from eab_probe_rs import ProbeRsSession

# Connect to target
session = ProbeRsSession(chip="STM32L476RG")  # or "nRF52840_xxAA", "ESP32C6"
session.attach()

# Start RTT
num_channels = session.start_rtt()
print(f"Found {num_channels} RTT channels")

# Read RTT output
import time
for i in range(10):
    data = session.rtt_read(channel=0)
    if data:
        print(data.decode('utf-8', errors='ignore'), end='')
    time.sleep(0.1)

# Write to down channel (if firmware supports it)
session.rtt_write(channel=0, data=b"command\n")

# Cleanup
session.detach()
```

**Expected output:**
```
Found 1 RTT channels
Hello from STM32! Counter: 42
Hello from STM32! Counter: 43
Hello from STM32! Counter: 44
...
```

**Common errors:**
- `No debug probes found` → Check USB connection, install udev rules (Linux), run with sudo (Linux), check drivers (Windows)
- `Failed to attach to chip 'XXX'` → Check chip name (use `probe-rs chip list`), verify power, verify SWD/JTAG wiring
- `RTT control block not found` → Firmware doesn't have RTT enabled, or RTT init hasn't run yet (add delay after flash)

## CLI Test (Hardware Required)

Test via `eabctl rtt start`:

```bash
# Basic connectivity test (expect graceful error if no RTT firmware)
eabctl rtt start --device STM32L476RG --transport probe-rs --json

# With RTT-enabled firmware (should connect and report channels)
eabctl rtt start --device STM32L476RG --transport probe-rs --json
```

**Expected output (no RTT firmware):**
```json
{
  "running": false,
  "device": "STM32L476RG",
  "channel": 0,
  "transport": "probe-rs",
  "last_error": "RTT control block not found: ..."
}
```

**Expected output (RTT firmware running):**
```json
{
  "running": true,
  "device": "STM32L476RG",
  "channel": 0,
  "num_up_channels": 1,
  "transport": "probe-rs",
  "note": "probe-rs transport does not yet support background logging. Use Python API for streaming."
}
```

**With specific probe selector:**
```bash
# Find your probe
probe-rs list

# Use it
eabctl rtt start --device STM32L476RG --transport probe-rs --probe-selector "0483:374b" --json
```

## E2E Integration Test

Full workflow test using EAB device registry:

```bash
# 1. Register device (if not already registered)
# Device config at /tmp/eab-devices/stm32/device.json should have chip: "stm32l476rg"

# 2. Flash RTT-enabled firmware
eabctl flash --chip stm32l476rg --runner openocd  # or jlink

# 3. Start probe-rs RTT
eabctl rtt start --device STM32L476RG --transport probe-rs --json

# 4. Verify connection in Python
python3 << EOF
from eab_probe_rs import ProbeRsSession
s = ProbeRsSession(chip="STM32L476RG")
s.attach()
num = s.start_rtt()
print(f"Channels: {num}")
data = s.rtt_read(0)
print(f"Data: {data[:100]}")  # First 100 bytes
s.detach()
EOF
```

## Performance Benchmarking

Compare throughput vs J-Link:

```bash
# Generate high-rate RTT output on target (e.g., 100 KB/s)
# Firmware loop:
# while(1) { SEGGER_RTT_Write(0, buffer, 1024); }

# Test with probe-rs
python3 << EOF
from eab_probe_rs import ProbeRsSession
import time
s = ProbeRsSession(chip="STM32L476RG")
s.attach()
s.start_rtt()

total_bytes = 0
start = time.time()
while time.time() - start < 5:  # 5 seconds
    data = s.rtt_read(0)
    total_bytes += len(data)

rate_kbps = (total_bytes / 1024) / 5
print(f"Throughput: {rate_kbps:.1f} KB/s")
s.detach()
EOF
```

**Expected rates:**
- ST-Link V2: ~100-150 KB/s
- J-Link OB (USB Full Speed): ~150 KB/s
- J-Link EDU (USB Hi-Speed): ~800 KB/s
- CMSIS-DAP v2: ~200-400 KB/s

## Troubleshooting

### Import Error: `eab_probe_rs` not found

```bash
# Rebuild and reinstall
cd eab-probe-rs
PYO3_USE_ABI3_FORWARD_COMPATIBILITY=1 maturin build --release
pip install --force-reinstall target/wheels/eab_probe_rs-*.whl
```

### Permission Denied (Linux)

```bash
# Add udev rules for debug probes
sudo curl https://probe.rs/files/69-probe-rs.rules -o /etc/udev/rules.d/69-probe-rs.rules
sudo udevadm control --reload
sudo udevadm trigger

# Or run as root (not recommended)
sudo python3 -c "from eab_probe_rs import ProbeRsSession; ..."
```

### Wrong Chip Name

```bash
# List all supported chips
probe-rs chip list

# Search for your chip
probe-rs chip list | grep -i stm32l4
probe-rs chip list | grep -i nrf52

# Use exact name from output
```

### Multiple Probes Connected

```bash
# List probes with identifiers
probe-rs list

# Use --probe-selector with serial number or VID:PID
eabctl rtt start --device STM32L476RG --transport probe-rs --probe-selector "066DFF303130594E43071534" --json
```

## Next Steps

- [ ] Integrate probe-rs transport with EAB daemon for background RTT logging
- [ ] Add `eabctl rtt stop` support for probe-rs (currently no-op)
- [ ] Implement streaming capture to `.rttbin` files
- [ ] Add probe-rs support to regression test YAML (wait step on probe-rs RTT)
- [ ] Performance tuning: buffer sizes, polling intervals
- [ ] Multi-channel RTT support (currently hardcoded to channel 0)
- [ ] Add probe-rs to Docker container for CI testing

## References

- probe-rs documentation: https://probe.rs/docs/
- probe-rs chip support: https://probe.rs/targets/
- SEGGER RTT specification: https://wiki.segger.com/RTT
- PyO3 documentation: https://pyo3.rs/
