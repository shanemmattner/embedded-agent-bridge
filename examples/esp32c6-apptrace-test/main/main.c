/**
 * EAB ESP32-C6 Apptrace Stress Test
 *
 * PRODUCTION PATTERN (matches ESP-IDF app_trace_to_plot example):
 * - Waits for OpenOCD connection
 * - Streams continuously while host is connected
 * - Exits gracefully when host disconnects
 * - Writes from app_main() for simplicity
 *
 * CRITICAL QUIRKS FOR RISC-V ESP32 CHIPS (C6, C3, H2, C5):
 * ========================================================
 * 1. RESET SEQUENCE: Chip must boot AFTER OpenOCD connects
 *    See: https://github.com/espressif/openocd-esp32/issues/188
 * 2. TIMING: Start apptrace within 1-2 seconds of reset
 * 3. POLL PERIOD: Use 1ms (not 0)
 *
 * OpenOCD commands:
 *   reset run
 *   esp apptrace start file:///tmp/apptrace.log 1 0 10 0 0
 */

#include <stdio.h>
#include <string.h>
#include "freertos/FreeRTOS.h"
#include "freertos/task.h"
#include "esp_system.h"
#include "esp_chip_info.h"
#include "esp_flash.h"
#include "esp_log.h"
#include "esp_timer.h"
#include "esp_app_trace.h"

static const char *TAG = "STRESS_TEST";

void app_main(void)
{
    int64_t start_time = esp_timer_get_time();

    printf("\n\n");
    printf("=======================================\n");
    printf(" ESP32-C6 Apptrace STRESS TEST\n");
    printf("=======================================\n");
    printf("Continuous streaming (production pattern)\n\n");

    esp_chip_info_t info;
    esp_chip_info(&info);
    ESP_LOGI(TAG, "Chip: ESP32-C6, Cores: %d, Free heap: %lu bytes",
            info.cores, (unsigned long)esp_get_free_heap_size());

    // Wait for OpenOCD connection (ESP-IDF pattern)
    ESP_LOGI(TAG, "Waiting for OpenOCD connection...");
    while (!esp_apptrace_host_is_connected(ESP_APPTRACE_DEST_JTAG)) {
        vTaskDelay(1);
    }

    ESP_LOGI(TAG, "=== CONNECTED! Starting continuous stream ===");

    uint32_t msg_count = 0;
    uint32_t total_bytes = 0;
    int64_t test_start = esp_timer_get_time();
    int64_t last_report = test_start;

    // PRODUCTION PATTERN: Loop while host is connected!
    // This is the KEY - not while(1), but while(connected)!
    while (esp_apptrace_host_is_connected(ESP_APPTRACE_DEST_JTAG)) {
        msg_count++;
        int64_t uptime_ms = (esp_timer_get_time() - start_time) / 1000;
        uint32_t free_heap = esp_get_free_heap_size();

        char trace_buf[128];
        int len = snprintf(trace_buf, sizeof(trace_buf),
                          "[TRACE] msg=%lu uptime=%lldms heap=%lu\n",
                          (unsigned long)msg_count,
                          (long long)uptime_ms,
                          (unsigned long)free_heap);

        // Write with infinite timeout
        esp_err_t res = esp_apptrace_write(ESP_APPTRACE_DEST_JTAG,
                                           trace_buf,
                                           len,
                                           ESP_APPTRACE_TMO_INFINITE);
        if (res != ESP_OK) {
            ESP_LOGE(TAG, "Write FAILED: %s - exiting", esp_err_to_name(res));
            break;
        }

        total_bytes += len;

        // Flush every 10 writes
        if (msg_count % 10 == 0) {
            esp_apptrace_flush(ESP_APPTRACE_DEST_JTAG, 1000);
        }

        // Report throughput every second
        int64_t now = esp_timer_get_time();
        if ((now - last_report) >= 1000000) {  // 1 second
            float elapsed_s = (now - last_report) / 1000000.0;
            float throughput_kbps = (total_bytes / 1024.0) / elapsed_s;

            ESP_LOGI(TAG, "Throughput: %.2f KB/s | Total: %lu msgs, %.1f KB",
                    throughput_kbps, (unsigned long)msg_count, (msg_count * len) / 1024.0);

            total_bytes = 0;
            last_report = now;
        }

        // NO DELAY - send as fast as possible for stress test!
        // For production: add vTaskDelay or only send when data available
    }

    // Cleanup when host disconnects
    int64_t test_end = esp_timer_get_time();
    float total_time_s = (test_end - test_start) / 1000000.0;
    float avg_throughput = ((msg_count * 50) / 1024.0) / total_time_s;  // ~50 bytes/msg

    ESP_LOGI(TAG, "=== HOST DISCONNECTED ===");
    ESP_LOGI(TAG, "Total messages: %lu", (unsigned long)msg_count);
    ESP_LOGI(TAG, "Total time: %.3f seconds", total_time_s);
    ESP_LOGI(TAG, "Average throughput: %.2f KB/s", avg_throughput);
    ESP_LOGI(TAG, "Done!");
}
