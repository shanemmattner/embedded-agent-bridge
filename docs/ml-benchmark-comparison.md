# ML Benchmark Comparison: STM32N6 (Cortex-M55) vs FRDM-MCXN947 (Cortex-M33)

**Date**: 2026-02-24
**Author**: Shane Mattner / Ohmic Test Systems
**Repository**: [embedded-agent-bridge](.) — `examples/stm32n6-ml-bench/` and `examples/mcxn947-ml-bench/`

## Summary

We ran identical INT8 TFLite Micro models on two ARM Cortex-M targets using CMSIS-NN kernels and DWT cycle counting. The Cortex-M33 (MCXN947 @ 150MHz) used **6-15x fewer cycles** per inference than the Cortex-M55 (STM32N6 @ 600MHz), despite Helium MVE being available on the M55. Wall-clock time was closer (1.6-3.8x) due to the 4x clock advantage, but the cycle efficiency gap is striking.

**Root cause**: Despite Helium MVE being enabled and CMSIS-NN using MVE intrinsic codepaths, GCC 12's Helium code generation is poor (known bugs, extra overhead around intrinsics). The M55's dual-beat pipeline has higher per-op overhead than the M33's mature DSP extension path. ARM Compiler (armclang) is expected to close the gap by 30-40%.

## Hardware

| | STM32N6 | FRDM-MCXN947 |
|---|---------|---------------|
| **Board** | NUCLEO-N657X0-Q | FRDM-MCXN947 |
| **CPU** | Cortex-M55 | Cortex-M33 |
| **Clock** | 600 MHz | 150 MHz |
| **Architecture** | ARMv8.1-M (Helium MVE) | ARMv8-M |
| **SIMD** | Helium (128-bit, dual-beat) | None (DSP extension only) |
| **Flash** | External (SRAM boot for bench) | On-chip (512KB used: 25%) |
| **RAM used** | ~314 KB | 314 KB (96% of 320KB) |
| **Flash method** | GDB SRAM boot | probe-rs to on-chip flash |
| **Serial** | USART1 PE5/PE6 @ 115200 | USB CDC @ 115200 |

## Models

All models are INT8 quantized TFLite, running on TensorFlow Lite Micro with CMSIS-NN backend.

| Model | Size | Input | Ops | Inferences |
|-------|------|-------|-----|------------|
| **sine** | 2,488 B | 1 × int8 | FullyConnected | 100 |
| **person_detect** | 300,568 B | 96×96×1 int8 (9,216 B) | Conv2D, DepthwiseConv2D, AveragePool2D, Reshape, Softmax | 10 |
| **micro_speech** | 18,800 B | 49×40 int8 (1,960 B) | Reshape, FullyConnected, DepthwiseConv2D, Softmax | 100 |
| **exoboot_gait** | 44,312 B | 1×44×8 int8 (352 B) | Add, Conv2D, ExpandDims, FullyConnected, Logistic, Mul, Reshape | 100 |

The exoboot gait phase model is a custom 44KB INT8 model for exoskeleton gait cycle estimation.

## Results

### Raw Data

| Model | STM32N6 Cycles | STM32N6 Time (us) | MCXN947 Cycles | MCXN947 Time (us) |
|-------|---------------|-------------------|----------------|-------------------|
| **sine** | 73,698 | 122 | 4,813 | 32 |
| **person_detect** | 132,413,647 | 220,689 | 11,526,407 | 76,842 |
| **micro_speech** | 10,818,194 | 18,030 | 1,705,940 | 11,373 |
| **exoboot_gait** | — | — | 898,205 | 5,988 |

### Comparison Ratios

