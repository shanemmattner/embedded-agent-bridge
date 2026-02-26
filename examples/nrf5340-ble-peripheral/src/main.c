/*
 * EAB BLE Peripheral — nRF5340 DK
 *
 * Standalone BLE peripheral demonstrating core GATT patterns:
 *   - Notify:  Sensor data pushed to client every 200ms/1000ms (EAB20002)
 *   - Write:   Control characteristic — client sets notify rate (EAB20003)
 *   - Read:    Status characteristic — uptime, counts, mode (EAB20004)
 *
 * All BLE events logged via RTT → readable with:
 *   eabctl rtt start --device NRF5340_XXAA_APP --transport jlink
 *   eabctl rtt tail 50
 *
 * Shell commands (via eabctl send):
 *   ble status     — print connection state, MTU, notify count
 *   ble fast       — 200ms notify interval
 *   ble slow       — 1000ms notify interval
 *   ble off        — stop notifications
 *   ble disconnect — drop current connection
 */

#include <zephyr/kernel.h>
#include <zephyr/logging/log.h>
#include <zephyr/settings/settings.h>
#include <zephyr/shell/shell.h>

#include <zephyr/bluetooth/bluetooth.h>
#include <zephyr/bluetooth/conn.h>
#include <zephyr/bluetooth/gatt.h>
#include <zephyr/bluetooth/uuid.h>
#include <zephyr/bluetooth/hci.h>

#include <string.h>
#include <stdlib.h>
#include <math.h>

LOG_MODULE_REGISTER(ble_peripheral, LOG_LEVEL_INF);

/* ===================================================================
 * UUIDs — 128-bit custom service
 *
 *   Service:  EAB20001-0000-1000-8000-00805F9B34FB
 *   Sensor:   EAB20002-0000-1000-8000-00805F9B34FB  (notify)
 *   Control:  EAB20003-0000-1000-8000-00805F9B34FB  (write)
 *   Status:   EAB20004-0000-1000-8000-00805F9B34FB  (read)
 * =================================================================== */

#define EAB_SVC_UUID_VAL \
	BT_UUID_128_ENCODE(0xEAB20001, 0x0000, 0x1000, 0x8000, 0x00805F9B34FB)
#define EAB_SENSOR_UUID_VAL \
	BT_UUID_128_ENCODE(0xEAB20002, 0x0000, 0x1000, 0x8000, 0x00805F9B34FB)
#define EAB_CONTROL_UUID_VAL \
	BT_UUID_128_ENCODE(0xEAB20003, 0x0000, 0x1000, 0x8000, 0x00805F9B34FB)
#define EAB_STATUS_UUID_VAL \
	BT_UUID_128_ENCODE(0xEAB20004, 0x0000, 0x1000, 0x8000, 0x00805F9B34FB)

static struct bt_uuid_128 eab_svc_uuid     = BT_UUID_INIT_128(EAB_SVC_UUID_VAL);
static struct bt_uuid_128 eab_sensor_uuid  = BT_UUID_INIT_128(EAB_SENSOR_UUID_VAL);
static struct bt_uuid_128 eab_control_uuid = BT_UUID_INIT_128(EAB_CONTROL_UUID_VAL);
static struct bt_uuid_128 eab_status_uuid  = BT_UUID_INIT_128(EAB_STATUS_UUID_VAL);

/* ===================================================================
 * Shared state
 * =================================================================== */

#define NOTIFY_MODE_FAST  0   /* 200ms */
#define NOTIFY_MODE_SLOW  1   /* 1000ms */
#define NOTIFY_MODE_OFF   2

static K_MUTEX_DEFINE(state_mutex);
static struct bt_conn *current_conn;
static uint8_t  notify_mode      = NOTIFY_MODE_SLOW;
static uint32_t notify_count     = 0;
static uint32_t conn_count       = 0;
static bool     notify_enabled   = false;
static uint16_t negotiated_mtu   = 23;  /* default until exchanged */

/* Sensor data packet — what we notify */
struct __packed sensor_payload {
	int32_t  counter;       /* monotonic tick */
	int16_t  temp_x100;     /* temperature * 100 (e.g. 2450 = 24.50°C) */
	uint16_t notify_count;  /* how many notifies sent this connection */
};

