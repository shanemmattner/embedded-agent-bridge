# STM32N6 Gait Phase Benchmark

Exoboot gait phase estimator (Shepherd et al., Georgia Tech EPIC Lab, ICRA 2022) benchmarked on NUCLEO-N657X0-Q using TFLite Micro with CMSIS-NN kernels and DWT cycle-accurate profiling.

## Model

| Property | Value |
|----------|-------|
| Source | [exoboot-ml-gait-state-estimator](https://github.com/maxshep/exoboot-ml-gait-state-estimator) (Apache 2.0) |
| Architecture | Conv1D(30,k=20)→BN → Conv1D(30,k=20)→BN → Conv1D(30,k=6) → 2 Dense heads |
| Input | (1, 44, 8) int8 — 44 timesteps × 8 channels (accel xyz, gyro xyz, ankle angle, ankle velocity) |
| Output 0 | gait_phase: (1,1,1) int8, scale=0.00245, zp=-128 → 0.0-1.0 (0-100% gait cycle) |
| Output 1 | stance_swing: (1,1,1) int8, scale=0.00391, zp=-128 → 0.0-1.0 (sigmoid) |
| Size | 43.3 KB (INT8 quantized) |
| TFLM Ops | ADD, CONV_2D, EXPAND_DIMS, FULLY_CONNECTED, LOGISTIC, MUL, RESHAPE (7 ops) |
| Arena | 32 KB |

## Build

```bash
cd /Users/shane/zephyrproject
west build -b nucleo_n657x0_q/stm32n657xx \
  /path/to/embedded-agent-bridge/examples/stm32n6-gait-bench \
  -d build-stm32n6-gait --pristine
```

## Flash (SRAM Boot)

See [docs/stm32n6-sram-boot.md](../../docs/stm32n6-sram-boot.md) for the complete procedure.

Quick reference:
```bash
CUBE_CLI=/Applications/STMicroelectronics/STM32Cube/STM32CubeProgrammer/STM32CubeProgrammer.app/Contents/Resources/bin/STM32_Programmer_CLI

$CUBE_CLI -c port=SWD mode=HOTPLUG -hardRst -halt
$CUBE_CLI -c port=SWD mode=HOTPLUG -w build-stm32n6-gait/zephyr/zephyr.bin 0x34000000

# Extract SP/PC, boot via GDB — see SRAM boot guide for full steps
```

Or use the regression test:
```bash
eabctl regression --test tests/hw/stm32n6_gait_bench.yaml --json
```

## Expected Serial Output (115200 baud)

```
=== STM32N6 Gait Phase Benchmark (NUCLEO-N657X0-Q) ===
Board: NUCLEO-N657X0-Q
CPU Frequency: 600000000 Hz
Arena: 32768 bytes (32 KB)

DWT profiler initialized

Model loaded: exoboot_gait (size=44312 bytes)
Arena used: XXXX / 32768 bytes
Warm-up inference: gait_phase=XX.X% stance_swing=X.XXX
[ML_BENCH] model=exoboot_gait backend=cmsis_nn cycles=XXX time_us=XXX input=352 ops=INT8 inferences=100

[ML_BENCH_DONE] board=nucleo_n657x0_q models=1
```

## See Also

- [SRAM Boot Guide](../../docs/stm32n6-sram-boot.md) — complete flash procedure and troubleshooting
- [STM32N6 ML Bench](../stm32n6-ml-bench/) — multi-model CPU benchmark (sine, person_detect, micro_speech)
- [STM32N6 NPU Bench](../stm32n6-npu-bench/) — NPU benchmark (145x faster for person_detect)
- [Regression Test](../../tests/hw/stm32n6_gait_bench.yaml) — automated test YAML
- [Original Paper](https://github.com/maxshep/exoboot-ml-gait-state-estimator) — Shepherd et al., ICRA 2022
