# Comprehensive Debug Testing Plan - All Platforms

**Goal:** Enable and test ALL debugging features on ALL 5 boards using existing open-source firmware and tools.

**Platforms:**
1. ESP32-C6 (RISC-V, FreeRTOS via ESP-IDF)
2. ESP32-S3 (Xtensa, FreeRTOS via ESP-IDF)
3. nRF5340 (ARM Cortex-M33, Zephyr)
4. MCXN947 (ARM Cortex-M33, Zephyr)
5. STM32L4 (ARM Cortex-M4, Zephyr)

**Test Matrix:** Every feature × Every platform

---

## Phase 0: Research Existing Examples (CRITICAL - DO FIRST)

**Use `/firecrawl` to find and download existing open-source examples. DON'T write firmware from scratch!**

### ESP-IDF Research Tasks

```bash
/firecrawl
```

**Search queries:**
1. **SystemView Examples**
   - URL: `https://github.com/espressif/esp-idf/tree/master/examples/system/sysview_tracing`
   - Find: Official ESP-IDF SystemView example with FreeRTOS task tracing
   - Extract: Configuration, code patterns, host scripts

2. **Heap Tracing Examples**
   - URL: `https://github.com/espressif/esp-idf/tree/master/examples/system/heap_task_tracking`
   - Find: Heap allocation tracking demo
   - Extract: APIs, configuration

3. **Coredump Examples**
   - URL: `https://docs.espressif.com/projects/esp-idf/en/latest/esp32/api-guides/core_dump.html`
   - Find: How to enable and decode coredumps
   - Extract: Configuration, decoding scripts

4. **Apptrace + SystemView Integration**
   - URL: `https://github.com/espressif/esp-idf/tree/master/examples/system/app_trace_to_plot`
   - Already scraped, review for SystemView specifics

5. **ESP-IDF Testing Framework**
   - URL: `https://github.com/espressif/esp-idf/tree/master/tools/test_apps`
   - Find: How ESP-IDF does automated testing
   - Extract: pytest patterns, hardware test setup

### Zephyr Research Tasks

```bash
/firecrawl
```

**Search queries:**
1. **Zephyr Tracing Samples**
   - URL: `https://github.com/zephyrproject-rtos/zephyr/tree/main/samples/subsys/tracing`
   - Find: Official tracing examples
   - Extract: Configuration, CTF export, visualization tools

2. **Zephyr Coredump**
   - URL: `https://docs.zephyrproject.org/latest/services/debugging/coredump.html`
   - Find: How to enable coredump in Zephyr
   - Extract: Backend configuration, decoding tools

3. **Zephyr Percepio TraceRecorder**
   - URL: `https://github.com/zephyrproject-rtos/zephyr/tree/main/subsys/tracing/tracerecorder`
   - Find: Alternative to built-in tracing (commercial but has free tier)
   - Extract: Configuration, comparison to built-in

4. **Zephyr Testing Framework**
   - URL: `https://docs.zephyrproject.org/latest/develop/test/index.html`
   - Find: Twister test framework
   - Extract: YAML test format, hardware-in-loop setup

5. **Zephyr Shell Commands**
   - URL: `https://github.com/zephyrproject-rtos/zephyr/tree/main/samples/subsys/shell`
   - Find: Shell subsystem examples
   - Extract: Runtime debug commands (kernel stats, thread info, etc.)

### Third-Party Tools Research

```bash
/firecrawl
```

**Search queries:**
1. **Perfetto CTF Import**
   - URL: `https://perfetto.dev/docs/data-sources/native-heap-profiling`
   - Find: How Perfetto imports CTF traces from Zephyr
   - Extract: Conversion scripts, format specs

2. **Tonbandgerät (RTOS Tracing)**
   - URL: `https://github.com/absw/tonbandgeraet`
   - Find: Rust CLI for FreeRTOS/Zephyr trace export
   - Extract: Firmware hooks, decoder usage

3. **RTEdbg (Binary Logging)**
   - URL: `https://github.com/rte-design/RTEdbg`
   - Find: Minimal overhead binary logging
   - Extract: Firmware integration, decoder

4. **pytest-embedded (ESP-IDF Testing)**
   - URL: `https://github.com/espressif/pytest-embedded`
   - Find: ESP-IDF's hardware testing framework
   - Extract: Fixture patterns, serial/JTAG integration

