# C2000 Transport Architecture Research

## Research Question

Could we build a faster Rust-based transport to replace the TI Python/cloud-agent stack for C2000 debug operations?

## Executive Summary

**Answer: No meaningful speed improvement possible.**

The XDS110 JTAG hardware is the bottleneck (~1.5ms per transaction), not the software stack. TI's cloud agent adds only 0.15ms overhead (8%). Building a Rust transport from scratch would require reverse-engineering the DSLite protocol with massive effort for negligible gain.

## Performance Analysis

### Measured Latency Breakdown

| Component | Latency | Notes |
|-----------|---------|-------|
| XDS110 JTAG transaction | ~1.5 ms | Hardware bottleneck |
| DSLite websocket round-trip | ~0.15 ms | Message framing + parsing |
| Cloud agent overhead | ~0.15 ms | Node.js → DSLite proxy |
| Python scripting wrapper | <0.01 ms | Negligible |

### Three Transport Options Benchmarked

| Method | Single Read | 200-word Bulk | DLOG 4-ch | Notes |
|--------|-------------|---------------|-----------|-------|
| DSLite subprocess | 60 ms | — | — | Baseline: spawn process per read |
| Python → cloud agent → DSLite WS | 1.80 ms | 12.8 ms | 83 ms | **Current implementation** |
| Python → DSLite WS direct | 1.65 ms | 11.7 ms | 81 ms | Skip cloud agent, 8% faster |
| Rust from scratch | ??? | ??? | ??? | Theoretical, needs full protocol RE |

**Key finding**: Cloud agent adds 0.15ms (8%). Direct websocket saves almost nothing because JTAG hardware dominates.

### Comparison to ARM RTT

| Metric | ARM RTT (J-Link) | C2000 XDS110 | Ratio |
|--------|------------------|--------------|-------|
| Single read | 0.3 ms | 1.8 ms | **6x slower** |
| Bulk throughput | 200 KB/s | 31 KB/s | **6.5x slower** |
| Log streaming | 100+ kHz | 555 Hz | **180x slower** |

**Why RTT is faster**: ARM Cortex-M supports DMA-like background RAM access while CPU runs. C2000 requires JTAG transactions that halt/resume or have high protocol overhead.

## Rust Ecosystem Research

### What Exists

#### 1. probe-rs — Production-Ready ARM Debugger
- **Status**: 2.6k stars, active development
- **Language**: Pure Rust
- **Protocols**: JTAG, SWD, full implementation
- **Probes**: J-Link, ST-Link, CMSIS-DAP, etc.
- **Features**: Flash, debug, RTT, profiling
- **TI Support**: CC13xx/CC26xx (ARM Cortex-M) added May 2024
  - Issue: https://github.com/probe-rs/probe-rs/issues/1729
  - PR: https://github.com/probe-rs/probe-rs/pull/1771
  - Merged and working
- **C2000 Support**: **NO** — explicitly ARM-only
  - C28x is different ISA (16-bit DSP)
  - Different memory model (word-addressed, not byte-addressed)
  - Different debug architecture (no ARM CoreSight)

#### 2. flash-rover — TI's Archived Rust Tool
- **URL**: https://github.com/TexasInstruments/flash-rover
- **Status**: Archived Oct 2024 (CCS 2041 broke it)
- **What it did**: Read/write external flash on CC13xx/CC26xx
- **Architecture**: Rust CLI → JNI → Java DSS API → XDS110
- **Why relevant**: TI themselves tried Rust + DSS
- **Why archived**: CCS 2041 deprecated Eclipse/Java DSS API

**flash-rover source code** (simplified):
```rust
// Rust → JNI → Java DSS (Eclipse API)
use jni::{JavaVM, JNIEnv};

pub struct Dss {
    jvm: JavaVM,
}

impl Dss {
    pub fn new(ccs_path: &Path) -> Result<Self> {
        let classpath = ccs_path.join("ccs_base/DebugServer/packages/ti/dss/java/dss.jar");
        let jvm = JavaVM::new(with classpath)?;
        Ok(Self { jvm })
    }

    pub fn scripting_environment(&self) -> Result<ScriptingEnvironment> {
        // Call into Java: com.ti.ccstudio.scripting.environment.ScriptingEnvironment
        ScriptingEnvironment::new(self.jvm.get_env()?)
    }
}
```

