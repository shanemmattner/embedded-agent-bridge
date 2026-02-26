# EAB — Next Feature Ideas

*Research date: 2026-02-26. Sources: emBO++ 2024, Memfault/Interrupt blog, Zephyr docs, USENIX Security 2024, Nordic PPK2 docs, embedded.com, Percepio.*

---

## Quick-Reference Table

| # | Feature | Difficulty | Wow Factor | Hardware Needed |
|---|---------|-----------|-----------|----------------|
| 1 | PPK2 Power Profiler + CI Budget | M | ★★★★★ | PPK2 + nRF5340 |
| 2 | Auto-Watchpoint from Anomaly Correlation | M | ★★★★★ | Any Cortex-M |
| 3 | LLM DWT Stream Interpreter | S | ★★★★★ | Any Cortex-M |
| 4 | Zephyr Coredump + LLM Root-Cause | M | ★★★★☆ | nRF5340 |
| 5 | BLE Connection Quality Analyzer | M | ★★★★☆ | nRF5340 (2x) |
| 6 | ITM/SWO Daemon + Perfetto ETM Export | M-L | ★★★★★ | STM32 / MCXN947 |
| 7 | Firmware Variable Snapshot Diff | M | ★★★★☆ | Any |
| 8 | RTOS Thread Stack Inspector | S-M | ★★★☆☆ | nRF5340 |
| 9 | RTT Shell Fuzzer / Chaos Mode | M | ★★★★☆ | nRF5340 |
| 10 | Live Memory Snapshot on Demand | S-M | ★★★★☆ | Any |
| 11 | PC Sampling Statistical Profiler | M | ★★★★☆ | Any Cortex-M |
| 12 | Continuous RTOS Event Trace | L | ★★★★★ | nRF5340 |
| 13+ | Memfault Feature Re-implementations | Various | ★★★★★ | Various |

---

## Recommended Sprint Order

**Sprint 1 — Small, maximum reuse (~1 day each):**
1. **#3 LLM DWT Stream Interpreter** — mostly prompt engineering + one new MCP tool
2. **#10 Live Memory Snapshot** — GDB bridge already exists; new work is ELF core file format
3. **#8 RTOS Thread Stack Inspector** — GDB Python already used in EAB for DWT watchpoints

**Sprint 2 — Medium, nRF5340 required (~2 days each):**
4. **#4 Zephyr Coredump + LLM** — extends existing fault analysis with Zephyr thread context
5. **#2 Auto-Watchpoint from Anomaly** — most novel EAB-native feature; closes anomaly→cause loop
6. **#5 BLE Connection Quality Analyzer** — BLE HIL + RTT + anomaly all exist; new daemon is the bridge

**Sprint 3 — Hardware or longer effort:**
7. **#1 PPK2 Power Profiler** — needs Nordic PPK2 hardware (~$100)
8. **#6 ITM/SWO + Perfetto** — biggest win for STM32 users; ship ITM daemon first, ETM later
9. **#12 Continuous RTOS Event Trace** — Percepio-killer if done right

---

## Feature Details

### #1 — PPK2 Power Profiler Integration + CI Power Budget Regression

**One-liner:** Stream Nordic PPK2 current measurements as JSONL and add a `power_budget` HIL step that fails CI if energy consumption regresses >N%.

**Problem:** Power consumption is a top-tier concern for BLE embedded products and nearly everyone measures it manually in a GUI. No automated, CI-integrated power regression tool exists for nRF5340 / Nordic ecosystem projects.

**Solution:** New `PowerDaemon` (pyPPK2 Python library speaks USB HID → JSONL sink). Mirrors the RTT daemon pattern. Expose one-shot and streaming modes.

```bash
eabctl power start --device NRF5340_XXAA_APP   # stream μA readings as JSONL
eabctl power snapshot --duration 30s --json     # one-shot stats (avg, peak, energy)
eabctl power stop
```

**HIL integration:**
```yaml
steps:
  - ble_connect: {device: central}
  - power_budget:
      duration: 10
      avg_ua_max: 1500
      peak_ua_max: 8000
      energy_uj_max: 15000
      fail_on_regression: true
      baseline: tests/baselines/ble_connected_power.json
```

