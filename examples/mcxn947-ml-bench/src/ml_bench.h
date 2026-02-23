#ifndef ML_BENCH_H
#define ML_BENCH_H

#include <stdint.h>
#include <stdbool.h>

/* CPU frequency for MCXN947 */
#define MCXN947_CPU_FREQ_HZ 150000000

/* Maximum model name length */
#define ML_BENCH_NAME_MAX 32

/* Benchmark result for one model */
typedef struct {
    char name[ML_BENCH_NAME_MAX];
    uint32_t input_size;       /* total input bytes */
    uint32_t model_size;       /* .tflite size in bytes */
    uint32_t npu_cycles;       /* DWT cycles with NPU */
    uint32_t cpu_cycles;       /* DWT cycles CPU-only */
    uint32_t npu_time_us;      /* inference time NPU (microseconds) */
    uint32_t cpu_time_us;      /* inference time CPU-only (microseconds) */
    float speedup;             /* cpu_time / npu_time */
    bool npu_available;        /* NPU delegate loaded successfully */
} ml_bench_result_t;

/* Print one result in EAB-parseable format */
void ml_bench_print_result(const ml_bench_result_t *r);

/* Print summary table header */
void ml_bench_print_header(void);

/* Print summary table row */
void ml_bench_print_row(const ml_bench_result_t *r);

/* Run a dummy benchmark (placeholder until real TFLite models are integrated) */
ml_bench_result_t ml_bench_run_dummy(const char *name, uint32_t input_bytes,
                                      uint32_t model_bytes, uint32_t iterations);

#endif