/* Status packet — what client can read */
struct __packed status_payload {
	uint32_t uptime_ms;
	uint16_t notify_count;
	uint8_t  conn_count;
	uint8_t  mode;
};

/* ===================================================================
 * Disconnect reason name lookup
 * =================================================================== */

static const char *disconnect_reason_str(uint8_t reason)
{
	switch (reason) {
	case 0x08: return "connection-timeout";
	case 0x13: return "remote-user-terminated";
	case 0x16: return "local-host-terminated";
	case 0x22: return "ll-response-timeout";
	case 0x3A: return "controller-busy";
	case 0x3B: return "unacceptable-conn-params";
	case 0x3E: return "failed-to-establish";
	default:   return "unknown";
	}
}

/* ===================================================================
 * GATT: Read handler — Status characteristic
 * =================================================================== */

static ssize_t read_status(struct bt_conn *conn,
			   const struct bt_gatt_attr *attr,
			   void *buf, uint16_t len, uint16_t offset)
{
	struct status_payload status;

	k_mutex_lock(&state_mutex, K_FOREVER);
	status.uptime_ms    = k_uptime_get_32();
	status.notify_count = (uint16_t)notify_count;
	status.conn_count   = (uint8_t)conn_count;
	status.mode         = notify_mode;
	k_mutex_unlock(&state_mutex);

	LOG_INF("GATT READ status: uptime=%u notify=%u conns=%u mode=%u",
		status.uptime_ms, status.notify_count,
		status.conn_count, status.mode);

	return bt_gatt_attr_read(conn, attr, buf, len, offset,
				 &status, sizeof(status));
}

/* ===================================================================
 * GATT: Write handler — Control characteristic
 *
 * Protocol:
 *   0x01 = fast mode (200ms)
 *   0x02 = slow mode (1000ms)
 *   0x03 = off
 * =================================================================== */

static ssize_t write_control(struct bt_conn *conn,
			     const struct bt_gatt_attr *attr,
			     const void *buf, uint16_t len,
			     uint16_t offset, uint8_t flags)
{
	if (len < 1) {
		LOG_WRN("Control write: empty payload");
		return BT_GATT_ERR(BT_ATT_ERR_INVALID_ATTRIBUTE_LEN);
	}

	uint8_t cmd = ((const uint8_t *)buf)[0];

	k_mutex_lock(&state_mutex, K_FOREVER);
	switch (cmd) {
	case 0x01:
		notify_mode = NOTIFY_MODE_FAST;
		LOG_INF("CONTROL: → FAST mode (200ms)");
		break;
	case 0x02:
		notify_mode = NOTIFY_MODE_SLOW;
		LOG_INF("CONTROL: → SLOW mode (1000ms)");
		break;
	case 0x03:
		notify_mode = NOTIFY_MODE_OFF;
		LOG_INF("CONTROL: → OFF (notifications stopped)");
		break;
	default:
		k_mutex_unlock(&state_mutex);
		LOG_WRN("CONTROL: unknown command 0x%02x (use 0x01=fast 0x02=slow 0x03=off)", cmd);
		return BT_GATT_ERR(BT_ATT_ERR_VALUE_NOT_ALLOWED);
	}
	k_mutex_unlock(&state_mutex);

	return len;
}

/* ===================================================================
 * GATT: CCCD changed — client subscribes/unsubscribes to notifications
 * =================================================================== */

static void cccd_changed(const struct bt_gatt_attr *attr, uint16_t value)
{
	notify_enabled = (value == BT_GATT_CCC_NOTIFY);

	if (notify_enabled) {
		LOG_INF("CCCD: client subscribed to notifications (value=0x%04x)", value);
	} else {
		LOG_INF("CCCD: client unsubscribed (value=0x%04x)", value);
	}
}

/* ===================================================================
 * GATT Service Definition
 * =================================================================== */

