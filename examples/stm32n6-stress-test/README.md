# STM32-N6 Stress Test Firmware

High-throughput RTT streaming test for STM32-N6 dev kit.

## Build & Flash

```bash
# Set ZEPHYR_BASE if not already set
export ZEPHYR_BASE=~/zephyrproject/zephyr

# Build (replace board name with actual STM32-N6 board target)
west build -b nucleo_n657x0q examples/stm32n6-stress-test

# Flash via ST-Link
west flash --runner openocd
```

## Monitor via RTT

```bash
# Start RTT capture
eabctl --device stm32-n6 rtt start --transport probe-rs

# Tail output
eabctl --device stm32-n6 rtt tail 100
```

## Expected Output

```
[DATA] seq=0 t=12345
[DATA] seq=1 t=12456
...
[STATS] msgs=1000 bytes=32000 uptime=10.0s throughput=3.2_KB/s rate=100_msg/s
```

## Throughput Target

- **Expected**: TBD (first STM32-N6 RTT benchmark with EAB)
- **Message rate**: ~1400 msg/s @ 32 bytes/msg
- **Burst pattern**: 100 messages every 10ms

## Notes

- STM32-N6 is a new Cortex-M55 chip - may need Zephyr board definition
- Check `west boards | grep stm32n6` for available targets
- May need custom board overlay if dev kit not in Zephyr mainline yet
