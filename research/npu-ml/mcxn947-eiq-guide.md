# MCXN947 eIQ Neutron NPU — Getting Started Guide

_Generated 2026-02-23 from Firecrawl research_

## Hardware
- **Board**: FRDM-MCXN947
- **MCU**: MCXN947 dual Cortex-M33 @ 150 MHz
- **NPU**: eIQ Neutron NPU, INT8, up to 2 TOPS claimed
- **RAM**: 512 KB SRAM
- **Flash**: 2 MB on-chip flash
- **USB**: J17 provides power, debugging, and serial

## Software Requirements
- MCUXpresso IDE v25.6 or later
- MCUXpresso SDK (latest for FRDM-MCXN947)
- eIQ Toolkit (includes Neutron NPU converter)
- eIQ Neutron SDK 2.2.3
- Python 3.x for model preparation

## Model Deployment Workflow

### Step 1: Get a quantized TFLite model
- Must be INT8 quantized (full integer quantization)
- Input/output tensors must also be INT8
- Sources: TF Model Garden, MLPerf Tiny, STM32 Model Zoo (convert first)

### Step 2: Convert with eIQ Neutron Converter
The Neutron converter transforms standard INT8 TFLite models into NPU-optimized format.
- Tool: Part of eIQ Toolkit installation
- Env var: `export EIQ_NEUTRON_PATH=/path/to/neutron-converter`
- The converter identifies ops that run on NPU vs CPU fallback
- Reference: [eIQ Neutron NPU Lab Guide (VSCode)](https://community.nxp.com/pwmxy87654/attachments/pwmxy87654/MCX%40tkb/9/47/eIQ%20Neutron%20NPU%20for%20MCX%20N%20Lab%20Guide%20-%20VSCode.pdf)

### Step 3: Use SDK Example as Template
Best starting example: **tflm_cifar10** (MCUXpresso SDK)
- Import via MCUXpresso IDE SDK examples
- Project structure:
  - `model.cpp` — model loading
  - `model_cifarnet_ops_npu.cpp` — operator resolver
  - `image_load.c` — test input data
  - Serial output for inference results

### Step 4: Replace Model in Project
1. Copy converted `.tflite` to project `Model/` folder
2. Create assembly source with `.incbin` directive to embed model data
3. Update `model.cpp` to reference your model data array
4. Update operator resolver with required ops:
```cpp
s_microOpResolver.AddConv2D();
s_microOpResolver.AddRelu();
s_microOpResolver.AddMaxPool2D();
s_microOpResolver.AddReshape();
s_microOpResolver.AddFullyConnected();
s_microOpResolver.AddSoftmax();
s_microOpResolver.AddCustom(
    GetString_NEUTRON_GRAPH(),
    tflite::Register_NEUTRON_GRAPH());
```

### Step 5: Build and Flash
- Build in MCUXpresso IDE
- Flash via J-Link / MCU-Link debugger on J17
- Monitor serial output via terminal at 115200 baud

## Key Constraints
- Model must fit in SRAM (~512KB total, shared with stack/heap)
- Only INT8 quantized models work with Neutron NPU
- Not all TFLite ops are supported on NPU — unsupported ops fall back to CPU
- The Neutron converter shows which ops are NPU-accelerated vs CPU

## NXP Resources
- [eIQ Getting Started Guide PDF](https://community.nxp.com/pwmxy87654/attachments/pwmxy87654/eiq%40tkb/15/9/eIQ%20Getting%20Started%20Guide.pdf)
- [Neutron NPU Lab Guide (MCUXpresso IDE)](https://community.nxp.com/pwmxy87654/attachments/pwmxy87654/MCX%40tkb/9/40/eIQ%20Neutron%20NPU%20for%20MCX%20N%20Lab%20Guide%20-%20MCUXpresso%20IDE.pdf)
- [MCX NPU/ML Knowledge Base](https://community.nxp.com/t5/MCX-Microcontrollers-Knowledge/tkb-p/MCX%40tkb/label-name/npu%7Cml)
- [eIQ Time Series Studio (TSS)](https://community.nxp.com/t5/eIQ-Machine-Learning-Software/tkb-p/eiq%40tkb) — for IMU/time-series models
- [NXP Neutron NPU Benchmark Video](https://www.nxp.com/company/about-nxp/smarter-world-videos/NPU-BENCHMARK-MCXN947-VID)
- [Model Conversion Docs](https://mcuxpresso.nxp.com/mcuxsdk/latest/html/middleware/eiq/tensorflow-lite/docs/topics/convert_model.html)
- [Deploying models forum thread](https://community.nxp.com/t5/MCX-Microcontrollers/Deploying-trained-model-on-FRDM-MCXN947/m-p/2072575)

## uNPU-Bench Integration
- Supports `--target_format eiq --target_hardware mcxn947`
- Requires eIQ Toolkit 1.12.1 Ubuntu 20.04 Installer
- Docker-based setup (Linux x86_64 only)
- Set `EIQ_NEUTRON_PATH` env var

## Existing MCXN947 ML Projects
1. **tflm_cifar10** — Image classification, INT8, ~50KB model (SDK example)
2. **Smart Gait Analysis** — Pressure sensor insole + TFLite gait classification ([maker.pro](https://maker.pro/nxp-frdm/projects/smart-gait-analysis-device-using-nxp-mcx-n-series-board))
3. **eIQ Time Series Studio** — IMU-based classification models
4. **NXP Neutron NPU Benchmark demo** — MobileNet inference demo
