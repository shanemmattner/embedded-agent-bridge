/*
 * STM32-N6 High-Throughput Stress Test
 *
 * Streams continuous data via RTT (Real-Time Transfer) at maximum speed.
 * Outputs timestamped messages with sequence numbers for throughput/latency analysis.
 *
 * Transport: RTT (SEGGER Real-Time Transfer via ST-Link debug probe)
 * Expected throughput: TBD (first STM32-N6 benchmark)
 */

#include <zephyr/kernel.h>
#include <zephyr/sys/printk.h>
#include <zephyr/logging/log.h>

LOG_MODULE_REGISTER(stress_test, LOG_LEVEL_INF);

/* Configuration */
#define MESSAGE_SIZE    64      /* bytes per message */
#define BURST_COUNT     100     /* messages per burst */
#define BURST_DELAY_MS  10      /* delay between bursts */

/* Controlled test pattern - set via debugger */
volatile uint32_t test_enabled = 0;       /* Set to 1 via debugger to start */
volatile uint32_t sample_count = 0;       /* Current sample count */
volatile uint32_t samples_target = 1000000; /* Stop after 1M samples */

/* Statistics */
static uint32_t msg_count = 0;
static uint32_t byte_count = 0;
static uint64_t start_time_ms = 0;

static void print_stats(void)
{
    uint64_t now_ms = k_uptime_get();
    uint64_t elapsed_ms = now_ms - start_time_ms;

    if (elapsed_ms == 0) return;

    double elapsed_sec = elapsed_ms / 1000.0;
    double throughput_kbps = (byte_count / 1024.0) / elapsed_sec;
    double msg_rate = msg_count / elapsed_sec;

    printk("[STATS] msgs=%u bytes=%u uptime=%.1fs throughput=%.1f_KB/s rate=%.0f_msg/s\n",
           msg_count, byte_count, elapsed_sec, throughput_kbps, msg_rate);
}

static void stress_test_thread(void *p1, void *p2, void *p3)
{
    ARG_UNUSED(p1);
    ARG_UNUSED(p2);
    ARG_UNUSED(p3);

    char buffer[MESSAGE_SIZE];

    LOG_INF("STM32N6 Stress Test Ready");
    LOG_INF("Waiting for test_enabled=1 (set via debugger)...");
    LOG_INF("Target: %u samples", samples_target);

    /* Wait for test_enabled flag (set via debugger) */
    while (!test_enabled) {
        k_msleep(100);
    }

    start_time_ms = k_uptime_get();
    LOG_INF("Test starting...");
    LOG_INF("Message size: %d bytes", MESSAGE_SIZE);
    LOG_INF("Burst: %d messages every %d ms", BURST_COUNT, BURST_DELAY_MS);

    /* Run until target samples reached */
    while (sample_count < samples_target && test_enabled) {
        /* Burst of messages */
        for (int i = 0; i < BURST_COUNT && sample_count < samples_target; i++) {
            uint64_t timestamp_ms = k_uptime_get();

            int len = snprintf(buffer, MESSAGE_SIZE,
                             "[DATA] seq=%u t=%llu\n",
                             sample_count, timestamp_ms);

            /* Write to RTT */
            printk("%s", buffer);

            msg_count++;
            sample_count++;
            byte_count += len;
        }

        /* Print stats every 10 bursts (1 second at 10ms burst delay) */
        if ((msg_count % (BURST_COUNT * 10)) == 0) {
            print_stats();
        }

        k_msleep(BURST_DELAY_MS);
    }

    /* Test complete */
    print_stats();
    LOG_INF("Test complete!");
    LOG_INF("Total samples: %u", sample_count);
    test_enabled = 0;
    LOG_INF("Entering low-power idle mode...");

    /* Idle loop */
    while (1) {
        k_msleep(1000);
    }
}

K_THREAD_DEFINE(stress_test_tid, 2048,
                stress_test_thread, NULL, NULL, NULL,
                5, 0, 0);

int main(void)
{
    LOG_INF("STM32-N6 Stress Test Firmware");
    LOG_INF("Board: %s", CONFIG_BOARD);

    /* Main thread exits, stress_test_thread continues */
    return 0;
}
