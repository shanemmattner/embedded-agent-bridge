#include <zephyr/kernel.h>
#include <stdio.h>
#include "dwt_profiler.h"
#include "ml_bench.h"

int main(void) {
    /* Print banner */
    printk("=== MCXN947 ML Benchmark (FRDM-MCXN947) ===\n");
    printk("Board: FRDM-MCXN947\n");
    printk("CPU Frequency: %u Hz\n", MCXN947_CPU_FREQ_HZ);
    printk("\n");

    /* Initialize DWT cycle counter */
    dwt_init();
    printk("DWT profiler initialized\n\n");

    /* Run benchmarks for placeholder models */
    ml_bench_result_t results[3];

    /* cifar10: 32*32*3 = 3072 input bytes, 50000 model bytes, 100 iterations */
    results[0] = ml_bench_run_dummy("cifar10", 32 * 32 * 3, 50000, 100);

    /* person_detect: 96*96*1 = 9216 input bytes, 300000 model bytes, 50 iterations */
    results[1] = ml_bench_run_dummy("person_detect", 96 * 96 * 1, 300000, 50);

    /* micro_speech: 49*40 = 1960 input bytes, 20000 model bytes, 200 iterations */
    results[2] = ml_bench_run_dummy("micro_speech", 49 * 40, 20000, 200);

    /* Print detailed results */
    for (int i = 0; i < 3; i++) {
        ml_bench_print_result(&results[i]);
    }

    /* Print summary table */
    printk("\n");
    ml_bench_print_header();
    for (int i = 0; i < 3; i++) {
        ml_bench_print_row(&results[i]);
    }
    printk("\n");

    /* Print completion marker */
    printk("[ML_BENCH_DONE] board=frdm_mcxn947 models=3\n");

    /* Enter idle loop */
    while (1) {
        k_msleep(1000);
    }

    return 0;
}
