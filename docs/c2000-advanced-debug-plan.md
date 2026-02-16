# C2000 Advanced Debug — Implementation Plan

## Goal

Bring fault analysis, profiling, variable streaming, and trace to C2000 — matching what EAB already does for ARM Cortex-M boards. Design the architecture so adding a new chip family means dropping in a register map JSON, not rewriting code.

## Architecture: Register-Map-Driven Debug

The core insight from MCUViewer and C2000-IDEA: separate **what to read** (register definitions) from **how to read** (probe transport). Everything keys off JSON register maps.

```
┌─────────────────────────────────────────────────┐
│                   eabctl CLI                     │
│  fault-analyze  profile  stream-vars  trace      │
└──────────┬──────────────────────────┬────────────┘
           │                          │
    ┌──────▼──────┐          ┌────────▼────────┐
    │  Analyzers  │          │  Register Maps  │
    │  (generic)  │◄─────────│  (per-chip JSON) │
    │             │          │                  │
    │ fault.py    │          │ f28003x.json     │
    │ erad.py     │          │ stm32f4.json     │
    │ stream.py   │          │ nrf5340.json     │
    └──────┬──────┘          └─────────────────┘
           │
    ┌──────▼──────┐
    │  Transport  │
    │  (per-probe)│
    │             │
    │ xds110.py   │  → DSLite memory read/write
    │ openocd.py  │  → GDB/OpenOCD memory read
    │ jlink.py    │  → pylink memory read
    └─────────────┘
```

## Register Map Format

One JSON file per chip family. Sourced from TI's C2000-IDEA `register_data/` (F28003x) and ARM CMSIS SVD files (Cortex-M).

