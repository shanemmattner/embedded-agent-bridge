#ifndef ML_BENCH_H
#define ML_BENCH_H

#include <stdint.h>
#include <stdbool.h>

#define STM32N6_CPU_FREQ_HZ 600000000

#define ML_BENCH_NAME_MAX 32

typedef struct {
    char name[ML_BENCH_NAME_MAX];
    uint32_t input_size;
    uint32_t model_size;
    uint32_t npu_cycles;
    uint32_t cpu_cycles;
    uint32_t npu_time_us;
    uint32_t cpu_time_us;
    float speedup;
    bool npu_available;
} ml_bench_result_t;

void ml_bench_print_result(const ml_bench_result_t *r);
void ml_bench_print_header(void);
void ml_bench_print_row(const ml_bench_result_t *r);
ml_bench_result_t ml_bench_run_dummy(const char *name, uint32_t input_bytes,
                                      uint32_t model_bytes, uint32_t iterations);

#endif
