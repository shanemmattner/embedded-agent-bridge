# EAB Observability Integration Plan

**Goal:** Add best-in-class RTOS observability to EAB by integrating proven open-source tools, keeping the library lean and focused.

## Research Summary

We evaluated 3 open-source embedded observability projects:

| Project | Stars | Last Update | Key Features | Output Format |
|---------|-------|-------------|--------------|---------------|
| **RTEdbg** | 116 | Jan 2026 | Binary logging, minimal instrumentation, core dumps | Custom binary + Python decoder |
| **Tonbandgerät** | 52 | Dec 2025 | FreeRTOS tracing, bare-metal support, Rust CLI | Binary → Perfetto JSON |
| **TaskMonitor** | 1 | 2022 | Simple FreeRTOS monitor | Custom (stale) |

**Winner: Tonbandgerät** - actively maintained, outputs to Perfetto (industry standard), FreeRTOS hooks already written.

## Architecture: Thin Integration Layer

**EAB's role:** Transport and capture. **Don't reimplement tracing logic.**

```
┌─────────────────────────────────────────────────┐
│ Firmware (user's code)                          │
│  ├─ Tonbandgerät C lib (FreeRTOS hooks)        │
│  └─ RTT buffer (binary trace events)           │
└─────────────────┬───────────────────────────────┘
                  │ RTT (J-Link/CMSIS-DAP)
┌─────────────────▼───────────────────────────────┐
│ EAB (host-side capture)                         │
│  ├─ rtt_binary.py (capture .rttbin)            │
│  └─ CLI: eabctl trace {start,stop,export}      │
└─────────────────┬───────────────────────────────┘
                  │ .rttbin or raw binary
┌─────────────────▼───────────────────────────────┐
│ Decoder (external tools - ship as dependencies) │
│  ├─ tband CLI (Tonbandgerät Rust tool)         │
│  ├─ RTEdbg decoder (Python)                     │
│  └─ Custom EAB decoder (future, if needed)      │
└─────────────────┬───────────────────────────────┘
                  │ Perfetto JSON / CSV
┌─────────────────▼───────────────────────────────┐
│ Visualization                                   │
│  ├─ Perfetto (chrome://tracing)                │
│  ├─ Custom web UI (future)                      │
│  └─ Terminal UI (future)                        │
└─────────────────────────────────────────────────┘
```

**Key principle:** EAB captures binary data. External decoders (tband, RTEdbg) handle decoding. We don't bloat EAB with visualization or RTOS-specific parsing.

## Phase 1: Minimal Viable Integration (2-4 hours)

### 1.1 Add Tonbandgerät as Optional Dependency

```bash
pip install embedded-agent-bridge[tracing]
# installs: tonbandgeraet-cli (Rust binary via PyPI wrapper)
```

### 1.2 CLI Commands

```bash
# Start capturing trace (uses existing rtt_binary.py)
eabctl trace start --output trace.rttbin

# Stop and convert to Perfetto
eabctl trace stop
eabctl trace export trace.rttbin --format perfetto --output trace.json

# View in browser
eabctl trace view trace.json
# (opens chrome://tracing with the file loaded)
```

### 1.3 Implementation

**New file:** `eab/cli/trace_cmds.py` (~200 lines)

```python
def cmd_trace_start(args):
    """Start RTT trace capture to binary file."""
    # Use existing rtt_binary.py infrastructure
    from eab.rtt_binary import RTTBinaryCapture
    capture = RTTBinaryCapture(output=args.output, channels=[0])
    capture.start()
    # Save PID to /tmp/eab-trace.pid for stop command

def cmd_trace_stop(args):
    """Stop active trace capture."""
    # Send SIGTERM to capture process

def cmd_trace_export(args):
    """Convert .rttbin to Perfetto JSON using tband CLI."""
    subprocess.run([
        "tband", "convert",
        "--input", args.input,
        "--output", args.output,
        "--format", "perfetto"
    ])

def cmd_trace_view(args):
    """Open Perfetto in browser with trace loaded."""
    subprocess.run(["open", "chrome://tracing"])
    # Or serve local Perfetto UI
```

**No new core modules.** Just CLI glue around:
- Existing `rtt_binary.py` (already captures binary data)
- External `tband` CLI (handles Tonbandgerät decoding)
- Browser (Perfetto UI)

