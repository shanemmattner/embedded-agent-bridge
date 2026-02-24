# ML Benchmark Results — 2026-02-23

## Hardware

| Board | MCU | Core | Clock | Memory | NPU | Debug |
|-------|-----|------|-------|--------|-----|-------|
| FRDM-MCXN947 | MCXN947 | Cortex-M33 | 150 MHz | 512KB SRAM, 2MB Flash | eIQ Neutron N1-16 (4.8 GOPS) | CMSIS-DAP |
| NUCLEO-N657X0-Q | STM32N657 | Cortex-M55 | 600 MHz | 4.2MB SRAM | Neural-ART (600 GOPS) | ST-Link V3 |

## CPU-Only Results (CMSIS-NN, INT8, DWT profiled)

| Model | MCXN947 Cycles | MCXN947 Time | STM32N6 Cycles | STM32N6 Time | Notes |
|-------|---------------|-------------|---------------|-------------|-------|
| sine (FC only) | 4,814 | 32 us | 68,346 | 113 us | 1 input, 100 inferences |
| person_detect (CNN) | 26,316,498 | 175 ms | 136,182,370 | 227 ms | 96x96x1, 10 inferences |
| micro_speech (CNN) | 1,716,853 | 11.4 ms | 13,637,906 | 22.7 ms | 1960 input, 100 inferences |

## Key Findings

1. **MCXN947 (M33) is faster than STM32N6 (M55) in wall-clock time** despite 4x lower clock speed
   - Likely causes: SRAM execution penalty on N6, suboptimal M55 CMSIS-NN kernels, or cache/bus config
   - M33 has better-optimized CMSIS-NN DSP extensions for INT8
   - N6 running from SRAM (no flash) — may have alignment or wait-state issues

2. **DWT profiling accurate** after fixing counter reset bug (dwt_reset vs dwt_init)

3. **Arena sizing**: person_detect needs ~83KB tensor arena (was failing on N6 with 32KB default)

---

## NPU Hardware Acceleration Research

### MCXN947 — eIQ Neutron NPU (N1-16)

- **Performance**: 4.8 GOPS (8-bit), **42x faster than CPU-only** (NXP claim)
- **Toolchain**: eIQ Toolkit (MCUXpresso SDK) — NOT TFLite Micro directly
- **Workflow**: Train model (TF/PyTorch) → export ONNX/TFLite → eIQ Toolkit converts to Neutron NPU binary → link into MCUXpresso project
- **NXP community guide**: "MCXN947: How to Train and Deploy Customer ML model to NPU" (ta-p/1899497)
- **Key limitation**: NPU lacks native softmax — needs CPU post-processing step
- **eIQ Glow**: Ahead-of-time compiler for i.MX RT crossover MCUs (NOT directly for MCXN947 NPU — Glow targets CMSIS-NN/HiFi DSP, Neutron NPU uses its own compiler)
- **SDK**: MCUXpresso SDK with eIQ component — download via MCUXpresso SDK Builder
- **NOT Zephyr compatible** — NPU requires NXP's proprietary eIQ runtime, not available in Zephyr

### STM32N6 — Neural-ART Accelerator