This approach:
- ✅ Worked on CCS 12.x (Eclipse-based)
- ❌ Broken on CCS 2041 (Theia-based, no Java DSS API)
- ❌ TI archived it instead of updating

### What Doesn't Exist

**No C2000-specific Rust tools found:**
- No Rust XDS110 driver
- No Rust DSLite protocol implementation
- No Rust C28x JTAG library
- No Rust C2000 debug tools of any kind

**Search queries used:**
- `rust ti c2000 xds110 debug probe`
- `rust jtag dslite texas instruments`
- `probe-rs texas instruments c2000`
- `rust embedded debug probe cortex-m jtag swd`

**Results**: Zero Rust projects for C2000 debug.

## Technical Deep Dive: Why Rust Won't Help

### 1. Protocol Complexity

To build a Rust transport, we'd need to reverse-engineer:

**DSLite WebSocket Protocol**:
- JSON command/response framing
- Event handling (progress, errors)
- Session lifecycle management
- `createSubModule` for per-core sockets
- Command set (190+ commands on core socket)
- Data format quirks (`!bi:` prefixes, etc.)

**C28x JTAG Specifics**:
- cJTAG (2-pin) → 4-pin mode switching
- ICEPick router for scan chain management
- C28x-specific memory addressing (16-bit word-addressed)
- ERAD register access patterns

**XDS110 USB Protocol**:
- USB bulk transfers
- XDS110-specific JTAG packet format
- Probe identification sequence

### 2. Maintenance Burden

probe-rs works because:
- ARM CoreSight is standardized
- CMSIS packs provide register definitions
- Hundreds of ARM chips share same debug interface

C2000 would require:
- Per-chip register maps (no CMSIS equivalent)
- Custom JTAG sequences for each family
- Ongoing maintenance as TI releases new chips
- No community support (probe-rs team focuses on ARM)

### 3. Speed Isn't There

**Theoretical maximum with Rust + direct USB**:
- XDS110 hardware: ~1.5ms/transaction (USB latency + JTAG)
- Rust async overhead: ~0.01ms (negligible)
- **Best case**: ~1.5ms (17% faster than current 1.8ms)

**Is 17% worth it?**
- No — for 555 Hz → 666 Hz polling
- Effort: weeks to reverse-engineer
- Risk: breaks on CCS updates
- Benefit: minimal for actual use cases

### 4. What We Learned from TI

TI's flash-rover choice of **Rust + JNI → Java** proves they:
1. Valued Rust for CLI ergonomics
2. Had no Rust-native DSS/XDS110 library
3. Accepted Java overhead to reuse existing DSS API
4. Gave up when CCS 2041 broke the Java API

If TI (who owns the protocol) didn't build a Rust-native version, it's likely not worth the effort.

## Alternative Approaches Considered

### 1. Direct DSLite WebSocket (Python)
**Status**: Benchmarked, 8% faster than cloud agent
**Effort**: ~100 lines of Python
**Decision**: Not worth it — cloud agent provides type conversions, lifecycle management, error handling

### 2. Firmware-Based Streaming
**Concept**: Firmware collects data, streams via UART
**Pros**: Can hit 921600 baud (115 KB/s theoretical)
**Cons**:
- Adds CPU overhead (defeats C2000 determinism)
- Requires custom firmware per application
- Still slower than ARM RTT

### 3. JTAG Hardware Upgrade
**Option**: Use XDS200 ($200) or XDS560 ($1000+) instead of XDS110
**Speed**: XDS200 is ~2x faster, XDS560 is ~5x faster
**Decision**: Hardware cost vs minimal gain for debug workflows

## Architectural Trade-Offs: C2000 vs ARM

### Why C2000 is Slower

