/*
 * EAB BLE Hub — nRF5340 DK
 *
 * BLE central + UART aggregator. The hub that combines all sensor data.
 *
 * BLE Central: Scans for "EAB-ESP32C6", connects, subscribes to notifications.
 * UART RX from STM32L4: Arduino header D0 (P1.01 RX), D1 (P1.02 TX), 115200.
 * Aggregation: Parses JSON from both sources, outputs combined DATA lines via RTT.
 *
 * RTT output format (compatible with EAB RTT plotter / uPlot):
 *   DATA: stm32_temp=24.5 nxp_adc=1234 esp32_heap=280000 uptime=42
 */

#include <zephyr/kernel.h>
#include <zephyr/device.h>
#include <zephyr/devicetree.h>
#include <zephyr/drivers/uart.h>
#include <zephyr/logging/log.h>

#include <zephyr/bluetooth/bluetooth.h>
#include <zephyr/bluetooth/conn.h>
#include <zephyr/bluetooth/gatt.h>
#include <zephyr/bluetooth/uuid.h>

#include <string.h>
#include <stdlib.h>
#include <stdio.h>

LOG_MODULE_REGISTER(ble_hub, LOG_LEVEL_INF);

/* ===================================================================
 * BLE UUIDs — must match ESP32-C6 gateway
 * =================================================================== */

/* EAB10001-0000-1000-8000-00805F9B34FB */
static struct bt_uuid_128 svc_uuid = BT_UUID_INIT_128(
	BT_UUID_128_ENCODE(0xEAB10001, 0x0000, 0x1000, 0x8000, 0x00805F9B34FB)
);

/* EAB10002-0000-1000-8000-00805F9B34FB */
static struct bt_uuid_128 chr_notify_uuid = BT_UUID_INIT_128(
	BT_UUID_128_ENCODE(0xEAB10002, 0x0000, 0x1000, 0x8000, 0x00805F9B34FB)
);

/* ===================================================================
 * Shared sensor state
 * =================================================================== */

static struct k_mutex data_mutex;

/* Data from STM32L4 (via UART) */
static int stm32_temp_x10 = 0;  /* temp * 10 for one-decimal precision */
static int stm32_vref = 0;

/* Data from ESP32-C6 (via BLE) */
static int esp32_heap = 0;
static int esp32_uptime = 0;
static int nxp_adc = 0;
static int nxp_btn = 0;

/*
 * Parse a simple integer field from JSON string.
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

/*
 * Parse a simple float-like field as x10 int (e.g., "24.5" -> 245).
 */
static int json_get_fixed1(const char *json, const char *key, int fallback)
{
	char search[64];
	snprintf(search, sizeof(search), "\"%s\":", key);
	const char *p = strstr(json, search);
	if (!p) {
		return fallback;
	}
	p += strlen(search);

	/* Parse integer part */
	int sign = 1;
	if (*p == '-') {
		sign = -1;
		p++;
	}
	int integer = 0;
	while (*p >= '0' && *p <= '9') {
		integer = integer * 10 + (*p - '0');
		p++;
	}
	int frac = 0;
	if (*p == '.') {
		p++;
		if (*p >= '0' && *p <= '9') {
			frac = *p - '0';
		}
	}
	return sign * (integer * 10 + frac);
}

/* ===================================================================
 * UART RX — reads JSON from STM32L4 on USART1 (Arduino D0/D1)
 * =================================================================== */

#define UART_DATA_DEV DT_NODELABEL(uart1)
static const struct device *data_uart = DEVICE_DT_GET(UART_DATA_DEV);

#define UART_BUF_SIZE 256
static char uart_line[UART_BUF_SIZE];
static int uart_pos = 0;

