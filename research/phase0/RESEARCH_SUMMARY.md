# Phase 0 Research Summary

## Successfully Scraped Documentation

### ESP-IDF

#### Coredump (esp-idf-coredump.md - 19K) ✅
**Key Findings:**
- Configuration options:
  - `CONFIG_ESP_COREDUMP_TO_FLASH_OR_UART` - Enable and select destination
  - `CONFIG_ESP_COREDUMP_MAX_TASKS_NUM` - Number of task snapshots
  - `CONFIG_ESP_COREDUMP_CAPTURE_DRAM` - Include .bss, .data, heap (larger file)
  - `CONFIG_ESP_COREDUMP_STACK_SIZE` - Stack size for coredump routines (1300+ bytes)

- Partition requirements:
  ```
  coredump, data, coredump,, 64K
  ```
  - Size calculation: `20 + max_tasks * (12 + TCB_size + max_stack_size)` bytes

- Analysis tools:
  - `idf.py coredump-info` - Analyze core dump
  - `idf.py coredump-debug` - GDB debugging with core dump
  - `espcoredump.py` - Standalone decoder

- Format: ELF with SHA256 checksum

#### Apptrace (esp-idf-apptrace.md - 17K) ✅
**Key Findings:**
- SystemView integration via app_trace
- Host tools location: `$IDF_PATH/tools/esp_app_trace/`
- Key tool: `sysviewtrace_proc.py` - Converts SystemView trace to formats
- Configuration for apptrace + SystemView
- Can output to JTAG or UART

#### Testing Framework (esp-idf-testing.md - 10K) ✅
**Key Findings:**
- pytest-embedded framework (see pytest-embedded.md)
- Test app structure under `tools/test_apps/`
- Hardware testing patterns

#### Heap Tracking (esp-idf-heap-tracking.md - 3.7K) ⚠️
- Some content, but limited

### Zephyr

#### Coredump (zephyr-coredump.md - 18K) ✅
**Key Findings:**
- Configuration options:
  - `CONFIG_DEBUG_COREDUMP=y`
  - `CONFIG_DEBUG_COREDUMP_BACKEND_LOGGING=y` - Output via logging subsystem
  - `CONFIG_DEBUG_COREDUMP_BACKEND_FLASH_PARTITION=y` - Store in flash
  - `CONFIG_DEBUG_COREDUMP_BACKEND_INTEL_ADSP_MEM_WINDOW=y` - Intel DSP specific

- Multiple backends supported:
  - Logging (print to console)
  - Flash partition
  - Memory window (DSP)

- Includes register state, stack dumps, and memory regions

#### Testing Framework (zephyr-testing.md - 1.6K) ⚠️
- Some content about Twister
- Need more details

#### Shell (zephyr-shell.md - 5.1K) ✅
**Key Findings:**
- Shell subsystem for runtime commands
- Backends: UART, RTT, USB
- Kernel shell module provides:
  - `kernel threads` - List all threads
  - `kernel stacks` - Show stack usage
  - `kernel uptime` - System uptime
  - Runtime debugging commands

### Third-Party Tools

#### pytest-embedded (pytest-embedded.md - 26K) ✅
**Excellent resource!**
- ESP-IDF hardware testing framework
- Fixture patterns for serial, JTAG connections
- Integration with pytest
- Hardware-in-loop test setup
- CI/CD patterns

#### Renode (renode.md - 29K) ✅
**Comprehensive emulation platform**
- Supports: ESP32, nRF52, STM32, and many others
- Platform configurations available
- Can run tests without hardware
- Integration with CI systems

#### Tonbandgerät (tonbandgeraet.md - 1.1K) ⚠️
- Rust CLI for RTOS tracing
- Limited content captured

#### RTEdbg (rtedbg.md - 1.1K) ⚠️
- Binary logging tool
- Limited content captured

## Failed Scrapes

### Need to Re-scrape with Different Approach

1. **ESP-IDF SystemView Example** (esp-idf-sysview.md - 1.2K) ❌
   - URL: https://github.com/espressif/esp-idf/tree/master/examples/system/sysview_tracing
   - Problem: GitHub directory listing, not content
   - Solution: Clone repo and extract files directly

2. **Perfetto CTF Import** (perfetto-ctf.md - 228B) ❌
   - URL: https://perfetto.dev/docs/data-sources/native-heap-profiling (404 error)
   - Problem: Wrong URL
   - Solution: Search for correct Perfetto CTF documentation URL

3. **Zephyr Tracing Sample** (zephyr-tracing.md - 17K)
   - Captured directory listing, not actual source
   - Solution: Clone and extract

4. **Zephyr TraceRecorder** (zephyr-tracerecorder.md - 1.5K)
   - Directory listing only
   - Solution: Clone and extract

## Next Actions

### Immediate (Clone and Extract Source)

1. **Clone ESP-IDF examples:**
   ```bash
   # Clone just the examples we need
   git clone --depth 1 --filter=blob:none --sparse https://github.com/espressif/esp-idf.git
   cd esp-idf
   git sparse-checkout set examples/system/sysview_tracing examples/system/heap_task_tracking examples/system/app_trace_to_plot
   ```

