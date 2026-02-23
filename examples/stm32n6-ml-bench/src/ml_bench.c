#include "ml_bench.h"
#include "dwt_profiler.h"
#include <stdio.h>
#include <string.h>

void ml_bench_print_result(const ml_bench_result_t *r) {
    /* Print NPU result */
    printk("[ML_BENCH] model=%s backend=npu cycles=%u time_us=%u input=%u ops=INT8\n",
           r->name, r->npu_cycles, r->npu_time_us, r->input_size);

    /* Print CPU result */
    printk("[ML_BENCH] model=%s backend=cpu cycles=%u time_us=%u input=%u ops=INT8\n",
           r->name, r->cpu_cycles, r->cpu_time_us, r->input_size);
}

void ml_bench_print_header(void) {
    printk("| Model          | NPU us   | CPU us   | Speedup | Size    |\n");
    printk("|----------------|----------|----------|---------|---------|\n");
}

void ml_bench_print_row(const ml_bench_result_t *r) {
    printk("| %-14s | %8u | %8u | %7.2f | %7u |\n",
           r->name, r->npu_time_us, r->cpu_time_us, r->speedup, r->model_size);
}

ml_bench_result_t ml_bench_run_dummy(const char *name, uint32_t input_bytes,
                                      uint32_t model_bytes, uint32_t iterations) {
    ml_bench_result_t result;

    memset(&result, 0, sizeof(result));
    strncpy(result.name, name, ML_BENCH_NAME_MAX - 1);
    result.name[ML_BENCH_NAME_MAX - 1] = '\0';
    result.input_size = input_bytes;
    result.model_size = model_bytes;
    result.npu_available = false;  /* Placeholder until NPU delegate is integrated */

    /* Simulate CPU-only inference with a dummy loop */
    volatile uint32_t dummy = 0;

    /* Time CPU-only execution */
    dwt_reset();
    for (uint32_t i = 0; i < iterations; i++) {
        /* Simulate some work proportional to input size */
        for (uint32_t j = 0; j < input_bytes; j++) {
            dummy++;
        }
    }
    result.cpu_cycles = dwt_get_cycles();
    result.cpu_time_us = dwt_cycles_to_us(result.cpu_cycles, STM32N6_CPU_FREQ_HZ);

    /* Simulate NPU execution with 600x speedup (placeholder for Neural-ART) */
    /* In Phase 2, this will be replaced with actual NPU delegate timing */
    result.npu_cycles = result.cpu_cycles / 600;
    if (result.npu_cycles == 0) {
        result.npu_cycles = 1;  /* Avoid division by zero */
    }
    result.npu_time_us = dwt_cycles_to_us(result.npu_cycles, STM32N6_CPU_FREQ_HZ);

    /* Calculate speedup */
    if (result.npu_time_us > 0) {
        result.speedup = (float)result.cpu_time_us / (float)result.npu_time_us;
    } else {
        result.speedup = 0.0f;
    }

    return result;
}
