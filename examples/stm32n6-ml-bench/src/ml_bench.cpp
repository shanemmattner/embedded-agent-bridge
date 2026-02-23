#include <zephyr/kernel.h>
#include "ml_bench.h"

void ml_bench_print_result(const ml_bench_result_t *r) {
    printk("[ML_BENCH] model=%s backend=%s cycles=%u time_us=%u input=%u ops=INT8\n",
           r->name,
           r->npu_available ? "npu" : "cpu",
           r->npu_available ? r->npu_cycles : r->cpu_cycles,
           r->npu_available ? r->npu_time_us : r->cpu_time_us,
           r->input_size);
}

void ml_bench_print_header(void) {
    printk("%-16s %10s %10s %10s %10s %8s\n",
           "Model", "CPU cyc", "CPU us", "NPU cyc", "NPU us", "Speedup");
    printk("%-16s %10s %10s %10s %10s %8s\n",
           "-----", "-------", "------", "-------", "------", "-------");
}

void ml_bench_print_row(const ml_bench_result_t *r) {
    if (r->npu_available) {
        printk("%-16s %10u %10u %10u %10u %7.1fx\n",
               r->name, r->cpu_cycles, r->cpu_time_us,
               r->npu_cycles, r->npu_time_us, (double)r->speedup);
    } else {
        printk("%-16s %10u %10u %10s %10s %8s\n",
               r->name, r->cpu_cycles, r->cpu_time_us,
               "N/A", "N/A", "N/A");
    }
}
