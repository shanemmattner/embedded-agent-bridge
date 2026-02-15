# Configuration Patterns Extracted from Official Examples

## ESP-IDF SystemView Tracing

### Source
`esp-idf/examples/system/sysview_tracing/sdkconfig.defaults`

### Full Configuration
```ini
# FreeRTOS tick rate (1ms for better resolution)
CONFIG_FREERTOS_HZ=1000

# Enable ESP Trace framework
CONFIG_ESP_TRACE_ENABLE=y
CONFIG_ESP_TRACE_LIB_EXTERNAL=y
CONFIG_ESP_TRACE_TRANSPORT_APPTRACE=y
CONFIG_ESP_TRACE_TS_SOURCE_ESP_TIMER=y

# SystemView event configuration (enable all events)
CONFIG_SEGGER_SYSVIEW_EVT_OVERFLOW_ENABLE=y
CONFIG_SEGGER_SYSVIEW_EVT_ISR_ENTER_ENABLE=y
CONFIG_SEGGER_SYSVIEW_EVT_ISR_EXIT_ENABLE=y
CONFIG_SEGGER_SYSVIEW_EVT_ISR_TO_SCHED_ENABLE=y
CONFIG_SEGGER_SYSVIEW_EVT_TASK_START_EXEC_ENABLE=y
CONFIG_SEGGER_SYSVIEW_EVT_TASK_STOP_EXEC_ENABLE=y
CONFIG_SEGGER_SYSVIEW_EVT_TASK_START_READY_ENABLE=y
CONFIG_SEGGER_SYSVIEW_EVT_TASK_STOP_READY_ENABLE=y
CONFIG_SEGGER_SYSVIEW_EVT_TASK_CREATE_ENABLE=y
CONFIG_SEGGER_SYSVIEW_EVT_TASK_TERMINATE_ENABLE=y
CONFIG_SEGGER_SYSVIEW_EVT_IDLE_ENABLE=y
CONFIG_SEGGER_SYSVIEW_EVT_TIMER_ENTER_ENABLE=y
CONFIG_SEGGER_SYSVIEW_EVT_TIMER_EXIT_ENABLE=y
```

### Key Code Patterns

**Include headers:**
```c
#include "esp_trace.h"
#include "freertos/FreeRTOS.h"
#include "freertos/task.h"
```

**Custom event tracking:**
```c
// Define event IDs
#define SYSVIEW_EXAMPLE_SEND_EVENT_ID  0
#define SYSVIEW_EXAMPLE_WAIT_EVENT_ID  1

// Mark event start/stop
SEGGER_SYSVIEW_OnUserStart(event_id);
// ... code being measured ...
SEGGER_SYSVIEW_OnUserStop(event_id);
```

**Module registration (optional):**
```c
static SEGGER_SYSVIEW_MODULE s_module = {
    .sModule = "my_module",
    .NumEvents = NUM_EVENTS,
    .pfSendModuleDesc = module_desc_func,
};
```

## ESP-IDF Combined Debug Config (SystemView + Heap + Coredump)

### For ESP32-C6 / ESP32-S3 Debug-Full Example

```ini
# ============= FreeRTOS =============
CONFIG_FREERTOS_HZ=1000

# ============= SystemView Tracing =============
CONFIG_ESP_TRACE_ENABLE=y
CONFIG_ESP_TRACE_LIB_EXTERNAL=y
CONFIG_ESP_TRACE_TRANSPORT_APPTRACE=y
CONFIG_ESP_TRACE_TS_SOURCE_ESP_TIMER=y
CONFIG_SEGGER_SYSVIEW_EVT_OVERFLOW_ENABLE=y
CONFIG_SEGGER_SYSVIEW_EVT_ISR_ENTER_ENABLE=y
CONFIG_SEGGER_SYSVIEW_EVT_ISR_EXIT_ENABLE=y
CONFIG_SEGGER_SYSVIEW_EVT_ISR_TO_SCHED_ENABLE=y
CONFIG_SEGGER_SYSVIEW_EVT_TASK_START_EXEC_ENABLE=y
CONFIG_SEGGER_SYSVIEW_EVT_TASK_STOP_EXEC_ENABLE=y
CONFIG_SEGGER_SYSVIEW_EVT_TASK_START_READY_ENABLE=y
CONFIG_SEGGER_SYSVIEW_EVT_TASK_STOP_READY_ENABLE=y
CONFIG_SEGGER_SYSVIEW_EVT_TASK_CREATE_ENABLE=y
CONFIG_SEGGER_SYSVIEW_EVT_TASK_TERMINATE_ENABLE=y
CONFIG_SEGGER_SYSVIEW_EVT_IDLE_ENABLE=y
CONFIG_SEGGER_SYSVIEW_EVT_TIMER_ENTER_ENABLE=y
CONFIG_SEGGER_SYSVIEW_EVT_TIMER_EXIT_ENABLE=y

# ============= Heap Tracing =============
# (Configuration extracted from esp-idf-heap-tracking.md research)
CONFIG_HEAP_TRACING=y
CONFIG_HEAP_TRACING_DEST_TRAX=y
CONFIG_HEAP_TRACING_STACK_DEPTH=4

# ============= Coredump =============
CONFIG_ESP_COREDUMP_ENABLE=y
CONFIG_ESP_COREDUMP_DATA_FORMAT_ELF=y
CONFIG_ESP_COREDUMP_CHECKSUM_CRC32=y
CONFIG_ESP_COREDUMP_CAPTURE_DRAM=y
CONFIG_ESP_COREDUMP_MAX_TASKS_NUM=16

# ============= Stack Protection =============
CONFIG_FREERTOS_WATCHPOINT_END_OF_STACK=y
CONFIG_FREERTOS_CHECK_STACKOVERFLOW_PTRVAL=y

# ============= Task Watchdog =============
CONFIG_ESP_TASK_WDT=y
CONFIG_ESP_TASK_WDT_PANIC=y
CONFIG_ESP_TASK_WDT_TIMEOUT_S=10
```

