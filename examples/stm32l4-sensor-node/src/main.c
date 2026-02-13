/*
 * EAB Sensor Node — STM32L4 (Nucleo-L432KC)
 *
 * Reads internal temperature sensor and VREFINT via ADC.
 * Sends JSON lines over USART1 (PA9 TX, PA10 RX) to nRF5340 hub every 1s.
 * Console output via USART2 (PA2/PA15) ST-Link VCP — EAB monitors this.
 *
 * Output format (USART1 data link):
 *   {"node":"stm32","temp_c":24.5,"vref_mv":3301}
 */

#include <zephyr/kernel.h>
#include <zephyr/device.h>
#include <zephyr/devicetree.h>
#include <zephyr/drivers/adc.h>
#include <zephyr/drivers/uart.h>
#include <zephyr/logging/log.h>
#include <stdio.h>

LOG_MODULE_REGISTER(sensor_node, LOG_LEVEL_INF);

/* ADC channels — STM32L4 internal sensors */
#define ADC_NODE       DT_NODELABEL(adc1)
#define ADC_RESOLUTION 12
#define ADC_VREF_MV    3300

/* STM32L4 internal temp sensor calibration (from datasheet) */
#define TS_CAL1_TEMP   30
#define TS_CAL2_TEMP   130
#define TS_CAL_VREF    3000  /* Calibration reference voltage in mV */

static const struct device *adc_dev = DEVICE_DT_GET(ADC_NODE);

/* Channel 17 = internal temp sensor, Channel 0 = VREFINT on STM32L4 */
static struct adc_channel_cfg temp_ch_cfg = {
	.gain = ADC_GAIN_1,
	.reference = ADC_REF_INTERNAL,
	.acquisition_time = ADC_ACQ_TIME_DEFAULT,
	.channel_id = 17,
	.differential = 0,
};

static struct adc_channel_cfg vref_ch_cfg = {
	.gain = ADC_GAIN_1,
	.reference = ADC_REF_INTERNAL,
	.acquisition_time = ADC_ACQ_TIME_DEFAULT,
	.channel_id = 0,
	.differential = 0,
};

/* Data link UART — USART1 to nRF5340 */
static const struct device *data_uart = DEVICE_DT_GET(DT_NODELABEL(usart1));

static int16_t adc_buf[1];

static struct adc_sequence adc_seq = {
	.buffer = adc_buf,
	.buffer_size = sizeof(adc_buf),
	.resolution = ADC_RESOLUTION,
};

static void uart_send_string(const struct device *dev, const char *str)
{
	while (*str) {
		uart_poll_out(dev, *str++);
	}
}

static int read_adc_channel(uint8_t channel_id)
{
	adc_seq.channels = BIT(channel_id);
	int ret = adc_read(adc_dev, &adc_seq);
	if (ret < 0) {
		LOG_ERR("ADC read failed (ch %u): %d", channel_id, ret);
		return -1;
	}
	return adc_buf[0];
}

int main(void)
{
	LOG_INF("=== EAB Sensor Node (STM32L4) v1.0 ===");

	if (!device_is_ready(adc_dev)) {
		LOG_ERR("ADC device not ready");
		return -1;
	}

	if (!device_is_ready(data_uart)) {
		LOG_ERR("Data UART (USART1) not ready");
		return -1;
	}

	/* Configure ADC channels */
	int ret = adc_channel_setup(adc_dev, &temp_ch_cfg);
	if (ret < 0) {
		LOG_ERR("ADC temp channel setup failed: %d", ret);
		return ret;
	}

	ret = adc_channel_setup(adc_dev, &vref_ch_cfg);
	if (ret < 0) {
		LOG_ERR("ADC vref channel setup failed: %d", ret);
		return ret;
	}

	LOG_INF("ADC configured — reading temp sensor + VREFINT");
	LOG_INF("Data link: USART1 (PA9/PA10) → nRF5340");

	char json_buf[128];
	uint32_t seq = 0;

	while (1) {
		/* Read internal temperature sensor */
		int raw_temp = read_adc_channel(17);
		/* Read VREFINT */
		int raw_vref = read_adc_channel(0);

		if (raw_temp < 0 || raw_vref < 0) {
			k_msleep(1000);
			continue;
		}

		/*
		 * Convert raw ADC to temperature (simplified).
		 * STM32L4 temp sensor: ~2.5mV/°C, Vat25 ~0.76V
		 * Using linear approximation from ADC raw values.
		 */
		int32_t temp_mv = (int32_t)raw_temp * ADC_VREF_MV / (1 << ADC_RESOLUTION);
		/* Approximate: 760mV at 25°C, 2.5mV/°C slope */
		int32_t temp_c_x10 = 250 + (7600 - temp_mv * 10) / 25;

		/* VREFINT: typically ~1.212V, use to calculate actual VDD */
		int32_t vref_mv = (int32_t)raw_vref * ADC_VREF_MV / (1 << ADC_RESOLUTION);

		/* Format JSON */
		snprintf(json_buf, sizeof(json_buf),
			 "{\"node\":\"stm32\",\"temp_c\":%d.%d,\"vref_mv\":%d}\n",
			 (int)(temp_c_x10 / 10),
			 (int)(temp_c_x10 >= 0 ? temp_c_x10 % 10 : -(temp_c_x10 % 10)),
			 (int)vref_mv);

		/* Send over data link to nRF5340 */
		uart_send_string(data_uart, json_buf);

		/* Log to console (EAB monitors via ST-Link VCP) */
		seq++;
		LOG_INF("[%u] TX → nRF5340: temp=%d.%d°C vref=%dmV",
			seq,
			(int)(temp_c_x10 / 10),
			(int)(temp_c_x10 >= 0 ? temp_c_x10 % 10 : -(temp_c_x10 % 10)),
			(int)vref_mv);

		k_msleep(1000);
	}

	return 0;
}