```json
{
  "chip": "f28003x",
  "family": "c2000",
  "cpu_freq_hz": 120000000,

  "fault_registers": {
    "NMIFLG": {
      "address": "0x7060",
      "size": 2,
      "description": "NMI Flag Register",
      "bits": {
        "NMIINT":    { "bit": 0, "description": "NMI Interrupt Flag" },
        "CLOCKFAIL": { "bit": 1, "description": "Clock Fail Detect Flag" },
        "RAMUNCERR": { "bit": 2, "description": "RAM Uncorrectable Error" },
        "FLUNCERR":  { "bit": 3, "description": "Flash Uncorrectable Error" },
        "PIEVECTERR":{ "bit": 4, "description": "PIE Vector Fetch Error" },
        "SYSDBGNMI": { "bit": 8, "description": "System Debug NMI" },
        "RLNMI":     { "bit": 9, "description": "Reconfigurable Logic NMI" },
        "SDFM1ERR":  { "bit": 13, "description": "SDFM1 Error" },
        "SDFM2ERR":  { "bit": 14, "description": "SDFM2 Error" }
      }
    },
    "NMISHDFLG": {
      "address": "0x7064",
      "size": 2,
      "description": "NMI Shadow Flag Register (latched)"
    },
    "PIECTRL": {
      "address": "0x0CE0",
      "size": 2,
      "description": "PIE Control Register",
      "bits": {
        "ENPIE":    { "bit": 0, "description": "PIE Enable" },
        "PIEVECT":  { "bits": [1,15], "description": "PIE Vector Address" }
      }
    },
    "RESC": {
      "address": "0x5D00C",
      "size": 4,
      "description": "Reset Cause Register",
      "bits": {
        "POR":       { "bit": 0, "description": "Power-On Reset" },
        "XRSN":      { "bit": 1, "description": "External Reset" },
        "WDRSN":     { "bit": 2, "description": "Watchdog Reset" },
        "NMIWDRSN":  { "bit": 3, "description": "NMI Watchdog Reset" },
        "SCCRESETN": { "bit": 8, "description": "SCC Reset" }
      }
    }
  },

  "erad": {
    "supported": true,
    "ebc_count": 8,
    "sec_count": 4,
    "base_address": "0x0005E800",
    "registers": {
      "GLBL_EVENT_STAT":    { "offset": "0x00", "size": 2 },
      "GLBL_HALT_STAT":     { "offset": "0x02", "size": 2 },
      "GLBL_ENABLE":        { "offset": "0x04", "size": 2 },
      "GLBL_CTM_RESET":     { "offset": "0x06", "size": 2 },
      "GLBL_NMI_CTL":       { "offset": "0x08", "size": 2 },
      "EBC1_CNTL":          { "offset": "0x20", "size": 2 },
      "EBC1_STATUS":        { "offset": "0x22", "size": 2 },
      "EBC1_STATUSCLEAR":   { "offset": "0x24", "size": 2 },
      "EBC1_REFL":          { "offset": "0x28", "size": 4, "description": "Reference address low" },
      "EBC1_REFH":          { "offset": "0x2A", "size": 4, "description": "Reference address high (mask)" },
      "SEC1_CNTL":          { "offset": "0x80", "size": 2 },
      "SEC1_STATUS":        { "offset": "0x82", "size": 2 },
      "SEC1_COUNT":         { "offset": "0x88", "size": 4, "description": "Counter value" },
      "SEC1_MAX_COUNT":     { "offset": "0x8A", "size": 4, "description": "Max count (worst-case)" },
      "SEC1_REF":           { "offset": "0x90", "size": 4, "description": "Reference value" },
      "SEC1_INPUT_SEL1":    { "offset": "0x94", "size": 2, "description": "Start event select" },
      "SEC1_INPUT_SEL2":    { "offset": "0x96", "size": 2, "description": "Stop event select" }
    },
    "ebc_cntl_bits": {
      "BUS_SEL":   { "bits": [0,3], "values": { "0": "DWAB", "1": "DRAB", "2": "DWDB", "3": "DRDB", "4": "VPC", "5": "PAB" }},
      "HALT":      { "bit": 4 },
      "INTERRUPT": { "bit": 5 },
      "NMI":       { "bit": 6 },
      "ENABLE":    { "bit": 15 }
    },
    "sec_cntl_bits": {
      "MODE":         { "bits": [0,1], "values": { "0": "continuous", "1": "timer", "2": "start_stop" }},
      "EDGE_LEVEL":   { "bit": 2, "values": { "0": "edge", "1": "level" }},
      "START_STOP_CUMULATIVE": { "bit": 3 },
      "RST_ON_MATCH": { "bit": 4 },
      "ENABLE":       { "bit": 15 }
    }
  },

  "datalog": {
    "description": "DLOG_4CH circular buffer addresses read from MAP file at runtime",
    "requires_map_file": true,
    "typical_symbols": ["dBuff1", "dBuff2", "dBuff3", "dBuff4", "dLog1"],
    "buffer_size_symbol": "DBUFF_SIZE"
  },

  "watchdog": {
    "WDCR":  { "address": "0x7029", "size": 2, "description": "Watchdog Control Register" },
    "WDWCR": { "address": "0x7026", "size": 2, "description": "Watchdog Window Control" },
    "WDCNTR":{ "address": "0x7023", "size": 2, "description": "Watchdog Counter" }
  },

  "clock": {
    "CLKSRCCTL1": { "address": "0x5D208", "size": 4, "description": "Clock Source Control" },
    "SYSPLLCTL1": { "address": "0x5D20E", "size": 4, "description": "PLL Control" },
    "SYSCLKDIVSEL": { "address": "0x5D222", "size": 2, "description": "Clock Divider Select" }
  }
}
```

For ARM Cortex-M, the same format covers SCB, CFSR, DWT — just different addresses and bit fields. One JSON per chip, loaded by name.

## Phases

### Phase 1: Register Map Infrastructure

**What**: JSON register map loader + generic memory read/decode engine.

**Files**:
- `eab/register_maps/` — new directory
- `eab/register_maps/__init__.py` — `load_register_map(chip: str) -> RegisterMap`
- `eab/register_maps/f28003x.json` — C2000 F28003x register definitions
- `eab/register_maps/base.py` — `RegisterMap`, `Register`, `BitField` dataclasses
- `eab/register_maps/decoder.py` — generic `decode_register(raw_value, register_def) -> dict[str, Any]`

**Source the data from**:
- TI C2000-IDEA repo `register_data/` for F28003x register addresses
- F28003x TRM (spruiw9) for bit field definitions
- Existing EAB fault analyzer for Cortex-M register format (port to same JSON schema)

**Key design**: `decoder.py` takes raw bytes + register definition → returns decoded dict with bit names and values. Zero chip-specific code.

### Phase 2: Fault Analysis for C2000

