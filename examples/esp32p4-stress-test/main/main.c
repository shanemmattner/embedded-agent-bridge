/*
 * ESP32-P4 High-Throughput Stress Test
 *
 * Streams continuous data via UART at maximum speed to test EAB serial daemon.
 * Outputs timestamped messages with sequence numbers for throughput/latency analysis.
 *
 * Transport: USB Serial (built-in USB-JTAG/Serial)
 * Expected throughput: ~90 KB/s (similar to ESP32-C6 apptrace)
 */

#include <stdio.h>
#include <string.h>
#include "freertos/FreeRTOS.h"
#include "freertos/task.h"
#include "esp_system.h"
#include "esp_log.h"
#include "esp_timer.h"

static const char *TAG = "stress-test";

/* Configuration */
#define MESSAGE_SIZE    64      /* bytes per message */
#define BURST_COUNT     100     /* messages per burst */
#define BURST_DELAY_MS  10      /* delay between bursts */

/* Statistics */
static uint32_t msg_count = 0;
static uint32_t byte_count = 0;
static uint64_t start_time_us = 0;

static void print_stats(void)
{
    uint64_t now_us = esp_timer_get_time();
    uint64_t elapsed_us = now_us - start_time_us;

    if (elapsed_us == 0) return;

    double elapsed_sec = elapsed_us / 1000000.0;
    double throughput_kbps = (byte_count / 1024.0) / elapsed_sec;
    double msg_rate = msg_count / elapsed_sec;

    uint32_t heap_free = esp_get_free_heap_size();

    printf("[STATS] msgs=%lu bytes=%lu uptime=%.1fs throughput=%.1f_KB/s rate=%.0f_msg/s heap=%lu\n",
           msg_count, byte_count, elapsed_sec, throughput_kbps, msg_rate, heap_free);
}

static void stress_test_task(void *pvParameters)
{
    char buffer[MESSAGE_SIZE];

    start_time_us = esp_timer_get_time();

    ESP_LOGI(TAG, "Starting high-throughput stress test");
    ESP_LOGI(TAG, "Message size: %d bytes", MESSAGE_SIZE);
    ESP_LOGI(TAG, "Burst: %d messages every %d ms", BURST_COUNT, BURST_DELAY_MS);

    while (1) {
        /* Burst of messages */
        for (int i = 0; i < BURST_COUNT; i++) {
            uint64_t timestamp_us = esp_timer_get_time();

            int len = snprintf(buffer, MESSAGE_SIZE,
                             "[DATA] seq=%lu t=%llu heap=%lu\n",
                             msg_count, timestamp_us, esp_get_free_heap_size());

            /* Write to stdout (USB serial) */
            fwrite(buffer, 1, len, stdout);
            fflush(stdout);

            msg_count++;
            byte_count += len;
        }

        /* Print stats every 10 bursts (1 second at 10ms burst delay) */
        if ((msg_count % (BURST_COUNT * 10)) == 0) {
            print_stats();
        }

        vTaskDelay(pdMS_TO_TICKS(BURST_DELAY_MS));
    }
}

void app_main(void)
{
    ESP_LOGI(TAG, "ESP32-P4 Stress Test Firmware");
    ESP_LOGI(TAG, "Chip: %s", CONFIG_IDF_TARGET);
    ESP_LOGI(TAG, "Free heap: %lu bytes", esp_get_free_heap_size());

    /* Disable buffering for immediate output */
    setvbuf(stdout, NULL, _IONBF, 0);

    /* Start stress test task */
    xTaskCreate(stress_test_task, "stress_test", 4096, NULL, 5, NULL);
}
