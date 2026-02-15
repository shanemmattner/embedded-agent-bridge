/* ESP32-C6 Debug Full Example
 *
 * Demonstrates all EAB debugging features:
 * - SystemView task tracing
 * - Heap allocation tracking
 * - Coredump generation
 * - Stack overflow detection
 * - Task watchdog testing
 *
 * Based on ESP-IDF sysview_tracing example.
 * Public Domain (CC0)
 */

#include "esp_err.h"
#include "sdkconfig.h"
#include <stdio.h>
#include <string.h>
#include <stdlib.h>
#include <inttypes.h>
#include "esp_log.h"
#include "esp_app_trace.h"
#include "esp_heap_trace.h"
#include "esp_system.h"
#include "freertos/FreeRTOS.h"
#include "freertos/task.h"
#include "driver/gptimer.h"
#include "driver/uart.h"
#include "esp_trace.h"

static const char *TAG = "debug_full";

/* SystemView event IDs */
#define SYSVIEW_COMPUTE_EVENT_ID     0
#define SYSVIEW_IO_EVENT_ID          1
#define SYSVIEW_ALLOC_EVENT_ID       2

#define SYSVIEW_COMPUTE_START()  SEGGER_SYSVIEW_OnUserStart(SYSVIEW_COMPUTE_EVENT_ID)
#define SYSVIEW_COMPUTE_END()    SEGGER_SYSVIEW_OnUserStop(SYSVIEW_COMPUTE_EVENT_ID)
#define SYSVIEW_IO_START()       SEGGER_SYSVIEW_OnUserStart(SYSVIEW_IO_EVENT_ID)
#define SYSVIEW_IO_END()         SEGGER_SYSVIEW_OnUserStop(SYSVIEW_IO_EVENT_ID)
#define SYSVIEW_ALLOC_START()    SEGGER_SYSVIEW_OnUserStart(SYSVIEW_ALLOC_EVENT_ID)
#define SYSVIEW_ALLOC_END()      SEGGER_SYSVIEW_OnUserStop(SYSVIEW_ALLOC_EVENT_ID)

/* Test heap tracing */
#if CONFIG_HEAP_TRACING
#define NUM_HEAP_RECORDS 128
static heap_trace_record_t heap_trace_records[NUM_HEAP_RECORDS];
static bool heap_tracing_active = false;
#endif

/* Test control via UART commands */
static void cmd_task(void *arg);

/* High-priority compute task */
static void compute_task(void *arg)
{
    ESP_LOGI(TAG, "Compute task started");
    uint32_t count = 0;

    while (1) {
        SYSVIEW_COMPUTE_START();

        /* Simulate computation */
        volatile uint32_t sum = 0;
        for (int i = 0; i < 10000; i++) {
            sum += i * i;
        }

        SYSVIEW_COMPUTE_END();

        if (++count % 100 == 0) {
            ESP_LOGI(TAG, "Compute: %"PRIu32" iterations", count);
        }

        vTaskDelay(pdMS_TO_TICKS(50));
    }
}

/* Low-priority I/O task */
static void io_task(void *arg)
{
    ESP_LOGI(TAG, "I/O task started");
    uint32_t count = 0;

    while (1) {
        SYSVIEW_IO_START();

        /* Simulate I/O operation */
        vTaskDelay(pdMS_TO_TICKS(10));

        SYSVIEW_IO_END();

        if (++count % 50 == 0) {
            ESP_LOGI(TAG, "I/O: %"PRIu32" operations", count);
        }

        vTaskDelay(pdMS_TO_TICKS(100));
    }
}

/* Periodic memory allocation task */
static void alloc_task(void *arg)
{
    ESP_LOGI(TAG, "Alloc task started");
    void *ptrs[5] = {NULL};
    int idx = 0;

    while (1) {
        SYSVIEW_ALLOC_START();

        /* Free old allocation */
        if (ptrs[idx] != NULL) {
            free(ptrs[idx]);
            ptrs[idx] = NULL;
        }

        /* Allocate new buffer */
        size_t size = 128 + (rand() % 512);
        ptrs[idx] = malloc(size);
        if (ptrs[idx]) {
            memset(ptrs[idx], 0xAA, size);
        }

        SYSVIEW_ALLOC_END();

        idx = (idx + 1) % 5;
        vTaskDelay(pdMS_TO_TICKS(200));
    }
}