**EAB building blocks:** New `PowerDaemon` (pyPPK2), `eabctl power` commands, `power_budget` HIL step, `hil_power` pytest fixture, anomaly detection integration for power traces.

**Dependencies:** Nordic PPK2 hardware (~$100), `pyPPK2` Python library.

**Sources:**
- Nordic PPK2: https://www.nordicsemi.com/Products/Development-hardware/Power-Profiler-Kit-2
- Qoitech Otii (shows market demand): https://www.qoitech.com/wp-content/uploads/2024/10/Otii-Product-Suite_Qoitech_2024.pdf

---

### #2 — Auto-Watchpoint Placement from Anomaly Correlation

**One-liner:** When `anomaly_watch` flags a metric spike, automatically program DWT comparators on the ELF symbols that correlate most strongly with the anomaly.

**Problem:** EAB has anomaly detection (EWMA z-score on RTT metrics) AND non-halting DWT watchpoints with ELF symbol resolution. The missing link: when anomaly detection fires, *which variable caused it?*

**Solution:** Extend `AnomalyWatcher` to maintain a rolling Pearson cross-correlation matrix across metric channels. On anomaly trigger: resolve top-N correlated ELF symbols, auto-arm DWT watchpoints, emit `auto_watchpoint_armed` event in JSONL.

**EAB building blocks:**
- Extend `AnomalyWatcher` — rolling Pearson correlation matrix
- On anomaly trigger: resolve correlated symbols from ELF via `nm`/`pyelftools`
- Call existing DWT watchpoint engine to arm comparators
- Emit `auto_watchpoint_armed` event with correlation coefficient + `ai_prompt` field

**Sources:**
- Memfault Interrupt watchpoints: https://interrupt.memfault.com/blog/cortex-m-watchpoints

---

### #3 — LLM DWT Stream Interpreter

**One-liner:** Feed the live DWT watchpoint event stream to an LLM via MCP and ask it to narrate what the firmware is doing in plain English.

**Problem:** DWT streams 100 Hz watchpoint events as JSONL. No tool interprets this stream for a developer who doesn't know what to look for.

**Solution:** New MCP tool `dwt_stream_explain(symbols, duration_s)`: arm watchpoints → capture N-second JSONL stream → enrich with ELF source line info → send to LLM → return narrative + suggested follow-up watchpoints.

```python
# Claude Desktop / Cursor usage:
# "Watch conn_interval and mtu_size for 10 seconds and describe what you see"
# → arms DWT on both symbols, captures stream, LLM narrates state machine behavior
```

**EAB building blocks:** New MCP tool in existing `eab/mcp_server.py`, reads existing DWT JSONL output, ELF source line enrichment (already done for watchpoints).

**Difficulty:** S — mostly prompt engineering + wiring MCP → DWT.

**Sources:**
- emBO++ 2024 Perfetto + ARM trace talk: https://salkinium.com/talks/embo24_perfetto.pdf

---

### #4 — Zephyr Coredump Capture + LLM Root-Cause Analysis

**One-liner:** On a Zephyr fatal error, automatically capture the coredump over RTT, parse it with GDB, and feed registers + stack trace + last N RTT lines to the LLM for root-cause hypothesis.

**Problem:** EAB's fault analysis reads CFSR/HFSR but doesn't capture Zephyr-level context: thread names, scheduler state, C-level backtrace.

**Solution:** Zephyr `CONFIG_DEBUG_COREDUMP=y` + `CONFIG_DEBUG_COREDUMP_BACKEND_RTT=y` emits a structured binary blob over RTT channel 1 on fatal error. Zephyr ships `coredump_gdbserver.py` that serves it as a GDB stub.

```bash
eabctl coredump last --json        # show most recent coredump with LLM analysis
eabctl coredump list               # all captured coredumps
eabctl coredump load dump.core     # load specific dump into GDB stub
```

**EAB building blocks:** Extend `RTTDaemon` to detect coredump blob markers, new `ZephyrCoredumpParser`, reuse fault analysis `ai_prompt` format, new `assert_no_coredump` HIL step.

**Sources:**
- Zephyr Core Dump docs: https://docs.zephyrproject.org/latest/services/debugging/coredump.html
- Nordic NCS coredump: https://docs.nordicsemi.com/bundle/ncs-3.1.0/page/zephyr/services/debugging/coredump.html

---

### #5 — BLE Connection Quality Analyzer

