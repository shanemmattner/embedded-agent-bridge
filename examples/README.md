# Example Firmware

Test firmware for verifying EAB with real hardware. Each example targets a different platform and transport.

| Example | Platform | Transport | Features |
|---------|----------|-----------|----------|
| [esp32c6-test-firmware](esp32c6-test-firmware/) | ESP32-C6 | USB Serial | Interactive shell, heartbeat, simulated crashes |
| [stm32l4-test-firmware](stm32l4-test-firmware/) | STM32L476RG | UART (ST-Link VCP) | Bare-metal blinky + heartbeat |
| [nrf5340-test-firmware](nrf5340-test-firmware/) | nRF5340 DK | SEGGER RTT | Sine wave data, state machine, real-time plotter |
| [nrf5340-fault-demo](nrf5340-fault-demo/) | nRF5340 DK | SEGGER RTT | Injectable Cortex-M33 faults for `eabctl fault-analyze` |

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

Requires J-Link Software Pack installed (provides `JLinkRTTLogger`).

```bash
west build -b nrf5340dk/nrf5340/cpuapp examples/nrf5340-test-firmware
west flash

# Start RTT bridge (uses JLinkRTTLogger subprocess)
python -c "
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
