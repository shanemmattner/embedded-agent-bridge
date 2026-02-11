# nRF5340 Test Firmware (Zephyr RTT)

Fake sensor data over SEGGER RTT. Exercises the EAB RTT bridge and real-time plotter.

## What it does

- Two sine waves (90 degrees out of phase) as `sine_a` and `sine_b`
- Noisy temperature reading as `temp`
- Rotating state machine: IDLE -> SAMPLING -> PROCESSING -> TRANSMITTING
- 200ms tick interval

Output format (Zephyr log backend):
```
[00:03:35.610] <inf> eab_test: DATA: sine_a=0.68 sine_b=0.72 temp=22.95
[00:03:35.810] <inf> eab_test: STATE: SAMPLING
```

## Requirements

- nRF5340 DK (or any nRF5340-based board)
- Zephyr SDK + west
- J-Link probe (built into DK)

## Build and flash

```bash
cd /path/to/zephyrproject
west build -b nrf5340dk/nrf5340/cpuapp examples/nrf5340-test-firmware
west flash
```

## Use with EAB

Requires J-Link Software Pack installed (provides `JLinkRTTLogger`).

```bash
# Via Python — uses JLinkRTTLogger subprocess (no pylink needed)
from eab.jlink_bridge import JLinkBridge
bridge = JLinkBridge("/tmp/eab-session")
bridge.start_rtt(device="NRF5340_XXAA_APP")

# Output files:
cat /tmp/eab-session/rtt.log    # cleaned text
cat /tmp/eab-session/rtt.csv    # DATA records as CSV
cat /tmp/eab-session/rtt.jsonl  # structured JSON
```