2. **Clone Zephyr samples:**
   ```bash
   git clone --depth 1 --filter=blob:none --sparse https://github.com/zephyrproject-rtos/zephyr.git
   cd zephyr
   git sparse-checkout set samples/subsys/tracing samples/subsys/shell
   ```

3. **Extract configuration templates:**
   - ESP-IDF: Extract sdkconfig.defaults from examples
   - Zephyr: Extract prj.conf from samples

### Extract Key Patterns

From the cloned code, extract:

1. **Configuration Templates**
   - ESP-IDF sdkconfig for SystemView, heap tracing, coredump
   - Zephyr prj.conf for CTF tracing, shell, coredump

2. **Code Patterns**
   - How to start/stop tracing
   - FreeRTOS task creation patterns
   - Zephyr thread creation patterns
   - Shell command registration

3. **Build System**
   - CMakeLists.txt structure
   - Component dependencies
   - Build flags

4. **Host Tools**
   - Location of sysviewtrace_proc.py
   - How to use babeltrace for CTF
   - Existing visualization tools

## Key Configuration Patterns Discovered

### ESP-IDF SystemView + Coredump

```ini
# SystemView Tracing
CONFIG_APPTRACE_SV_ENABLE=y
CONFIG_SYSVIEW_ENABLE=y
CONFIG_SYSVIEW_DEST_JTAG=y

# Coredump
CONFIG_ESP_COREDUMP_ENABLE=y
CONFIG_ESP_COREDUMP_DATA_FORMAT_ELF=y
CONFIG_ESP_COREDUMP_CHECKSUM_CRC32=y
CONFIG_ESP_COREDUMP_CAPTURE_DRAM=y  # Include heap

# Heap Tracing
CONFIG_HEAP_TRACING=y
CONFIG_HEAP_TRACING_DEST_TRAX=y
CONFIG_HEAP_TRACING_STACK_DEPTH=4
```

### Zephyr CTF Tracing + Coredump + Shell

```ini
# Tracing (CTF format)
CONFIG_TRACING=y
CONFIG_TRACING_BACKEND_RTT=y
CONFIG_TRACING_CTF=y

# Coredump
CONFIG_DEBUG_COREDUMP=y
CONFIG_DEBUG_COREDUMP_BACKEND_LOGGING=y

# Shell (for runtime debug)
CONFIG_SHELL=y
CONFIG_SHELL_BACKEND_RTT=y
CONFIG_KERNEL_SHELL=y

# Thread monitoring
CONFIG_THREAD_MONITOR=y
CONFIG_THREAD_RUNTIME_STATS=y
CONFIG_THREAD_STACK_INFO=y

# Stack protection
CONFIG_MPU_STACK_GUARD=y
CONFIG_STACK_SENTINEL=y
```

## Tools to Use (Not Build)

### ESP-IDF
- **sysviewtrace_proc.py** - SystemView to Perfetto conversion (location: `$IDF_PATH/tools/esp_app_trace/`)
- **espcoredump.py** - Coredump decoder
- **pytest-embedded** - Hardware testing framework

### Zephyr
- **babeltrace** - CTF decoder (install via package manager)
- **Percepio Tracealyzer** - Commercial tool with free tier
- **Twister** - Test runner (built into Zephyr)

### Cross-Platform
- **Perfetto UI** - Visualization (https://ui.perfetto.dev)
- **Tonbandgerät** - Alternative RTOS trace decoder (Rust CLI)
- **Renode** - Emulator for testing without hardware

## Research Checklist Status

- [x] ESP-IDF coredump docs - **EXCELLENT**
- [x] ESP-IDF apptrace docs - **GOOD**
- [x] ESP-IDF testing framework - **GOOD**
- [ ] ESP-IDF SystemView example - **NEED SOURCE CODE**
- [ ] ESP-IDF heap tracking example - **PARTIAL**
- [x] Zephyr coredump docs - **EXCELLENT**
- [x] Zephyr shell samples - **GOOD**
- [ ] Zephyr tracing samples - **NEED SOURCE CODE**
- [ ] Zephyr testing framework - **PARTIAL**
- [ ] Zephyr TraceRecorder - **NEED SOURCE CODE**
- [x] pytest-embedded - **EXCELLENT**
- [x] Renode - **EXCELLENT**
- [ ] Perfetto CTF import - **NEED CORRECT URL**
- [ ] Tonbandgerät - **PARTIAL**
- [ ] RTEdbg - **PARTIAL**

## Critical Insights

1. **Don't write decoders** - Use sysviewtrace_proc.py (ESP-IDF) and babeltrace (Zephyr)
2. **Clone official examples** - We have the paths, just need to extract the source
3. **pytest-embedded is powerful** - Use it as reference for our regression framework
4. **Renode can help** - Test without hardware for some platforms
5. **Configuration is well-documented** - We have the CONFIG options we need

## Next Phase: Clone and Extract

Before moving to Phase 1 (firmware creation), we need to:
1. Clone the example source code
2. Extract configuration files
3. Understand the code structure
4. Document the patterns

Then we can copy and adapt the official examples rather than writing from scratch.