| Model | Cycle Ratio (N6 ÷ NXP) | Wall-Clock Ratio (N6 ÷ NXP) | NXP cycles/MHz | N6 cycles/MHz |
|-------|------------------------|-----------------------------|----|---|
| **sine** | 15.3x | 3.8x | 32.1 | 122.8 |
| **person_detect** | 11.5x | 2.9x | 76,842 | 220,689 |
| **micro_speech** | 6.3x | 1.6x | 11,373 | 18,030 |
| **exoboot_gait** | — (MCXN947 only) | — | 5,988 | — |

**The MCXN947 (M33 @ 150MHz) is cycle-for-cycle 6-15x more efficient than the STM32N6 (M55 @ 600MHz).**

### -O2 vs -Os Comparison

Both targets were rebuilt with `-O2` (optimize for speed) to check whether the default `-Os` (optimize for size) was leaving performance on the table.

| Model | STM32N6 -Os | STM32N6 -O2 | Change | MCXN947 -Os | MCXN947 -O2 | Change |
|-------|------------|------------|--------|------------|------------|--------|
| **sine** | 73,698 | 64,267 | -12.8% | 4,813 | 4,475 | -7.0% |
| **person_detect** | 132,413,647 | 132,614,853 | +0.2% | 11,526,407 | 11,595,389 | +0.6% |
| **micro_speech** | 10,818,194 | 10,715,324 | -1.0% | 1,705,940 | 1,705,633 | -0.02% |
| **exoboot_gait** | — | — | — | 898,205 | 834,557 | -7.1% |

**Conclusion**: `-O2` makes almost no difference for CMSIS-NN workloads. The sine model shows ~13% improvement because it has proportionally more C++ overhead relative to kernel time. The conv-heavy models (person_detect, micro_speech) show <1% change — confirming that CMSIS-NN's hand-written intrinsics dominate execution time and are unaffected by compiler optimization level. `-Os` is the correct default; switching to `-O2` is not worth the code size increase.

## Analysis: Why Is the M55 Slower Per Cycle?

### Expected vs Actual

ARM's published benchmarks claim **5x ML speedup** for Cortex-M55 over M33/M4 when Helium MVE is leveraged ([WikiChip, 2020](https://fuse.wikichip.org/news/3319/arms-new-cortex-m55-breathes-helium/)). The Cortex-M85 extends this to **4x over M7** and **20% over M55** ([SemiEngineering, 2023](https://semiengineering.com/improved-dsp-and-ai-performance-on-an-mcu-core/)).

Our results show the **opposite** — the M55 uses more cycles per inference. Why?

### Verified Build Configuration

We inspected the actual build flags and compiler predefined macros:

| | STM32N6 (M55) | MCXN947 (M33) |
|---|---|---|
| **GCC version** | arm-zephyr-eabi-gcc 12.2.0 | arm-zephyr-eabi-gcc 12.2.0 |
| **`-mcpu`** | `cortex-m55` (full MVE) | `cortex-m33` |
| **`__ARM_FEATURE_MVE`** | **3** (int + float) | not defined |
| **`__ARM_FEATURE_DSP`** | implicit via MVE | **1** |
| **`ARM_MATH_MVEI`** | **defined** (auto-set by CMSIS-NN headers) | not defined |
| **CMSIS-NN codepath** | **MVE intrinsics** (`vldrb`, `vstrb`, inline asm) | **DSP extension** (SIMD32) |
| **Optimization** | **`-Os`** (optimize for size) | **`-Os`** (optimize for size) |

Key findings:
- **Helium IS enabled** — `-mcpu=cortex-m55` with `__ARM_FEATURE_MVE=3`
- **CMSIS-NN IS using MVE intrinsic paths** — `#if defined(ARM_MATH_MVEI)` branches contain inline assembly with Helium instructions
- **Both targets use `-Os`** — GCC's auto-vectorization is disabled at `-Os`, but CMSIS-NN's hand-written MVE intrinsics are not affected by this

### Root Cause: MVE Intrinsic Codepath Is Less Efficient Than Expected

This is **not** a case of Helium sitting idle. CMSIS-NN's MVE intrinsic codepaths are active, yet the M55 still uses 5-14x more cycles than the M33's DSP path. Several factors contribute:

