# uNPU-Bench Analysis

_Generated 2026-02-23 from Firecrawl research of paper and GitHub repo_

## Paper
- **Title**: Benchmarking Ultra-Low-Power μNPUs
- **Authors**: Josh Millar et al. (Imperial College London, University of Cambridge)
- **Venue**: ACM MobiCom '25 (31st Annual International Conference on Mobile Computing and Networking)
- **arXiv**: [2503.22567](https://arxiv.org/abs/2503.22567)
- **GitHub**: [j0shmillar/uNPU-Bench](https://github.com/j0shmillar/uNPU-Bench)

## Key Contributions
1. First comparative evaluation of commercially-available μNPUs
2. First independent benchmarks for multiple platforms
3. Open-source model compilation toolchain for cross-platform benchmarking
4. Practical recommendations for developers

## Platforms Benchmarked

| Platform | NPU | Key Specs |
|----------|-----|-----------|
| NXP MCXN947 | eIQ Neutron NPU | INT8, up to 2 TOPS claimed |
| Analog Devices MAX78000 | CNN accelerator | 64 parallel processors, SRAM weight storage |
| Analog Devices MAX78002 | CNN accelerator | Upgraded MAX78000, more SRAM |
| Himax WiseEye2 (WE2) | Ethos-U55 | ARM NPU, configurable MAC units |
| CVITEK CV181x | TPU | Milkv Duo platform |

## Key Findings
- **"Surprising disparities between hardware specifications and actual performance"**
- Certain μNPUs exhibit **unexpected scaling behaviors with model complexity**
- End-to-end performance includes NPU init, memory I/O overhead, CPU pre/post-processing
- Vendor-claimed TOPS/GOPS numbers may not reflect real-world performance
- Fine-grained profiling reveals where time is actually spent (init vs inference vs I/O)

## Compilation Pipeline

Supported output formats:

| Format | Target | Notes |
|--------|--------|-------|
| onnx | All | Universal intermediate |
| tflm | All | TFLite Micro |
| eiq | MCXN947 | Requires eIQ Toolkit 1.12.1 + Neutron converter |
| ai8x | MAX78000/78002 | Requires ai8x-synthesis repo |
| vela | Ethos-U55/U65 | ARM Vela compiler |
| cvi | CVITEK | Requires tpu-mlir, Linux Docker only |

## Setup for MCXN947 (eIQ target)
1. Download eIQ Toolkit 1.12.1 Ubuntu 20.04 Installer from NXP
2. Set `EIQ_NEUTRON_PATH=/path/to/neutron-converter`
3. Docker: `docker build -t unpu-bench . && docker run --rm -it -v $(pwd):/workspace unpu-bench`
4. **IMPORTANT**: Requires Linux x86_64 for eIQ and CVI compilation

## Example Command
```bash
python3 main.py \
  --model model/yolo/yolov1_96.py \
  --model_ckpt model/yolo/yolov1.pth.tar \
  --model_name ai85yolo96 \
  --model_module_name Yolov1_net \
  --target_format eiq \
  --target_hardware mcxn947 \
  --data_sample model/yolo/sample_data_nchw.npy \
  --input_shape 1 3 96 96 \
  --output_shape 10 12 2 \
  --input_names input \
  --output_names output \
  --bit_width 8
```

## What We Can Reproduce
- MCXN947 results from the paper using their pipeline
- Direct NPU vs CPU comparison on same models
- Per-layer profiling (init, inference, I/O overhead)

## What We'd Add (Novel Contributions)
- **STM32N6 Neural-ART benchmarks** — not in their paper, they don't test Neural-ART
- DWT cycle counting for finer-grained profiling
- EAB integration for streaming results
- IMU/motion models (their focus is vision/audio CNNs)
- Cross-board comparison table: MCXN947 vs STM32N6

## Relevance
1. Ready-made compilation pipeline for MCXN947
2. Baseline benchmark numbers to validate against
3. Methodology for fair cross-platform comparison
4. Evidence that vendor specs don't match reality (motivates independent testing)

**Their framework does NOT support STM32N6 Neural-ART — this is our novel contribution.**