BT_GATT_SERVICE_DEFINE(eab_svc,
	BT_GATT_PRIMARY_SERVICE(&eab_svc_uuid),

	/* Sensor characteristic — server pushes data via notify */
	BT_GATT_CHARACTERISTIC(&eab_sensor_uuid.uuid,
		BT_GATT_CHRC_NOTIFY,
		BT_GATT_PERM_NONE,   /* no direct read — only notify */
		NULL, NULL, NULL),
	BT_GATT_CCC(cccd_changed,
		BT_GATT_PERM_READ | BT_GATT_PERM_WRITE),

	/* Control characteristic — client writes mode */
	BT_GATT_CHARACTERISTIC(&eab_control_uuid.uuid,
		BT_GATT_CHRC_WRITE | BT_GATT_CHRC_WRITE_WITHOUT_RESP,
		BT_GATT_PERM_WRITE,
		NULL, write_control, NULL),

	/* Status characteristic — client reads state */
	BT_GATT_CHARACTERISTIC(&eab_status_uuid.uuid,
		BT_GATT_CHRC_READ,
		BT_GATT_PERM_READ,
		read_status, NULL, NULL),
);

/* ===================================================================
 * Advertising data
 * =================================================================== */

static const struct bt_data ad[] = {
	BT_DATA_BYTES(BT_DATA_FLAGS, (BT_LE_AD_GENERAL | BT_LE_AD_NO_BREDR)),
	/* Advertise our custom service UUID so scanners can filter by it */
	BT_DATA_BYTES(BT_DATA_UUID128_ALL, EAB_SVC_UUID_VAL),
};

static const struct bt_data sd[] = {
	BT_DATA(BT_DATA_NAME_COMPLETE, "EAB-Peripheral",
		sizeof("EAB-Peripheral") - 1),
};

static void start_advertising(void)
{
	int err = bt_le_adv_start(BT_LE_ADV_CONN_FAST_2, ad, ARRAY_SIZE(ad),
				  sd, ARRAY_SIZE(sd));
	if (err) {
		LOG_ERR("Advertising start failed: %d", err);
	} else {
		LOG_INF("Advertising as: EAB-Peripheral");
	}
}

/* ===================================================================
 * Connection callbacks
 * =================================================================== */

static void connected_cb(struct bt_conn *conn, uint8_t err)
{
	char addr[BT_ADDR_LE_STR_LEN];

	bt_addr_le_to_str(bt_conn_get_dst(conn), addr, sizeof(addr));

	if (err) {
		LOG_ERR("Connection failed to %s: %u", addr, err);
		return;
	}

	k_mutex_lock(&state_mutex, K_FOREVER);
	current_conn = bt_conn_ref(conn);
	conn_count++;
	notify_count  = 0;
	notify_enabled = false;
	k_mutex_unlock(&state_mutex);

	struct bt_conn_info info;
	bt_conn_get_info(conn, &info);

	LOG_INF("=== CONNECTED ===");
	LOG_INF("  Peer:     %s", addr);
	LOG_INF("  Handle:   %u", bt_conn_index(conn));
	/* info.le.interval deprecated in Zephyr 4.x — use conn_param_updated_cb for live params */
	LOG_INF("  Latency:  %u events", info.le.latency);
	LOG_INF("  Timeout:  %u ms", info.le.timeout * 10);
	LOG_INF("  Security: L%u", bt_conn_get_security(conn));
	LOG_INF("  Total connections: %u", conn_count);

	/* MTU exchange handled automatically by CONFIG_BT_GATT_AUTO_UPDATE_MTU */
	negotiated_mtu = bt_gatt_get_mtu(conn);
	LOG_INF("  MTU:      %u bytes (payload: %u)", negotiated_mtu, negotiated_mtu - 3);
}

static void disconnected_cb(struct bt_conn *conn, uint8_t reason)
{
	char addr[BT_ADDR_LE_STR_LEN];

	bt_addr_le_to_str(bt_conn_get_dst(conn), addr, sizeof(addr));

	LOG_INF("=== DISCONNECTED ===");
	LOG_INF("  Peer:   %s", addr);
	LOG_INF("  Reason: 0x%02x (%s)", reason, disconnect_reason_str(reason));

	k_mutex_lock(&state_mutex, K_FOREVER);
	if (current_conn) {
		bt_conn_unref(current_conn);
		current_conn   = NULL;
	}
	notify_enabled = false;
	negotiated_mtu = 23;
	k_mutex_unlock(&state_mutex);

	start_advertising();
}

