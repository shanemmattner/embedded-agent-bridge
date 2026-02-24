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
#include "micro_speech_model.h"
#include "person_detect_model.h"

/* Tensor arena shared across models — 140KB for person_detect */
constexpr int kTensorArenaSize = 140 * 1024;
static uint8_t tensor_arena[kTensorArenaSize] __attribute__((aligned(16)));

static void bench_sine(void) {
    const tflite::Model *model = tflite::GetModel(g_sine_model);
    if (model->version() != TFLITE_SCHEMA_VERSION) {
        printk("ERROR: sine model schema mismatch\n");
        return;
    }

    static tflite::MicroMutableOpResolver<1> resolver;
    resolver.AddFullyConnected();

    tflite::MicroInterpreter interpreter(model, resolver, tensor_arena, kTensorArenaSize);
    if (interpreter.AllocateTensors() != kTfLiteOk) {
        printk("ERROR: sine AllocateTensors() failed\n");
        return;
    }

    TfLiteTensor *input = interpreter.input(0);
    TfLiteTensor *output = interpreter.output(0);

    printk("Model loaded: sine (size=%d bytes)\n", g_sine_model_len);
    printk("Arena used: %zu / %d bytes\n", interpreter.arena_used_bytes(), kTensorArenaSize);

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
    uint32_t avg_cycles = total_cycles / num_inferences;
    uint32_t avg_time_us = dwt_cycles_to_us(avg_cycles, STM32N6_CPU_FREQ_HZ);

    printk("[ML_BENCH] model=sine backend=cmsis_nn cycles=%u time_us=%u input=1 ops=INT8 inferences=%d\n",
           avg_cycles, avg_time_us, num_inferences);

    int8_t y_q = output->data.int8[0];
    float y = (y_q - output->params.zero_point) * output->params.scale;
    printk("Last inference: sin(~6.28) = %.4f (expected ~0.0)\n\n", (double)y);
}

static void bench_person_detect(void) {
    const tflite::Model *model = tflite::GetModel(g_person_detect_model);
    if (model->version() != TFLITE_SCHEMA_VERSION) {
        printk("ERROR: person_detect model schema mismatch\n");
        return;
    }

    static tflite::MicroMutableOpResolver<5> resolver;
    resolver.AddAveragePool2D();
    resolver.AddConv2D();
    resolver.AddDepthwiseConv2D();
    resolver.AddReshape();
    resolver.AddSoftmax();

    tflite::MicroInterpreter interpreter(model, resolver, tensor_arena, kTensorArenaSize);
    if (interpreter.AllocateTensors() != kTfLiteOk) {
        printk("ERROR: person_detect AllocateTensors() failed\n");
        return;
    }

    TfLiteTensor *input = interpreter.input(0);

    printk("Model loaded: person_detect (size=%d bytes)\n", g_person_detect_model_len);
    printk("Arena used: %zu / %d bytes\n", interpreter.arena_used_bytes(), kTensorArenaSize);
    printk("Input shape: %dx%dx%d\n", input->dims->data[1], input->dims->data[2], input->dims->data[3]);

    memset(input->data.int8, 0, input->bytes);
    interpreter.Invoke();

    const int num_iters = 10;
    dwt_reset();
    for (int i = 0; i < num_iters; i++) {
        interpreter.Invoke();
    }
    uint32_t total_cycles = dwt_get_cycles();
    uint32_t avg_cycles = total_cycles / num_iters;
    uint32_t avg_time_us = dwt_cycles_to_us(avg_cycles, STM32N6_CPU_FREQ_HZ);

    printk("[ML_BENCH] model=person_detect backend=cmsis_nn cycles=%u time_us=%u input=%u ops=INT8 inferences=%d\n",
           avg_cycles, avg_time_us, (unsigned)input->bytes, num_iters);

    TfLiteTensor *output = interpreter.output(0);
    int8_t person_score = output->data.int8[1];
    int8_t no_person_score = output->data.int8[0];
    printk("Scores: person=%d no_person=%d (dummy input)\n\n", person_score, no_person_score);
}

static void bench_micro_speech(void) {
    const tflite::Model *model = tflite::GetModel(g_micro_speech_model);
    if (model->version() != TFLITE_SCHEMA_VERSION) {
        printk("ERROR: micro_speech model schema mismatch\n");
        return;
    }

    static tflite::MicroMutableOpResolver<4> resolver;
    resolver.AddReshape();
    resolver.AddFullyConnected();
    resolver.AddDepthwiseConv2D();
    resolver.AddSoftmax();

    tflite::MicroInterpreter interpreter(model, resolver, tensor_arena, kTensorArenaSize);
    if (interpreter.AllocateTensors() != kTfLiteOk) {
        printk("ERROR: micro_speech AllocateTensors() failed\n");
        return;
    }

    TfLiteTensor *input = interpreter.input(0);
    TfLiteTensor *output = interpreter.output(0);

    printk("Model loaded: micro_speech (size=%d bytes)\n", g_micro_speech_model_len);
    printk("Arena used: %zu / %d bytes\n", interpreter.arena_used_bytes(), kTensorArenaSize);

    const int num_inferences = 100;

    /* Fill with dummy MFCC features */
    memset(input->data.int8, 0, input->bytes);

    /* Warm up */
    interpreter.Invoke();

    /* Timed run */
    dwt_reset();
    for (int i = 0; i < num_inferences; i++) {
        interpreter.Invoke();
    }
    uint32_t total_cycles = dwt_get_cycles();
    uint32_t avg_cycles = total_cycles / num_inferences;
    uint32_t avg_time_us = dwt_cycles_to_us(avg_cycles, STM32N6_CPU_FREQ_HZ);

    printk("[ML_BENCH] model=micro_speech backend=cmsis_nn cycles=%u time_us=%u input=%u ops=INT8 inferences=%d\n",
           avg_cycles, avg_time_us, (unsigned)input->bytes, num_inferences);

    /* Print classification */
    printk("Output scores: [0]=%d [1]=%d [2]=%d [3]=%d\n\n",
           output->data.int8[0], output->data.int8[1],
           output->data.int8[2], output->data.int8[3]);
}

int main(void) {
    printk("=== STM32N6 ML Benchmark (NUCLEO-N657X0-Q) ===\n");
    printk("Board: NUCLEO-N657X0-Q\n");
    printk("CPU Frequency: %u Hz\n", STM32N6_CPU_FREQ_HZ);
    printk("Arena: %d bytes (%d KB)\n\n", kTensorArenaSize, kTensorArenaSize / 1024);

    dwt_init();
    printk("DWT profiler initialized\n\n");

    bench_sine();
    bench_person_detect();
    bench_micro_speech();

    printk("[ML_BENCH_DONE] board=nucleo_n657x0_q models=3\n");

    while (1) {
        k_msleep(1000);
    }
    return 0;
}
