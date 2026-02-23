# Overnight Plan: NPU ML Benchmarks — MCXN947 + STM32N6

_2026-02-23. Branch: `feat/npu-ml-benchmarks`_

## Goal

Benchmark on-device machine learning inference on two NPU-equipped dev boards using **pre-trained open-source models only**. No custom model training. Get both boards producing DWT-profiled inference results streaming through EAB.

## Hardware

| Board | MCU | NPU | NPU Specs | SDK/Runtime |
|-------|-----|-----|-----------|-------------|
| FRDM-MCXN947 | Cortex-M33 @ 150 MHz | eIQ Neutron NPU | INT8, up to 2 TOPS (claimed) | MCUXpresso SDK + eIQ TFLite Micro |
| STM32N6 | Cortex-M55 + Helium | Neural-ART NPU | INT8, up to 600 GOPS (claimed) | STM32Cube.AI + Neural-ART runtime |

## Model Categories

### 1. IMU / Motion Classification
_Directly relevant to exoskeleton work — IMU-based gait/gesture recognition_

| Model | Input Shape | Size | Source |
|-------|-------------|------|--------|
| Gesture recognition (magic wand) | 128x3 float | ~20 KB | TFLite Micro examples |
| Activity recognition (HAR) | varies | ~50 KB | Edge Impulse / TFLite hub |
| Gait phase detection | IMU windows | ~30 KB | Research repos |

### 2. Image Classification
_Tests NPU memory bandwidth and larger model support_

| Model | Input Shape | Size | Source |
|-------|-------------|------|--------|
| Person detection | 96x96x1 INT8 | ~300 KB | TFLite Micro examples |
| MobileNet v1 0.25 | 128x128x3 INT8 | ~500 KB | TF model garden |
| MobileNet v2 | 224x224x3 INT8 | ~3 MB | TF model garden (may not fit) |
| CIFAR-10 classifier | 32x32x3 INT8 | ~50 KB | Various |

### 3. Audio / Keyword Spotting
_Mid-size models, streaming inference pattern_

| Model | Input Shape | Size | Source |
|-------|-------------|------|--------|
| Micro speech (yes/no) | 49x40 INT8 | ~20 KB | TFLite Micro examples |
| Keyword spotting (DS-CNN) | MFCC features | ~80 KB | MLPerf Tiny / ARM |
| Anomaly detection (DCASE) | Mel spectrogram | ~100 KB | MLPerf Tiny |

### 4. uNPU-Bench Suite
_Published ACM MobiCom '25 benchmark — reproduce their MCXN947 results, add STM32N6 data_

| Model | What | Source |
|-------|------|--------|
| Various CNNs | Standardized NPU benchmark suite | github.com/j0shmillar/uNPU-Bench |

---

## Workstream 1: Research (Firecrawl)

**Agent**: Main session (Firecrawl skill)
**Output**: `research/npu-ml/` directory with findings

### Tasks

1. **NXP eIQ Model Zoo** — scrape NXP's eIQ portal for pre-trained .tflite models compatible with MCXN947 Neutron NPU. Get model list, sizes, supported ops, example projects.

2. **STM32Cube.AI Model Zoo** — scrape ST's model zoo for Neural-ART compatible models. Get STM32N6-specific examples, deployment guides, model conversion steps.

3. **uNPU-Bench repo** — clone and analyze. Understand their benchmark methodology, which models they tested, how they measured, what MCXN947 results they got. Identify what we need to reproduce.

4. **TFLite Micro examples** — catalog all pre-trained models in the official tflite-micro repo. Focus on: person_detect, micro_speech, magic_wand, hello_world.

5. **MLPerf Tiny** — scrape the MLPerf Tiny benchmark suite. They have standardized models for keyword spotting, visual wake words, image classification, anomaly detection. All pre-trained.

6. **IMU/motion models** — search for pre-trained gesture/activity/gait models in .tflite format. Edge Impulse public projects, TensorFlow Hub, GitHub repos.

7. **NXP MCXN947 + eIQ Neutron NPU getting started** — find the official getting-started guide, SDK setup, how to deploy a .tflite model to the Neutron NPU. Any gotchas, required toolchain versions.

8. **STM32N6 Neural-ART getting started** — find ST's deployment guide for Neural-ART. STM32Cube.AI workflow, model quantization requirements, memory constraints.

9. **Existing benchmark comparisons** — search for anyone who has already compared these two NPUs. Blog posts, papers, forum threads. Know the landscape before we benchmark.

---

## Workstream 2: MCXN947 Firmware (MiniMax agents)

**Agent**: `/minimax` delegated tasks
**Prereqs**: Research from Workstream 1
**Output**: `examples/mcxn947-ml-bench/` directory

### Tasks