static void security_changed_cb(struct bt_conn *conn, bt_security_t level,
				enum bt_security_err err)
{
	if (err) {
		LOG_ERR("Security change failed: level=%u err=%u", level, err);
	} else {
		LOG_INF("Security changed: L%u (encrypted=%s, authenticated=%s)",
			level,
			level >= BT_SECURITY_L2 ? "yes" : "no",
			level >= BT_SECURITY_L3 ? "yes" : "no");
	}
}

BT_CONN_CB_DEFINE(conn_cbs) = {
	.connected        = connected_cb,
	.disconnected     = disconnected_cb,
	.security_changed = security_changed_cb,
};

/* ===================================================================
 * Notify Thread — pushes sensor data to connected client
 * =================================================================== */

#define NOTIFY_STACK_SIZE 1024
#define NOTIFY_PRIORITY   5

static void notify_thread_fn(void *p1, void *p2, void *p3)
{
	ARG_UNUSED(p1); ARG_UNUSED(p2); ARG_UNUSED(p3);

	int32_t tick = 0;

	LOG_INF("[notify] Thread started");

	while (1) {
		k_mutex_lock(&state_mutex, K_FOREVER);
		uint8_t  mode    = notify_mode;
		bool     enabled = notify_enabled;
		struct bt_conn *conn = current_conn ? bt_conn_ref(current_conn) : NULL;
		k_mutex_unlock(&state_mutex);

		if (mode == NOTIFY_MODE_OFF || !enabled || !conn) {
			if (conn) {
				bt_conn_unref(conn);
			}
			k_msleep(200);
			continue;
		}

		/* Build sensor payload */
		struct sensor_payload payload;
		payload.counter    = tick;
		payload.temp_x100  = (int16_t)(2450 + (tick % 100));  /* fake 24.50–25.49 */

		k_mutex_lock(&state_mutex, K_FOREVER);
		notify_count++;
		payload.notify_count = (uint16_t)notify_count;
		k_mutex_unlock(&state_mutex);

		/* Send notification — check return value for backpressure */
		int err = bt_gatt_notify(conn, &eab_svc.attrs[1], &payload, sizeof(payload));
		if (err == 0) {
			LOG_INF("DATA: counter=%d temp=%d.%02d notify_count=%u",
				tick,
				payload.temp_x100 / 100,
				abs(payload.temp_x100 % 100),
				payload.notify_count);
		} else if (err == -ENOMEM || err == -ENOBUFS) {
			/* TX buffer full — back off, don't drop silently */
			LOG_WRN("TX buffer full (err=%d), backoff — reduce notify rate", err);
			k_msleep(100);
		} else if (err != -ENOTCONN) {
			LOG_ERR("bt_gatt_notify failed: %d", err);
		}

		bt_conn_unref(conn);
		tick++;

		k_msleep(mode == NOTIFY_MODE_FAST ? 200 : 1000);
	}
}

K_THREAD_DEFINE(notify_tid, NOTIFY_STACK_SIZE,
		notify_thread_fn, NULL, NULL, NULL,
		NOTIFY_PRIORITY, 0, 0);

/* ===================================================================
 * Shell Commands
 * =================================================================== */

static int cmd_ble_status(const struct shell *sh, size_t argc, char **argv)
{
	ARG_UNUSED(argc); ARG_UNUSED(argv);

	k_mutex_lock(&state_mutex, K_FOREVER);
	bool connected  = (current_conn != NULL);
	uint32_t nc     = notify_count;
	uint32_t cc     = conn_count;
	uint8_t  mode   = notify_mode;
	uint16_t mtu    = negotiated_mtu;
	bool     nenbl  = notify_enabled;
	k_mutex_unlock(&state_mutex);

	static const char *mode_names[] = {"FAST(200ms)", "SLOW(1000ms)", "OFF"};

	shell_print(sh, "=== BLE Status ===");
	shell_print(sh, "  Connected:     %s", connected ? "yes" : "no");
	shell_print(sh, "  MTU:           %u (payload %u bytes)", mtu, mtu - 3);
	shell_print(sh, "  Notify mode:   %s", mode_names[mode]);
	shell_print(sh, "  Notify enabled:%s", nenbl ? "yes" : "no");
	shell_print(sh, "  Notify count:  %u (this session)", nc);
	shell_print(sh, "  Total conns:   %u", cc);
	shell_print(sh, "  Uptime:        %u ms", k_uptime_get_32());

	return 0;
}