5. **Renode Integration**
   - URL: `https://renode.readthedocs.io/en/latest/`
   - Find: Emulator testing (can we test without hardware?)
   - Extract: Platform configurations

---

## Phase 1: Create Example Firmware (Use Researched Examples!)

### 1.1 ESP32-C6 Debug Full Example

**Source:** Copy from ESP-IDF `sysview_tracing` + `app_trace_to_plot`

```
examples/esp32c6-debug-full/
├── main/
│   ├── main.c                    # Based on sysview_tracing example
│   ├── CMakeLists.txt
│   └── tasks.c                   # Multiple FreeRTOS tasks for testing
├── CMakeLists.txt
├── sdkconfig.defaults            # All debug features enabled
└── README.md
```

**Features to enable (from research):**
```ini
# SystemView
CONFIG_APPTRACE_SV_ENABLE=y
CONFIG_SYSVIEW_ENABLE=y
CONFIG_SYSVIEW_DEST_JTAG=y

# Heap Tracing
CONFIG_HEAP_TRACING=y
CONFIG_HEAP_TRACING_DEST_TRAX=y
CONFIG_HEAP_TRACING_STACK_DEPTH=4

# Coredump
CONFIG_ESP_COREDUMP_ENABLE=y
CONFIG_ESP_COREDUMP_DATA_FORMAT_ELF=y
CONFIG_ESP_COREDUMP_CHECKSUM_CRC32=y

# Task Watchdog
CONFIG_ESP_TASK_WDT=y
CONFIG_ESP_TASK_WDT_PANIC=y

# Stack Overflow
CONFIG_FREERTOS_WATCHPOINT_END_OF_STACK=y
CONFIG_FREERTOS_CHECK_STACKOVERFLOW_PTRVAL=y
```

**Tasks in firmware:**
- Idle task
- High-priority compute task
- Low-priority logging task
- Periodic sensor read task
- Command handler task

### 1.2 ESP32-S3 Debug Full Example

**Same as ESP32-C6 but for Xtensa architecture**

```
examples/esp32s3-debug-full/
```

**Key difference:** Test Xtensa-specific features:
- Dual-core task scheduling (if using both cores)
- Xtensa coredump format differences
- Performance counter differences

### 1.3 nRF5340 Debug Full Example

**Source:** Copy from Zephyr `samples/subsys/tracing` + `samples/subsys/shell`

```
examples/nrf5340-debug-full/
├── src/
│   ├── main.c                    # Based on Zephyr tracing sample
│   ├── tasks.c                   # Multiple threads
│   └── shell_commands.c          # Runtime debug commands
├── prj.conf                      # Full debug config
├── CMakeLists.txt
└── README.md
```

**Features to enable (from research):**
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

**Shell commands to implement:**
- `kernel threads` - List all threads
- `kernel stacks` - Show stack usage
- `kernel uptime` - System uptime
- `fault` - Trigger fault for testing

### 1.4 MCXN947 Debug Full Example

**Same as nRF5340** (both are Cortex-M33 Zephyr)

```
examples/mcxn947-debug-full/
```

### 1.5 STM32L4 Debug Full Example

**Same as nRF5340** (Cortex-M4 Zephyr)

```
examples/stm32l4-debug-full/
```

---

## Phase 2: Host-Side Tools (Use Existing!)

### 2.1 Trace Decoders (Research First!)

**DON'T write our own decoders. Use existing tools:**

1. **ESP-IDF SystemView Decoder**
   - Location: `$IDF_PATH/tools/esp_app_trace/`
   - Tool: `sysviewtrace_proc.py`
   - Research: How it converts to Perfetto JSON

2. **Zephyr CTF Decoder**
   - Tool: `babeltrace` (standard CTF decoder)
   - Research: How to convert CTF → Perfetto JSON
   - Alternative: Use Perfetto's built-in CTF importer

3. **Tonbandgerät CLI**
   - Install: `cargo install tonbandgeraet-cli`
   - Usage: `tband convert trace.rtt --format perfetto`

### 2.2 Extend EAB Trace Export

**Add format converters based on research:**

