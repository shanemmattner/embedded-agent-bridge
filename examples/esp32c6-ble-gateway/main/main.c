/*
 * EAB BLE Gateway — ESP32-C6
 *
 * BLE peripheral + UART bridge. Collects sensor data from MCXN947 via UART,
 * combines with own heap/uptime stats, and advertises via BLE GATT notifications.
 *
 * UART from MCXN947: GPIO4 (RX), GPIO5 (TX), 115200 baud
 * BLE: Custom GATT service (EAB10001-...), notify characteristic with JSON payload
 * Advertise name: EAB-ESP32C6
 * Console: USB Serial/JTAG — EAB monitors this
 */

#include <stdio.h>
#include <string.h>
#include <stdlib.h>

#include "freertos/FreeRTOS.h"
#include "freertos/task.h"
#include "freertos/queue.h"

#include "esp_system.h"
#include "esp_log.h"
#include "esp_timer.h"
#include "nvs_flash.h"

#include "driver/uart.h"
#include "driver/usb_serial_jtag.h"
#include "driver/usb_serial_jtag_vfs.h"

/* NimBLE */
#include "host/ble_hs.h"
#include "host/util/util.h"
#include "nimble/nimble_port.h"
#include "nimble/nimble_port_freertos.h"
#include "services/gap/ble_svc_gap.h"
#include "services/gatt/ble_svc_gatt.h"

static const char *TAG = "EAB_GW";

/* UART config for MCXN947 data link */
#define DATA_UART_NUM    UART_NUM_1
#define DATA_UART_TX_PIN 5
#define DATA_UART_RX_PIN 4
#define DATA_UART_BAUD   115200
#define DATA_UART_BUF_SZ 1024

/* BLE UUIDs */
static const ble_uuid128_t svc_uuid = BLE_UUID128_INIT(
	0xfb, 0x34, 0x9b, 0x5f, 0x80, 0x00, 0x00, 0x80,
	0x00, 0x10, 0x00, 0x00, 0x01, 0x00, 0xB1, 0xEA
);

static const ble_uuid128_t chr_notify_uuid = BLE_UUID128_INIT(
	0xfb, 0x34, 0x9b, 0x5f, 0x80, 0x00, 0x00, 0x80,
	0x00, 0x10, 0x00, 0x00, 0x02, 0x00, 0xB1, 0xEA
);

static const ble_uuid128_t chr_write_uuid = BLE_UUID128_INIT(
	0xfb, 0x34, 0x9b, 0x5f, 0x80, 0x00, 0x00, 0x80,
	0x00, 0x10, 0x00, 0x00, 0x03, 0x00, 0xB1, 0xEA
);

static uint16_t notify_handle;
static uint16_t conn_handle;
static bool ble_connected = false;

/* Latest data from MCXN947 (protected by mutex) */
static SemaphoreHandle_t data_mutex;
static char nxp_data[256] = "{\"adc0\":0,\"btn_sw2\":0,\"btn_sw3\":0}";
static int64_t start_time_us;

/*
 * Parse a simple integer field from JSON string.
 * Returns the value or fallback if not found.
 */
static int json_get_int(const char *json, const char *key, int fallback)
{
	char search[64];
	snprintf(search, sizeof(search), "\"%s\":", key);
	const char *p = strstr(json, search);
	if (!p) {
		return fallback;
	}
	p += strlen(search);
	return atoi(p);
}

/* ===================================================================
 * GATT Server
 * =================================================================== */