static int cmd_ble_fast(const struct shell *sh, size_t argc, char **argv)
{
	ARG_UNUSED(argc); ARG_UNUSED(argv);
	k_mutex_lock(&state_mutex, K_FOREVER);
	notify_mode = NOTIFY_MODE_FAST;
	k_mutex_unlock(&state_mutex);
	shell_print(sh, "Notify mode: FAST (200ms)");
	return 0;
}

static int cmd_ble_slow(const struct shell *sh, size_t argc, char **argv)
{
	ARG_UNUSED(argc); ARG_UNUSED(argv);
	k_mutex_lock(&state_mutex, K_FOREVER);
	notify_mode = NOTIFY_MODE_SLOW;
	k_mutex_unlock(&state_mutex);
	shell_print(sh, "Notify mode: SLOW (1000ms)");
	return 0;
}

static int cmd_ble_off(const struct shell *sh, size_t argc, char **argv)
{
	ARG_UNUSED(argc); ARG_UNUSED(argv);
	k_mutex_lock(&state_mutex, K_FOREVER);
	notify_mode = NOTIFY_MODE_OFF;
	k_mutex_unlock(&state_mutex);
	shell_print(sh, "Notify mode: OFF");
	return 0;
}

static int cmd_ble_disconnect(const struct shell *sh, size_t argc, char **argv)
{
	ARG_UNUSED(argc); ARG_UNUSED(argv);

	k_mutex_lock(&state_mutex, K_FOREVER);
	struct bt_conn *conn = current_conn ? bt_conn_ref(current_conn) : NULL;
	k_mutex_unlock(&state_mutex);

	if (!conn) {
		shell_print(sh, "Not connected");
		return 0;
	}

	int err = bt_conn_disconnect(conn, BT_HCI_ERR_REMOTE_USER_TERM_CONN);
	if (err) {
		shell_print(sh, "Disconnect failed: %d", err);
	} else {
		shell_print(sh, "Disconnecting...");
	}
	bt_conn_unref(conn);
	return 0;
}

SHELL_STATIC_SUBCMD_SET_CREATE(ble_cmds,
	SHELL_CMD(status,     NULL, "Print BLE status",             cmd_ble_status),
	SHELL_CMD(fast,       NULL, "200ms notify interval",        cmd_ble_fast),
	SHELL_CMD(slow,       NULL, "1000ms notify interval",       cmd_ble_slow),
	SHELL_CMD(off,        NULL, "Stop notifications",           cmd_ble_off),
	SHELL_CMD(disconnect, NULL, "Disconnect current connection", cmd_ble_disconnect),
	SHELL_SUBCMD_SET_END
);
SHELL_CMD_REGISTER(ble, &ble_cmds, "BLE peripheral commands", NULL);

/* ===================================================================
 * Main
 * =================================================================== */

int main(void)
{
	LOG_INF("========================================");
	LOG_INF("  EAB BLE Peripheral v1.0");
	LOG_INF("========================================");
	LOG_INF("  Service UUID:  EAB20001-...");
	LOG_INF("  Sensor (notify):  EAB20002");
	LOG_INF("  Control (write):  EAB20003");
	LOG_INF("  Status (read):    EAB20004");
	LOG_INF("----------------------------------------");

	/* Initialize Bluetooth first — bt_gatt_init() must run before
	 * settings_load() to avoid NULL work handler crash (Zephyr 4.x).
	 * settings_load() triggers db_hash_commit() → gatt_sc.work which
	 * must be initialized by bt_gatt_init() first.
	 */
	int err = bt_enable(NULL);
	if (err) {
		LOG_ERR("BLE init failed: %d", err);
		return err;
	}
	LOG_INF("BLE initialized");

	/* Load bonding keys from NVS — MUST be after bt_enable() in Zephyr 4.x */
	err = settings_load();
	if (err) {
		LOG_WRN("settings_load failed: %d (bonds won't persist)", err);
	} else {
		LOG_INF("Settings loaded (bonding keys restored)");
	}

	/* Start advertising */
	start_advertising();

	LOG_INF("Ready — connect with nRF Connect app or any BLE central");
	LOG_INF("Shell: type 'ble status', 'ble fast', 'ble slow', 'ble off'");

	return 0;
}