```python
# eab/cli/trace/export.py
def export_trace(input_file, output_file, format):
    if format == "perfetto":
        if _is_esp_systemview(input_file):
            # Use ESP-IDF's sysviewtrace_proc.py
            _convert_systemview_to_perfetto(input_file, output_file)
        elif _is_zephyr_ctf(input_file):
            # Use babeltrace or Perfetto CTF importer
            _convert_ctf_to_perfetto(input_file, output_file)
        else:
            # Fallback: our simple log-line exporter
            _convert_logs_to_perfetto(input_file, output_file)
```

---

## Phase 3: Regression Test Suite

### 3.1 Extend Test Step Types

**Add to `eab/cli/regression/steps.py`:**

```python
# New step types (implement based on pytest-embedded research)

class RTTCaptureStep:
    """Start RTT capture for N seconds."""

class ApptraceCaptureStep:
    """Start apptrace capture for N seconds."""

class ExportTraceStep:
    """Convert .rttbin to Perfetto JSON using appropriate decoder."""

class AssertTraceStep:
    """Verify trace file contains expected events."""

class TriggerFaultStep:
    """Send command to trigger fault (for coredump testing)."""
```

### 3.2 Test YAML Templates

**Create comprehensive tests for each platform:**

#### tests/hw/esp32c6_debug_full.yaml
```yaml
name: ESP32-C6 Full Debug Suite
device: esp32c6
chip: esp32c6
timeout: 180

setup:
  - flash:
      firmware: examples/esp32c6-debug-full

steps:
  # Test 1: SystemView Trace Capture
  - reset: {}
  - apptrace_capture:
      duration: 15
      output: /tmp/esp32c6-trace.rttbin

  - export_trace:
      input: /tmp/esp32c6-trace.rttbin
      output: /tmp/esp32c6-trace.json
      format: perfetto

  - assert_trace:
      file: /tmp/esp32c6-trace.json
      contains: ["IDLE", "main", "tasks"]
      min_events: 100

  # Test 2: Heap Tracing
  - send:
      text: "heap start"

  - sleep: 5

  - send:
      text: "heap stop"

  - wait:
      pattern: "Heap trace"
      timeout: 5

  # Test 3: Coredump
  - send:
      text: "fault"

  - wait:
      pattern: "Coredump"
      timeout: 10

  # Test 4: Task Watchdog
  - send:
      text: "wdt_test"

  - wait:
      pattern: "Task watchdog"
      timeout: 15

teardown:
  - reset: {}
```

#### tests/hw/esp32s3_debug_full.yaml
**Same as C6 but for S3**

#### tests/hw/nrf5340_debug_full.yaml
```yaml
name: nRF5340 Full Debug Suite
device: nrf5340
chip: nrf5340
timeout: 180

setup:
  - flash:
      firmware: examples/nrf5340-debug-full
      runner: jlink

steps:
  # Test 1: CTF Trace Capture
  - reset: {}
  - rtt_capture:
      duration: 15
      output: /tmp/nrf5340-trace.rttbin

  - export_trace:
      input: /tmp/nrf5340-trace.rttbin
      output: /tmp/nrf5340-trace.json
      format: perfetto

  - assert_trace:
      file: /tmp/nrf5340-trace.json
      contains: ["idle", "main", "sysworkq"]
      min_events: 100

  # Test 2: Thread Info via Shell
  - send:
      text: "kernel threads"

  - wait:
      pattern: "thread"
      timeout: 2

  # Test 3: Stack Usage
  - send:
      text: "kernel stacks"

  - wait:
      pattern: "unused"
      timeout: 2

  # Test 4: Fault Trigger
  - send:
      text: "fault null"

  - wait:
      pattern: "FAULT"
      timeout: 5

  # Test 5: MPU Stack Guard
  - send:
      text: "fault stack"

  - wait:
      pattern: "MPU FAULT"
      timeout: 5

teardown:
  - reset: {}
```

#### tests/hw/mcxn947_debug_full.yaml
**Same as nRF5340 but with probe-rs transport**

#### tests/hw/stm32l4_debug_full.yaml
**Same as nRF5340 but with probe-rs transport**

### 3.3 Cross-Platform Test Matrix

**Run SAME tests on ALL platforms to verify parity:**

```bash
# Matrix test runner
eabctl regression --suite tests/hw/ --filter "*debug_full*" --matrix

# This runs each test on each compatible platform:
# - Thread tracing: All 5 platforms
# - Heap tracing: ESP32-C6, ESP32-S3 (FreeRTOS specific)
# - CTF export: nRF5340, MCXN947, STM32L4 (Zephyr specific)
# - Coredump: All 5 platforms
# - Shell commands: nRF5340, MCXN947, STM32L4 (Zephyr shell)
```

