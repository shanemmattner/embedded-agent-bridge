/**
 * EAB ESP32-C6 Apptrace Test Firmware
 *
 * Demonstrates high-speed trace streaming via OpenOCD esp_apptrace.
 * Sends periodic heartbeat messages via apptrace for performance analysis.
 *
 * CRITICAL QUIRKS FOR RISC-V ESP32 CHIPS (C6, C3, H2, C5):
 * ========================================================
 *
 * 1. TIMING: Start apptrace within 1-2 seconds of reset (not 5+!)
 *    - Firmware waits in esp_apptrace_host_is_connected() loop
 *    - If you start apptrace too late, firmware finishes and exits
 *    - Result: 0 bytes captured even though connection succeeds
 *
 * 2. RESET SEQUENCE: Chip must boot AFTER OpenOCD connects
 *    - During boot, firmware calls esp_apptrace_advertise_ctrl_block()
 *    - This uses semihosting to tell OpenOCD where trace buffer is
 *    - If OpenOCD not running, semihosting call fails, no buffer info
 *    - Always: Start OpenOCD → reset chip → start apptrace quickly
 *    - See: https://github.com/espressif/openocd-esp32/issues/188
 *
 * 3. POLL PERIOD: Must be non-zero (use 1ms or 3ms)
 *    - Command: esp apptrace start file://log.txt 1 2000 10 0 0
 *                                                   ^ poll_period in ms
 *    - poll_period=0 may use default, but 1ms is explicit and works
 *
 * 4. WRITE FROM app_main(): Don't use FreeRTOS tasks
 *    - ESP-IDF examples write directly from app_main()
 *    - Task scheduling can cause timing issues
 *    - Keep it simple: wait for connection, write, done
 *
 * OpenOCD commands (via telnet localhost 4444):
 *   reset run
 *   esp apptrace start file:///tmp/apptrace.log 1 2000 10 0 0
 *   esp apptrace stop
 *   esp apptrace status
 *
 * EAB integration (future):
 *   eabctl trace start --source apptrace --device esp32c6 -o /tmp/trace.rttbin
 *   eabctl trace stop
 *   eabctl trace export -i /tmp/trace.rttbin -o /tmp/trace.json
 */

#include <stdio.h>
#include <string.h>
#include <stdlib.h>
#include "freertos/FreeRTOS.h"
#include "freertos/task.h"
#include "esp_system.h"
#include "esp_chip_info.h"
#include "esp_flash.h"
#include "esp_log.h"
#include "esp_timer.h"
#include "esp_app_trace.h"

static const char *TAG = "APPTRACE_TEST";

#define HEARTBEAT_MS   100  // Fast heartbeat for throughput testing
#define TRACE_TIMEOUT  pdMS_TO_TICKS(10)

static uint32_t heartbeat_count = 0;
static int64_t start_time_us = 0;

static void print_chip_info(void)
{
    esp_chip_info_t info;
    esp_chip_info(&info);

    uint32_t flash_size = 0;
    esp_flash_get_size(NULL, &flash_size);

    ESP_LOGI(TAG, "Chip: ESP32-C6, Cores: %d", info.cores);
    ESP_LOGI(TAG, "Features: WiFi%s%s",
           (info.features & CHIP_FEATURE_BLE) ? " BLE" : "",
           (info.features & CHIP_FEATURE_IEEE802154) ? " 802.15.4" : "");
    ESP_LOGI(TAG, "Flash: %lu MB", (unsigned long)(flash_size / (1024 * 1024)));
    ESP_LOGI(TAG, "Free heap: %lu bytes", (unsigned long)esp_get_free_heap_size());
}

static void apptrace_heartbeat_task(void *arg)
{
    ESP_LOGI(TAG, "=== APPTRACE TASK STARTED ===");
    ESP_LOGI(TAG, "Task stack size: %u bytes", uxTaskGetStackHighWaterMark(NULL));
    ESP_LOGI(TAG, "Waiting for OpenOCD apptrace connection...");

    // Wait for OpenOCD to connect (with debug counter)
    uint32_t wait_count = 0;
    while (!esp_apptrace_host_is_connected(ESP_APPTRACE_DEST_JTAG)) {
        wait_count++;
        if (wait_count % 10 == 0) {
            ESP_LOGI(TAG, "Still waiting for OpenOCD... (checks: %lu)", (unsigned long)wait_count);
        }
        vTaskDelay(pdMS_TO_TICKS(100));
    }

    ESP_LOGI(TAG, "=== OPENOCD APPTRACE CONNECTED! ===");
    ESP_LOGI(TAG, "Connection detected after %lu checks", (unsigned long)wait_count);
    ESP_LOGI(TAG, "Starting trace stream...");

    while (1) {
        heartbeat_count++;
        int64_t uptime_ms = (esp_timer_get_time() - start_time_us) / 1000;
        uint32_t free_heap = esp_get_free_heap_size();

        // Format trace message
        char trace_buf[128];
        int len = snprintf(trace_buf, sizeof(trace_buf),
                          "[TRACE] beat=%lu uptime=%lldms heap=%lu\n",
                          (unsigned long)heartbeat_count,
                          (long long)uptime_ms,
                          (unsigned long)free_heap);

        // Debug log every write for first 5 beats
        if (heartbeat_count <= 5) {
            ESP_LOGI(TAG, "Writing beat #%lu (%d bytes): %s",
                    (unsigned long)heartbeat_count, len, trace_buf);
        }

        // Write to apptrace (high-speed JTAG stream)
        esp_err_t res = esp_apptrace_write(ESP_APPTRACE_DEST_JTAG,
                                           trace_buf,
                                           len,
                                           TRACE_TIMEOUT);
        if (res != ESP_OK) {
            ESP_LOGW(TAG, "apptrace write FAILED: %s (beat #%lu)",
                    esp_err_to_name(res), (unsigned long)heartbeat_count);
        } else if (heartbeat_count <= 5) {
            ESP_LOGI(TAG, "Write SUCCESS (beat #%lu)", (unsigned long)heartbeat_count);
        }

        // Flush periodically to ensure data reaches host
        if (heartbeat_count % 10 == 0) {
            ESP_LOGI(TAG, "Flushing apptrace buffer (beat #%lu)", (unsigned long)heartbeat_count);
            esp_err_t flush_res = esp_apptrace_flush(ESP_APPTRACE_DEST_JTAG, TRACE_TIMEOUT);
            if (flush_res != ESP_OK) {
                ESP_LOGW(TAG, "Flush FAILED: %s", esp_err_to_name(flush_res));
            }
        }

        // Also log to UART for debug visibility
        if (heartbeat_count % 50 == 0) {
            ESP_LOGI(TAG, "=== STATUS: beat=%lu uptime=%lldms heap=%lu ===",
                    (unsigned long)heartbeat_count,
                    (long long)uptime_ms,
                    (unsigned long)free_heap);
        }

        vTaskDelay(pdMS_TO_TICKS(HEARTBEAT_MS));
    }
}

