/*
 * nRF5340 Debug Full Example
 *
 * Demonstrates all EAB debugging features on Zephyr:
 * - CTF task tracing via RTT
 * - Runtime shell commands (kernel threads, stacks, uptime)
 * - Coredump generation
 * - Stack overflow detection (MPU)
 * - Thread monitoring
 *
 * Based on Zephyr tracing and shell samples.
 * SPDX-License-Identifier: Apache-2.0
 */

#include <zephyr/kernel.h>
#include <zephyr/sys/printk.h>
#include <zephyr/logging/log.h>
#include <zephyr/shell/shell.h>
#include <zephyr/tracing/tracing.h>
#include <zephyr/random/random.h>
#include <string.h>

LOG_MODULE_REGISTER(debug_full, LOG_LEVEL_INF);

/* Thread stack sizes */
#define STACKSIZE_COMPUTE   2048
#define STACKSIZE_IO        1024
#define STACKSIZE_ALLOC     2048

/* Thread priorities */
#define PRIORITY_COMPUTE    7   /* Higher number = lower priority in Zephyr */
#define PRIORITY_IO         8
#define PRIORITY_ALLOC      9

/* Shared counter for tracing events */
static uint32_t event_counter = 0;

/* Compute-intensive thread */
void compute_thread(void *arg1, void *arg2, void *arg3)
{
	ARG_UNUSED(arg1);
	ARG_UNUSED(arg2);
	ARG_UNUSED(arg3);

	LOG_INF("Compute thread started");
	uint32_t count = 0;

	while (1) {
		/* Simulate computation */
		volatile uint32_t sum = 0;
		for (int i = 0; i < 10000; i++) {
			sum += i * i;
		}

		/* Emit trace event */
		sys_trace_named_event("compute_work", event_counter++, sum);

		if (++count % 100 == 0) {
			LOG_INF("Compute: %u iterations", count);
		}

		k_msleep(50);
	}
}

/* I/O simulation thread */
void io_thread(void *arg1, void *arg2, void *arg3)
{
	ARG_UNUSED(arg1);
	ARG_UNUSED(arg2);
	ARG_UNUSED(arg3);

	LOG_INF("I/O thread started");
	uint32_t count = 0;

	while (1) {
		/* Simulate I/O operation */
		k_msleep(10);

		/* Emit trace event */
		sys_trace_named_event("io_operation", event_counter++, 0);

		if (++count % 50 == 0) {
			LOG_INF("I/O: %u operations", count);
		}

		k_msleep(100);
	}
}

/* Memory allocation test thread */
void alloc_thread(void *arg1, void *arg2, void *arg3)
{
	ARG_UNUSED(arg1);
	ARG_UNUSED(arg2);
	ARG_UNUSED(arg3);

	LOG_INF("Alloc thread started");
	void *ptrs[5] = {NULL};
	int idx = 0;

	while (1) {
		/* Free old allocation */
		if (ptrs[idx] != NULL) {
			k_free(ptrs[idx]);
			ptrs[idx] = NULL;
		}

		/* Allocate new buffer */
		size_t size = 128 + (sys_rand32_get() % 512);
		ptrs[idx] = k_malloc(size);
		if (ptrs[idx]) {
			memset(ptrs[idx], 0xAA, size);
		}

		/* Emit trace event */
		sys_trace_named_event("alloc_event", event_counter++, size);

		idx = (idx + 1) % 5;
		k_msleep(200);
	}
}

/* Define thread stacks */
K_THREAD_STACK_DEFINE(compute_stack, STACKSIZE_COMPUTE);
K_THREAD_STACK_DEFINE(io_stack, STACKSIZE_IO);
K_THREAD_STACK_DEFINE(alloc_stack, STACKSIZE_ALLOC);

/* Define thread structures */
static struct k_thread compute_thread_data;
static struct k_thread io_thread_data;
static struct k_thread alloc_thread_data;

/* Shell command: trigger null pointer fault */
static int cmd_fault_null(const struct shell *sh, size_t argc, char **argv)
{
	ARG_UNUSED(argc);
	ARG_UNUSED(argv);

	shell_print(sh, "Triggering NULL pointer fault...");
	shell_print(sh, "Coredump will be generated");
	k_msleep(100);

	volatile int *p = NULL;
	*p = 42;  /* This will fault */

	return 0;
}

