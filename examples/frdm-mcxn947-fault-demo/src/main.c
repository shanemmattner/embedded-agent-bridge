/*
 * EAB Fault Demo — FRDM-MCXN947 (Cortex-M33, dual core @ 150MHz)
 *
 * Three worker threads run continuously (sensor, blinker, watchdog).
 * Trigger faults via buttons (primary) or shell commands (advanced):
 *
 * Buttons (FRDM-MCXN947):
 *   SW2 — NULL pointer dereference  (DACCVIOL)
 *   SW3 — Invalid peripheral read   (PRECISERR)
 *
 * Shell commands (via UART console):
 *   fault null       — NULL pointer dereference  (DACCVIOL)
 *   fault divzero    — Integer divide by zero     (DIVBYZERO)
 *   fault unaligned  — Unaligned 32-bit access    (UNALIGNED)
 *   fault undef      — Undefined instruction       (UNDEFINSTR)
 *   fault overflow   — Stack overflow              (STKOF)
 *   fault bus        — Invalid peripheral address  (PRECISERR)
 *
 * Debug with: eabctl fault-analyze --device MCXN947 --probe openocd --chip mcxn947
 */

#include <zephyr/kernel.h>
#include <zephyr/drivers/gpio.h>
#include <zephyr/logging/log.h>
#include <zephyr/shell/shell.h>
#include <math.h>
#include <stdlib.h>
#include <string.h>

LOG_MODULE_REGISTER(fault_demo, LOG_LEVEL_INF);

/* ===================================================================
 * Button-Triggered Faults (FRDM-MCXN947: SW2=sw0, SW3=sw1)
 * =================================================================== */

static const struct gpio_dt_spec btn_sw2 = GPIO_DT_SPEC_GET(DT_ALIAS(sw0), gpios);
static const struct gpio_dt_spec btn_sw3 = GPIO_DT_SPEC_GET(DT_ALIAS(sw1), gpios);

static struct gpio_callback btn_sw2_cb, btn_sw3_cb;

/* Prevent compiler from optimizing away our fault triggers */
static volatile int fault_sink;

static void btn_sw2_handler(const struct device *dev, struct gpio_callback *cb, uint32_t pins)
{
	LOG_INF("SW2 pressed → NULL pointer dereference");
	volatile int *p = NULL;
	fault_sink = *p;
}

static void btn_sw3_handler(const struct device *dev, struct gpio_callback *cb, uint32_t pins)
{
	LOG_INF("SW3 pressed → Invalid peripheral read");
	/* 0x5FFF0000 is unmapped on MCXN947 — guaranteed bus error */
	volatile uint32_t *bad_periph = (volatile uint32_t *)0x5FFF0000;
	fault_sink = *bad_periph;
}

static int init_buttons(void)
{
	const struct gpio_dt_spec *btns[] = {&btn_sw2, &btn_sw3};
	struct gpio_callback *cbs[] = {&btn_sw2_cb, &btn_sw3_cb};
	gpio_callback_handler_t handlers[] = {btn_sw2_handler, btn_sw3_handler};

	for (int i = 0; i < 2; i++) {
		if (!gpio_is_ready_dt(btns[i])) {
			LOG_WRN("Button %d not ready", i);
			continue;
		}
		gpio_pin_configure_dt(btns[i], GPIO_INPUT);
		gpio_pin_interrupt_configure_dt(btns[i], GPIO_INT_EDGE_TO_ACTIVE);
		gpio_init_callback(cbs[i], handlers[i], BIT(btns[i]->pin));
		gpio_add_callback(btns[i]->port, cbs[i]);
	}

	return 0;
}

/* ===================================================================
 * Worker Thread: Sensor (reads fake ADC, logs DATA lines)
 * =================================================================== */

#define SENSOR_STACK_SIZE  1024
#define SENSOR_PRIORITY    5

static void sensor_thread(void *p1, void *p2, void *p3)
{
	ARG_UNUSED(p1); ARG_UNUSED(p2); ARG_UNUSED(p3);
	uint32_t tick = 0;
	float temp_base = 23.0f;

	LOG_INF("[sensor] Started — sampling at 500ms");

	while (1) {
		float phase = 6.2831853f * (float)tick / 60.0f;
		float drift = sinf(phase) * 3.0f;
		float noise = ((float)(rand() % 100) - 50.0f) / 200.0f;
		float temp = temp_base + drift + noise;

		int ti = (int)(temp * 100);
		LOG_INF("DATA: temp=%d.%02d tick=%u",
			ti / 100, abs(ti % 100), tick);

		tick++;
		k_msleep(500);
	}
}

K_THREAD_DEFINE(sensor_tid, SENSOR_STACK_SIZE,
		sensor_thread, NULL, NULL, NULL,
		SENSOR_PRIORITY, 0, 0);

/* ===================================================================
 * Worker Thread: Blinker (toggles LED state, logs heartbeat)
 * =================================================================== */

#define BLINKER_STACK_SIZE 512
#define BLINKER_PRIORITY   7

static void blinker_thread(void *p1, void *p2, void *p3)
{
	ARG_UNUSED(p1); ARG_UNUSED(p2); ARG_UNUSED(p3);
	bool led_on = false;
	uint32_t beat = 0;

	LOG_INF("[blinker] Started — heartbeat at 1s");

	while (1) {
		led_on = !led_on;
		beat++;
		if (beat % 5 == 0) {
			LOG_INF("[blinker] heartbeat #%u led=%s",
				beat, led_on ? "ON" : "OFF");
		}
		k_msleep(1000);
	}
}

