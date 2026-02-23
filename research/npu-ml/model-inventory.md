# NPU ML Benchmark — Pre-Trained Model Inventory

_Generated 2026-02-23 from Firecrawl research_

## 1. Image Classification

| Model | Input Shape | Size | Quant | Source | MCXN947 | STM32N6 | Notes |
|-------|-------------|------|-------|--------|---------|---------|-------|
| Person Detection | 96x96x1 | ~300KB | INT8 | [TFLite Micro](https://github.com/tensorflow/tflite-micro/tree/main/tensorflow/lite/micro/examples/person_detection) | Yes | Yes | Binary classification, greyscale |
| CIFAR-10 CNN | 32x32x3 | ~50KB | INT8 | NXP eIQ `tflm_cifar10` SDK example | Yes | Yes | NXP has working MCXN947 example |
| MobileNet v1 0.25 | 128x128x3 | ~500KB | INT8 | TF Model Garden | Yes | Yes | Smallest MobileNet variant |
| MobileNet v2 | 224x224x3 | ~3MB | INT8 | TF Model Garden | Maybe | Yes | May exceed MCXN947 512KB SRAM |
| Visual Wake Words | 96x96x3 | ~250KB | INT8 | [MLPerf Tiny](https://github.com/mlcommons/tiny) | Yes | Yes | MobileNet v1 based, person/no-person |
| STM32 Zoo IC models | Various | Various | INT8/Mixed | [stm32ai-modelzoo](https://github.com/STMicroelectronics/stm32ai-modelzoo) | No | Yes | 24 model families, STEdgeAI format |

## 2. Audio / Keyword Spotting

| Model | Input Shape | Size | Quant | Source | MCXN947 | STM32N6 | Notes |
|-------|-------------|------|-------|--------|---------|---------|-------|
| Micro Speech (yes/no) | 49x40 | ~20KB | INT8 | [TFLite Micro](https://github.com/tensorflow/tflite-micro/tree/main/tensorflow/lite/micro/examples/micro_speech) | Yes | Yes | Simplest audio model |
| DS-CNN Keyword Spotting | MFCC features | ~80KB | INT8 | [MLPerf Tiny](https://github.com/mlcommons/tiny/tree/master/benchmark/training/keyword_spotting) / ARM | Yes | Yes | 12-class keyword detection |
| Anomaly Detection (DCASE) | Mel spectrogram | ~100KB | INT8 | [MLPerf Tiny](https://github.com/mlcommons/tiny/tree/master/benchmark/training/anomaly_detection) | Yes | Yes | FC-AutoEncoder, unsupervised |
| STM32 Zoo AED models | Various | Various | INT8 | [stm32ai-modelzoo/audio_event_detection](https://github.com/STMicroelectronics/stm32ai-modelzoo/tree/main/audio_event_detection) | No | Yes | 3 model families |

## 3. IMU / Motion Classification

| Model | Input Shape | Size | Quant | Source | MCXN947 | STM32N6 | Notes |
|-------|-------------|------|-------|--------|---------|---------|-------|
| Magic Wand Gesture | 128x3 | ~20KB | Float32 | [TFLite Micro](https://codelabs.developers.google.com/magicwand) | Yes | Yes | Accelerometer gestures |
| HAR (Human Activity) | IMU windows | ~50KB | INT8 | [STM32 Model Zoo](https://github.com/STMicroelectronics/stm32ai-modelzoo/tree/main/human_activity_recognition) (2 families) | Yes | Yes | Walk/run/sit/stand |
| Hand Posture | IMU/ToF | ~30KB | INT8 | [STM32 Model Zoo](https://github.com/STMicroelectronics/stm32ai-modelzoo/tree/main/hand_posture) (1 family) | Maybe | Yes | ST-specific sensors |
| Gait Analysis | Pressure array | ~50KB | INT8 | [maker.pro MCXN947 project](https://maker.pro/nxp-frdm/projects/smart-gait-analysis-device-using-nxp-mcx-n-series-board) | Yes | Maybe | Pressure insole + NPU |

## 4. Object Detection (STM32N6 primary)

| Model | Input Shape | Size | Quant | Source | MCXN947 | STM32N6 | Notes |
|-------|-------------|------|-------|--------|---------|---------|-------|
| ST YOLO x nano | 256x256x3 | ~2MB | INT8/Mixed | STM32 Model Zoo | No | Yes | Demo'd on STM32N6570-DK |
| YOLOv8n | 256x256x3 | ~3MB | INT8 | STM32 Model Zoo (12 OD families) | No | Yes | Requires Neural-ART NPU |

## 5. MLPerf Tiny Suite (Standardized Benchmarks)

| Benchmark | Model | Input | Size | Source |
|-----------|-------|-------|------|--------|
| Keyword Spotting | DS-CNN | MFCC 49x10 | ~80KB | [mlcommons/tiny/.../keyword_spotting](https://github.com/mlcommons/tiny/tree/master/benchmark/training/keyword_spotting) |
| Visual Wake Words | MobileNet v1 0.25 | 96x96x3 | ~250KB | [mlcommons/tiny/.../visual_wake_words](https://github.com/mlcommons/tiny/tree/master/benchmark/training/visual_wake_words) |
| Image Classification | ResNet-8 | 32x32x3 | ~50KB | [mlcommons/tiny/.../image_classification](https://github.com/mlcommons/tiny/tree/master/benchmark/training/image_classification) |
| Anomaly Detection | FC-AutoEncoder | 640 features | ~100KB | [mlcommons/tiny/.../anomaly_detection](https://github.com/mlcommons/tiny/tree/master/benchmark/training/anomaly_detection) |

## 6. uNPU-Bench Framework

- **Source**: [github.com/j0shmillar/uNPU-Bench](https://github.com/j0shmillar/uNPU-Bench)
- **Paper**: [arxiv.org/abs/2503.22567](https://arxiv.org/abs/2503.22567) (ACM MobiCom '25)
- **Supported formats**: onnx, tflm, eiq (MCXN947), ai8x (MAX78000/78002), vela (Ethos-U55/U65), cvi (CVITEK)
- **Setup**: Docker-based, Linux x86_64 required for eIQ compilation
- **MCXN947 support**: Yes, via `--target_format eiq --target_hardware mcxn947`
- **STM32N6 support**: No — this is our novel contribution

## Priority Models for Initial Benchmarking

### Tier 1 — Start here (smallest, best SDK support)
1. **CIFAR-10 CNN** (~50KB) — NXP has working `tflm_cifar10` example for MCXN947
2. **Micro Speech yes/no** (~20KB) — TFLite Micro standard example
3. **Person Detection** (~300KB) — TFLite Micro standard example

### Tier 2 — After Tier 1 works
4. **DS-CNN Keyword Spotting** (~80KB) — MLPerf Tiny standardized
5. **Visual Wake Words** (~250KB) — MLPerf Tiny standardized
6. **Magic Wand Gesture** (~20KB) — IMU-relevant for exoskeleton work

### Tier 3 — Stretch goals
7. **MobileNet v1 0.25** (~500KB) — Larger model stress test
8. **HAR model** (~50KB) — Directly relevant to exoskeleton IMU work
9. **ST YOLO x nano** (~2MB) — STM32N6 only, object detection