---

## Phase 4: Documentation & Validation

### 4.1 Platform Comparison Matrix

Create `docs/debug-features-matrix.md`:

| Feature | ESP32-C6 | ESP32-S3 | nRF5340 | MCXN947 | STM32L4 |
|---------|----------|----------|---------|---------|---------|
| Thread/Task Tracing | ✅ SystemView | ✅ SystemView | ✅ CTF | ✅ CTF | ✅ CTF |
| Heap Profiling | ✅ | ✅ | ⚠️ Limited | ⚠️ Limited | ⚠️ Limited |
| Coredump | ✅ | ✅ | ✅ | ✅ | ✅ |
| Stack Overflow Detection | ✅ | ✅ | ✅ MPU | ✅ MPU | ✅ MPU |
| Perfetto Export | ✅ | ✅ | ✅ | ✅ | ✅ |
| Runtime Shell | ❌ | ❌ | ✅ | ✅ | ✅ |

### 4.2 Update CLAUDE.md

Add comprehensive debug workflow examples.

---

## Implementation Order

### Week 1: Research & Setup
1. **Day 1-2:** `/firecrawl` all research tasks (ESP-IDF, Zephyr, tools)
2. **Day 3:** Review scraped examples, extract patterns
3. **Day 4:** Set up build environments for all platforms

### Week 2: Firmware Examples
1. **Day 5:** ESP32-C6 debug-full (based on researched examples)
2. **Day 6:** ESP32-S3 debug-full (clone from C6, test Xtensa)
3. **Day 7:** nRF5340 debug-full (based on Zephyr samples)
4. **Day 8:** MCXN947 & STM32L4 debug-full (clone from nRF5340)

### Week 3: Integration & Testing
1. **Day 9-10:** Extend trace export with researched decoders
2. **Day 11-12:** Extend regression framework with new step types
3. **Day 13:** Write YAML tests for all platforms
4. **Day 14:** Run full regression suite, fix issues

### Week 4: Validation & Documentation
1. **Day 15-16:** Cross-platform matrix testing
2. **Day 17:** Create comparison docs
3. **Day 18:** Update CLAUDE.md, README
4. **Day 19:** Create demo video/screenshots
5. **Day 20:** Final validation, merge PR

---

## Success Criteria

### Firmware
- [ ] All 5 platforms have debug-full examples
- [ ] All examples based on official samples (not custom code)
- [ ] Each example demonstrates all debug features

### Testing
- [ ] Regression tests pass on all 5 platforms
- [ ] Same test scenarios run on all compatible platforms
- [ ] Perfetto shows meaningful data for all platforms

### Tools
- [ ] Trace export uses official decoders (ESP-IDF, babeltrace, etc.)
- [ ] No custom parsers written (use existing tools)
- [ ] Automated end-to-end: capture → export → validate

### Documentation
- [ ] Feature comparison matrix complete
- [ ] Each platform has usage guide
- [ ] CLAUDE.md has complete debug workflows
- [ ] All examples have README with expected output

---

## Research Checklist

**COMPLETE THESE FIRST before writing any code:**

- [ ] Scrape ESP-IDF SystemView example
- [ ] Scrape ESP-IDF heap tracing example
- [ ] Scrape ESP-IDF coredump docs
- [ ] Scrape Zephyr tracing samples
- [ ] Scrape Zephyr coredump docs
- [ ] Scrape Zephyr shell samples
- [ ] Scrape pytest-embedded examples
- [ ] Scrape Zephyr Twister test framework
- [ ] Research Perfetto CTF import
- [ ] Research Tonbandgerät integration
- [ ] Research babeltrace usage
- [ ] Find ESP-IDF sysviewtrace_proc.py location

---

## Notes

**CRITICAL:** Use existing open-source examples as templates. Don't invent new patterns when official samples exist. The goal is to validate EAB's ability to work with standard embedded debugging workflows, not to create custom firmware.

**Hardware Required:**
- ESP32-C6 DevKit
- ESP32-S3 DevKit
- nRF5340 DK
- FRDM-MCXN947
- Nucleo-L432KC

**Estimated Total Time:** 3-4 weeks (assuming research finds good examples to clone)