**What**: `eabctl fault-analyze --chip c2000` reads NMI, PIE, reset-cause, watchdog registers and decodes them.

**Equivalent to**: ARM Cortex-M `eabctl fault-analyze` which reads SCB/CFSR/HFSR/MMFAR/BFAR.

**How it works**:
1. Load `f28003x.json` register map
2. Read each fault register address via `XDS110Probe.memory_read()`
3. Decode bit fields via `decoder.py`
4. Report which faults are active (NMI source, reset cause, PIE errors)
5. Output JSON for machine parsing

**Files**:
- `eab/analyzers/fault.py` — generic fault analyzer (reads `fault_registers` section from any register map)
- `eab/analyzers/__init__.py` — `analyze_faults(probe, register_map) -> FaultReport`
- Update `eab/cli/` to wire `fault-analyze` for C2000

**Registers to read** (F28003x):

| Register | Address | What It Tells You |
|----------|---------|-------------------|
| NMIFLG | 0x7060 | Active NMI source (clock fail, RAM error, flash error, PIE error) |
| NMISHDFLG | 0x7064 | Latched NMI flags (survives clear) |
| PIECTRL | 0x0CE0 | PIE enable + vector address of last interrupt |
| PIEIFR1-12 | 0x0CE2+ | Pending interrupts per group |
| RESC | 0x5D00C | Reset cause (POR, external, watchdog, NMI-watchdog) |
| WDCR | 0x7029 | Watchdog config (enabled? prescale?) |
| WDCNTR | 0x7023 | Watchdog counter value |

### Phase 3: ERAD Profiling (C2000 DWT Equivalent)

**What**: `eabctl profile-function --chip c2000 --function motor_isr --map firmware.map`

**Equivalent to**: ARM `eabctl profile-function` which uses DWT CYCCNT + comparators.

**How it works**:
1. Parse MAP file → get function start address
2. Configure ERAD EBC1 to match function entry address (VPC bus)
3. Configure ERAD EBC2 to match function exit address (VPC bus)
4. Configure ERAD SEC1 in start-stop mode: start=EBC1 event, stop=EBC2 event, count=CPU cycles
5. Let firmware run for N iterations
6. Read SEC1_COUNT (last measurement) and SEC1_MAX_COUNT (worst case)
7. Convert cycles → time using `cpu_freq_hz` from register map

All ERAD configuration is done via DSLite memory writes to ERAD registers. No CCS needed.

**Files**:
- `eab/analyzers/erad.py` — ERAD configuration + readback
  - `configure_function_profile(probe, register_map, start_addr, end_addr)`
  - `read_profile_results(probe, register_map) -> ProfileResult`
  - `configure_watchpoint(probe, register_map, address, bus="DWAB")`
  - `configure_event_counter(probe, register_map, event_source)`
- `eab/analyzers/profiler.py` — generic profiler interface
  - For C2000: delegates to `erad.py`
  - For ARM: delegates to existing DWT code
  - Common output format: `ProfileResult(cycles, time_us, max_cycles, max_time_us, iterations)`

**ERAD configuration sequence** (via DSLite memory writes):
```
1. Write GLBL_ENABLE = 0          # Disable ERAD
2. Write GLBL_CTM_RESET = 0xF     # Reset all counters
3. Write EBC1_REFL = start_addr   # Function entry address
4. Write EBC1_REFH = 0xFFFFFFFF   # Exact match (no mask)
5. Write EBC1_CNTL = VPC | ENABLE # Monitor program counter
6. Write EBC2_REFL = end_addr     # Function exit address
7. Write EBC2_CNTL = VPC | ENABLE
8. Write SEC1_INPUT_SEL1 = EBC1   # Start counting on EBC1 match
9. Write SEC1_INPUT_SEL2 = EBC2   # Stop counting on EBC2 match
10. Write SEC1_CNTL = START_STOP | LEVEL | ENABLE
11. Write GLBL_ENABLE = 0xF       # Enable ERAD
12. ... wait ...
13. Read SEC1_COUNT               # CPU cycles for last call
14. Read SEC1_MAX_COUNT           # Worst-case cycles
```

### Phase 4: Variable Streaming (MCUViewer-style)