1. **Scaffold project** — Create Zephyr or MCUXpresso SDK project for MCXN947 with TFLite Micro + eIQ Neutron NPU enabled. Use existing NXP SDK examples as starting point (don't write from scratch).

2. **Integrate first model** — person_detect or micro_speech .tflite. Load model, allocate tensors, run inference with dummy input. Print result + cycle count via serial.

3. **Add DWT profiling** — wrap inference call with DWT cycle counter reads. Report: total cycles, cycles per layer (if TFLite Micro exposes per-op profiling), inference time in microseconds.

4. **NPU vs CPU toggle** — build with and without NPU delegate. Same model, same input, measure both paths. Output comparison.

5. **EAB integration** — output results in EAB-parseable format:
   ```
   [ML_BENCH] model=person_detect backend=npu cycles=12345 time_us=82 input=96x96x1 ops=INT8
   [ML_BENCH] model=person_detect backend=cpu cycles=567890 time_us=3786 input=96x96x1 ops=INT8
   ```

6. **Multi-model runner** — load multiple .tflite models sequentially, benchmark each, produce summary table over serial.

7. **YAML regression test** — write `tests/hw/mcxn947_ml_bench.yaml` that flashes firmware, waits for benchmark output, validates results.

---

## Workstream 3: STM32N6 Firmware (MiniMax agents)

**Agent**: `/minimax` delegated tasks
**Prereqs**: Research from Workstream 1
**Output**: `examples/stm32n6-ml-bench/` directory

### Tasks

1. **Scaffold project** — STM32Cube or Zephyr project for STM32N6 with STM32Cube.AI + Neural-ART runtime. Use ST's example projects as starting point.

2. **Integrate first model** — same model as MCXN947 (person_detect or micro_speech) for direct comparison. Load, run inference, print results.

3. **Add DWT profiling** — same DWT cycle counting approach. Cortex-M55 + Helium may have additional performance counters.

4. **NPU vs CPU toggle** — Neural-ART NPU path vs Cortex-M55 software path. Same model, same input.

5. **EAB integration** — same `[ML_BENCH]` output format for cross-board comparison.

6. **Multi-model runner** — same multi-model approach, sequential benchmarks.

7. **YAML regression test** — write `tests/hw/stm32n6_ml_bench.yaml`.

---

## Workstream 4: Board Auto-Detection + Regression Tests

**Agent**: `/minimax` delegated tasks
**Output**: `eab/auto_detect.py` + `tests/hw/` YAML files

### Tasks

1. **USB auto-detection script** — `eabctl detect` scans USB devices (via `ioreg` or `pyserial`), matches VID:PID + serial numbers against `devices.json`, reports which boards are connected and on which ports. Handles port renumbering gracefully.

2. **Port update command** — `eabctl detect --update` writes corrected ports back to `devices.json` so we never have stale port mappings again.

3. **Per-board YAML regression tests** — one test file per board:
   - `tests/hw/esp32_c6_smoke.yaml` — flash, wait for boot, verify output
   - `tests/hw/esp32_p4_smoke.yaml`
   - `tests/hw/esp32_s3_smoke.yaml`
   - `tests/hw/nrf5340_smoke.yaml`
   - `tests/hw/mcxn947_smoke.yaml`
   - `tests/hw/stm32l4_smoke.yaml`
   - `tests/hw/stm32n6_smoke.yaml`
   - `tests/hw/c2000_smoke.yaml`

4. **Fix devices.json** — rename `stm32-n6` entry with correct chip info, update C2000 port to actual detected value.

---

## Execution Order

```
Phase 0 — Research (serial, blocks everything)
  Firecrawl: NXP eIQ, STM32Cube.AI, uNPU-Bench, TFLite Micro, MLPerf Tiny
  Output: research/npu-ml/ with model inventory + SDK guides

Phase 1 — Scaffold + First Model (parallel)
  /minimax: MCXN947 scaffold + person_detect
  /minimax: STM32N6 scaffold + person_detect
  /minimax: Board auto-detection script

Phase 2 — DWT Profiling + NPU/CPU Toggle (parallel)
  /minimax: MCXN947 DWT profiling + NPU vs CPU
  /minimax: STM32N6 DWT profiling + NPU vs CPU
  /minimax: YAML regression tests for all boards

Phase 3 — Multi-Model Benchmarks (parallel)
  /minimax: MCXN947 multi-model runner (motion, image, audio)
  /minimax: STM32N6 multi-model runner (motion, image, audio)

Phase 4 — Cross-Board Comparison
  /minimax: Generate comparison table, Perfetto traces
  /minimax: uNPU-Bench reproduction if models available
```

## Success Criteria

- [ ] Both boards running ML inference with DWT cycle counts streaming to EAB
- [ ] At least 3 model categories benchmarked (motion, image, audio) on each board
- [ ] NPU vs CPU comparison data for each model on each board
- [ ] `eabctl detect` auto-identifies all connected boards
- [ ] YAML smoke tests pass for all 7+ boards
- [ ] Results in `[ML_BENCH]` format parseable by EAB
- [ ] Cross-board comparison table (MCXN947 vs STM32N6) generated

## Key Constraint

**No custom code from scratch.** Use existing:
- NXP eIQ SDK examples
- STM32Cube.AI example projects
- TFLite Micro example code
- uNPU-Bench benchmark harness
- Adapt and integrate only — Firecrawl finds it, MiniMax adapts it.

## Output Artifacts

```
research/npu-ml/
  model-inventory.md          # All discovered pre-trained models
  mcxn947-eiq-guide.md        # NXP eIQ + Neutron NPU setup
  stm32n6-neural-art-guide.md # ST Neural-ART setup
  unpu-bench-analysis.md      # uNPU-Bench methodology + results
  existing-benchmarks.md      # What others have published

examples/mcxn947-ml-bench/    # MCXN947 benchmark firmware
examples/stm32n6-ml-bench/    # STM32N6 benchmark firmware

eab/auto_detect.py            # USB board auto-detection
tests/hw/*.yaml               # Per-board regression tests

docs/npu-benchmark-results.md # Cross-board comparison table
```