void app_main(void)
{
    start_time_us = esp_timer_get_time();

    printf("\n\n");
    printf("========================================\n");
    printf("  ESP32-C6 Apptrace Test Firmware\n");
    printf("========================================\n");
    printf("High-speed trace streaming via OpenOCD\n\n");

    ESP_LOGI(TAG, "=== APP_MAIN STARTED ===");
    ESP_LOGI(TAG, "Firmware version: DEBUG - apptrace from app_main()");
    print_chip_info();

    ESP_LOGI(TAG, "Waiting for OpenOCD apptrace connection...");

    // CRITICAL: Wait for OpenOCD connection (blocking loop)
    // This loop runs AFTER "reset run" command in OpenOCD
    // OpenOCD must start apptrace within ~1-2 seconds or firmware will timeout/finish
    // On RISC-V ESP chips, this check reads ASSIST_DEBUG register to detect debugger
    uint32_t wait_count = 0;
    while (!esp_apptrace_host_is_connected(ESP_APPTRACE_DEST_JTAG)) {
        wait_count++;
        if (wait_count % 100 == 0) {
            ESP_LOGI(TAG, "Still waiting... (count: %lu)", (unsigned long)wait_count);
        }
        vTaskDelay(1);  // 1 tick delay (not 100ms!) to poll frequently
    }

    ESP_LOGI(TAG, "=== OPENOCD CONNECTED! ===");
    ESP_LOGI(TAG, "Sending test data...");

    // Send 50 heartbeat messages (matches ESP-IDF app_trace_basic example)
    // IMPORTANT: Write directly from app_main(), NOT from a FreeRTOS task
    // ESP-IDF examples use this pattern to avoid task scheduling issues
    // Each write is flushed immediately for low-latency streaming
    for (heartbeat_count = 1; heartbeat_count <= 50; heartbeat_count++) {
        int64_t uptime_ms = (esp_timer_get_time() - start_time_us) / 1000;
        uint32_t free_heap = esp_get_free_heap_size();

        char trace_buf[128];
        int len = snprintf(trace_buf, sizeof(trace_buf),
                          "[TRACE] beat=%lu uptime=%lldms heap=%lu\n",
                          (unsigned long)heartbeat_count,
                          (long long)uptime_ms,
                          (unsigned long)free_heap);

        // Log first 5 writes
        if (heartbeat_count <= 5) {
            ESP_LOGI(TAG, "Writing beat #%lu (%d bytes)", (unsigned long)heartbeat_count, len);
        }

        // Write with infinite timeout (like ESP-IDF example)
        // INFINITE timeout ensures write completes even if JTAG is slow
        // Alternative: Use pdMS_TO_TICKS(10) for 10ms timeout with error handling
        esp_err_t res = esp_apptrace_write(ESP_APPTRACE_DEST_JTAG,
                                           trace_buf,
                                           len,
                                           ESP_APPTRACE_TMO_INFINITE);
        if (res != ESP_OK) {
            ESP_LOGE(TAG, "Write FAILED: %s", esp_err_to_name(res));
        } else if (heartbeat_count <= 5) {
            ESP_LOGI(TAG, "Write SUCCESS");
        }

        // Flush after every write (ESP-IDF example pattern)
        // This ensures low-latency delivery to OpenOCD
        // For higher throughput, flush every N writes instead of every write
        esp_apptrace_flush(ESP_APPTRACE_DEST_JTAG, 1000);

        // Status every 10 beats
        if (heartbeat_count % 10 == 0) {
            ESP_LOGI(TAG, "Progress: %lu/50 beats sent", (unsigned long)heartbeat_count);
        }

        vTaskDelay(pdMS_TO_TICKS(100));
    }

    ESP_LOGI(TAG, "=== ALL DATA SENT! ===");
    ESP_LOGI(TAG, "Total: %lu heartbeats transmitted", (unsigned long)heartbeat_count - 1);
}
