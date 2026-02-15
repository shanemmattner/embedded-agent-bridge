# Phase 0 Research Tracker

**Goal:** Find existing open-source examples to clone, not write firmware from scratch.

## Research Status

### ESP-IDF Research
- [ ] **SystemView Examples** (`esp-idf-sysview.md`)
  - Extract: Configuration patterns, FreeRTOS task setup, sdkconfig options
  - Look for: `CONFIG_SYSVIEW_*`, task creation patterns, trace start/stop APIs

- [ ] **Heap Tracing** (`esp-idf-heap-tracking.md`)
  - Extract: Heap tracking APIs, configuration, analysis scripts
  - Look for: `CONFIG_HEAP_TRACING_*`, allocation tracking patterns

- [ ] **Coredump** (`esp-idf-coredump.md`)
  - Extract: Configuration, decoding scripts, backend options
  - Look for: `CONFIG_ESP_COREDUMP_*`, espcoredump.py usage

- [ ] **Apptrace + SystemView** (`esp-idf-apptrace.md`)
  - Extract: Integration patterns, host tools, visualization
  - Look for: sysviewtrace_proc.py location, Perfetto export

- [ ] **Testing Framework** (`esp-idf-testing.md`)
  - Extract: pytest patterns, hardware test setup, test app structure
  - Look for: pytest-embedded fixtures, test organization

### Zephyr Research
- [ ] **Tracing Samples** (`zephyr-tracing.md`)
  - Extract: prj.conf patterns, CTF configuration, sample code structure
  - Look for: `CONFIG_TRACING_*`, CTF backend setup, visualization tools

- [ ] **Coredump** (`zephyr-coredump.md`)
  - Extract: Backend options, configuration, decoding tools
  - Look for: `CONFIG_DEBUG_COREDUMP_*`, coredump backends

- [ ] **Percepio TraceRecorder** (`zephyr-tracerecorder.md`)
  - Extract: Integration patterns, configuration, comparison to built-in tracing
  - Look for: `CONFIG_TRACING_TRACERECORDER_*`, licensing info

- [ ] **Testing Framework (Twister)** (`zephyr-testing.md`)
  - Extract: YAML test format, hardware-in-loop setup, test runner
  - Look for: testcase.yaml format, harness types, test organization

- [ ] **Shell Commands** (`zephyr-shell.md`)
  - Extract: Shell subsystem setup, runtime debug commands, backends
  - Look for: `CONFIG_SHELL_*`, kernel shell commands, custom command registration

### Third-Party Tools
- [ ] **Perfetto CTF Import** (`perfetto-ctf.md`)
  - Extract: CTF to Perfetto conversion, format specs
  - Look for: Babeltrace integration, trace format specifications

- [ ] **Tonbandgerät** (`tonbandgeraet.md`)
  - Extract: Firmware hooks, decoder usage, supported RTOS
  - Look for: Installation, CLI usage, FreeRTOS/Zephyr support

- [ ] **RTEdbg** (`rtedbg.md`)
  - Extract: Firmware integration, binary logging format, decoder
  - Look for: Minimal overhead design, integration examples

- [ ] **pytest-embedded** (`pytest-embedded.md`)
  - Extract: Fixture patterns, serial/JTAG integration, ESP-IDF specific features
  - Look for: Hardware fixture setup, test organization, CI integration

- [ ] **Renode** (`renode.md`)
  - Extract: Platform configurations, test automation without hardware
  - Look for: Supported platforms (ESP32, nRF5340, MCXN947, STM32L4)

## Key Questions to Answer

### Configuration
1. What sdkconfig/prj.conf options are REQUIRED for each debug feature?
2. What are the minimal configs vs full debug configs?
3. Are there conflicts between features (e.g., SystemView + heap tracing)?

### Firmware Structure
1. How do official examples structure their code?
2. What APIs are used to start/stop tracing?
3. How are test tasks/threads organized?

### Host Tools
1. Where is sysviewtrace_proc.py in ESP-IDF?
2. How to use babeltrace for Zephyr CTF?
3. Can we use existing tools instead of writing decoders?

### Testing
1. How does pytest-embedded handle hardware fixtures?
2. How does Twister define test cases in YAML?
3. What test patterns can we reuse?

## Next Steps After Scraping

1. **Extract Patterns** - Create config templates from examples
2. **Clone Examples** - Copy official examples as starting point
3. **Document Tools** - Map existing decoders/scripts we can use
4. **Plan Firmware** - Outline what to copy vs what to write