## Zephyr CTF Tracing

### Source
`zephyr/samples/subsys/tracing/prj.conf`

### Minimal Configuration
```ini
# Thread names for tracing
CONFIG_THREAD_NAME=y
CONFIG_MP_MAX_NUM_CPUS=1

# Debugging
CONFIG_DEBUG_OPTIMIZATIONS=n
CONFIG_DEBUG_THREAD_INFO=y
```

### Full CTF Tracing (from prj_native_ctf.conf and docs)
```ini
# Thread names
CONFIG_THREAD_NAME=y
CONFIG_MP_MAX_NUM_CPUS=1

# Debugging
CONFIG_DEBUG_OPTIMIZATIONS=n
CONFIG_DEBUG_THREAD_INFO=y

# Tracing subsystem
CONFIG_TRACING=y
CONFIG_TRACING_CTF=y
CONFIG_TRACING_BACKEND_RTT=y  # or CONFIG_TRACING_BACKEND_UART=y

# CTF format options
CONFIG_TRACING_CTF_TIMESTAMP=y

# Thread monitoring (for better trace context)
CONFIG_THREAD_MONITOR=y
CONFIG_THREAD_RUNTIME_STATS=y
CONFIG_THREAD_STACK_INFO=y
```

## Zephyr Combined Debug Config (CTF + Coredump + Shell)

### For nRF5340 / MCXN947 / STM32L4 Debug-Full Example

```ini
# ============= Thread Monitoring =============
CONFIG_THREAD_NAME=y
CONFIG_THREAD_MONITOR=y
CONFIG_THREAD_RUNTIME_STATS=y
CONFIG_THREAD_STACK_INFO=y
CONFIG_MP_MAX_NUM_CPUS=1

# ============= Debugging =============
CONFIG_DEBUG_OPTIMIZATIONS=n
CONFIG_DEBUG_THREAD_INFO=y

# ============= CTF Tracing =============
CONFIG_TRACING=y
CONFIG_TRACING_CTF=y
CONFIG_TRACING_BACKEND_RTT=y
CONFIG_TRACING_CTF_TIMESTAMP=y

# ============= Coredump =============
CONFIG_DEBUG_COREDUMP=y
CONFIG_DEBUG_COREDUMP_BACKEND_LOGGING=y

# ============= Shell (Runtime Debug) =============
CONFIG_SHELL=y
CONFIG_SHELL_BACKEND_RTT=y
CONFIG_KERNEL_SHELL=y
CONFIG_SHELL_CMDS=y
CONFIG_SHELL_CMDS_RESIZE=y

# ============= Stack Protection =============
CONFIG_MPU_STACK_GUARD=y  # ARM Cortex-M MPU
CONFIG_STACK_SENTINEL=y
CONFIG_THREAD_STACK_INFO=y

# ============= Assertions =============
CONFIG_ASSERT=y
CONFIG_ASSERT_LEVEL=2
```

### Zephyr Shell Commands Available

When `CONFIG_KERNEL_SHELL=y` is enabled, these commands are available:

```bash
kernel threads    # List all threads with state, priority, stack usage
kernel stacks     # Show stack usage for all threads
kernel uptime     # System uptime in milliseconds
kernel cycles     # CPU cycles since boot
kernel version    # Zephyr version info
```

Custom commands can be added (see shell sample for examples).

## Tool Locations

### ESP-IDF
- **SystemView decoder:** `$IDF_PATH/tools/esp_app_trace/sysviewtrace_proc.py`
- **Coredump decoder:** `idf.py coredump-info` or `espcoredump.py`
- **Heap trace analysis:** `esp_app_trace` tools

### Zephyr
- **CTF decoder:** `babeltrace` (install via package manager)
  ```bash
  # Ubuntu/Debian
  sudo apt-get install babeltrace

  # macOS
  brew install babeltrace
  ```
- **Perfetto import:** CTF files can be imported directly to Perfetto UI
- **Percepio Tracealyzer:** Commercial tool (has free tier) for TraceRecorder format

## Partition Table (ESP-IDF)

### Coredump Partition

Add to `partitions.csv`:
```csv
# Name,   Type, SubType, Offset,  Size
nvs,      data, nvs,     0x9000,  0x6000
phy_init, data, phy,     0xf000,  0x1000
factory,  app,  factory, 0x10000, 2M
coredump, data, coredump,,        128K
```

**Size calculation:**
- Overhead: 20 bytes
- Per task: 12 bytes + TCB size + stack size
- Recommended: 128K for 16 tasks with 8KB stacks

## Next Steps

Use these configurations to create:
1. `examples/esp32c6-debug-full/sdkconfig.defaults`
2. `examples/esp32s3-debug-full/sdkconfig.defaults`
3. `examples/nrf5340-debug-full/prj.conf`
4. `examples/mcxn947-debug-full/prj.conf`
5. `examples/stm32l4-debug-full/prj.conf`

Copy the official example code from:
- ESP-IDF: `esp-idf/examples/system/sysview_tracing/main/sysview_tracing.c`
- Zephyr: `zephyr/samples/subsys/tracing/src/main.c`

Adapt to include all debug features (tracing, coredump triggers, shell commands).