**What**: `eabctl stream-vars --chip c2000 --map firmware.map --var motorVars_M1.speedRef --var motorVars_M1.speedFbk --interval 100`

**Equivalent to**: MCUViewer's real-time variable viewer, but headless (JSON output for piping to plots/dashboards).

**How it works**:
1. Parse MAP file → get symbol addresses and sizes
2. Poll: every `interval` ms, read each variable's memory region via DSLite
3. Decode raw bytes → typed values (int16, int32, float32, IQ format)
4. Output JSONL stream to stdout (or file)

**Transport optimization**: DSLite spawns a subprocess per memory read (~50ms overhead). For polling, we have two strategies:
- **Strategy A (DSLite batch)**: Read a contiguous memory region covering all variables in one call, slice locally. Works when variables are co-located (e.g., all in `motorVars_M1` struct).
- **Strategy B (DSS persistent session)**: Use DSS (`dss.sh`) to start a persistent debug session, then script repeated reads without subprocess overhead. Better for high-frequency polling.

**Files**:
- `eab/analyzers/var_stream.py` — variable streaming engine
  - `VarStream(probe, map_symbols, variables, interval_ms, output)`
  - `start()` → background polling loop
  - `stop()` → cleanup
  - Outputs JSONL: `{"ts": 1234567890.123, "motorVars_M1.speedRef": 1500.0, "motorVars_M1.speedFbk": 1498.2}`
- `eab/analyzers/type_decode.py` — raw bytes → typed values
  - C2000 uses 16-bit word-addressed memory (not byte-addressed!)
  - Support: `int16`, `uint16`, `int32`, `uint32`, `float32`, `float64`, `IQ24`, `IQ20`, `IQ15` (TI fixed-point)
  - Type info comes from MAP file section sizes or explicit user config

**C2000-specific gotcha**: C2000 is **16-bit word-addressed**. Address 0xC002 means word 0xC002 (2 bytes), not byte 0xC002. DSLite `memory` command returns bytes, but addresses are word addresses. The decoder must account for this.

### Phase 5: DLOG Buffer Capture

**What**: `eabctl dlog-capture --chip c2000 --map firmware.map --buffers dBuff1,dBuff2 --trigger`

**Equivalent to**: CCS graph window showing DLOG_4CH circular buffer data.

**How it works**:
1. Parse MAP file → find `dLog1` struct address, `dBuff1-4` buffer addresses, `DBUFF_SIZE`
2. Read `dLog1.status` to check if capture is complete (trigger fired + buffer full)
3. Read entire buffer in one DSLite `memory` call (contiguous, typically 200-400 words)
4. Decode float32 array
5. Output CSV or JSON for plotting

This is the high-bandwidth equivalent of variable streaming — instead of polling individual variables, the firmware fills a buffer at ISR rate and we read the whole buffer after capture completes.

**Files**:
- `eab/analyzers/dlog.py` — DLOG buffer reader
  - `DLOGCapture(probe, map_symbols, buffer_names)`
  - `wait_and_read() -> dict[str, list[float]]`
  - `trigger()` — write to dLog1 trigger variable to start capture

### Phase 6: DSS Integration (Power Mode)

**What**: Persistent debug session via TI's DSS for high-frequency operations.

**Why**: DSLite spawns a new process per command (~50ms). DSS opens a persistent JTAG session and can do repeated reads at ~1-5ms each. This is the difference between 20 Hz and 200+ Hz polling.

**How**:
1. Ship a `c2000_bridge.js` DSS script that:
   - Opens debug session with CCXML
   - Accepts commands on stdin (JSON protocol)
   - Returns results on stdout
   - Commands: `read <addr> <size>`, `write <addr> <data>`, `halt`, `resume`, `reset`
2. EAB launches `dss.sh c2000_bridge.js` as a subprocess
3. Communicate via stdin/stdout JSON protocol (like an MCP server)

**Files**:
- `eab/transports/dss_bridge.js` — DSS JavaScript bridge script
- `eab/transports/dss.py` — Python wrapper for DSS subprocess
  - `DSSTransport(ccxml, dss_path) -> Transport`
  - `read(addr, size) -> bytes`
  - `write(addr, data) -> bool`
  - Implements same interface as `XDS110Probe.memory_read/write`
- `eab/transports/__init__.py` — transport factory

