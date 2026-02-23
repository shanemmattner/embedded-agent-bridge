# STM32N6 Neural-ART NPU — Getting Started Guide

_Generated 2026-02-23 from Firecrawl research_

## Hardware
- **Board**: STM32N6570-DK (Discovery Kit) or Nucleo-N657X0-Q
- **MCU**: STM32N6 series — Cortex-M55 + Helium DSP
- **NPU**: Neural-ART accelerator, INT8, up to 600 GOPS claimed
- **External flash**: XSPI2 serial NOR flash for model weights
- **Camera**: Optional for vision use cases

## Software Requirements
- STM32CubeIDE 1.17.0 or later
- STM32CubeProgrammer 2.18 or later
- STM32N6 HAL driver 1.1.1 or later (STM32CubeN6 package)
- STEdgeAI-Core 2.1 (model converter and optimizer)
- STM32AI-ModelZoo-Services 3.1.0
- Python 3.12.9
- armcc toolchain (bundled with STM32CubeIDE)

## Environment Setup
Set PATH to include:
- `stedgeai` executable path
- armcc toolchain from STM32CubeIDE plugins

Verify: `stedgeai --version`

## Model Deployment Workflow

### Step 1: Select Model from STM32 Model Zoo
- **GitHub**: [stm32ai-modelzoo v4.0](https://github.com/STMicroelectronics/stm32ai-modelzoo) (Jan 2026)
- **140+ pre-trained models** across categories:
  - Image Classification (24 families)
  - Object Detection (12 families — ST_YOLO, YOLOv8, YOLO11)
  - Audio Event Detection (3 families)
  - Human Activity Recognition (2 families)
  - Hand Posture Recognition (1 family)
  - Arc Fault Detection (2 families)
  - Pose Estimation (6 families)
  - Plus: depth estimation, segmentation, face detection, re-ID, speech enhancement

### Step 2: Convert Model with STEdgeAI-Core
`stedgeai` converts TFLite/Keras/ONNX models to optimized C code for Neural-ART NPU.
- Handles quantization (INT8, mixed W4A8)
- Generates optimized inference library (.a file)
- Outputs C source files for integration

### Step 3: Generate Application Code
Model zoo services auto-generate:
- Application template with camera input, display output
- Pre/post-processing pipelines
- Neural-ART runtime integration

### Step 4: Build Firmware
- Open generated project in STM32CubeIDE
- Build for STM32N6 target
- Model weights → external XSPI2 flash
- Inference code → internal RAM

### Step 5: Flash and Run
Use STM32CubeProgrammer:
1. Flash firmware binary to internal flash
2. Flash model weights to external XSPI2 flash
3. Monitor serial output at 115200 baud

## Key Architecture
- Neural-ART NPU handles convolutions, pooling, activations
- Cortex-M55 + Helium handles pre/post-processing and unsupported ops
- Model weights in external flash (XSPI2)
- Activation buffers in internal SRAM
- Supports mixed precision: W4A8 (4-bit weights, 8-bit activations)

## STM32 Model Zoo — Categories for Cross-Board Benchmarking

### For comparison with MCXN947:
- **Image Classification**: MobileNet variants (various sizes)
- **Audio**: AED models (yamnet, miniresnet variants)
- **HAR**: ign/gmp models for accelerometer data

### STM32N6-only (too large for MCXN947):
- **Object Detection**: ST YOLO variants
- **Pose Estimation**: YOLOv8-pose, movenet

## Resources
- [How to run AI models on STM32N6](https://community.st.com/t5/stm32-mcus/how-to-run-ai-models-from-model-zoo-on-stm32n6/ta-p/814254)
- [Getting Started Webinar (YouTube)](https://www.youtube.com/watch?v=u1bDyDm961g)
- [STM32 AI Ecosystem](https://stm32ai.st.com)
- [Hugging Face Model Cards](https://huggingface.co/STMicroelectronics)
- [ST Edge AI Developer Cloud](https://stm32ai.st.com/st-edge-ai-dc/) — cloud-based model conversion
- [Object Detection on STM32N6 (YouTube)](https://www.youtube.com/watch?v=O7pCXkFWBCM)

## Zephyr Support
- Board target: `nucleo_n657x0q` (confirmed working in EAB stress test)
- Existing firmware: `examples/stm32n6-stress-test/` in EAB repo
- Zephyr may not have full Neural-ART NPU support — ST's native SDK is more complete for NPU work