static void uart_irq_handler(const struct device *dev, void *user_data)
{
	ARG_UNUSED(user_data);

	while (uart_irq_update(dev) && uart_irq_is_pending(dev)) {
		if (!uart_irq_rx_ready(dev)) {
			continue;
		}

		uint8_t buf[64];
		int len = uart_fifo_read(dev, buf, sizeof(buf));

		for (int i = 0; i < len; i++) {
			char c = (char)buf[i];

			if (c == '\n' || c == '\r') {
				if (uart_pos > 0) {
					uart_line[uart_pos] = '\0';

					/* Parse STM32 JSON */
					if (uart_line[0] == '{' &&
					    strstr(uart_line, "\"stm32\"")) {
						k_mutex_lock(&data_mutex, K_FOREVER);
						stm32_temp_x10 = json_get_fixed1(
							uart_line, "temp_c", stm32_temp_x10);
						stm32_vref = json_get_int(
							uart_line, "vref_mv", stm32_vref);
						k_mutex_unlock(&data_mutex);

						LOG_INF("UART RX ← STM32: %s", uart_line);
					}
					uart_pos = 0;
				}
			} else if (uart_pos < UART_BUF_SIZE - 1) {
				uart_line[uart_pos++] = c;
			}
		}
	}
}

static int init_data_uart(void)
{
	if (!device_is_ready(data_uart)) {
		LOG_ERR("Data UART (uart1) not ready");
		return -1;
	}

	uart_irq_callback_set(data_uart, uart_irq_handler);
	uart_irq_rx_enable(data_uart);

	LOG_INF("Data UART ready — P1.01(RX) P1.02(TX) @ 115200");
	return 0;
}

/* ===================================================================
 * BLE Central — scans for EAB-ESP32C6, connects, subscribes
 * =================================================================== */

static struct bt_conn *ble_conn;
static struct bt_gatt_subscribe_params sub_params;

static uint8_t ble_notify_cb(struct bt_conn *conn,
			     struct bt_gatt_subscribe_params *params,
			     const void *data, uint16_t length)
{
	if (!data) {
		LOG_INF("BLE notification unsubscribed");
		params->value_handle = 0;
		return BT_GATT_ITER_STOP;
	}

	/* Parse ESP32-C6 gateway JSON */
	char buf[256];
	if (length >= sizeof(buf)) {
		length = sizeof(buf) - 1;
	}
	memcpy(buf, data, length);
	buf[length] = '\0';

	k_mutex_lock(&data_mutex, K_FOREVER);
	esp32_heap = json_get_int(buf, "esp32_heap", esp32_heap);
	esp32_uptime = json_get_int(buf, "esp32_uptime", esp32_uptime);
	nxp_adc = json_get_int(buf, "nxp_adc", nxp_adc);
	nxp_btn = json_get_int(buf, "nxp_btn", nxp_btn);
	k_mutex_unlock(&data_mutex);

	LOG_INF("BLE RX ← ESP32: %s", buf);

	return BT_GATT_ITER_CONTINUE;
}

static struct bt_gatt_discover_params disc_params;
static struct bt_gatt_discover_params sub_disc_params;
static uint16_t notify_value_handle;

static uint8_t discover_cb(struct bt_conn *conn,
			   const struct bt_gatt_attr *attr,
			   struct bt_gatt_discover_params *params)
{
	if (!attr) {
		LOG_INF("GATT discovery complete (type=%u)", params->type);
		return BT_GATT_ITER_STOP;
	}

	LOG_INF("GATT attr: handle=%u type=%u", attr->handle, params->type);

	if (params->type == BT_GATT_DISCOVER_CHARACTERISTIC) {
		struct bt_gatt_chrc *chrc = (struct bt_gatt_chrc *)attr->user_data;
		notify_value_handle = chrc->value_handle;
		LOG_INF("Found notify char, value_handle=%u", notify_value_handle);

		/* Subscribe using auto-discover (separate disc_params struct) */
		sub_params.notify = ble_notify_cb;
		sub_params.value = BT_GATT_CCC_NOTIFY;
		sub_params.value_handle = notify_value_handle;
		sub_params.end_handle = BT_ATT_LAST_ATTRIBUTE_HANDLE;
		sub_params.disc_params = &sub_disc_params;

		int err = bt_gatt_subscribe(conn, &sub_params);
		if (err && err != -EALREADY) {
			LOG_ERR("Subscribe failed: %d", err);
		} else {
			LOG_INF("Subscribe initiated (auto-discover CCC)");
		}
		return BT_GATT_ITER_STOP;
	}