static int gatt_access_cb(uint16_t conn_handle_arg, uint16_t attr_handle,
			   struct ble_gatt_access_ctxt *ctxt, void *arg)
{
	if (attr_handle == notify_handle) {
		/* Read: return current combined data */
		char buf[244];
		int64_t uptime_s = (esp_timer_get_time() - start_time_us) / 1000000;
		uint32_t heap = esp_get_free_heap_size();

		xSemaphoreTake(data_mutex, portMAX_DELAY);
		int nxp_adc = json_get_int(nxp_data, "adc0", 0);
		int nxp_btn = json_get_int(nxp_data, "btn_sw2", 0);
		xSemaphoreGive(data_mutex);

		snprintf(buf, sizeof(buf),
			 "{\"esp32_heap\":%lu,\"esp32_uptime\":%lld,"
			 "\"nxp_adc\":%d,\"nxp_btn\":%d}",
			 (unsigned long)heap, (long long)uptime_s,
			 nxp_adc, nxp_btn);

		int rc = os_mbuf_append(ctxt->om, buf, strlen(buf));
		return rc == 0 ? 0 : BLE_ATT_ERR_INSUFFICIENT_RES;
	}

	if (ctxt->op == BLE_GATT_ACCESS_OP_WRITE_CHR) {
		/* Write command from hub — log it */
		uint16_t len = OS_MBUF_PKTLEN(ctxt->om);
		char cmd[128];
		if (len >= sizeof(cmd)) {
			len = sizeof(cmd) - 1;
		}
		os_mbuf_copydata(ctxt->om, 0, len, cmd);
		cmd[len] = '\0';
		ESP_LOGI(TAG, "BLE CMD from hub: %s", cmd);
		return 0;
	}

	return 0;
}

static const struct ble_gatt_svc_def gatt_svcs[] = {
	{
		.type = BLE_GATT_SVC_TYPE_PRIMARY,
		.uuid = &svc_uuid.u,
		.characteristics = (struct ble_gatt_chr_def[]) {
			{
				.uuid = &chr_notify_uuid.u,
				.access_cb = gatt_access_cb,
				.val_handle = &notify_handle,
				.flags = BLE_GATT_CHR_F_READ | BLE_GATT_CHR_F_NOTIFY,
			},
			{
				.uuid = &chr_write_uuid.u,
				.access_cb = gatt_access_cb,
				.flags = BLE_GATT_CHR_F_WRITE,
			},
			{ 0 },
		},
	},
	{ 0 },
};

/* ===================================================================
 * BLE GAP Event Handler
 * =================================================================== */

static void ble_advertise(void);

static int ble_gap_event(struct ble_gap_event *event, void *arg)
{
	switch (event->type) {
	case BLE_GAP_EVENT_CONNECT:
		if (event->connect.status == 0) {
			conn_handle = event->connect.conn_handle;
			ble_connected = true;
			ESP_LOGI(TAG, "BLE connected (handle=%d)", conn_handle);
		} else {
			ESP_LOGW(TAG, "BLE connect failed: %d", event->connect.status);
			ble_advertise();
		}
		break;

	case BLE_GAP_EVENT_DISCONNECT:
		ble_connected = false;
		ESP_LOGI(TAG, "BLE disconnected (reason=%d)", event->disconnect.reason);
		ble_advertise();
		break;

	case BLE_GAP_EVENT_SUBSCRIBE:
		ESP_LOGI(TAG, "BLE subscribe: notify=%d indicate=%d",
			 event->subscribe.cur_notify,
			 event->subscribe.cur_indicate);
		break;

	case BLE_GAP_EVENT_MTU:
		ESP_LOGI(TAG, "BLE MTU updated: %d", event->mtu.value);
		break;

	default:
		break;
	}
	return 0;
}

