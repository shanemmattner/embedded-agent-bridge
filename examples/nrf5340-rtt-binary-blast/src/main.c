/*
 * RTT Binary Blast — Maximum throughput test for nRF5340
 *
 * Generates a synthetic 500 Hz sine wave as int16_t samples and writes
 * raw binary data to RTT channel 1 as fast as possible.
 *
 * Channel 0: text status (printk)
 * Channel 1: raw binary data (int16_t samples, little-endian)
 *
 * The sine table is precomputed. The tight loop does:
 *   1. Copy chunk from sine table into tx buffer
 *   2. SEGGER_RTT_Write(1, buf, len)
 *   3. Track stats
 */

#include <zephyr/kernel.h>
#include <SEGGER_RTT.h>
#include <string.h>

/* 16 KB up buffer on channel 1 for binary data */
static char rtt_up_buf_1[16384];

/* Pre-computed sine table: one full cycle, 64 samples, int16_t
 * 500 Hz at ~32 kHz sample rate = 64 samples/cycle
 * Amplitude: +/- 30000 (leaves headroom below int16 max)
 */
#define SINE_TABLE_LEN 64
static int16_t sine_table[SINE_TABLE_LEN];

static void init_sine_table(void)
{
    /* Integer sine approximation — no floating point needed.
     * sin(2*pi*i/64) * 30000, precomputed via integer math.
     * Using a well-known 64-point sine lookup.
     */
    static const int16_t lut[SINE_TABLE_LEN] = {
        0,  2940,  5843,  8672, 11392, 13969, 16369, 18564,
        20527, 22234, 23666, 24808, 25645, 26172, 26384, 26283,
        25872, 25160, 24160, 22886, 21358, 19597, 17626, 15472,
        13160, 10720,  8181,  5573,  2927,   274, -2364, -4965,
        -7506, -9966, -12323, -14558, -16651, -18586, -20347, -21921,
        -23296, -24463, -25414, -26143, -26649, -26929, -26984, -26816,
        -26430, -25831, -25027, -24027, -22843, -21488, -19977, -18326,
        -16551, -14672, -12706, -10672, -8590, -6479, -4359, -2248,
    };
    memcpy(sine_table, lut, sizeof(lut));
}

/* Transmit buffer — filled with sine samples then sent via RTT */
#define TX_CHUNK_SAMPLES 512
#define TX_CHUNK_BYTES   (TX_CHUNK_SAMPLES * sizeof(int16_t))
static int16_t tx_buf[TX_CHUNK_SAMPLES];

int main(void)
{
    init_sine_table();

    /* Configure RTT channel 1 for binary data with large buffer */
    SEGGER_RTT_ConfigUpBuffer(1, "BinaryData", rtt_up_buf_1,
                              sizeof(rtt_up_buf_1),
                              SEGGER_RTT_MODE_NO_BLOCK_SKIP);

    printk("RTT Binary Blast starting\n");
    printk("Channel 1: %d byte buffer, %d sample chunks\n",
           (int)sizeof(rtt_up_buf_1), TX_CHUNK_SAMPLES);

    uint32_t total_bytes = 0;
    uint32_t total_dropped = 0;
    uint32_t writes = 0;
    uint32_t sine_idx = 0;
    uint32_t start_ms = k_uptime_get_32();
    uint32_t last_report_ms = start_ms;

    while (1) {
        /* Fill tx buffer with sine samples */
        for (int i = 0; i < TX_CHUNK_SAMPLES; i++) {
            tx_buf[i] = sine_table[sine_idx % SINE_TABLE_LEN];
            sine_idx++;
        }

        /* Write raw binary to RTT channel 1 */
        unsigned written = SEGGER_RTT_Write(1, tx_buf, TX_CHUNK_BYTES);
        if (written == TX_CHUNK_BYTES) {
            total_bytes += written;
            writes++;
        } else {
            /* Buffer full — data dropped (non-blocking mode) */
            total_dropped += TX_CHUNK_BYTES - written;
            total_bytes += written;
            writes++;
            /* Small yield to let J-Link drain the buffer */
            k_busy_wait(10);
        }

        /* Report stats every second on channel 0 */
        uint32_t now = k_uptime_get_32();
        if (now - last_report_ms >= 1000) {
            uint32_t elapsed_s = (now - start_ms) / 1000;
            uint32_t rate_bps = 0;
            if (elapsed_s > 0) {
                rate_bps = total_bytes / elapsed_s;
            }
            printk("[%us] %u KB sent, %u KB/s, %u drops, %u writes\n",
                   elapsed_s,
                   total_bytes / 1024,
                   rate_bps / 1024,
                   total_dropped / 1024,
                   writes);
            last_report_ms = now;
        }
    }
    return 0;
}