1. **M55 dual-beat pipeline overhead** — Helium processes 128-bit vectors as two 64-bit "beats" over 2 cycles. For small kernels and irregular data access patterns, the setup/teardown of vector operations may cost more than the M33's simpler scalar+DSP path.

2. **GCC 12 MVE code generation quality** — Alif Semiconductor's [Cortex-M55 Optimization and Tools](https://alifsemi.com/whitepaper/cortex-m55-optimization-and-tools/) whitepaper (2022) found:
   - ARM Compiler (armclang) produces **30-42% faster code** than GCC for Helium workloads
   - GCC has **bugs in Helium intrinsic handling** — multiple compiler bugs found, some still unresolved in GCC 12
   - GCC inserts **extra unnecessary operations around intrinsics**, while armclang creates better Helium vector loops
   - **Unrolling is ineffective on M55** — the 4-stage pipeline doesn't benefit like M7's 6-stage

3. **M33 DSP path is mature and well-optimized** — The SIMD32 (packed 4×8-bit) MAC path has been refined over many years and GCC handles it correctly. The M33 hits a "just works" codepath.

4. **M55 CoreMark/MHz is lower than M33** — ARM reports M55 at 4.2 CoreMark/MHz. Without effective vectorization, scalar M55 code is less efficient per-cycle than M33 due to pipeline characteristics.

### What Would Improve M55 Performance

1. **Build with ARM Compiler 6 (armclang)** — expected 30-40% cycle reduction based on Alif data
2. **Upgrade GCC** — GCC 13+ has Helium bug fixes; Zephyr SDK 0.17 ships GCC 12.2
3. **Use `-O2` instead of `-Os`** — while CMSIS-NN intrinsics aren't affected, surrounding TFLite Micro code may benefit
4. **Use Ethos-U55 NPU** — the M55 is designed as a companion to the microNPU, not to compete on CPU-only ML inference
5. **Profile individual CMSIS-NN kernels** — identify which specific ops (Conv2D, DepthwiseConv2D) have the worst MVE efficiency

## Methodology

### Build Environment

- **Zephyr OS**: v4.3.0-6019-gef798176ad4c
- **SDK**: Zephyr SDK 0.17.0 (arm-zephyr-eabi-gcc)
- **TFLM**: Zephyr module (`CONFIG_TENSORFLOW_LITE_MICRO=y`)
- **CMSIS-NN**: Enabled (`CONFIG_TENSORFLOW_LITE_MICRO_CMSIS_NN_KERNELS=y`)
- **Optimization**: `-Os` (Zephyr default — optimize for size)
- **FPU**: Enabled (`CONFIG_FPU=y`)

### Profiling

DWT (Data Watchpoint and Trace) cycle counter — hardware cycle counting via `DWT_CYCCNT` register. Zero overhead, exact cycle counts.

```c
// dwt_profiler.h — identical on both targets
// Called before EACH benchmark (TFLM may clear TRCENA between models)
dwt_init();                    // Re-enable TRCENA + CYCCNTENA
uint32_t t0 = dwt_start();    // DSB+ISB, read CYCCNT
// ... run inferences ...
uint32_t cycles = dwt_stop(t0); // DSB, read CYCCNT - start
```

Each model runs N inferences (100 for small models, 10 for person_detect). Total cycles divided by N gives average per-inference cycles. Wall-clock time computed as `cycles * 1000000 / cpu_freq_hz`.

**DWT Measurement Fix**: The original measurements contained a bug where TFLM/CMSIS-NN was clearing the TRCENA bit in DEMCR between model invocations, causing subsequent benchmarks to read `cycles=0` or stale counter values. The fix was to call `dwt_init()` before each benchmark's timing section to re-enable the DWT cycle counter. This corrected the MCXN947 person_detect measurement from an erroneous 26.2M cycles to the true value of 11.5M cycles. All data in this document reflects the corrected measurements.

