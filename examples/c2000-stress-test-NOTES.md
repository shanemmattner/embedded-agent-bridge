# C2000 Stress Test Firmware - TODO

## Status
Need to create CCS (Code Composer Studio) project for F28003x LaunchPad.

## Requirements
- **Hardware**: LAUNCHXL-F280039C (has XDS110 onboard)
- **Software**: CCS 2041+ with C2000 compiler
- **Transport**: DSS (Debug Sub-System) trace via XDS110

## Firmware Goals
1. High-speed data logging via DLOG (F28003x Data Logger)
2. Continuous variable streaming to test EAB's C2000 var_stream capability
3. ERAD (Embedded Real-time Analysis and Diagnostics) profiling markers

## Expected Throughput
- **DLOG snapshot rate**: ~12 Hz (limited by XDS110 JTAG latency ~1.8ms/read)
- **Variable streaming**: ~31 KB/s bulk memory reads
- **Single reads**: ~1.8 ms per transaction

## Implementation Notes
- C2000 is optimized for post-capture analysis, not live streaming
- Use DLOG for waveform capture (ISR-rate data logging)
- Use ERAD for zero-overhead profiling
- Refer to: `docs/c2000-transport-research.md` for architecture details

## CCS Project Structure
```
c2000-stress-test/
├── main.c                  # Main application
├── dlog_config.c           # DLOG 4-channel setup
├── erad_config.c           # ERAD profiling setup
├── F280039C.cmd            # Linker command file
├── targetConfigs/          # XDS110 CCXML
└── Debug/                  # Build output
```

## Build Steps
1. Create new CCS project: File > New > CCS Project
2. Select: F280039C LaunchPad + XDS110 Emulator
3. Copy source files
4. Build: Project > Build All
5. Flash: Run > Debug (loads via XDS110)

## Alternative: Use TI Example
- C2000Ware includes DLOG examples: `C2000Ware/driverlib/f28003x/examples/`
- Adapt `dlog_f28003x.c` for continuous data generation

## EAB Integration
Once firmware is flashed:
```bash
# Register device
eabctl device add c2000-1 --type debug --chip f28003x

# Start variable streaming
eabctl --device c2000-1 stream-vars --vars "var1,var2,var3,var4" --rate 12

# Capture DLOG snapshot
eabctl --device c2000-1 dlog-capture --output snapshot.csv
```

## References
- C2000 transport architecture: `docs/c2000-advanced-debug-plan.md`
- XDS110 probe class: `eab/debug_probes/xds110.py`
- DLOG analyzer: `eab/analyzers/dlog.py`
- ERAD support: `eab/analyzers/erad.py`
