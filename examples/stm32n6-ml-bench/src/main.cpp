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
#include "ml_bench.h"
#include "sine_model.h"

constexpr int kTensorArenaSize = 4096;
static uint8_t tensor_arena[kTensorArenaSize];

int main(void) {
    printk("=== STM32N6 ML Benchmark (NUCLEO-N657X0-Q) ===\n");
    printk("Board: NUCLEO-N657X0-Q\n");
    printk("CPU Frequency: %u Hz\n", STM32N6_CPU_FREQ_HZ);
    printk("\n");

    dwt_init();
    printk("DWT profiler initialized\n\n");

    /* Load sine model */
    const tflite::Model *model = tflite::GetModel(g_sine_model);
    if (model->version() != TFLITE_SCHEMA_VERSION) {
        printk("ERROR: Model schema version %d != %d\n",
               (int)model->version(), TFLITE_SCHEMA_VERSION);
        return 1;
    }

    /* Set up op resolver - sine model uses FullyConnected only */
    static tflite::MicroMutableOpResolver<1> resolver;
    resolver.AddFullyConnected();

    /* Build interpreter */
    static tflite::MicroInterpreter interpreter(
        model, resolver, tensor_arena, kTensorArenaSize);
    if (interpreter.AllocateTensors() != kTfLiteOk) {
        printk("ERROR: AllocateTensors() failed\n");
        return 1;
    }

    TfLiteTensor *input = interpreter.input(0);
    TfLiteTensor *output = interpreter.output(0);

    printk("Model loaded: sine (size=%d bytes)\n", g_sine_model_len);
    printk("Arena used: %zu / %d bytes\n",
           interpreter.arena_used_bytes(), kTensorArenaSize);
    printk("\n");

    /* Benchmark setup */
    ml_bench_result_t result;
    memset(&result, 0, sizeof(result));
    strncpy(result.name, "sine", ML_BENCH_NAME_MAX - 1);
    result.input_size = 1;
    result.model_size = g_sine_model_len;
    result.npu_available = false;

    const int num_inferences = 100;

    /* Warm up */
    input->data.int8[0] = 0;
    interpreter.Invoke();

    /* Timed run */
    dwt_reset();
    for (int i = 0; i < num_inferences; i++) {
        float x = (float)i / (float)num_inferences * 6.28318f;
        int8_t x_q = (int8_t)(x / input->params.scale + input->params.zero_point);
        input->data.int8[0] = x_q;
        interpreter.Invoke();
    }
    uint32_t total_cycles = dwt_get_cycles();

    result.cpu_cycles = total_cycles / num_inferences;
    result.cpu_time_us = dwt_cycles_to_us(result.cpu_cycles, STM32N6_CPU_FREQ_HZ);

    /* Print EAB-parseable result */
    printk("[ML_BENCH] model=sine backend=cpu cycles=%u time_us=%u input=%u ops=INT8 inferences=%d\n",
           result.cpu_cycles, result.cpu_time_us, result.input_size, num_inferences);

    /* Sanity check last inference */
    int8_t y_q = output->data.int8[0];
    float y = (y_q - output->params.zero_point) * output->params.scale;
    printk("Last inference: sin(~6.28) = %.4f (expected ~0.0)\n", (double)y);

    printk("\n[ML_BENCH_DONE] board=nucleo_n657x0_q models=1\n");

    while (1) {
        k_msleep(1000);
    }
    return 0;
}
