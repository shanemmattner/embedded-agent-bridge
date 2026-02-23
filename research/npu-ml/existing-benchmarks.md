# Existing NPU Benchmark Comparisons

_Generated 2026-02-23 from Firecrawl research_

## Key Finding: No Direct MCXN947 vs STM32N6 Comparison Exists

No published benchmarks compare the NXP MCXN947 Neutron NPU against the STM32N6 Neural-ART NPU side-by-side. This is our novel contribution.

## Published Benchmarks

### 1. uNPU-Bench (MobiCom '25) — Most Comprehensive
- **Source**: [arxiv.org/abs/2503.22567](https://arxiv.org/abs/2503.22567)
- **MCXN947 result**: 4.8 GOPS actual (vs 2 TOPS claimed by NXP)
- **42x NPU speedup** over CPU-only on MCXN947
- Tests MCXN947, MAX78000, MAX78002, Himax WE2 (Ethos-U55), CVITEK
- **Does NOT test STM32N6**
- Finding: "surprising disparities between specs and actual performance"

### 2. NXP eIQ Neutron NPU Benchmark (Vendor)
- **Source**: [NXP demo video](https://www.nxp.com/company/about-nxp/smarter-world-videos/NPU-BENCHMARK-MCXN947-VID)
- Claims up to 42x faster ML inference with NPU vs standalone CPU
- CIFAR-10 and face detection demos shown
- Vendor-provided, not independently verified

### 3. STM32N6 Neural-ART Claims (Vendor)
- **Source**: [ST blog post](https://blog.st.com/stm32n6/), [Fierce Sensors](https://www.fiercesensors.com/ai/stmicroelectronics-launches-mcu-npu-ai)
- 600 GOPS claimed (300 configurable MAC units)
- "600 times more ML performance than high-end STM32 MCU"
- No independent verification
- Object detection (YOLO) demonstrated on STM32N6570-DK

### 4. Medium Analysis (Independent Blogger)
- **Source**: [Medium — Exploring STM32N6](https://medium.com/@pkusolruangchai/exploring-stm32n6-f41df8e2e516)
- Notes STM32N6 is faster because "most heavy work doesn't run on CPU at all"
- NPU executes neural network ops directly
- Qualitative comparison, no quantitative benchmarks

## Spec Comparison (Claimed vs Known)

| | MCXN947 Neutron NPU | STM32N6 Neural-ART |
|---|---|---|
| **Vendor claimed** | Up to 2 TOPS | 600 GOPS |
| **Independent measured** | 4.8 GOPS (uNPU-Bench) | None published |
| **NPU vs CPU speedup** | 42x (NXP + uNPU-Bench) | 600x (ST claim, unverified) |
| **CPU core** | Cortex-M33 @ 150 MHz | Cortex-M55 + Helium |
| **Quantization** | INT8 only | INT8, W4A8 mixed |
| **Memory** | 512 KB SRAM | Internal + external XSPI2 flash |

## Why Our Benchmark Matters
1. **First independent STM32N6 Neural-ART benchmarks** — no one has published these
2. **First side-by-side comparison** of these two NPUs
3. **Same models, same methodology** — fair comparison unlike vendor demos
4. **DWT cycle counting** — hardware-level profiling, not just wall-clock time
5. **Multiple model categories** — not just one demo model
6. **EAB streaming** — continuous monitoring, not one-shot test

## Gaps in Existing Literature
- No standardized cross-vendor NPU benchmark suite (uNPU-Bench is closest)
- Vendor benchmarks use different models, inputs, and measurement methods
- End-to-end latency (including I/O, init) rarely reported
- Power consumption data sparse for both platforms
- No IMU/motion model benchmarks on either NPU (vision and audio dominate)