/* Command task - processes UART input */
static void cmd_task(void *arg)
{
    ESP_LOGI(TAG, "Command task started");
    ESP_LOGI(TAG, "Available commands:");
    ESP_LOGI(TAG, "  heap_start  - Start heap tracing");
    ESP_LOGI(TAG, "  heap_stop   - Stop heap tracing and dump");
    ESP_LOGI(TAG, "  fault_null  - Trigger NULL pointer fault");
    ESP_LOGI(TAG, "  fault_div0  - Trigger divide by zero");
    ESP_LOGI(TAG, "  wdt_test    - Trigger watchdog timeout");
    ESP_LOGI(TAG, "  status      - Print system status");

    char line[128];
    int pos = 0;

    while (1) {
        int c = fgetc(stdin);
        if (c == EOF) {
            vTaskDelay(pdMS_TO_TICKS(10));
            continue;
        }

        if (c == '\n' || c == '\r') {
            if (pos > 0) {
                line[pos] = '\0';

                /* Process command */
                if (strcmp(line, "heap_start") == 0) {
#if CONFIG_HEAP_TRACING
                    if (!heap_tracing_active) {
                        ESP_ERROR_CHECK(heap_trace_init_standalone(heap_trace_records, NUM_HEAP_RECORDS));
                        ESP_ERROR_CHECK(heap_trace_start(HEAP_TRACE_LEAKS));
                        heap_tracing_active = true;
                        ESP_LOGI(TAG, "Heap tracing started");
                    } else {
                        ESP_LOGW(TAG, "Heap tracing already active");
                    }
#else
                    ESP_LOGW(TAG, "Heap tracing not enabled in config");
#endif
                } else if (strcmp(line, "heap_stop") == 0) {
#if CONFIG_HEAP_TRACING
                    if (heap_tracing_active) {
                        ESP_ERROR_CHECK(heap_trace_stop());
                        heap_trace_dump();
                        heap_tracing_active = false;
                        ESP_LOGI(TAG, "Heap tracing stopped");
                    } else {
                        ESP_LOGW(TAG, "Heap tracing not active");
                    }
#else
                    ESP_LOGW(TAG, "Heap tracing not enabled in config");
#endif
                } else if (strcmp(line, "fault_null") == 0) {
                    ESP_LOGE(TAG, "Triggering NULL pointer fault...");
                    vTaskDelay(pdMS_TO_TICKS(100));
                    volatile int *p = NULL;
                    *p = 42;  /* This will fault */
                } else if (strcmp(line, "fault_div0") == 0) {
                    ESP_LOGE(TAG, "Triggering divide by zero...");
                    vTaskDelay(pdMS_TO_TICKS(100));
                    volatile int a = 10;
                    volatile int b = 0;
                    volatile int c = a / b;  /* This will fault */
                    (void)c;
                } else if (strcmp(line, "wdt_test") == 0) {
                    ESP_LOGE(TAG, "Triggering watchdog timeout...");
                    ESP_LOGE(TAG, "System will reset in ~10 seconds");
                    vTaskDelay(pdMS_TO_TICKS(100));
                    /* Spin forever to trigger watchdog */
                    while (1) {
                        /* Do nothing */
                    }
                } else if (strcmp(line, "status") == 0) {
                    ESP_LOGI(TAG, "=== System Status ===");
                    ESP_LOGI(TAG, "Free heap: %"PRIu32" bytes", esp_get_free_heap_size());
                    ESP_LOGI(TAG, "Min free heap: %"PRIu32" bytes", esp_get_minimum_free_heap_size());
                    UBaseType_t task_count = uxTaskGetNumberOfTasks();
                    ESP_LOGI(TAG, "Active tasks: %u", task_count);
#if CONFIG_HEAP_TRACING
                    ESP_LOGI(TAG, "Heap tracing: %s", heap_tracing_active ? "active" : "inactive");
#endif
                } else {
                    ESP_LOGW(TAG, "Unknown command: %s", line);
                }

                pos = 0;
            }
        } else if (pos < sizeof(line) - 1) {
            line[pos++] = c;
        }
    }
}

/* Configure trace parameters for apptrace */
esp_trace_open_params_t esp_trace_get_user_params(void)
{
    static esp_apptrace_config_t app_trace_config = APPTRACE_CONFIG_DEFAULT();

    esp_trace_open_params_t trace_params = {
        .core_cfg = NULL,
        .encoder_name = "sysview",
        .encoder_cfg = NULL,
        .transport_name = "apptrace",
        .transport_cfg = &app_trace_config,
    };
    return trace_params;
}

void app_main(void)
{
    ESP_LOGI(TAG, "========================================");
    ESP_LOGI(TAG, "ESP32-C6 Debug Full Example");
    ESP_LOGI(TAG, "========================================");
    ESP_LOGI(TAG, "Features enabled:");
    ESP_LOGI(TAG, "  - SystemView task tracing");
#if CONFIG_HEAP_TRACING
    ESP_LOGI(TAG, "  - Heap allocation tracking");
#endif
#if CONFIG_ESP_COREDUMP_ENABLE
    ESP_LOGI(TAG, "  - Coredump generation");
#endif
#if CONFIG_ESP_TASK_WDT
    ESP_LOGI(TAG, "  - Task watchdog");
#endif
    ESP_LOGI(TAG, "========================================");

    /* Create tasks with different priorities */
    xTaskCreate(cmd_task,     "cmd",     4096, NULL, 5, NULL);  /* Highest priority */
    xTaskCreate(compute_task, "compute", 3072, NULL, 3, NULL);  /* High priority */
    xTaskCreate(io_task,      "io",      2048, NULL, 2, NULL);  /* Medium priority */
    xTaskCreate(alloc_task,   "alloc",   3072, NULL, 1, NULL);  /* Low priority */

    ESP_LOGI(TAG, "All tasks created. Ready for debugging!");
    ESP_LOGI(TAG, "Type 'status' for system info");
}