**One-liner:** Stream BLE connection parameters (RSSI, PHY, connection interval, packet error rate, supervision timeout proximity) as JSONL and detect link degradation before it causes disconnection.

**Problem:** EAB's BLE HIL tests pass/fail on data — not on link health. No tool tracks `supervision_timeout_proximity` (the earliest warning of impending disconnection).

**Solution:** `BleQualityDaemon` polls RTT shell (`bt rssi`, `bt phy`, NCS BT_CONN_CB stats) at configurable interval, streams as JSONL metrics. Feeds into existing `AnomalyWatcher`.

```yaml
steps:
  - ble_connect: {device: central}
  - ble_quality_assert:
      min_rssi_dbm: -70
      max_per: 0.01
      supervision_timeout_margin_pct: 50  # fail if >50% of timeout consumed
      duration: 30
```

**EAB building blocks:** New `BleQualityDaemon`, `ble_quality_assert` HIL step, `hil_ble_quality` pytest fixture, browser plotter BLE quality tab.

**Sources:**
- BLE connection quality metrics: https://www.sciencedirect.com/article/pii/S2405959524000912

---

### #6 — ITM/SWO Streaming Daemon + Perfetto Export

**One-liner:** Capture ITM/SWO trace from STM32 and other Cortex-M boards, stream printf channels as JSONL, export DWT+ITM+ETM combined traces to Perfetto for Chrome-based timeline analysis.

**Problem:** STM32 users use SWO/ITM for printf output and PC sampling — EAB has nothing for this. nRF targets use RTT; STM32 targets currently have no structured log stream.

**Solution:** New `ITMDaemon` using probe-rs or OpenOCD SWO decoder subprocess. ITM channel 0 → printf stream as JSONL. DWT PC sampling → hotspot histogram. Export to Perfetto JSON (reuse C2000 Perfetto exporter pattern).

```bash
eabctl itm start --device STM32L476RG --transport probe-rs
eabctl itm tail 100 --json
eabctl itm stop
eabctl trace export --format perfetto -o trace.json   # opens in ui.perfetto.dev
```

**EAB building blocks:** New `ITMDaemon` (probe-rs SWO support), new `eabctl itm` commands, extend Perfetto exporter for Cortex-M events (reuse C2000 ERAD/DLOG exporter).

**Sources:**
- emBO++ 2024 Perfetto talk: https://salkinium.com/talks/embo24_perfetto.pdf
- Auterion embedded-debug-tools: https://github.com/Auterion/embedded-debug-tools
- YouTube — Analyzing ARM Cortex-M Firmware with Perfetto: https://www.youtube.com/watch?v=FIStxUz2ERY
- ARM ETM learning path: https://learn.arm.com/learning-paths/embedded-and-microcontrollers/uv_debug/5_etm_trace/

---

### #7 — Firmware Variable Snapshot Diff

**One-liner:** Flash firmware A, run a test, snapshot N variable values via GDB. Flash firmware B, run the same test, snapshot the same variables. Diff the runtime state between builds.

**Problem:** "I refactored the ISR — did it change any runtime behavior?" Today engineers manually inspect variables after each flash.

**Solution:** New `snapshot` HIL step + `eabctl firmware-diff` command. Orchestrate: build A → run scenario → GDB read symbol list → build B → repeat → structured JSON diff.

```bash
eabctl firmware-diff \
  --build-a firmware_v1.elf \
  --build-b firmware_v2.elf \
  --scenario tests/hw/throughput.yaml \
  --symbols conn_interval,mtu_size,error_count \
  --json
```

**EAB building blocks:** New `snapshot` HIL step (GDB read list of ELF symbols), diff engine (numeric delta + bit-field decode), `ai_prompt` field for LLM summary.

**Sources:**
- DIFFER tool (Trail of Bits 2024): https://blog.trailofbits.com/2024/01/31/introducing-differ-a-new-tool-for-testing-and-validating-transformed-programs/

---

### #8 — RTOS Thread Stack Inspector (Zephyr-first)

**One-liner:** At any time, dump all Zephyr thread names, states, priorities, and stack high-water marks via GDB Python RTOS awareness.

**Problem:** Stack overflow is the most common hard-to-reproduce RTOS bug. No tool monitors stack headroom continuously.