K_THREAD_DEFINE(blinker_tid, BLINKER_STACK_SIZE,
		blinker_thread, NULL, NULL, NULL,
		BLINKER_PRIORITY, 0, 0);

/* ===================================================================
 * Worker Thread: Monitor (checks heap, uptime, logs stats)
 * =================================================================== */

#define MONITOR_STACK_SIZE 1024
#define MONITOR_PRIORITY   10

static void monitor_thread(void *p1, void *p2, void *p3)
{
	ARG_UNUSED(p1); ARG_UNUSED(p2); ARG_UNUSED(p3);

	LOG_INF("[monitor] Started — stats every 5s");

	while (1) {
		int64_t uptime_ms = k_uptime_get();
		int secs = (int)(uptime_ms / 1000);
		int mins = secs / 60;
		secs = secs % 60;

		LOG_INF("[monitor] uptime=%dm%ds threads=3", mins, secs);
		k_msleep(5000);
	}
}

K_THREAD_DEFINE(monitor_tid, MONITOR_STACK_SIZE,
		monitor_thread, NULL, NULL, NULL,
		MONITOR_PRIORITY, 0, 0);

/* ===================================================================
 * Fault Injection Shell Commands
 * =================================================================== */

static void overflow_recurse(volatile int depth)
{
	volatile char buf[256];
	memset((void *)buf, (int)depth, sizeof(buf));
	overflow_recurse(depth + 1);
}

static int cmd_fault_null(const struct shell *sh, size_t argc, char **argv)
{
	shell_print(sh, "Triggering NULL pointer dereference...");
	volatile int *p = NULL;
	fault_sink = *p;  /* DACCVIOL — read from address 0x00000000 */
	return 0;
}

static int cmd_fault_divzero(const struct shell *sh, size_t argc, char **argv)
{
	shell_print(sh, "Triggering divide by zero...");
	volatile int a = 42;
	volatile int b = 0;
	fault_sink = a / b;  /* DIVBYZERO */
	return 0;
}

static int cmd_fault_unaligned(const struct shell *sh, size_t argc, char **argv)
{
	shell_print(sh, "Triggering unaligned access...");
	uint8_t buf[8] = {0x01, 0x02, 0x03, 0x04, 0x05, 0x06, 0x07, 0x08};
	volatile uint32_t *p = (volatile uint32_t *)(buf + 1);  /* misaligned */
	fault_sink = *p;  /* UNALIGNED */
	return 0;
}

static int cmd_fault_undef(const struct shell *sh, size_t argc, char **argv)
{
	shell_print(sh, "Triggering undefined instruction...");
	/* UDF #0 — permanently undefined on ARM Thumb-2 */
	__asm volatile (".hword 0xDE00");  /* UNDEFINSTR */
	return 0;
}

static int cmd_fault_overflow(const struct shell *sh, size_t argc, char **argv)
{
	shell_print(sh, "Triggering stack overflow via recursion...");
	overflow_recurse(0);  /* STKOF */
	return 0;
}

static int cmd_fault_bus(const struct shell *sh, size_t argc, char **argv)
{
	shell_print(sh, "Triggering bus fault (invalid peripheral read)...");
	/* Read from a non-existent peripheral address.
	 * 0x5FFF0000 is unmapped on MCXN947 — guaranteed bus error. */
	volatile uint32_t *bad_periph = (volatile uint32_t *)0x5FFF0000;
	fault_sink = *bad_periph;  /* PRECISERR */
	return 0;
}

/* Register "fault" shell command group */
SHELL_STATIC_SUBCMD_SET_CREATE(fault_cmds,
	SHELL_CMD(null,      NULL, "NULL pointer dereference (DACCVIOL)",   cmd_fault_null),
	SHELL_CMD(divzero,   NULL, "Divide by zero (DIVBYZERO)",           cmd_fault_divzero),
	SHELL_CMD(unaligned, NULL, "Unaligned 32-bit access (UNALIGNED)",  cmd_fault_unaligned),
	SHELL_CMD(undef,     NULL, "Undefined instruction (UNDEFINSTR)",   cmd_fault_undef),
	SHELL_CMD(overflow,  NULL, "Stack overflow via recursion (STKOF)", cmd_fault_overflow),
	SHELL_CMD(bus,       NULL, "Invalid peripheral read (PRECISERR)",  cmd_fault_bus),
	SHELL_SUBCMD_SET_END
);

SHELL_CMD_REGISTER(fault, &fault_cmds, "Inject a CPU fault for testing", NULL);

/* ===================================================================
 * Main
 * =================================================================== */

int main(void)
{
	LOG_INF("=== EAB Fault Demo (FRDM-MCXN947) v1.0 ===");
	LOG_INF("3 worker threads running (sensor, blinker, monitor)");
	LOG_INF("Press buttons to trigger faults:");
	LOG_INF("  SW2=NULL  SW3=BusFault");

	init_buttons();

	LOG_INF("Shell available on UART console: fault <type>");
	LOG_INF("Then run: eabctl fault-analyze --device MCXN947 --probe openocd --chip mcxn947");

	return 0;
}
