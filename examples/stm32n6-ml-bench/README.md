# STM32N6 ML Benchmark (CPU-Only)

TFLite Micro inference benchmarks for NUCLEO-N657X0-Q using Zephyr RTOS, CMSIS-NN optimized kernels, and DWT cycle-accurate profiling.

## CPU vs NPU Comparison (person_detect — MobileNet V1 96x96x1 INT8)

| Backend | Runtime | Avg Time | Avg Cycles | Clock | Throughput | Speedup |
|---------|---------|----------|------------|-------|------------|---------|
| CPU (CMSIS-NN) | TFLite Micro | 226,970 us | 136,182,370 | 600 MHz | ~4.4 inf/s | 1x |
| **NPU (Neural-ART)** | LL-ATON | **1,563 us** | 1,251,021 | 800 MHz | ~640 inf/s | **145x** |

See examples/stm32n6-npu-bench/ for the NPU benchmark.

## Models Benchmarked (CPU-Only)

| Model | Input | Ops | Backend | Arena |
|-------|-------|-----|---------|-------|
| sine | 1 byte | FullyConnected | CMSIS-NN | ~800 B |
| person_detect | 96x96x1 (9216 B) | Conv2D, DWConv2D, AvgPool2D, Reshape, Softmax | CMSIS-NN | ~82 KB |
| micro_speech | 49x40 (1960 B) | Reshape, FullyConnected, DWConv2D, Softmax | CMSIS-NN | ~28 KB |

## Build

```bash
cd /Users/shane/zephyrproject
west build -b nucleo_n657x0_q/stm32n657xx examples/stm32n6-ml-bench -d build-stm32n6-mlbench --pristine
```

## Flash (SRAM Boot)

STM32N6 has no internal flash — firmware runs from SRAM:

```bash
CUBE_CLI=/Applications/STMicroelectronics/STM32Cube/STM32CubeProgrammer/STM32CubeProgrammer.app/Contents/Resources/bin/STM32_Programmer_CLI

# Load to SRAM
\$CUBE_CLI -c port=SWD mode=HOTPLUG -hardRst -halt
\$CUBE_CLI -c port=SWD mode=HOTPLUG -w build-stm32n6-mlbench/zephyr/zephyr.bin 0x34000000

# Boot via GDB (extract SP/PC from binary vector table first)
probe-rs gdb --chip STM32N657 --probe 0483:3754 &
arm-zephyr-eabi-gdb --batch -ex 'target remote :1337' -ex 'set \$sp=<SP>' -ex 'set \$pc=<RESET>' -ex 'set \$msp=<SP>' -ex 'c &' -ex 'disconnect' -ex 'quit'
```

Or use the regression test (handles everything automatically):
```bash
eabctl regression --test tests/hw/stm32n6_ml_bench.yaml --json
```

## Serial Output (115200 baud via Zephyr console)

```
=== STM32N6 ML Benchmark (NUCLEO-N657X0-Q) ===
Board: NUCLEO-N657X0-Q
CPU Frequency: 600000000 Hz
Arena: 143360 bytes (140 KB)

DWT profiler initialized

Model loaded: sine (size=2488 bytes)
Arena used: 852 / 143360 bytes
[ML_BENCH] model=sine backend=cmsis_nn cycles=... time_us=... input=1 ops=INT8 inferences=100

Model loaded: person_detect (size=300568 bytes)
Arena used: 82724 / 143360 bytes
[ML_BENCH] model=person_detect backend=cmsis_nn cycles=... time_us=... input=9216 ops=INT8 inferences=10

Model loaded: micro_speech (size=18712 bytes)
Arena used: 28056 / 143360 bytes
[ML_BENCH] model=micro_speech backend=cmsis_nn cycles=... time_us=... input=1960 ops=INT8 inferences=100

[ML_BENCH_DONE] board=nucleo_n657x0_q models=3
```

## Switching Between CPU and NPU

The CPU and NPU benchmarks use different toolchains and cannot be toggled with a simple #define:

| | CPU-Only (this example) | NPU (stm32n6-npu-bench/) |
|---|---|---|
| **RTOS** | Zephyr | Bare-metal |
| **ML Runtime** | TFLite Micro + CMSIS-NN | LL-ATON (ST Edge AI Core) |
| **Build** | west build (CMake) | make (armgcc Makefile) |
| **Model format** | .tflite (flatbuffer) | NPU microcode (.xSPI2.bin) |
| **External flash** | Not used | Weights at 0x71000000 |
| **UART baud** | 115200 (Zephyr default) | 921600 (app_config.h) |
| **Clock** | 600 MHz (no overdrive) | 800 MHz (overdrive) |

To run NPU benchmarks, see examples/stm32n6-npu-bench/README.md.

## See Also

- [SRAM Boot Guide](../../docs/stm32n6-sram-boot.md) — complete boot procedure, gotchas, and troubleshooting
- examples/stm32n6-npu-bench/ — NPU benchmark (145x faster for person_detect)
- examples/mcxn947-ml-bench/ — Same CPU benchmark on FRDM-MCXN947
- tests/hw/stm32n6_ml_bench.yaml — Automated regression test
