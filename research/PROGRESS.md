# Debug Testing Implementation Progress

## ✅ Phase 0: Research (COMPLETE)

### Completed Tasks
- [x] Scraped 15 documentation sources via Firecrawl
- [x] Cloned ESP-IDF and Zephyr official examples
- [x] Extracted configuration patterns
- [x] Documented key findings and tool locations
- [x] Created configuration templates

### Key Deliverables
- `research/phase0/RESEARCH_SUMMARY.md` - Comprehensive findings
- `research/phase0/CONFIG_PATTERNS.md` - Extracted configurations
- `research/phase0/RESEARCH_TRACKER.md` - Research checklist
- `research/phase0/source-examples/` - Cloned official code

### Key Discoveries
1. **Don't write decoders** - Use `sysviewtrace_proc.py` (ESP-IDF) and `babeltrace` (Zephyr)
2. **Official examples are excellent** - Direct copy-and-adapt approach
3. **pytest-embedded** - Reference for our regression framework
4. **All CONFIG options documented** - Ready to use

## 🚧 Phase 1: Firmware Examples (IN PROGRESS)

### ESP32-C6 Debug Full ✅ COMPLETE

**Location:** `examples/esp32c6-debug-full/`

**Files Created:**
- [x] `main/debug_full_main.c` - Full-featured firmware (370 lines)
- [x] `sdkconfig.defaults` - All debug features enabled
- [x] `CMakeLists.txt` - Build configuration
- [x] `main/CMakeLists.txt` - Component registration
- [x] `partitions.csv` - Includes 128KB coredump partition
- [x] `README.md` - Comprehensive documentation

**Features:**
- ✅ SystemView task tracing with custom events
- ✅ Heap allocation tracking (128 records)
- ✅ Coredump generation (ELF format, saved to flash)
- ✅ Stack overflow detection
- ✅ Task watchdog (10s timeout)
- ✅ UART command interface (heap_start, fault_null, etc.)
- ✅ 4 tasks: cmd (P5), compute (P3), io (P2), alloc (P1)

**Testing Commands:**
```bash
status      # Print system info
heap_start  # Start heap tracing
heap_stop   # Dump heap allocations
fault_null  # Trigger NULL pointer fault → coredump
fault_div0  # Trigger divide-by-zero → coredump
wdt_test    # Trigger watchdog timeout
```

**Next:** Test build and flash

### ESP32-S3 Debug Full ⏳ NEXT

**Plan:** Clone ESP32-C6 example, test Xtensa-specific features

**Differences from C6:**
- Architecture: Xtensa (dual-core) vs RISC-V (single-core)
- Coredump format differences
- Performance counter differences
- Test dual-core task pinning (optional)

### nRF5340 Debug Full ⏳ TODO

**Plan:** Based on Zephyr tracing sample

**Features:**
- CTF tracing via RTT
- Coredump via logging backend
- Shell commands (kernel threads, stacks, uptime)
- MPU stack guard
- Multiple threads

### MCXN947 Debug Full ⏳ TODO

**Plan:** Clone from nRF5340 (both Cortex-M33 Zephyr)

**Differences:**
- Flash via probe-rs instead of J-Link
- NXP-specific peripherals

### STM32L4 Debug Full ⏳ TODO

**Plan:** Clone from nRF5340 (Cortex-M4 Zephyr)

**Differences:**
- Flash via probe-rs/OpenOCD
- STM32-specific peripherals

## ⏳ Phase 2: Host Tools (TODO)

### Extend EAB Trace Export

**Plan:**
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

**Integration:**
- Wrap `sysviewtrace_proc.py` for ESP32 traces
- Wrap `babeltrace` for Zephyr CTF traces
- Test end-to-end capture → export → Perfetto UI

## ⏳ Phase 3: Regression Tests (TODO)

### Extend Test Step Types

New steps needed:
```python
class RTTCaptureStep
class ApptraceCaptureStep
class ExportTraceStep
class AssertTraceStep
class TriggerFaultStep
```

### Test YAML Files

Create for each platform:
- `tests/hw/esp32c6_debug_full.yaml`
- `tests/hw/esp32s3_debug_full.yaml`
- `tests/hw/nrf5340_debug_full.yaml`
- `tests/hw/mcxn947_debug_full.yaml`
- `tests/hw/stm32l4_debug_full.yaml`

### Cross-Platform Matrix