**Solution:** GDB Python script walks `_kernel.threads` linked list. Streams thread name, state, priority, stack base/size, and high-water mark as JSONL.

```bash
eabctl threads snapshot --device NRF5340_XXAA_APP --json
eabctl threads watch --interval 5s --device NRF5340_XXAA_APP   # continuous
```

```yaml
steps:
  - stack_headroom_assert:
      min_free_bytes: 256   # fail if any thread < 256 bytes remaining
      device: NRF5340_XXAA_APP
```

**EAB building blocks:** GDB Python script (pattern already in EAB for DWT conditional watchpoints), new `ThreadWatchDaemon`, `stack_headroom_assert` HIL step, MCP tool `get_thread_state()`.

**Sources:**
- Continuous observability for RTOS firmware: https://www.embedded.com/continuous-observability-for-debugging-rtos-based-firmware/
- Percepio: https://percepio.com/continuous-observability-in-embedded-systems/

---

### #9 — RTT Shell Fuzzer / Chaos Mode

**One-liner:** Send automatically generated (random, boundary-value, malformed) commands to the RTT shell, detect crashes/hangs via fault analysis, and report crash-inducing inputs.

**Problem:** Zephyr shell CLIs are manually tested. Nobody automatically fuzzes RTT shell surfaces on embedded targets.

**Solution:** `FuzzEngine` drives the existing RTT cmd queue with generated inputs. Crash detection: combines pattern matching + fault analysis auto-trigger + hang timeout. Auto-reset after each crash.

```bash
eabctl fuzz start --device NRF5340_XXAA_APP --duration 300s --json
# Output JSONL: each input tried, result (ok/crash/hang/timeout), crash context
```

**EAB building blocks:** New `FuzzEngine` (wordlist + boundary values + mutation), drives existing RTT bidirectional cmd queue, crash detection via existing pattern matching + fault auto-trigger, auto-reset via existing chip reset commands.

**Sources:**
- SHiFT semi-hosted fuzzing USENIX 2024: https://www.usenix.org/conference/usenixsecurity24/presentation/mera
- SHiFT GitHub: https://github.com/RiS3-Lab/SHiFT

---

### #10 — Live Memory Snapshot / Coredump-on-Demand

**One-liner:** At any time (no crash required), dump all RAM regions + registers to a GDB-compatible `.core` file for offline analysis — like `gcore` but for embedded targets.

**Problem:** "My firmware is misbehaving intermittently. I want to capture state when anomaly_watch fires." Today there is no way to do this without a crash.

**Solution:** `eabctl snapshot` reads all RAM regions (from ELF LOAD segments) + all registers via GDB, writes standard ELF core format. Trigger modes: manual, on anomaly, on HIL step, on crash before reset.

```bash
eabctl snapshot --output snapshot.core --device NRF5340_XXAA_APP
# Then on laptop:
arm-none-eabi-gdb firmware.elf snapshot.core
(gdb) bt
(gdb) info locals
```

```yaml
steps:
  - snapshot:
      output: results/pre_reset_state.core
      trigger: on_fault  # auto-snapshot before reset after crash
```

**EAB building blocks:** GDB memory read (already works), ELF LOAD segment parsing, ELF core file writer (new), trigger conditions, MCP tool `capture_snapshot()`.

**Sources:**
- Memfault Interrupt HardFault debugging: https://interrupt.memfault.com/blog/cortex-m-hardfault-debug

---

### #11 — PC Sampling Statistical Profiler

**One-liner:** Use DWT PC sampling to build a statistical flamegraph of CPU hotspots without instrumenting source code or halting the CPU.

**Problem:** `perf stat` doesn't exist for embedded. DWT profiling in EAB today requires specifying a function — there's no whole-system hotspot view.

**Solution:** Poll `DWT_PCSR` register at ~1 kHz (without halting), collect 10K+ samples over N seconds, map each to ELF symbol + source line via `addr2line`. Output: hotspot histogram + Perfetto-compatible flamegraph JSON.

```bash
eabctl profile --device NRF5340_XXAA_APP --duration 30s --output flamegraph.json
# Open flamegraph.json in https://www.speedscope.app or Perfetto
```

**EAB building blocks:** Extend `DWTEngine` for `DWT_PCSR` register, ELF symbol resolution via `addr2line`/`pyelftools`, flamegraph JSON output (speedscope/Perfetto compatible), ML benchmarking integration.

