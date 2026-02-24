#include <zephyr/kernel.h>
#include "ml_bench.h"

void ml_bench_print_result(const ml_bench_result_t *r) {
    printk("[ML_BENCH] model=%s backend=cmsis_nn cycles=%u time_us=%u input=%u ops=INT8\n",
           r->name, r->cpu_cycles, r->cpu_time_us, r->input_size);
}

void ml_bench_print_header(void) {
    printk("%-16s %10s %10s\n",
           "Model", "CPU cyc", "CPU us");
    printk("%-16s %10s %10s\n",
           "-----", "-------", "------");
}

void ml_bench_print_row(const ml_bench_result_t *r) {
    printk("%-16s %10u %10u\n",
           r->name, r->cpu_cycles, r->cpu_time_us);
}
