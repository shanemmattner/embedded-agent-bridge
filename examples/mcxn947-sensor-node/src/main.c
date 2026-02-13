/*
 * EAB Sensor Node — FRDM-MCXN947
 *
 * Reads ADC channel 0 and GPIO buttons (SW2/SW3).
 * Sends JSON lines over LPUART2 (Arduino header D0/D1) to ESP32-C6 every 1s.
 * Console output via USB-CDC (flexcomm4_lpuart4) — EAB monitors this.
 *
 * Output format (LPUART2 data link):
 *   {"node":"nxp","adc0":1234,"btn_sw2":0,"btn_sw3":1}
 */

#include <zephyr/kernel.h>
#include <zephyr/device.h>
#include <zephyr/devicetree.h>
#include <zephyr/drivers/adc.h>
#include <zephyr/drivers/gpio.h>
#include <zephyr/drivers/uart.h>
#include <zephyr/logging/log.h>
#include <stdio.h>

LOG_MODULE_REGISTER(sensor_node, LOG_LEVEL_INF);

/* ADC */
#define ADC_NODE       DT_NODELABEL(lpadc0)
#define ADC_CHANNEL    0
#define ADC_RESOLUTION 12

static const struct device *adc_dev = DEVICE_DT_GET(ADC_NODE);

static struct adc_channel_cfg adc_ch_cfg = {
	.gain = ADC_GAIN_1,
	.reference = ADC_REF_EXTERNAL1,
	.acquisition_time = ADC_ACQ_TIME_DEFAULT,
	.channel_id = ADC_CHANNEL,
	.input_positive = ADC_CHANNEL,
	.differential = 0,
};

static int16_t adc_buf[1];

static struct adc_sequence adc_seq = {
	.channels = BIT(ADC_CHANNEL),
	.buffer = adc_buf,
	.buffer_size = sizeof(adc_buf),
	.resolution = ADC_RESOLUTION,
};

/* Buttons — SW2 (sw0), SW3 (sw1) */
static const struct gpio_dt_spec btn_sw2 = GPIO_DT_SPEC_GET(DT_ALIAS(sw0), gpios);
static const struct gpio_dt_spec btn_sw3 = GPIO_DT_SPEC_GET(DT_ALIAS(sw1), gpios);

/* Data link UART — LPUART2 on Arduino header D0/D1 */
static const struct device *data_uart = DEVICE_DT_GET(DT_NODELABEL(flexcomm2_lpuart2));

static void uart_send_string(const struct device *dev, const char *str)
{
	while (*str) {
		uart_poll_out(dev, *str++);
	}
}

int main(void)
{
	LOG_INF("=== EAB Sensor Node (FRDM-MCXN947) v1.0 ===");

	/* Init ADC */
	if (!device_is_ready(adc_dev)) {
		LOG_ERR("ADC device not ready");
		return -1;
	}

	int ret = adc_channel_setup(adc_dev, &adc_ch_cfg);
	if (ret < 0) {
		LOG_ERR("ADC channel setup failed: %d", ret);
		return ret;
	}

	/* Init buttons */
	if (gpio_is_ready_dt(&btn_sw2)) {
		gpio_pin_configure_dt(&btn_sw2, GPIO_INPUT);
	} else {
		LOG_WRN("SW2 not ready");
	}

	if (gpio_is_ready_dt(&btn_sw3)) {
		gpio_pin_configure_dt(&btn_sw3, GPIO_INPUT);
	} else {
		LOG_WRN("SW3 not ready");
	}

	/* Init data UART */
	if (!device_is_ready(data_uart)) {
		LOG_ERR("Data UART (LPUART2) not ready");
		return -1;
	}

	LOG_INF("ADC + GPIO configured");
	LOG_INF("Data link: LPUART2 (Arduino D0/D1) → ESP32-C6");

	char json_buf[128];
	uint32_t seq = 0;

	while (1) {
		/* Read ADC */
		ret = adc_read(adc_dev, &adc_seq);
		int adc_val = (ret == 0) ? adc_buf[0] : -1;

		/* Read buttons (active low on FRDM board) */
		int sw2 = gpio_is_ready_dt(&btn_sw2) ?
			  !gpio_pin_get_dt(&btn_sw2) : 0;
		int sw3 = gpio_is_ready_dt(&btn_sw3) ?
			  !gpio_pin_get_dt(&btn_sw3) : 0;

		/* Format JSON */
		snprintf(json_buf, sizeof(json_buf),
			 "{\"node\":\"nxp\",\"adc0\":%d,\"btn_sw2\":%d,\"btn_sw3\":%d}\n",
			 adc_val, sw2, sw3);

		/* Send over data link to ESP32-C6 */
		uart_send_string(data_uart, json_buf);

		/* Log to console (EAB monitors via USB-CDC) */
		seq++;
		LOG_INF("[%u] TX → ESP32: adc0=%d sw2=%d sw3=%d",
			seq, adc_val, sw2, sw3);

		k_msleep(1000);
	}

	return 0;
}