### 1.4 Firmware-Side Setup (User Responsibility)

EAB provides **documentation and examples**, not firmware libraries:

**Example:** `examples/freertos-tracing/`
- Includes Tonbandgerät C library as submodule
- Sample `FreeRTOSConfig.h` with hooks enabled
- README: "How to add tracing to your FreeRTOS project"

**We don't ship FreeRTOS or Tonbandgerät.** Users add it to their firmware. EAB just captures the output.

## Phase 2: Enhanced Features (optional, later)

### 2.1 RTEdbg Support

RTEdbg has different binary format. Add support via another export format:

```bash
eabctl trace export trace.rttbin --format rtedbg --output trace.rte
python3 -m rtedbg.decode trace.rte --output trace.csv
```

**Implementation:** Shell out to RTEdbg's Python decoder. ~50 lines.

### 2.2 Live Tracing

Stream trace data in real-time to Perfetto:

```bash
eabctl trace stream --live
# Opens browser with live updating Perfetto UI
```

**Implementation:** WebSocket server + Perfetto streaming mode. ~300 lines. **Skip for MVP.**

### 2.3 Built-in Decoder (far future)

If tband or RTEdbg aren't sufficient, write a minimal EAB-native decoder. But only if external tools prove inadequate.

## What EAB Does and Doesn't Do

### ✅ EAB Does (Transport Layer)
- Capture binary RTT data to `.rttbin` files (already implemented)
- Provide CLI commands for start/stop/export/view
- Document how to integrate Tonbandgerät/RTEdbg in firmware
- Ship example firmware with tracing enabled
- Handle multiple RTT channels

### ❌ EAB Doesn't Do (Keep Lean)
- Parse Tonbandgerät/RTEdbg binary formats (use their decoders)
- Render Perfetto UI (use browser)
- Implement FreeRTOS hooks (Tonbandgerät already did this)
- Parse RTOS task structs (too RTOS-specific, fragile)

## Integration Checklist

- [ ] Add `eab/cli/trace_cmds.py` with start/stop/export/view commands
- [ ] Update `eab/cli/parser.py` to register `trace` subcommands
- [ ] Add `examples/freertos-tracing/` with Tonbandgerät integration guide
- [ ] Add optional dependency: `pip install embedded-agent-bridge[tracing]` → installs `tband`
- [ ] Document in CLAUDE.md:
  ```bash
  eabctl trace start --output trace.rttbin
  eabctl trace stop
  eabctl trace export trace.rttbin --format perfetto -o trace.json
  eabctl trace view trace.json
  ```
- [ ] Add test: `tests/test_cli_trace_cmds.py`
- [ ] Update README with observability section

## Estimated Effort

- **Phase 1 (MVP):** 2-4 hours
  - CLI commands: 1 hour
  - Example firmware: 1 hour
  - Tests + docs: 1-2 hours

- **Phase 2 (Enhanced):** 4-8 hours (optional)
  - RTEdbg format support: 2 hours
  - Live streaming: 4-6 hours

## Success Criteria

After Phase 1, users can:
1. Add Tonbandgerät to their FreeRTOS firmware (copy example)
2. Run `eabctl trace start` to capture binary RTT data
3. Run `eabctl trace export` to convert to Perfetto JSON
4. Open Perfetto in Chrome and see their task timeline, context switches, and custom events

**Zero EAB bloat:** All tracing logic lives in Tonbandgerät (firmware) and tband CLI (host decoder). EAB is just the transport pipe.

## Why This Works

1. **Separation of concerns:** EAB = transport, Tonbandgerät = tracing semantics
2. **Best tools for the job:** Perfetto is industry-standard, battle-tested
3. **Minimal maintenance:** When FreeRTOS changes, Tonbandgerät updates, not EAB
4. **Extensible:** Add RTEdbg support later without changing EAB core
5. **User choice:** Firmware can use Tonbandgerät, RTEdbg, or custom - EAB just captures bytes

## Next Steps

1. Create GitHub issue: "Add observability via Tonbandgerät integration"
2. Implement Phase 1 MVP
3. Test with real FreeRTOS firmware on nRF5340 / ESP32
4. Consider Phase 2 if users request it
