# STM32N6 ML Benchmark

ML inference benchmark for STM32N6570-DK with Neural-ART NPU and DWT profiling.

## Build
west build -b nucleo_n657x0q examples/stm32n6-ml-bench

## Flash
eabctl flash examples/stm32n6-ml-bench

## Output
[ML_BENCH] lines on RTT console.

## Status
Scaffold with dummy models. Real STEdgeAI/Neural-ART integration in Phase 2.