**Sources:**
- ARM ITM/DWT blog: https://developer.arm.com/community/arm-community-blogs/b/tools-software-ides-blog/posts/trace-cortex-m-software-with-the-instruction-trace-macrocell-itm

---

### #12 — Continuous RTOS Event Trace (Open TraceRecorder Alternative)

**One-liner:** Decode Zephyr `CONFIG_TRACING_BACKEND_RTT` CTF events (task switches, ISR entry/exit, semaphore/mutex ops) as JSONL and export as Perfetto timeline — a free CLI-driven alternative to Percepio TraceRecorder.

**Problem:** Percepio TraceRecorder requires a commercial license and GUI. Zephyr already has `CONFIG_TRACING` + RTT backend built-in but no open CLI decoder.

**Solution:** Extend `RTTDaemon` to decode Zephyr CTF trace events from RTT channel 1. Output JSONL event stream. Export to Perfetto JSON for browser-based RTOS timeline.

```bash
eabctl trace start --device NRF5340_XXAA_APP --format rtos-ctf
eabctl trace export -o rtos_trace.json --format perfetto
# Open in ui.perfetto.dev — see thread switches, ISR timing, lock contention
```

**EAB building blocks:** CTF decoder for Zephyr trace format, extend Perfetto exporter (reuse C2000 exporter), `trace_duration` HIL step with jitter assertion.

**Sources:**
- Percepio TraceRecorder: https://percepio.com/continuous-observability-in-embedded-systems/
- emBO++ 2024 Perfetto pipeline: https://salkinium.com/talks/embo24_perfetto.pdf

---

## Memfault Feature Parity

*Memfault is the leading commercial embedded observability platform. This section identifies their key capabilities and how EAB could implement open, local equivalents.*

### What Memfault Does

| Memfault Feature | Description |
|---|---|
| **Coredumps** | Capture fault state (registers + RAM) on device, upload to cloud, browse in web GDB |
| **Metrics** | Structured key-value telemetry from firmware, dashboarded per device / fleet |
| **Traces** | Custom events with timestamps, shown as timeline per device |
| **Heartbeats** | Periodic health reports (uptime, battery, error counts) — fleet dashboarding |
| **OTA** | Delta firmware updates with rollback, A/B slot support |
| **Reboot Reasons** | Track and classify reset causes (watchdog, assert, power failure, etc.) |
| **Logging** | Structured log capture from devices, searchable per device in cloud |
| **Alerts** | Fleet-level anomaly detection — alert when error rate rises across devices |
| **Symbol File Upload** | Upload ELF to cloud, GDB-quality backtrace decode without sharing source |
| **Device Fleet View** | Per-device and aggregate health dashboards |

### EAB Open Equivalents

| Memfault Feature | EAB Equivalent (existing or proposed) |
|---|---|
| **Coredumps** | #10 Live Memory Snapshot + #4 Zephyr Coredump — local `.core` files, offline GDB |
| **Metrics** | Anomaly Detection (F7) already extracts RTT metrics as JSONL |
| **Traces** | Perfetto export (C2000 + proposed ITM/RTOS trace) — local browser |
| **Heartbeats** | **M2** below — `eabctl heartbeat`, periodic snapshot to JSONL |
| **OTA** | Not in scope (EAB is development tooling, not production fleet) |
| **Reboot Reasons** | **M1** below — parse `NRF_POWER->RESETREAS` / `RCC->CSR` |
| **Logging** | RTT + serial daemons already capture all logs to JSONL |
| **Alerts** | Anomaly Detection (F7) EWMA alerting — single-device equivalent |
| **Symbol File** | ELF-based symbol resolution in DWT watchpoints + proposed PC profiler |
| **Fleet View** | Out of scope for single-device; **M4** below for multi-board test rigs |

### Specific Memfault Ideas Worth Implementing

**M1 — Reboot Reason Classifier**

Parse hardware reset cause registers (`NRF_POWER->RESETREAS` for nRF, `RCC->CSR` for STM32) and Zephyr's `sys_reboot_reason()`. Emit structured `reboot_reason` event on every boot. Track reboot history in `events.jsonl`.

