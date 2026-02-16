# ESP32-P4 Stress Test Firmware

High-throughput serial streaming test for ESP32-P4 dev kit.

## Build & Flash

```bash
cd examples/esp32p4-stress-test
idf.py set-target esp32p4
idf.py build
eabctl flash .
```

## Monitor

```bash
eabctl --device esp32-p4 tail 100
```

## Expected Output

```
[DATA] seq=0 t=12345678 heap=428140
[DATA] seq=1 t=12345789 heap=428140
...
[STATS] msgs=1000 bytes=64000 uptime=10.0s throughput=6.3_KB/s rate=100_msg/s heap=428140
```

## Throughput Target

- **Expected**: ~90 KB/s (similar to ESP32-C6 via USB serial)
- **Message rate**: ~1400 msg/s @ 64 bytes/msg
- **Burst pattern**: 100 messages every 10ms = 10,000 msg/s instantaneous