static void ble_advertise(void)
{
	struct ble_gap_adv_params adv_params = {0};
	struct ble_hs_adv_fields fields = {0};
	struct ble_hs_adv_fields rsp_fields = {0};
	int rc;

	/* Advertising data: flags + name (must fit in 31 bytes) */
	fields.flags = BLE_HS_ADV_F_DISC_GEN | BLE_HS_ADV_F_BREDR_UNSUP;
	fields.name = (uint8_t *)"EAB-ESP32C6";
	fields.name_len = strlen("EAB-ESP32C6");
	fields.name_is_complete = 1;

	rc = ble_gap_adv_set_fields(&fields);
	if (rc != 0) {
		ESP_LOGE(TAG, "ble_gap_adv_set_fields failed: %d", rc);
		return;
	}

	/* Scan response: service UUID (too large for ad data) */
	rsp_fields.uuids128 = (ble_uuid128_t[]){ svc_uuid };
	rsp_fields.num_uuids128 = 1;
	rsp_fields.uuids128_is_complete = 1;

	rc = ble_gap_adv_rsp_set_fields(&rsp_fields);
	if (rc != 0) {
		ESP_LOGW(TAG, "ble_gap_adv_rsp_set_fields failed: %d", rc);
	}

	adv_params.conn_mode = BLE_GAP_CONN_MODE_UND;
	adv_params.disc_mode = BLE_GAP_DISC_MODE_GEN;

	rc = ble_gap_adv_start(BLE_OWN_ADDR_PUBLIC, NULL, BLE_HS_FOREVER,
				   &adv_params, ble_gap_event, NULL);
	if (rc != 0) {
		ESP_LOGE(TAG, "Advertising start failed: %d", rc);
	} else {
		ESP_LOGI(TAG, "Advertising started as EAB-ESP32C6");
	}
}

static void ble_on_sync(void)
{
	uint8_t addr_type;
	int rc = ble_hs_id_infer_auto(0, &addr_type);
	if (rc != 0) {
		ESP_LOGE(TAG, "ble_hs_id_infer_auto failed: %d", rc);
		return;
	}
	ESP_LOGI(TAG, "BLE addr type: %d", addr_type);

	ble_advertise();
}

static void ble_on_reset(int reason)
{
	ESP_LOGW(TAG, "BLE host reset: %d", reason);
}

static void nimble_host_task(void *param)
{
	nimble_port_run();
	nimble_port_freertos_deinit();
}

/* ===================================================================
 * UART RX Task — reads JSON from MCXN947
 * =================================================================== */

static void uart_rx_task(void *arg)
{
	uint8_t rx_buf[512];

	/* Configure UART for MCXN947 data link */
	uart_config_t uart_cfg = {
		.baud_rate = DATA_UART_BAUD,
		.data_bits = UART_DATA_8_BITS,
		.parity = UART_PARITY_DISABLE,
		.stop_bits = UART_STOP_BITS_1,
		.flow_ctrl = UART_HW_FLOWCTRL_DISABLE,
		.source_clk = UART_SCLK_DEFAULT,
	};
	uart_driver_install(DATA_UART_NUM, DATA_UART_BUF_SZ, 0, 0, NULL, 0);
	uart_param_config(DATA_UART_NUM, &uart_cfg);
	uart_set_pin(DATA_UART_NUM, DATA_UART_TX_PIN, DATA_UART_RX_PIN,
		     UART_PIN_NO_CHANGE, UART_PIN_NO_CHANGE);

	ESP_LOGI(TAG, "UART RX task started — GPIO%d(RX) GPIO%d(TX) @ %d baud",
		 DATA_UART_RX_PIN, DATA_UART_TX_PIN, DATA_UART_BAUD);

	char line_buf[256];
	int line_pos = 0;

	while (1) {
		int len = uart_read_bytes(DATA_UART_NUM, rx_buf, sizeof(rx_buf),
					  pdMS_TO_TICKS(100));
		if (len <= 0) {
			continue;
		}

		for (int i = 0; i < len; i++) {
			char c = (char)rx_buf[i];
			if (c == '\n' || c == '\r') {
				if (line_pos > 0) {
					line_buf[line_pos] = '\0';

					/* Validate it looks like JSON from NXP */
					if (line_buf[0] == '{' && strstr(line_buf, "\"node\"")) {
						xSemaphoreTake(data_mutex, portMAX_DELAY);
						strncpy(nxp_data, line_buf, sizeof(nxp_data) - 1);
						nxp_data[sizeof(nxp_data) - 1] = '\0';
						xSemaphoreGive(data_mutex);

						ESP_LOGI(TAG, "UART RX ← NXP: %s", line_buf);
					}
					line_pos = 0;
				}
			} else if (line_pos < (int)sizeof(line_buf) - 1) {
				line_buf[line_pos++] = c;
			}
		}
	}
}