**This is optional but high-value**: enables real-time variable monitoring at rates fast enough to observe motor control loops (10kHz control → need >100Hz sampling to see trends).

### Phase 7: Trace Export (Perfetto Integration)

**What**: Convert ERAD profiling data + DLOG captures + serial logs → Perfetto JSON.

**Equivalent to**: ARM `eabctl trace export` which converts RTT binary to Perfetto format.

**How**:
- ERAD profiling results → Perfetto duration events (function execution spans)
- DLOG buffer data → Perfetto counter tracks (variable values over time)
- Serial output → Perfetto instant events (log lines with timestamps)
- All combined into one Perfetto JSON file, viewable at ui.perfetto.dev

**Files**:
- Update `eab/trace/perfetto.py` to accept ERAD + DLOG data sources
- No new file needed — extend existing trace infrastructure

### Phase 8: CLI Wiring + Tests

**New commands**:
```bash
# Fault analysis (generic, works for any chip with fault_registers in JSON)
eabctl fault-analyze --chip c2000 --json

# ERAD profiling
eabctl profile-function --chip c2000 --function motor_isr --map firmware.map --json
eabctl profile-region --chip c2000 --start 0x8000 --end 0x8100 --map firmware.map --json
eabctl erad-status --chip c2000 --json

# Variable streaming
eabctl stream-vars --chip c2000 --map firmware.map --var motorVars_M1 --interval 100 --json

# DLOG capture
eabctl dlog-capture --chip c2000 --map firmware.map --json

# Register dump (generic utility)
eabctl reg-read --chip c2000 --register NMIFLG --json
eabctl reg-read --chip c2000 --group fault_registers --json
```

**Tests**:
- `tests/test_register_maps.py` — load JSON, decode registers, verify bit fields
- `tests/test_fault_analyzer.py` — mock memory reads, verify fault decode for C2000 + Cortex-M
- `tests/test_erad.py` — mock memory writes, verify ERAD config sequence
- `tests/test_var_stream.py` — mock polling, verify JSONL output
- `tests/test_type_decode.py` — verify IQ format, float32, word-address handling

## Execution Order

| Phase | Depends On | Effort | Value |
|-------|-----------|--------|-------|
| 1. Register map infra | Nothing | Medium | Foundation for everything |
| 2. Fault analysis | Phase 1 | Small | Immediate debugging value |
| 3. ERAD profiling | Phase 1 | Medium | Performance measurement |
| 4. Variable streaming | Existing MAP parser | Medium | Real-time monitoring |
| 5. DLOG capture | Phase 4 | Small | High-bandwidth data |
| 6. DSS bridge | Nothing (parallel) | Medium | 10x faster polling |
| 7. Trace/Perfetto | Phases 3-5 | Small | Visualization |
| 8. CLI + tests | All above | Small | Integration |

**Start with**: Phase 1 → Phase 2 → Phase 4 (most immediate value)
**Parallel track**: Phase 6 (DSS bridge) can start anytime

## Adding a New Chip Family

To add support for e.g. STM32H7:

1. Create `eab/register_maps/stm32h7.json` with fault registers (SCB, CFSR, HFSR, DWT)
2. That's it for fault analysis — `eab/analyzers/fault.py` reads the JSON and works

To add profiling:
1. Add `dwt` section to the JSON (DWT register addresses + bit fields)
2. Write a `dwt.py` analyzer (or port existing DWT code to use register map)

To add variable streaming:
1. Already generic — just needs ELF/DWARF parser instead of MAP parser
2. Transport is already abstracted (OpenOCD GDB, J-Link pylink, etc.)

## Data Sources for Register Maps

| Chip | Source | Format | Path |
|------|--------|--------|------|
| F28003x | TI C2000-IDEA `register_data/` | JSON | GitHub: TexasInstruments/C2000-IDEA |
| F28003x | F28003x TRM (SPRSP69) | PDF → extract | ti.com |
| STM32 | CMSIS SVD files | XML → convert | github.com/cmsis-svd |
| nRF5340 | Nordic SVD files | XML → convert | github.com/NordicSemiconductor |
| ESP32 | Espressif SVD files | XML → convert | github.com/espressif |

Long-term: write a `svd2regmap.py` converter that turns CMSIS SVD XML into our JSON format. Covers hundreds of ARM chips automatically.