```bash
eabctl regression --suite tests/hw/ --filter "*debug_full*" --matrix
```

Tests to run on all platforms:
- Trace capture (15s)
- Export to Perfetto JSON
- Assert trace contains expected events
- Trigger fault → verify coredump
- (Zephyr only) Shell commands
- (ESP32 only) Heap tracing

## ⏳ Phase 4: Validation & Docs (TODO)

### Platform Comparison Matrix

Create `docs/debug-features-matrix.md`:

| Feature | ESP32-C6 | ESP32-S3 | nRF5340 | MCXN947 | STM32L4 |
|---------|----------|----------|---------|---------|---------|
| Thread/Task Tracing | ✅ SystemView | ✅ SystemView | ✅ CTF | ✅ CTF | ✅ CTF |
| Heap Profiling | ✅ | ✅ | ⚠️ Limited | ⚠️ Limited | ⚠️ Limited |
| Coredump | ✅ | ✅ | ✅ | ✅ | ✅ |
| Stack Overflow | ✅ | ✅ | ✅ MPU | ✅ MPU | ✅ MPU |
| Perfetto Export | ✅ | ✅ | ✅ | ✅ | ✅ |
| Runtime Shell | ❌ | ❌ | ✅ | ✅ | ✅ |

### Update CLAUDE.md

Add comprehensive debug workflow examples to EAB CLAUDE.md.

## Timeline

### Original Estimate
- Week 1: Research (DONE)
- Week 2: Firmware examples
- Week 3: Integration & testing
- Week 4: Validation & docs

### Current Status
- **Day 1 COMPLETE:** Research phase finished, ESP32-C6 example created
- **Day 2 NEXT:** ESP32-S3 and nRF5340 examples
- **Day 3-4:** MCXN947, STM32L4, test builds
- **Week 2:** Host tools integration
- **Week 3:** Regression tests
- **Week 4:** Validation & docs

## Success Criteria

### Firmware ✅ 1/5 Complete
- [x] ESP32-C6 has debug-full example
- [ ] ESP32-S3 has debug-full example
- [ ] nRF5340 has debug-full example
- [ ] MCXN947 has debug-full example
- [ ] STM32L4 has debug-full example
- [x] All examples based on official samples ✅
- [ ] Each example demonstrates all debug features

### Testing ⏳ 0% Complete
- [ ] Regression tests pass on all 5 platforms
- [ ] Same test scenarios run on all compatible platforms
- [ ] Perfetto shows meaningful data for all platforms

### Tools ⏳ 0% Complete
- [ ] Trace export uses official decoders
- [ ] No custom parsers written
- [ ] Automated end-to-end: capture → export → validate

### Documentation ⏳ 20% Complete
- [x] ESP32-C6 README complete ✅
- [ ] Feature comparison matrix
- [ ] Each platform has usage guide
- [ ] CLAUDE.md has complete debug workflows

## Next Immediate Actions

1. **Test ESP32-C6 build** (verify it compiles)
2. **Create ESP32-S3 example** (clone from C6, adjust for Xtensa)
3. **Create nRF5340 example** (Zephyr CTF + shell)
4. **Create MCXN947 example** (clone from nRF5340)
5. **Create STM32L4 example** (clone from nRF5340)
6. **Test all builds** (ensure they compile)
7. **Flash to hardware** (ESP32-C6 first)
8. **Capture first trace** (verify SystemView works)

## Files Created This Session

```
examples/esp32c6-debug-full/
├── main/
│   ├── debug_full_main.c           # 370 lines, full-featured
│   └── CMakeLists.txt
├── sdkconfig.defaults               # All debug features
├── CMakeLists.txt
├── partitions.csv                   # 128KB coredump partition
└── README.md                        # Comprehensive docs

research/phase0/
├── RESEARCH_SUMMARY.md              # Key findings
├── CONFIG_PATTERNS.md               # Extracted configs
├── RESEARCH_TRACKER.md              # Checklist
├── source-examples/
│   ├── esp-idf/                     # Cloned examples
│   └── zephyr/                      # Cloned samples
└── *.md                             # Scraped docs (15 files)
```

## Estimated Remaining Time

- **Phase 1:** 1-2 days (4 more examples + testing)
- **Phase 2:** 2-3 days (tool integration)
- **Phase 3:** 3-4 days (regression framework + tests)
- **Phase 4:** 1-2 days (docs + validation)

**Total:** ~2 weeks remaining (on track for 3-week completion)
