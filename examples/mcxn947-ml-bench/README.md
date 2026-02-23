# MCXN947 ML Benchmark

ML inference benchmark for NXP FRDM-MCXN947 board with eIQ Neutron NPU.

## Overview

This project benchmarks ML inference on the FRDM-MCXN947 development board using the ARM Cortex-M DWT cycle counter for precise timing measurements. It provides a framework for comparing NPU-accelerated vs CPU-only inference.

## Status

**Phase 1 Complete** — Scaffold with dummy benchmark models.

**Phase 2 (Planned)** — Real TFLite Micro integration with:
- Actual .tflite model loading
- eIQ Neutron NPU delegate
- Real inference timing

## Building

```bash
# Build for FRDM-MCXN947
west build -b frdm_mcxn947 examples/mcxn947-ml-bench
```

## Flashing

```bash
# Flash using eabctl
eabctl flash examples/mcxn947-ml-bench
```

## Output Format

The benchmark outputs results in a machine-parseable format:

```
[ML_BENCH] model=<name> backend=npu cycles=<n> time_us=<n> input=<size> ops=INT8
[ML_BENCH] model=<name> backend=cpu cycles=<n> time_us=<n> input=<size> ops=INT8
```

Plus a summary table:

```
| Model          | NPU us   | CPU us   | Speedup | Size    |
|----------------|----------|----------|---------|---------|
| cifar10        |    12345 |   518490 |    42.0 |   50000 |
...
```

## Models

Placeholder models used for benchmarking:

| Model       | Input Size | Model Size | Iterations |
|-------------|------------|------------|------------|
| cifar10     | 3072 bytes | 50 KB      | 100        |
| person_detect | 9216 bytes | 300 KB   | 50         |
| micro_speech | 1960 bytes | 20 KB     | 200        |

## Profiling

Uses ARM Cortex-M DWT (Data Watchpoint and Trace) cycle counter for microsecond-precision timing:
- CPU frequency: 150 MHz
- Cycle counter enabled via DEMCR/TRCENA
- Cycles converted to microseconds for reporting