	return BT_GATT_ITER_CONTINUE;
}

static void subscribe_to_notifications(struct bt_conn *conn)
{
	disc_params.uuid = &chr_notify_uuid.uuid;
	disc_params.func = discover_cb;
	disc_params.start_handle = BT_ATT_FIRST_ATTRIBUTE_HANDLE;
	disc_params.end_handle = BT_ATT_LAST_ATTRIBUTE_HANDLE;
	disc_params.type = BT_GATT_DISCOVER_CHARACTERISTIC;

	int err = bt_gatt_discover(conn, &disc_params);
	if (err) {
		LOG_ERR("GATT discover failed: %d", err);
	} else {
		LOG_INF("Starting GATT discovery for notify char...");
	}
}

static void mtu_exchange_cb(struct bt_conn *conn, uint8_t err,
			   struct bt_gatt_exchange_params *params)
{
	if (err) {
		LOG_ERR("MTU exchange failed: %u", err);
	} else {
		LOG_INF("MTU exchanged: %u", bt_gatt_get_mtu(conn));
	}
}

static void connected_cb(struct bt_conn *conn, uint8_t err)
{
	if (err) {
		LOG_ERR("BLE connect failed: %u", err);
		ble_conn = NULL;
		/* Restart scanning */
		bt_le_scan_start(BT_LE_SCAN_ACTIVE, NULL);
		return;
	}

	LOG_INF("BLE connected to ESP32-C6");
	ble_conn = bt_conn_ref(conn);

	/* Exchange MTU first (default 23 is too small for JSON payloads) */
	static struct bt_gatt_exchange_params mtu_params;
	mtu_params.func = mtu_exchange_cb;
	int mtu_err = bt_gatt_exchange_mtu(conn, &mtu_params);
	if (mtu_err) {
		LOG_ERR("MTU exchange failed: %d", mtu_err);
	}

	/* Wait for MTU exchange + service discovery, then subscribe */
	k_msleep(500);
	subscribe_to_notifications(conn);
}

static void disconnected_cb(struct bt_conn *conn, uint8_t reason)
{
	LOG_INF("BLE disconnected (reason=%u)", reason);
	if (ble_conn) {
		bt_conn_unref(ble_conn);
		ble_conn = NULL;
	}
	/* Restart scanning */
	bt_le_scan_start(BT_LE_SCAN_ACTIVE, NULL);
}

BT_CONN_CB_DEFINE(conn_cbs) = {
	.connected = connected_cb,
	.disconnected = disconnected_cb,
};

static int scan_count = 0;

static void scan_recv_cb(const struct bt_le_scan_recv_info *info,
			 struct net_buf_simple *ad)
{
	/* Log every 50th scan result so we know scanning works */
	scan_count++;
	bool found_name = false;
	char name_buf[32] = {0};

	/* Look for the device name "EAB-ESP32C6" in the advertisement */
	/* Save initial state for debug */
	uint16_t ad_len_orig = ad->len;