```bash
eabctl reboot-reason --device NRF5340_XXAA_APP --json
# {"reason": "watchdog", "wdt_channel": 0, "uptime_before_reset_ms": 45230}
```

*Difficulty: S. Register addresses already in fault analysis; RTT pattern matching already works.*

---

**M2 — Structured Heartbeat Snapshots**

Every N seconds, capture a configurable set of metrics (heap free, error count, BLE connection state, uptime) and append to `heartbeat.jsonl`. Creates a time-series health record for a device under test.

```yaml
heartbeat:
  interval: 60
  metrics:
    - symbol: error_count
    - symbol: heap_free
    - rtt_pattern: 'notify_count=(\d+)'
    - rtt_pattern: 'conn_state=(\w+)'
```

*Difficulty: S-M. Combines GDB read-vars + RTT pattern extraction — both already in EAB.*

---

**M3 — ELF Symbol Export + Offline Backtrace Decode**

Strip the ELF to a symbol table only (no source code), store it alongside crash reports. Any backtrace (raw PC addresses) can be resolved to function+line offline, without sharing source. Enables sharing crash reports with teammates.

```bash
eabctl symbols export --elf firmware.elf --output symbols.json
eabctl backtrace decode --symbols symbols.json --pcs 0x12345,0x12389
```

*Difficulty: S. `pyelftools` + `addr2line` already used in EAB for DWT symbol resolution.*

---

**M4 — Multi-Device Health Dashboard (Local HTML)**

When running tests against multiple boards (already supported in BLE HIL), aggregate metrics across devices into a local HTML dashboard. Shows per-device health, test results, reboot history, and anomaly events.

*Difficulty: L. Could start as a simple static HTML generator from `events.jsonl` files.*

---

**M5 — Fault Fingerprinting**

Hash fault signatures (PC + CFSR + LR combination) to detect recurring crashes vs. new ones. Group crashes by fingerprint. Add a `known_faults.json` registry so CI auto-flags new crash types.

```bash
eabctl fault-analyze --device NRF5340_XXAA_APP --fingerprint --json
# {"fingerprint": "a3f7b2", "is_new": true, "similar_count": 0}
```

*Difficulty: S. Fault analysis already runs; hashing is 3 lines of Python.*

---

## Research Sources

- **emBO++ 2024 — Perfetto + ARM trace:** https://salkinium.com/talks/embo24_perfetto.pdf
- **Auterion embedded-debug-tools:** https://github.com/Auterion/embedded-debug-tools
- **YouTube — ARM Cortex-M Firmware with Perfetto:** https://www.youtube.com/watch?v=FIStxUz2ERY
- **Memfault Interrupt — Watchpoints:** https://interrupt.memfault.com/blog/cortex-m-watchpoints
- **Memfault Interrupt — HardFault debug:** https://interrupt.memfault.com/blog/cortex-m-hardfault-debug
- **Zephyr Core Dump docs:** https://docs.zephyrproject.org/latest/services/debugging/coredump.html
- **Nordic NCS coredump:** https://docs.nordicsemi.com/bundle/ncs-3.1.0/page/zephyr/services/debugging/coredump.html
- **Nordic PPK2:** https://www.nordicsemi.com/Products/Development-hardware/Power-Profiler-Kit-2
- **SHiFT fuzzing USENIX 2024:** https://www.usenix.org/conference/usenixsecurity24/presentation/mera
- **Golioth pytest hardware testing:** https://blog.golioth.io/automated-hardware-testing-using-pytest/
- **Continuous Observability for RTOS:** https://www.embedded.com/continuous-observability-for-debugging-rtos-based-firmware/
- **Percepio Continuous Observability:** https://percepio.com/continuous-observability-in-embedded-systems/
- **BLE connection quality metrics:** https://www.sciencedirect.com/article/pii/S2405959524000912
- **ARM ETM learning path:** https://learn.arm.com/learning-paths/embedded-and-microcontrollers/uv_debug/5_etm_trace/
- **ARM ITM blog:** https://developer.arm.com/community/arm-community-blogs/b/tools-software-ides-blog/posts/trace-cortex-m-software-with-the-instruction-trace-macrocell-itm
- **DIFFER (Trail of Bits):** https://blog.trailofbits.com/2024/01/31/introducing-differ-a-new-tool-for-testing-and-validating-transformed-programs/
