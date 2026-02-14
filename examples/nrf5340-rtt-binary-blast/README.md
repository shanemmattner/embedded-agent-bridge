# nRF5340 RTT Binary Blast

Maximum throughput test for the EAB binary RTT capture library. Streams a
synthetic 500 Hz sine wave as raw int16 samples over RTT channel 1.

## What it does

- Precomputes a 64-point sine lookup table (int16, amplitude +/- 26984)
- Tight loop fills 512-sample (1024 byte) chunks and writes to RTT channel 1
- Non-blocking skip mode: drops data rather than stalling the CPU
- Reports throughput stats on channel 0 (text) every second

## Measured throughput

| Probe | USB Speed | RTT Throughput | Sample Rate (int16) |
|-------|-----------|----------------|---------------------|
| J-Link OB (on DK) | Full Speed (12 Mbit) | ~145 KB/s | ~74 kHz |
| J-Link EDU | Hi-Speed (480 Mbit) | ~800 KB/s | ~400 kHz |

The bottleneck is USB speed, not SWD clock or CPU.

## Build and flash

```bash
west build -b nrf5340dk/nrf5340/cpuapp path/to/nrf5340-rtt-binary-blast
west flash --runner jlink
```

**WARNING**: Always use `west flash --runner jlink`. Never run a bare `erase`
on nRF5340 — it wipes UICR and locks the debug ports via APPROTECT. See
`scripts/nrf5340_recover.py` if this happens.

## Capture with EAB

```python
from eab.rtt_binary import RTTBinaryCapture
from eab.rtt_transport import JLinkTransport

capture = RTTBinaryCapture(
    transport=JLinkTransport(),
    device="NRF5340_XXAA_APP",
    channels=[1],
    sample_rate=32000,
    sample_width=2,
    output_path="blast.rttbin",
)
capture.start()
import time; time.sleep(5)
summary = capture.stop()
print(summary)

# Convert to numpy
data = capture.to_numpy()
print(f"Channel 1: {len(data[1])} samples")
```

## Use with the throughput benchmark

```bash
python3 scripts/rtt_throughput_bench.py --device NRF5340_XXAA_APP --duration 10
```