	while (ad->len > 1) {
		uint8_t len = net_buf_simple_pull_u8(ad);
		if (len == 0 || len > ad->len) {
			break;
		}
		uint8_t type = net_buf_simple_pull_u8(ad);
		len--;  /* type byte consumed */

		if (type == BT_DATA_NAME_COMPLETE || type == BT_DATA_NAME_SHORTENED) {
			/* Copy name for debug */
			int copy_len = (len < sizeof(name_buf) - 1) ? len : sizeof(name_buf) - 1;
			memcpy(name_buf, ad->data, copy_len);
			name_buf[copy_len] = '\0';
			found_name = true;

			if (len == strlen("EAB-ESP32C6") &&
			    memcmp(ad->data, "EAB-ESP32C6", len) == 0) {
				LOG_INF("Found EAB-ESP32C6, connecting...");

				/* Stop scanning and connect */
				bt_le_scan_stop();

				struct bt_conn *conn = NULL;
				int err = bt_conn_le_create(info->addr,
							    BT_CONN_LE_CREATE_CONN,
							    BT_LE_CONN_PARAM_DEFAULT,
							    &conn);
				if (err) {
					LOG_ERR("Create connection failed: %d", err);
					bt_le_scan_start(BT_LE_SCAN_ACTIVE, NULL);
				} else {
					bt_conn_unref(conn);
				}
				return;
			}
		}

		/* Skip remaining field data */
		if (len > ad->len) {
			break;
		}
		net_buf_simple_pull(ad, len);
	}

	/* Debug: log every 50th scan with name (or every 200th without) */
	if (found_name && (scan_count % 50 == 0)) {
		LOG_INF("SCAN[%d]: name=\"%s\" rssi=%d", scan_count, name_buf, info->rssi);
	} else if (scan_count % 200 == 0) {
		LOG_INF("SCAN[%d]: (no name, ad_len=%u) rssi=%d",
			scan_count, ad_len_orig, info->rssi);
	}
}

static struct bt_le_scan_cb scan_cbs = {
	.recv = scan_recv_cb,
};

/* ===================================================================
 * Aggregation Thread — outputs DATA lines via RTT every 1s
 * =================================================================== */

#define AGG_STACK_SIZE 2048
#define AGG_PRIORITY   5

static void aggregation_thread(void *p1, void *p2, void *p3)
{
	ARG_UNUSED(p1); ARG_UNUSED(p2); ARG_UNUSED(p3);

	LOG_INF("[aggregator] Started — DATA output every 1s");

	while (1) {
		k_mutex_lock(&data_mutex, K_FOREVER);
		int t10 = stm32_temp_x10;
		int vref = stm32_vref;
		int heap = esp32_heap;
		int up = esp32_uptime;
		int adc = nxp_adc;
		int btn = nxp_btn;
		k_mutex_unlock(&data_mutex);

		/* Output in EAB RTT plotter format (key=value pairs) */
		LOG_INF("DATA: stm32_temp=%d.%d stm32_vref=%d "
			"nxp_adc=%d nxp_btn=%d "
			"esp32_heap=%d esp32_uptime=%d",
			t10 / 10, abs(t10 % 10),
			vref, adc, btn, heap, up);

		k_msleep(1000);
	}
}

K_THREAD_DEFINE(agg_tid, AGG_STACK_SIZE,
		aggregation_thread, NULL, NULL, NULL,
		AGG_PRIORITY, 0, 0);

/* ===================================================================
 * Main
 * =================================================================== */

int main(void)
{
	LOG_INF("=== EAB BLE Hub (nRF5340 DK) v1.0 ===");

	k_mutex_init(&data_mutex);

	/* Init UART for STM32L4 data link */
	int ret = init_data_uart();
	if (ret < 0) {
		LOG_ERR("UART init failed");
	}

	/* Init BLE */
	ret = bt_enable(NULL);
	if (ret) {
		LOG_ERR("BLE init failed: %d", ret);
		return ret;
	}
	LOG_INF("BLE initialized");

	/* Register scan callback and start scanning */
	bt_le_scan_cb_register(&scan_cbs);

	ret = bt_le_scan_start(BT_LE_SCAN_ACTIVE, NULL);
	if (ret) {
		LOG_ERR("BLE scan start failed: %d", ret);
	} else {
		LOG_INF("Scanning for EAB-ESP32C6...");
	}

	LOG_INF("Hub running — UART(STM32) + BLE(ESP32) → RTT aggregated DATA");

	/* Main thread just sleeps — aggregation thread handles output */
	return 0;
}
