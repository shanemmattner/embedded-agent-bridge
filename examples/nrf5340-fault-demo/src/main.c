/*
 * EAB Fault Demo — Multi-threaded firmware with injectable faults
 *
 * Three worker threads run continuously (sensor, blinker, watchdog).
 * Shell commands let you trigger specific Cortex-M33 faults on demand
 * so you can diagnose them with: eabctl fault-analyze
 *
 * Shell commands (via RTT):
 *   fault null       — NULL pointer dereference  (DACCVIOL)
 *   fault divzero    — Integer divide by zero     (DIVBYZERO)
 *   fault unaligned  — Unaligned 32-bit access    (UNALIGNED)
 *   fault undef      — Undefined instruction       (UNDEFINSTR)
 *   fault overflow   — Stack overflow              (STKOF)
 *   fault bus        — Invalid peripheral address  (PRECISERR)
 */

#include <zephyr/kernel.h>
#include <zephyr/logging/log.h>
#include <zephyr/shell/shell.h>
#include <math.h>
#include <stdlib.h>
#include <string.h>

LOG_MODULE_REGISTER(fault_demo, LOG_LEVEL_INF);

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

/* Prevent compiler from optimizing away our fault triggers */
static volatile int fault_sink;

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

static void overflow_recurse(volatile int depth)
{
	volatile char buf[256];  /* eat stack quickly */
	memset((void *)buf, (int)depth, sizeof(buf));
	overflow_recurse(depth + 1);
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
	/* Read from a non-existent peripheral address in the peripheral range.
	 * 0x50FF0000 is unmapped on nRF5340 — guaranteed bus error. */
	volatile uint32_t *bad_periph = (volatile uint32_t *)0x50FF0000;
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
	LOG_INF("=== EAB Fault Demo v1.0 ===");
	LOG_INF("3 worker threads running (sensor, blinker, monitor)");
	LOG_INF("Type 'fault <type>' in shell to inject a fault");
	LOG_INF("Then run: eabctl fault-analyze --device NRF5340_XXAA_APP");
	LOG_INF("Fault types: null, divzero, unaligned, undef, overflow, bus");

	/* Main thread has nothing else to do — workers run independently */
	return 0;
}
