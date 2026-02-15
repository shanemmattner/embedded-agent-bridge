# ESP32-S3 Debug Full Example

Complete debugging demonstration for ESP32-S3 with all EAB features enabled.

## Features Enabled

### ✅ SystemView Task Tracing
- FreeRTOS task scheduling visualization
- Custom event markers for profiling
- ISR entry/exit tracking
- Task state transitions
- **Export:** Perfetto JSON via `sysviewtrace_proc.py`

### ✅ Heap Allocation Tracking
- Runtime heap trace start/stop
- Leak detection
- Allocation stack traces (4 levels deep)
- **Trigger:** UART command `heap_start` / `heap_stop`

### ✅ Coredump Generation
- ELF format with all task snapshots
- Saved to flash partition (128KB)
- Includes DRAM (.bss, .data, heap)
- **Trigger:** UART commands `fault_null`, `fault_div0`
- **Decode:** `idf.py coredump-info`

### ✅ Stack Protection
- Watchpoint at end of stack
- Overflow detection via pointer validation
- **Trigger:** Automatically on overflow

### ✅ Task Watchdog
- 10-second timeout
- Monitors IDLE task
- **Trigger:** UART command `wdt_test`

## Hardware Required

- ESP32-S3 DevKit (any variant)
- USB cable (for power and console)

## Build and Flash

```bash
# From EAB repo root
cd examples/esp32s3-debug-full

# Build (requires ESP-IDF environment)
idf.py build

# Flash via EAB (recommended)
eabctl flash .

# Or flash with idf.py
idf.py flash monitor
```

## Usage

### 1. Start Monitoring

```bash
# Via EAB
eabctl tail 100

# Or use idf.py monitor
idf.py monitor
```

### 2. Available Commands

Type commands into the serial console:

| Command | Action |
|---------|--------|
| `status` | Print system info (heap, tasks) |
| `heap_start` | Start heap tracing |
| `heap_stop` | Stop heap tracing and dump results |
| `fault_null` | Trigger NULL pointer fault (generates coredump) |
| `fault_div0` | Trigger divide-by-zero fault (generates coredump) |
| `wdt_test` | Trigger watchdog timeout (resets system) |

### 3. Capture SystemView Trace

#### Option A: EAB RTT Capture (if using J-Link)
```bash
eabctl trace start --source rtt -o /tmp/trace.rttbin --device ESP32C6
# ... let it run for 10-15 seconds ...
eabctl trace stop
eabctl trace export -i /tmp/trace.rttbin -o /tmp/trace.json
```

#### Option B: ESP-IDF apptrace (USB-JTAG)
```bash
# Start trace capture (run in separate terminal)
$IDF_PATH/tools/esp_app_trace/logtrace_proc.py /dev/ttyACM0

# Or for SystemView format:
$IDF_PATH/tools/esp_app_trace/sysviewtrace_proc.py /dev/ttyACM0 -o /tmp/trace.svdat

# Convert to Perfetto JSON
$IDF_PATH/tools/esp_app_trace/sysviewtrace_proc.py /tmp/trace.svdat -p -o /tmp/trace.json
```

### 4. Analyze Coredump

After triggering a fault, the coredump is saved to flash:

```bash
# Read and analyze coredump
idf.py coredump-info

# Launch GDB with coredump
idf.py coredump-debug
```

### 5. Visualize in Perfetto

Open https://ui.perfetto.dev and load `/tmp/trace.json` to see:
- Task scheduling timeline
- CPU utilization per task
- Custom event markers (compute, I/O, alloc)
- ISR activity

## Expected Output

### Boot Messages
```
I (XXX) debug_full: ========================================
I (XXX) debug_full: ESP32-S3 Debug Full Example
I (XXX) debug_full: ========================================
I (XXX) debug_full: Features enabled:
I (XXX) debug_full:   - SystemView task tracing
I (XXX) debug_full:   - Heap allocation tracking
I (XXX) debug_full:   - Coredump generation
I (XXX) debug_full:   - Task watchdog
I (XXX) debug_full: ========================================
I (XXX) debug_full: Command task started
I (XXX) debug_full: Available commands:
I (XXX) debug_full:   heap_start  - Start heap tracing
I (XXX) debug_full:   heap_stop   - Stop heap tracing and dump
I (XXX) debug_full:   fault_null  - Trigger NULL pointer fault
I (XXX) debug_full:   fault_div0  - Trigger divide by zero
I (XXX) debug_full:   wdt_test    - Trigger watchdog timeout
I (XXX) debug_full:   status      - Print system status
I (XXX) debug_full: Compute task started
I (XXX) debug_full: I/O task started
I (XXX) debug_full: Alloc task started
I (XXX) debug_full: All tasks created. Ready for debugging!
```

### Heap Trace Example
```
> heap_start
I (XXX) debug_full: Heap tracing started

> heap_stop
I (XXX) debug_full: Heap tracing stopped
128 allocations trace (128 entry buffer)
...allocation details...
```

### Coredump Example
```
> fault_null
E (XXX) debug_full: Triggering NULL pointer fault...
Guru Meditation Error: Core 0 panic'ed (Load access fault)
...coredump saved to flash...
```

## Tasks in Firmware

| Task | Priority | Stack | Purpose |
|------|----------|-------|---------|
| `cmd` | 5 (highest) | 4096 | Command processor |
| `compute` | 3 | 3072 | CPU-intensive work |
| `io` | 2 | 2048 | I/O simulation |
| `alloc` | 1 (lowest) | 3072 | Memory allocation patterns |
| IDLE | 0 | default | FreeRTOS idle task |

## Configuration Details

All features are enabled in `sdkconfig.defaults`. Key settings:

```ini
# SystemView
CONFIG_ESP_TRACE_ENABLE=y
CONFIG_SEGGER_SYSVIEW_EVT_TASK_START_EXEC_ENABLE=y
...

# Heap Tracing
CONFIG_HEAP_TRACING=y
CONFIG_HEAP_TRACING_STACK_DEPTH=4

# Coredump
CONFIG_ESP_COREDUMP_ENABLE=y
CONFIG_ESP_COREDUMP_CAPTURE_DRAM=y

# Watchdog
CONFIG_ESP_TASK_WDT=y
CONFIG_ESP_TASK_WDT_TIMEOUT_S=10
```

## Troubleshooting

### Trace Capture Issues
- **No trace output:** Ensure SystemView is started before launching apptrace
- **Buffer overflow:** Increase `CONFIG_ESP_APPTRACE_BUF_SIZE` in menuconfig

### Coredump Issues
- **Coredump not found:** Check partition table includes `coredump` partition
- **Decode failed:** Ensure you're using the matching ELF file from `build/`

### Heap Tracing Issues
- **Buffer full:** Increase `NUM_HEAP_RECORDS` in `debug_full_main.c`
- **Already active:** Run `heap_stop` before `heap_start`

## Next Steps

1. **Test with EAB regression framework:**
   ```bash
   eabctl regression --test tests/hw/esp32s3_debug_full.yaml
   ```

2. **Create test YAML** (see `tests/hw/esp32s3_debug_full.yaml`)

3. **Verify Perfetto export** pipeline works end-to-end

## References

- [ESP-IDF SystemView Guide](https://docs.espressif.com/projects/esp-idf/en/latest/esp32/api-guides/app_trace.html)
- [ESP-IDF Coredump Guide](https://docs.espressif.com/projects/esp-idf/en/latest/esp32/api-guides/core_dump.html)
- [Perfetto UI](https://ui.perfetto.dev)
