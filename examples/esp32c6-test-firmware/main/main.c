/**
 * EAB Test Firmware for ESP32-C6
 *
 * Minimal firmware that exercises all EAB serial monitoring features:
 * - Periodic heartbeat output (tests tail/logging)
 * - Command echo (tests send/receive)
 * - Simulated alerts (tests pattern detection)
 * - Status reporting (tests JSON parsing)
 *
 * Commands (send via serial):
 *   help        - Show available commands
 *   status      - Print device status JSON
 *   info        - Print chip info
 *   crash       - Simulate a crash pattern (for alert testing)
 *   error       - Simulate an error pattern
 *   echo <text> - Echo back text
 *   reboot      - Restart the device
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
#include "driver/uart.h"

static const char *TAG = "EAB_TEST";

#define UART_NUM       UART_NUM_0
#define BUF_SIZE       256
#define HEARTBEAT_MS   5000
#define MAX_CMD_LEN    128

static uint32_t heartbeat_count = 0;
static uint32_t cmd_count = 0;
static int64_t start_time_us = 0;

static void print_help(void)
{
    printf("=== EAB Test Firmware ===\n");
    printf("Commands:\n");
    printf("  help        Show this help\n");
    printf("  status      Print device status (JSON)\n");
    printf("  info        Print chip info\n");
    printf("  crash       Simulate crash pattern\n");
    printf("  error       Simulate error log\n");
    printf("  echo <txt>  Echo text back\n");
    printf("  reboot      Restart device\n");
}

static void print_status(void)
{
    int64_t uptime_s = (esp_timer_get_time() - start_time_us) / 1000000;
    uint32_t free_heap = esp_get_free_heap_size();

    printf("{\"uptime_s\":%lld,\"heartbeats\":%lu,\"commands\":%lu,"
           "\"free_heap\":%lu,\"status\":\"running\"}\n",
           (long long)uptime_s, (unsigned long)heartbeat_count,
           (unsigned long)cmd_count, (unsigned long)free_heap);
}

static void print_chip_info(void)
{
    esp_chip_info_t info;
    esp_chip_info(&info);

    uint32_t flash_size = 0;
    esp_flash_get_size(NULL, &flash_size);

    printf("Chip: ESP32-C6\n");
    printf("Cores: %d\n", info.cores);
    printf("Features: WiFi%s%s\n",
           (info.features & CHIP_FEATURE_BLE) ? " BLE" : "",
           (info.features & CHIP_FEATURE_IEEE802154) ? " 802.15.4" : "");
    printf("Flash: %lu MB\n", (unsigned long)(flash_size / (1024 * 1024)));
    printf("Free heap: %lu bytes\n", (unsigned long)esp_get_free_heap_size());
}

static void simulate_crash(void)
{
    /* These patterns trigger EAB's alert detection */
    printf("Guru Meditation Error: Core  0 panic'ed (IllegalInstruction)\n");
    printf("Backtrace: 0x40081234:0x3ffb0000 0x40082345:0x3ffb0010\n");
    printf("(This is a simulated crash for EAB testing)\n");
}

static void simulate_error(void)
{
    ESP_LOGE(TAG, "Simulated error for EAB alert testing");
    ESP_LOGW(TAG, "This is a warning pattern");
}

static void process_command(const char *cmd)
{
    cmd_count++;

    /* Trim leading/trailing whitespace */
    while (*cmd == ' ' || *cmd == '\r' || *cmd == '\n') cmd++;
    char trimmed[MAX_CMD_LEN];
    strncpy(trimmed, cmd, sizeof(trimmed) - 1);
    trimmed[sizeof(trimmed) - 1] = '\0';
    size_t len = strlen(trimmed);
    while (len > 0 && (trimmed[len-1] == ' ' || trimmed[len-1] == '\r' || trimmed[len-1] == '\n')) {
        trimmed[--len] = '\0';
    }

    if (len == 0) return;

    printf(">>> CMD: %s\n", trimmed);

    if (strcmp(trimmed, "help") == 0) {
        print_help();
    } else if (strcmp(trimmed, "status") == 0) {
        print_status();
    } else if (strcmp(trimmed, "info") == 0) {
        print_chip_info();
    } else if (strcmp(trimmed, "crash") == 0) {
        simulate_crash();
    } else if (strcmp(trimmed, "error") == 0) {
        simulate_error();
    } else if (strncmp(trimmed, "echo ", 5) == 0) {
        printf("ECHO: %s\n", trimmed + 5);
    } else if (strcmp(trimmed, "reboot") == 0) {
        printf("Rebooting in 1 second...\n");
        vTaskDelay(pdMS_TO_TICKS(1000));
        esp_restart();
    } else {
        printf("Unknown command: %s\n", trimmed);
        printf("Type 'help' for available commands.\n");
    }
}

static void heartbeat_task(void *arg)
{
    while (1) {
        heartbeat_count++;
        int64_t uptime_s = (esp_timer_get_time() - start_time_us) / 1000000;
        printf("[heartbeat] #%lu uptime=%llds heap=%lu\n",
               (unsigned long)heartbeat_count,
               (long long)uptime_s,
               (unsigned long)esp_get_free_heap_size());
        vTaskDelay(pdMS_TO_TICKS(HEARTBEAT_MS));
    }
}

static void uart_rx_task(void *arg)
{
    uint8_t buf[BUF_SIZE];
    char cmd_buf[MAX_CMD_LEN];
    int cmd_pos = 0;

    while (1) {
        int len = uart_read_bytes(UART_NUM, buf, sizeof(buf) - 1, pdMS_TO_TICKS(100));
        if (len > 0) {
            for (int i = 0; i < len; i++) {
                char c = (char)buf[i];
                if (c == '\n' || c == '\r') {
                    if (cmd_pos > 0) {
                        cmd_buf[cmd_pos] = '\0';
                        process_command(cmd_buf);
                        cmd_pos = 0;
                    }
                } else if (cmd_pos < MAX_CMD_LEN - 1) {
                    cmd_buf[cmd_pos++] = c;
                }
            }
        }
    }
}

void app_main(void)
{
    start_time_us = esp_timer_get_time();

    /* Configure UART0 for serial communication */
    uart_config_t uart_config = {
        .baud_rate = 115200,
        .data_bits = UART_DATA_8_BITS,
        .parity    = UART_PARITY_DISABLE,
        .stop_bits = UART_STOP_BITS_1,
        .flow_ctrl = UART_HW_FLOWCTRL_DISABLE,
    };
    uart_param_config(UART_NUM, &uart_config);
    uart_driver_install(UART_NUM, BUF_SIZE * 2, 0, 0, NULL, 0);

    printf("\n\n");
    printf("========================================\n");
    printf("  EAB Test Firmware v1.0 (ESP32-C6)\n");
    printf("========================================\n");
    printf("Ready. Type 'help' for commands.\n\n");

    ESP_LOGI(TAG, "EAB test firmware started");

    /* Start background tasks */
    xTaskCreate(heartbeat_task, "heartbeat", 2048, NULL, 5, NULL);
    xTaskCreate(uart_rx_task, "uart_rx", 4096, NULL, 10, NULL);
}