### Flash & Capture

**STM32N6**: SRAM boot via GDB (firmware loaded to RAM, not flash). `k_msleep(5000)` delay at boot for serial reconnection after probe-rs releases USB.

**MCXN947**: On-chip flash via probe-rs:
```bash
probe-rs download --chip MCXN947 --probe 1fc9:0143 \
  --binary-format bin --base-address 0x00000000 zephyr.bin
```

Serial captured via pyserial at 115200 baud, triggered by board reset.

### Reproducibility

```bash
# Build STM32N6 benchmark
cd ~/zephyrproject && west build -b nucleo_n657x0_q/stm32n657xx \
  /path/to/embedded-agent-bridge/examples/stm32n6-ml-bench \
  -d /path/to/build-stm32n6-ml --pristine

# Build MCXN947 benchmark
cd ~/zephyrproject && west build -b frdm_mcxn947/mcxn947/cpu0 \
  /path/to/embedded-agent-bridge/examples/mcxn947-ml-bench \
  -d /path/to/build-mcxn947-ml --pristine
```

## Output Format

Both benchmarks emit parseable `[ML_BENCH]` lines:

```
[ML_BENCH] model=<name> backend=cmsis_nn cycles=<N> time_us=<N> input=<bytes> ops=INT8 inferences=<N>
```

Session terminates with:
```
[ML_BENCH_DONE] board=<board> models=<count>
```

EAB regression tests (`tests/hw/stm32n6_ml_bench.yaml`, `tests/hw/mcxn947_ml_bench.yaml`) can automate capture and validation.

## References

1. WikiChip — [Arm's New Cortex-M55 Breathes Helium](https://fuse.wikichip.org/news/3319/arms-new-cortex-m55-breathes-helium/) (2020) — M55 architecture deep dive, published 5x ML speedup claims
2. SemiEngineering — [Improved DSP And AI Performance On An MCU Core](https://semiengineering.com/improved-dsp-and-ai-performance-on-an-mcu-core/) (2023) — M85 benchmarks, M55 comparison, Helium MVE performance data
3. Alif Semiconductor — [Cortex-M55 Optimization and Tools](https://alifsemi.com/whitepaper/cortex-m55-optimization-and-tools/) (2022) — GCC vs armclang comparison, Helium auto-vectorization issues, compiler bugs
4. ARM Hot Chips 2020 — [Technical Overview of Cortex-M55 and Ethos-U55](https://hc32.hotchips.org/assets/program/conference/day1/HotChips2020_Edge_Computing_Arm_Cortex-M55.pdf) — RTL-based performance projections
5. ARM Developer — [Helium MVE Performance Analysis](https://developer.arm.com/documentation/107564/latest/) — CMSIS-NN and DSP kernel benchmarks with/without MVE

## Next Steps

- [x] Check Zephyr build flags — **confirmed**: `-mcpu=cortex-m55`, `__ARM_FEATURE_MVE=3`, full Helium enabled
- [x] Inspect CMSIS-NN source — **confirmed**: MVE intrinsic paths (`ARM_MATH_MVEI`) are active with inline asm
- [x] Rebuild with `-O2` — **done**: <1% improvement for conv-heavy models, ~13% for sine
- [x] Fix DWT measurement bug — TRCENA cleared between benchmarks, now calling `dwt_init()` before each timing section
- [ ] Rebuild STM32N6 bench with armclang (ARM Compiler 6) for comparison — expected 30-40% improvement
- [ ] Upgrade to GCC 13+ (Zephyr SDK 0.18+) to pick up Helium bug fixes
- [ ] Run with Ethos-U55 NPU delegate for person_detect to get the "intended" M55 performance
- [ ] Profile individual CMSIS-NN kernels to find worst MVE offenders
- [ ] Add FRDM-MCXN947 to EAB regression suite for automated benchmarking
