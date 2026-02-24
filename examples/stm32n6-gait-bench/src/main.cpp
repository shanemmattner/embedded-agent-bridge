/*
 * STM32N6 Gait Phase Estimator Benchmark
 *
 * Runs the Shepherd Exoboot gait phase model (Georgia Tech EPIC Lab, ICRA 2022)
 * on Cortex-M55 @ 600MHz with DWT cycle counting.
 *
 * Model: Conv1D x3 + 2 Dense heads → gait_phase (0-100%) + stance/swing
 * Input: (1, 44, 8) int8 — 44 timesteps of 8 IMU channels
 * Source: github.com/maxshep/exoboot-ml-gait-state-estimator (Apache 2.0)
 */
#include <zephyr/kernel.h>
#include <string.h>

#include <tensorflow/lite/micro/micro_mutable_op_resolver.h>
#include <tensorflow/lite/micro/micro_interpreter.h>
#include <tensorflow/lite/micro/micro_log.h>
#include <tensorflow/lite/micro/system_setup.h>
#include <tensorflow/lite/schema/schema_generated.h>

extern "C" {
#include "dwt_profiler.h"
}
#include "exoboot_gait_model.h"

#define STM32N6_CPU_FREQ_HZ 600000000

constexpr int kTensorArenaSize = 32 * 1024;
static uint8_t tensor_arena[kTensorArenaSize] __attribute__((aligned(16)));

static void bench_exoboot_gait(void) {
    const tflite::Model *model = tflite::GetModel(g_exoboot_gait_model);
    if (model->version() != TFLITE_SCHEMA_VERSION) {
        printk("ERROR: exoboot_gait model schema mismatch\n");
        return;
    }

    static tflite::MicroMutableOpResolver<7> resolver;
    resolver.AddAdd();
    resolver.AddConv2D();
    resolver.AddExpandDims();
    resolver.AddFullyConnected();
    resolver.AddLogistic();
    resolver.AddMul();
    resolver.AddReshape();

    tflite::MicroInterpreter interpreter(model, resolver, tensor_arena, kTensorArenaSize);
    if (interpreter.AllocateTensors() != kTfLiteOk) {
        printk("ERROR: exoboot_gait AllocateTensors() failed\n");
        return;
    }

    TfLiteTensor *input = interpreter.input(0);

    printk("Model loaded: exoboot_gait (size=%d bytes)\n", g_exoboot_gait_model_len);
    printk("Arena used: %zu / %d bytes\n", interpreter.arena_used_bytes(), kTensorArenaSize);
    printk("Input shape: (%d, %d, %d)\n",
           input->dims->data[0], input->dims->data[1], input->dims->data[2]);
    printk("Input quant: scale=%.6f zero_point=%d\n",
           (double)input->params.scale, input->params.zero_point);

    const int num_inferences = 100;

    /* Warm up with zero input */
    memset(input->data.int8, 0, input->bytes);
    interpreter.Invoke();

    /* Timed run */
    dwt_reset();
    for (int i = 0; i < num_inferences; i++) {
        interpreter.Invoke();
    }
    uint32_t total_cycles = dwt_get_cycles();
    uint32_t avg_cycles = total_cycles / num_inferences;
    uint32_t avg_time_us = dwt_cycles_to_us(avg_cycles, STM32N6_CPU_FREQ_HZ);

    printk("[ML_BENCH] model=exoboot_gait backend=cmsis_nn cycles=%u time_us=%u input=%u ops=INT8 inferences=%d\n",
           avg_cycles, avg_time_us, (unsigned)input->bytes, num_inferences);

    /* Dequantize and print both output heads */
    TfLiteTensor *out_phase = interpreter.output(0);
    TfLiteTensor *out_stance = interpreter.output(1);

    float gait_phase = (out_phase->data.int8[0] - out_phase->params.zero_point) * out_phase->params.scale;
    float stance_swing = (out_stance->data.int8[0] - out_stance->params.zero_point) * out_stance->params.scale;

    printk("Output[0] gait_phase:   %.4f (%.1f%%)\n", (double)gait_phase, (double)(gait_phase * 100.0f));
    printk("Output[1] stance_swing: %.4f\n\n", (double)stance_swing);
}

int main(void) {
    /* Delay to allow serial reader to connect after SRAM boot.
     * probe-rs holds the USB device during GDB boot — serial reader
     * can only open after probe-rs releases it (~2-3s). */
    k_msleep(5000);

    printk("=== STM32N6 Gait Phase Benchmark (NUCLEO-N657X0-Q) ===\n");
    printk("Board: NUCLEO-N657X0-Q\n");
    printk("CPU Frequency: %u Hz\n", STM32N6_CPU_FREQ_HZ);
    printk("Arena: %d bytes (%d KB)\n\n", kTensorArenaSize, kTensorArenaSize / 1024);

    dwt_init();
    printk("DWT profiler initialized\n\n");

    bench_exoboot_gait();

    printk("[ML_BENCH_DONE] board=nucleo_n657x0_q models=1\n");

    while (1) {
        k_msleep(1000);
    }
    return 0;
}
