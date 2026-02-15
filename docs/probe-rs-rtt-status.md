# probe-rs RTT Integration Status

## Current State (2026-02-15)

### What Works ✅

1. **Rust Extension Built and Installed**
   - `eab-probe-rs` compiles successfully with probe-rs 0.31
   - PyO3 bindings expose ProbeRsSession to Python
   - Installation: `pip install eab_probe_rs-0.1.0-*.whl`

2. **Hardware Connectivity**
   - ✅ STM32L432KC via ST-Link V2-1
   - ✅ FRDM-MCXN947 via CMSIS-DAP
   - ⚠ nRF5340 via J-Link (ARM specific error - possible APPROTECT)
   - ⚠ ESP32-C6 via ESP USB-JTAG (probe initialization issue)

3. **CLI Integration**
   ```bash
   eabctl rtt start --device STM32L432KCUx --transport probe-rs --json
   # Connects successfully, but can't find RTT control block
   ```

4. **J-Link Transport (Reference Implementation)**
   ```bash
   eabctl rtt start --device nRF5340_xxAA --transport jlink --json
   # ✅ Works perfectly: "Hello from RTT! count=XXXXX"
   ```

### What Doesn't Work ❌

**RTT Auto-Detection on Zephyr Targets**
- probe-rs connects to target
- probe-rs scans RAM for RTT control block
- Returns "RTT control block not found"
- **Despite**: Control block verified at 0x20001010 via `eabctl memdump`

## Investigation Results

### Memory Dump Analysis

Used `eabctl memdump` to dump STM32L432 RAM and found:

```
Address: 0x20001010
Signature: SEGGER RTT\0\0\0\0\0\0
Structure:
  MaxNumUpBuffers: 3
  MaxNumDownBuffers: 3
  UpBuffer ptr: 0x0800ed51
  DownBuffer ptr: 0x20000010
```

**Conclusion**: RTT control block EXISTS and is VALID.

### probe-rs Source Analysis

From `probe-rs/src/rtt.rs`:

1. **ELF Symbol Search** (line 72):
   - Searches for `"_SEGGER_RTT"` symbol in ELF
   - Fallback if RAM scan fails

2. **RAM Signature** (line 248):
   ```rust
   pub const RTT_ID: [u8; 16] = *b"SEGGER RTT\0\0\0\0\0\0";
   ```
   - **MATCHES** Zephyr exactly!

3. **Memory Map** (`STM32L4_Series.yaml`):
   ```yaml
   - !Ram
     name: SRAM
     range:
       start: 0x20000000
       end: 0x2000c000  # 48KB
   ```
   - **CORRECT** - includes 0x20001010

4. **Scan Algorithm** (lines 399-404):
   ```rust
   let mut mem = vec![0; range_len];
   core.read(range.start, &mut mem).ok()?;
   let offset = mem.windows(Self::RTT_ID.len())
       .position(|w| w == Self::RTT_ID)?;
   ```

### The Mystery

**Why does it fail?** Three possibilities:

1. **Memory Access Method Difference**
   - OpenOCD (used by memdump): Reads via GDB protocol
   - probe-rs: Reads via direct SWD/JTAG memory access
   - **Hypothesis**: ST-Link may require special initialization for RAM access?

2. **Target State**
   - OpenOCD: Target may be halted when we dump
   - probe-rs: Target running when we scan?
   - **Hypothesis**: RAM access permissions different when running vs halted?

3. **Cache/Buffer Coherency**
   - **Hypothesis**: probe-rs reading stale data from cache?

## Implemented Solutions

### Option 1: Explicit Block Address ✅ (Implemented)

Modified `eab-probe-rs/src/lib.rs` to accept optional block address:

```python
# Python API
session.start_rtt(block_address=0x20001010)
```

**Status**: Implemented and compiles, but still fails to find control block even at exact address.

This suggests the issue is **not** the scanning algorithm but something about how probe-rs accesses STM32 memory via ST-Link.

### Option 2: Fix Memory Map ❌ (Not Needed)

Investigated probe-rs chip database (`STM32L4_Series.yaml`).
**Result**: Memory map is already correct. 0x20001010 is within SRAM range.

## Recommended Path Forward

### Short Term: Use J-Link Transport ✅
```bash
eabctl rtt start --device nRF5340_xxAA --transport jlink
# Works perfectly, production-ready
```

### Investigation Needed

1. **Enable probe-rs Debug Logging**
   - Modify extension to enable tracing
   - See exactly what memory ranges probe-rs scans
   - See what data probe-rs reads from 0x20001010

2. **Compare Memory Access Methods**
   - Test if halting target before scan helps
   - Compare ST-Link access via probe-rs vs OpenOCD
   - Check if memory caching is an issue

3. **Test with Different probe-rs Version**
   - Try probe-rs 0.24 (older, more stable?)
   - Check probe-rs changelog for ST-Link fixes

4. **Upstream Report**
   - File issue with probe-rs project
   - Include memdump proof that control block exists
   - Include exact chip/board/firmware details

## Files Created

- `eab-probe-rs/`: Rust extension (built and working for connectivity)
- `DEBUGGING.md`: Comprehensive debugging guide with memdump examples
- `docs/rtt-signature-mismatch.md`: Initial investigation (signature theory - disproven!)
- `docs/probe-rs-rtt-status.md`: This document
- `scripts/test_probe_rs_all_boards.py`: Automated hardware testing
- Test firmware: RTT enabled in STM32/MCXN947 examples

## Test Results

| Board | Probe | Connect | RTT (auto) | RTT (explicit addr) | Notes |
|-------|-------|---------|------------|---------------------|-------|
| nRF5340 | J-Link (JLinkBridge) | ✅ | ✅ | N/A | Full streaming verified |
| nRF5340 | J-Link (probe-rs) | ❌ | ❌ | ❌ | ARM specific error |
| STM32L432 | ST-Link (probe-rs) | ✅ | ❌ | ❌ | CB verified at 0x20001010 |
| MCXN947 | CMSIS-DAP (probe-rs) | ✅ | ❌ | Not tested | Needs firmware flash |
| ESP32-C6 | ESP JTAG (probe-rs) | ❌ | ❌ | ❌ | Probe init issue |

## Conclusion

**probe-rs native RTT is close but not ready** for Zephyr targets due to memory access issues with ST-Link. The control block is verified to exist, but probe-rs can't read it correctly.

**Recommendation**:
- **Production**: Use J-Link transport (fully working)
- **Development**: Continue investigating probe-rs memory access with ST-Link
- **Contribution**: File detailed issue report to probe-rs maintainers

The `block_address` parameter is implemented and ready for when the memory access issue is resolved.
