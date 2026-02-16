/*
 * C2000 Stress Test - Controlled High-Throughput Test
 *
 * Based on TI sci_ex3_echoback.c reference
 * - Controlled start/stop via debugger (test_enabled flag)
 * - Runs for 1M samples then auto-stops
 * - Generates sine wave data
 * - Outputs via SCI UART at 9600 baud (XDS110 backchannel)
 */

#include "driverlib.h"
#include "device.h"

/* Controlled test pattern - set via debugger */
volatile uint32_t test_enabled = 0;       /* Set to 1 via debugger to start */
volatile uint32_t sample_count = 0;       /* Current sample count */
volatile uint32_t samples_target = 1000000; /* Stop after 1M samples */

/* Sine table (64 samples, one full cycle) */
#define SINE_TABLE_LEN 64
static int16_t sine_table[SINE_TABLE_LEN] = {
    0,  2940,  5843,  8672, 11392, 13969, 16369, 18564,
    20527, 22234, 23666, 24808, 25645, 26172, 26384, 26283,
    25872, 25160, 24160, 22886, 21358, 19597, 17626, 15472,
    13160, 10720,  8181,  5573,  2927,   274, -2364, -4965,
    -7506, -9966, -12323, -14558, -16651, -18586, -20347, -21921,
    -23296, -24463, -25414, -26143, -26649, -26929, -26984, -26816,
    -26430, -25831, -25027, -24027, -22843, -21488, -19977, -18326,
    -16551, -14672, -12706, -10672, -8590, -6479, -4359, -2248,
};

/* Send a string via SCI-A using TI's writeCharArray */
static void sci_puts(const char *s)
{
    uint16_t len = 0;
    const char *p = s;
    while (*p++) len++;
    SCI_writeCharArray(SCIA_BASE, (const uint16_t*)s, len);
}

/* Simple unsigned int to string, then send */
static void sci_putu32(uint32_t val)
{
    char buf[12];
    uint16_t i = 0;
    if (val == 0) {
        uint16_t zero = '0';
        SCI_writeCharArray(SCIA_BASE, &zero, 1);
        return;
    }
    while (val > 0) {
        buf[i++] = '0' + (val % 10);
        val /= 10;
    }
    /* Reverse and send */
    while (i > 0) {
        uint16_t ch = (uint16_t)buf[--i];
        SCI_writeCharArray(SCIA_BASE, &ch, 1);
    }
}

/* Simple signed int to string, then send */
static void sci_puti16(int16_t val)
{
    if (val < 0) {
        uint16_t minus = '-';
        SCI_writeCharArray(SCIA_BASE, &minus, 1);
        sci_putu32((uint32_t)(-val));
    } else {
        sci_putu32((uint32_t)val);
    }
}

void main(void)
{
    uint32_t sine_idx = 0;

    /*
     * Configure PLL, disable WD, enable peripheral clocks.
     */
    Device_init();

    /*
     * Disable pin locks and enable internal pullups.
     */
    Device_initGPIO();

    /*
     * SCI-A GPIO configuration (GPIO28=RX, GPIO29=TX)
     * Matches TI sci_ex3_echoback reference
     */
    GPIO_setPinConfig(DEVICE_GPIO_CFG_SCIRXDA);
    GPIO_setDirectionMode(DEVICE_GPIO_PIN_SCIRXDA, GPIO_DIR_MODE_IN);
    GPIO_setPadConfig(DEVICE_GPIO_PIN_SCIRXDA, GPIO_PIN_TYPE_STD);
    GPIO_setQualificationMode(DEVICE_GPIO_PIN_SCIRXDA, GPIO_QUAL_ASYNC);

    GPIO_setPinConfig(DEVICE_GPIO_CFG_SCITXDA);
    GPIO_setDirectionMode(DEVICE_GPIO_PIN_SCITXDA, GPIO_DIR_MODE_OUT);
    GPIO_setPadConfig(DEVICE_GPIO_PIN_SCITXDA, GPIO_PIN_TYPE_STD);
    GPIO_setQualificationMode(DEVICE_GPIO_PIN_SCITXDA, GPIO_QUAL_ASYNC);

    /*
     * Initialize interrupt controller and vector table.
     */
    Interrupt_initModule();
    Interrupt_initVectorTable();

    /*
     * Initialize SCI-A at 9600 baud (matching TI reference)
     */
    SCI_performSoftwareReset(SCIA_BASE);

    SCI_setConfig(SCIA_BASE, DEVICE_LSPCLK_FREQ, 9600,
                  (SCI_CONFIG_WLEN_8 | SCI_CONFIG_STOP_ONE |
                   SCI_CONFIG_PAR_NONE));
    SCI_resetChannels(SCIA_BASE);
    SCI_resetRxFIFO(SCIA_BASE);
    SCI_resetTxFIFO(SCIA_BASE);
    SCI_clearInterruptStatus(SCIA_BASE, SCI_INT_TXFF | SCI_INT_RXFF);
    SCI_enableFIFO(SCIA_BASE);
    SCI_enableModule(SCIA_BASE);
    SCI_performSoftwareReset(SCIA_BASE);

    /*
     * Banner
     */
    sci_puts("\r\n\r\nC2000 Stress Test Ready\r\n");
    sci_puts("Waiting for test_enabled=1 (set via debugger)...\r\n");
    sci_puts("Target: ");
    sci_putu32(samples_target);
    sci_puts(" samples\r\n");

    while (!test_enabled) {
        DEVICE_DELAY_US(100000); /* 100ms delay */
    }

    sci_puts("Test starting...\r\n");

    /* Main test loop - run until target samples reached */
    while (sample_count < samples_target && test_enabled) {
        int16_t value = sine_table[sine_idx % SINE_TABLE_LEN];

        /* Output sample data */
        sci_puts("[DATA] seq=");
        sci_putu32(sample_count);
        sci_puts(" val=");
        sci_puti16(value);
        sci_puts("\r\n");

        sine_idx++;
        sample_count++;

        /* Print stats every 10,000 samples */
        if ((sample_count % 10000) == 0) {
            sci_puts("[STATS] samples=");
            sci_putu32(sample_count);
            sci_puts("\r\n");
        }

        DEVICE_DELAY_US(100); /* ~10kHz sample rate */
    }

    /* Test complete */
    sci_puts("Test complete!\r\n");
    sci_puts("Total samples: ");
    sci_putu32(sample_count);
    sci_puts("\r\n");

    /* Clear flag and enter idle loop */
    test_enabled = 0;
    sci_puts("Entering low-power idle mode...\r\n");

    while (1) {
        IDLE;
    }
}