/* ===================================================================
 * BLE Notify Task — sends combined data every 1s
 * =================================================================== */

static void ble_notify_task(void *arg)
{
	ESP_LOGI(TAG, "BLE notify task started");

	while (1) {
		vTaskDelay(pdMS_TO_TICKS(1000));

		if (!ble_connected) {
			continue;
		}

		/* Build combined payload */
		char buf[244];
		int64_t uptime_s = (esp_timer_get_time() - start_time_us) / 1000000;
		uint32_t heap = esp_get_free_heap_size();

		xSemaphoreTake(data_mutex, portMAX_DELAY);
		int nxp_adc = json_get_int(nxp_data, "adc0", 0);
		int nxp_btn = json_get_int(nxp_data, "btn_sw2", 0);
		xSemaphoreGive(data_mutex);

		snprintf(buf, sizeof(buf),
			 "{\"esp32_heap\":%lu,\"esp32_uptime\":%lld,"
			 "\"nxp_adc\":%d,\"nxp_btn\":%d}",
			 (unsigned long)heap, (long long)uptime_s,
			 nxp_adc, nxp_btn);

		struct os_mbuf *om = ble_hs_mbuf_from_flat(buf, strlen(buf));
		if (om) {
			int rc = ble_gatts_notify_custom(conn_handle, notify_handle, om);
			if (rc != 0) {
				ESP_LOGW(TAG, "BLE notify failed: %d", rc);
			} else {
				ESP_LOGI(TAG, "BLE TX → hub: %s", buf);
			}
		}
	}
}

/* ===================================================================
 * Main
 * =================================================================== */

void app_main(void)
{
	start_time_us = esp_timer_get_time();

	/* Install USB Serial/JTAG VFS driver for console */
	usb_serial_jtag_driver_config_t usb_serial_cfg = {
		.rx_buffer_size = 1024,
		.tx_buffer_size = 1024,
	};
	ESP_ERROR_CHECK(usb_serial_jtag_driver_install(&usb_serial_cfg));
	usb_serial_jtag_vfs_use_driver();

	printf("\n========================================\n");
	printf("  EAB BLE Gateway v1.0 (ESP32-C6)\n");
	printf("========================================\n\n");

	/* Init NVS (required by NimBLE) */
	esp_err_t ret = nvs_flash_init();
	if (ret == ESP_ERR_NVS_NO_FREE_PAGES || ret == ESP_ERR_NVS_NEW_VERSION_FOUND) {
		nvs_flash_erase();
		ret = nvs_flash_init();
	}
	ESP_ERROR_CHECK(ret);

	/* Init mutex for shared data */
	data_mutex = xSemaphoreCreateMutex();

	/* Init NimBLE */
	ret = nimble_port_init();
	ESP_ERROR_CHECK(ret);

	ble_hs_cfg.sync_cb = ble_on_sync;
	ble_hs_cfg.reset_cb = ble_on_reset;

	/* Register GATT services */
	ble_svc_gap_init();
	ble_svc_gatt_init();

	int rc = ble_gatts_count_cfg(gatt_svcs);
	if (rc != 0) {
		ESP_LOGE(TAG, "ble_gatts_count_cfg failed: %d", rc);
		return;
	}

	rc = ble_gatts_add_svcs(gatt_svcs);
	if (rc != 0) {
		ESP_LOGE(TAG, "ble_gatts_add_svcs failed: %d", rc);
		return;
	}

	ble_svc_gap_device_name_set("EAB-ESP32C6");

	/* Start NimBLE host task */
	nimble_port_freertos_init(nimble_host_task);

	ESP_LOGI(TAG, "NimBLE started — advertising as EAB-ESP32C6");

	/* Start UART RX task (reads from MCXN947) */
	xTaskCreate(uart_rx_task, "uart_rx", 4096, NULL, 5, NULL);

	/* Start BLE notify task */
	xTaskCreate(ble_notify_task, "ble_notify", 4096, NULL, 5, NULL);

	ESP_LOGI(TAG, "Gateway running — UART bridge + BLE peripheral");
}