- **Performance**: 600 GOPS with ~300 configurable MACs, **3 TOPS/W efficiency**
- **Toolchain**: ST Edge AI Core (CLI) or STM32Cube.AI (CubeMX plugin)
- **Workflow**: Train model → export TFLite/ONNX/Keras → `stedgeai generate --target stm32n6` → generates C code with NPU dispatch → build with STM32Cube
- **Model Zoo**: github.com/STMicroelectronics/stm32ai-modelzoo — pre-optimized models for person detection, pose estimation, image classification, audio scene recognition
- **Developer Cloud**: Online board farm for benchmarking — upload model, get real timing on physical N6 boards
- **Key advantage**: Supports largest number of TFLite/ONNX operators at launch; ONNX support means broader model compatibility
- **CPU clock**: Actually 800 MHz max (we're running at 600 MHz in Zephyr)
- **NOT raw TFLite Micro** — Neural-ART requires ST's code generator, can't use vanilla TFLite Micro interpreter for NPU

### Academic Benchmark (arXiv 2503.22567 — "Benchmarking Ultra-Low-Power μNPUs")

Independent benchmark of MCXN947 vs other μNPUs (first third-party evaluation):
- Open-source toolchain: github.com/j0shmillar/uNPU-Bench
- MCXN947 NPU: 4.8 GOPS, 512KB RAM, designed for lower-power applications
- Paper found "surprising disparities between hardware specifications and actual performance"
- End-to-end latency includes NPU init, memory I/O, and CPU pre/post-processing overhead

### NPU Integration Path (Both Boards)

**Problem**: Both NPUs require vendor-specific toolchains (NXP eIQ / ST Edge AI Core). Neither works with vanilla TFLite Micro — the NPU needs compiled model binaries from vendor tools, not interpreted TFLite flatbuffers.

**Options**:
1. **Dual firmware**: Keep TFLite Micro CPU-only for portability + add NPU variant using vendor SDK
2. **Vendor SDK only**: Switch to MCUXpresso (NXP) / STM32Cube (ST) — lose Zephyr RTOS
3. **Hybrid**: Use Zephyr for RTOS + link vendor NPU library as external module

**Recommended**: Option 1 — build NPU benchmarks as separate MCUXpresso/STM32Cube projects, compare against current Zephyr+TFLite numbers. Keep both for the portfolio.

---

## Robotics Inference Use Case

### Scenario: IMU + Motor Angles → Control Command

- **Inputs**: 6-axis IMU (accel xyz, gyro xyz) + N motor angles = ~10-20 values
- **Model**: Small FC network (3 layers, 64 hidden units) or small RNN/LSTM
- **Model size**: <50KB weights, <10KB arena
- **Quantization**: INT8 for MCU deployment

### Latency Estimates (CPU-only, based on our benchmarks)

| Model Complexity | Est. Cycles (MCXN947) | Est. Time (MCXN947) | Control Loop Rate |
|-----------------|----------------------|--------------------|--------------------|
| Tiny FC (sine-like) | ~5K | ~33 us | 30 kHz |
| Small FC (3x64) | ~50K | ~333 us | 3 kHz |
| Medium FC (3x128) | ~200K | ~1.3 ms | 750 Hz |
| Small LSTM (32 units) | ~500K | ~3.3 ms | 300 Hz |

**All well within 1kHz control loop** for typical robotics. Even the medium FC leaves >98% CPU headroom at 1kHz.

### With NPU Acceleration

- MCXN947 NPU (42x speedup claim): Small FC → ~8 us, Medium FC → ~31 us → **10+ kHz control possible**
- STM32N6 NPU (600 GOPS): Would be overkill for small FC, but enables running larger models (transformers, attention-based controllers) in real-time

### What to Build

A robotics control demo firmware:
1. Read IMU data (real or synthetic) at 1kHz
2. Feed through trained FC/RNN model
3. Output motor command (PWM values or target angles)
4. Benchmark: inference latency, total loop time, jitter

Model training: sim-to-real with PyBullet or MuJoCo → export TFLite INT8 → deploy

---

## Test Infrastructure

- Regression YAMLs: `tests/hw/mcxn947_ml_bench.yaml`, `tests/hw/stm32n6_ml_bench.yaml`
- Step types: `bench_capture` (parse ML_BENCH lines), `sram_boot` (STM32N6 SRAM load)
- Run: `eabctl regression --test tests/hw/<board>_ml_bench.yaml --json`

## Next Steps

### Phase 1: NPU Benchmarks (compare CPU vs NPU on same models)
- [ ] Build MCXN947 person_detect with eIQ Neutron NPU (MCUXpresso project)
- [ ] Build STM32N6 person_detect with Neural-ART NPU (ST Edge AI Core)
- [ ] Add NPU results to this doc — measure speedup vs CPU-only baseline

### Phase 2: Robotics Control Model
- [ ] Train small FC controller in sim (PyBullet: IMU+joints → torque)
- [ ] Export TFLite INT8, deploy on both boards
- [ ] Measure inference latency at 1kHz loop rate
- [ ] Compare CPU vs NPU inference for control model

### Phase 3: Infrastructure
- [ ] Historical benchmark tracking (JSON append, compare across versions)
- [ ] CI/CD with self-hosted runner (GitHub Actions)
- [ ] Add NPU benchmark regression tests