/* Shell command: trigger divide by zero */
static int cmd_fault_div0(const struct shell *sh, size_t argc, char **argv)
{
	ARG_UNUSED(argc);
	ARG_UNUSED(argv);

	shell_print(sh, "Triggering divide by zero...");
	shell_print(sh, "Coredump will be generated");
	k_msleep(100);

	volatile int a = 10;
	volatile int b = 0;
	volatile int c = a / b;  /* This will fault */

	shell_print(sh, "Result: %d", c);  /* Never reached */
	return 0;
}

/* Recursive function to blow the stack */
static void overflow_recursive(void) {
	volatile char buffer[1024];
	memset((void *)buffer, 0xFF, sizeof(buffer));
	overflow_recursive();
}

/* Shell command: trigger stack overflow */
static int cmd_fault_stack(const struct shell *sh, size_t argc, char **argv)
{
	ARG_UNUSED(argc);
	ARG_UNUSED(argv);

	shell_print(sh, "Triggering stack overflow...");
	shell_print(sh, "MPU will detect overflow");
	k_msleep(100);

	overflow_recursive();
	return 0;
}

/* Shell command: print system status */
static int cmd_status(const struct shell *sh, size_t argc, char **argv)
{
	ARG_UNUSED(argc);
	ARG_UNUSED(argv);

	shell_print(sh, "=== System Status ===");
	shell_print(sh, "Uptime: %llu ms", k_uptime_get());
	shell_print(sh, "Cycle count: %llu", k_cycle_get_64());
	shell_print(sh, "Event counter: %u", event_counter);

	return 0;
}

/* Register custom shell commands */
SHELL_STATIC_SUBCMD_SET_CREATE(sub_fault,
	SHELL_CMD(null, NULL, "Trigger NULL pointer fault", cmd_fault_null),
	SHELL_CMD(div0, NULL, "Trigger divide by zero", cmd_fault_div0),
	SHELL_CMD(stack, NULL, "Trigger stack overflow", cmd_fault_stack),
	SHELL_SUBCMD_SET_END
);

SHELL_CMD_REGISTER(fault, &sub_fault, "Fault injection commands", NULL);
SHELL_CMD_REGISTER(status, NULL, "Print system status", cmd_status);

/* Main function */
int main(void)
{
	LOG_INF("========================================");
	LOG_INF("nRF5340 Debug Full Example");
	LOG_INF("========================================");
	LOG_INF("Features enabled:");
#if defined(CONFIG_TRACING)
	LOG_INF("  - CTF task tracing via RTT");
#endif
#if defined(CONFIG_SHELL)
	LOG_INF("  - Shell commands (type 'help')");
#endif
#if defined(CONFIG_DEBUG_COREDUMP)
	LOG_INF("  - Coredump generation");
#endif
#if defined(CONFIG_MPU_STACK_GUARD)
	LOG_INF("  - MPU stack guard");
#endif
	LOG_INF("========================================");

	/* Create threads */
	k_thread_create(&compute_thread_data, compute_stack, STACKSIZE_COMPUTE,
			compute_thread, NULL, NULL, NULL,
			PRIORITY_COMPUTE, 0, K_NO_WAIT);
	k_thread_name_set(&compute_thread_data, "compute");

	k_thread_create(&io_thread_data, io_stack, STACKSIZE_IO,
			io_thread, NULL, NULL, NULL,
			PRIORITY_IO, 0, K_NO_WAIT);
	k_thread_name_set(&io_thread_data, "io");

	k_thread_create(&alloc_thread_data, alloc_stack, STACKSIZE_ALLOC,
			alloc_thread, NULL, NULL, NULL,
			PRIORITY_ALLOC, 0, K_NO_WAIT);
	k_thread_name_set(&alloc_thread_data, "alloc");

	LOG_INF("All threads created. Ready for debugging!");
	LOG_INF("");
	LOG_INF("Shell commands:");
	LOG_INF("  kernel threads  - List all threads");
	LOG_INF("  kernel stacks   - Show stack usage");
	LOG_INF("  kernel uptime   - System uptime");
	LOG_INF("  status          - System status");
	LOG_INF("  fault null      - Trigger NULL fault");
	LOG_INF("  fault div0      - Trigger div0 fault");
	LOG_INF("  fault stack     - Trigger stack overflow");
	LOG_INF("");

	return 0;
}