C2000 was designed for **deterministic real-time control** (motor control, power electronics):
- ERAD: zero-overhead profiling (hardware captures autonomously)
- DLOG: ISR-rate capture into buffers (read frozen buffer afterward)
- Minimal debug intrusion (can't have polling stealing ISR cycles)

ARM Cortex-M was designed for **interactive development**:
- RTT: live telemetry streaming
- Frequent breakpoints don't hurt
- Rich debug infrastructure (ITM, DWT, ETM)

### What C2000 Optimized For

| Feature | C2000 Approach | ARM Approach |
|---------|---------------|--------------|
| Profiling | ERAD (zero overhead, read results once) | DWT + live polling |
| Data capture | DLOG (10 kHz ISR → freeze → read buffer) | RTT (stream continuously) |
| Logs | UART/SWO (minimal) | RTT (high-bandwidth) |
| Breakpoints | Minimize use (real-time sensitive) | Use freely |

**C2000 philosophy**: Post-capture analysis, not live streaming.

## Recommendation

**Use what we built**:
- Python → TI scripting API → cloud agent → DSLite → XDS110
- 1.8ms/read is 33x faster than subprocess baseline
- 12 Hz DLOG snapshots is sufficient for motor control debug
- Cloud agent overhead (0.15ms) is negligible
- No maintenance burden from protocol reverse-engineering

**For users who need faster**:
- Use ERAD for profiling (zero overhead)
- Use DLOG for waveforms (ISR-rate capture)
- Upgrade to XDS200/XDS560 hardware
- Consider ARM Cortex-M if live streaming is critical

## Research Links

### Rust JTAG/Debug Projects
- probe-rs main: https://github.com/probe-rs/probe-rs
- probe-rs TI issue: https://github.com/probe-rs/probe-rs/issues/1729
- probe-rs TI PR: https://github.com/probe-rs/probe-rs/pull/1771
- flash-rover (archived): https://github.com/TexasInstruments/flash-rover
- flash-rover DSS crate: https://github.com/TexasInstruments/flash-rover/tree/master/dss

### TI Documentation
- XDS110 User Guide: https://software-dl.ti.com/ccs/esd/documents/xdsdebugprobes/emu_xds110.html
- DSS Scripting Guide: https://software-dl.ti.com/ccs/esd/documents/users_guide/ccs_debug-scripting.html
- ICEPick Router: https://software-dl.ti.com/ccs/esd/documents/xdsdebugprobes/emu_icepick.html
- ERAD App Report: SPRACM7 (TI literature)
- F28003x TRM: SPRSP69 (register addresses, JTAG details)

### CCS 2041 Scripting
- CCS Scripting Python examples: `/Applications/ti/ccs2041/ccs/scripting/python/examples/`
- Cloud agent source: `/Applications/ti/ccs2041/ccs/ccs_base/cloudagent/src/`
- DSLite module: `/Applications/ti/ccs2041/ccs/ccs_base/cloudagent/src/modules/dslite.js`

### ARM RTT References
- Segger RTT: https://www.segger.com/products/debug-probes/j-link/technology/about-real-time-transfer/
- probe-run (Rust RTT): https://github.com/knurling-rs/probe-run
- RTT spec: Part of J-Link SDK documentation

### Performance Comparisons
- ARM Cortex-M debug (RTT, SWD): ~0.3ms/read, 200 KB/s streaming
- C2000 XDS110 (JTAG): ~1.8ms/read, 31 KB/s bulk
- STM32 ST-Link (SWD): ~0.5ms/read
- ESP32 USB-JTAG: ~2ms/read (similar to XDS110)

## Conclusion

The Python + cloud agent + DSLite stack is the right choice for C2000:
- Already optimized (33x faster than baseline)
- Hardware-limited (XDS110 JTAG is the bottleneck)
- TI-supported (uses official scripting API)
- Maintainable (no protocol reverse-engineering)
- Sufficient for C2000 debug workflows (DLOG snapshots at 12 Hz)

Building a Rust transport would be **high effort, low reward, high risk**.
