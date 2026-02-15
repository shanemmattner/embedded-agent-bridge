# RTT Signature Mismatch: Zephyr vs probe-rs

## Problem

probe-rs cannot find RTT control blocks in Zephyr firmware, even though RTT is properly compiled and initialized.

## Root Cause (Discovered via GDB)

Using `eabctl memdump` to dump STM32L432 RAM at 0x20000000 and searching for RTT signatures revealed:

### Zephyr RTT Signature
- **Location**: 0x20001010
- **Signature**: `"SEGGER RTT"` (10 bytes + padding to 16 bytes)
- **Structure**:
  ```
  Offset  | Field                | Value
  --------|----------------------|----------
  0x1010  | acID[16]            | "SEGGER RTT\0\0\0\0\0\0"
  0x1020  | MaxNumUpBuffers     | 3
  0x1024  | MaxNumDownBuffers   | 3
  0x1028  | aUp pointer         | 0x0800ed51
  0x102c  | aDown pointer       | 0x20000010
  ```

### probe-rs Expected Signature
- **Searches for**: `"_SEGGER_RTT"` (with leading underscore)
- **Source**: probe-rs library hardcoded expectation
- **Result**: Fails to find Zephyr RTT control blocks

## Investigation Method

1. Built STM32L432 firmware with RTT enabled (verified via build logs showing SEGGER_RTT.c compilation)
2. Flashed firmware via `west flash --runner openocd`
3. Used `eabctl memdump --chip stm32l432kc --probe openocd 0x20000000 65536 /tmp/stm32_ram.bin` to dump RAM
4. Searched binary dump for RTT signatures:
   ```python
   signature = b"SEGGER RTT"  # Found at offset 0x1010
   underscore_sig = b"_SEGGER_RTT"  # NOT found
   ```
5. Decoded control block structure to verify it's valid RTT

## Impact

- **J-Link Transport**: Works perfectly (JLinkRTTLogger doesn't rely on signature search)
- **probe-rs Transport**: Cannot auto-detect RTT (signature mismatch)
- **All Zephyr Targets**: Affected (nRF5340, STM32, MCXN947, etc.)

## Workarounds

### Option 1: Use J-Link Transport (Recommended)
```bash
eabctl rtt start --device NRF5340_xxAA --transport jlink
# Works: ✓ RTT started (3 channels), streaming "Hello from RTT! count=XXXX"
```

### Option 2: Specify Explicit Control Block Address
Modify `eab-probe-rs/src/lib.rs` to accept optional block address:
```rust
fn start_rtt(&self, block_address: Option<u32>) -> PyResult<usize> {
    let mut rtt = if let Some(addr) = block_address {
        Rtt::attach_at(&mut core, addr)?  // If probe-rs supports this
    } else {
        Rtt::attach(&mut core)?
    };
    // ...
}
```

Then use: `session.start_rtt(block_address=0x20001010)`

### Option 3: Patch probe-rs
Fork probe-rs and modify RTT scanner to search for both signatures:
```rust
// In probe-rs RTT scanning code
const RTT_ID: &[u8] = b"_SEGGER_RTT";
const RTT_ID_ALT: &[u8] = b"SEGGER RTT\0\0\0\0\0\0";  // Zephyr format
```

### Option 4: Configure Zephyr (Unlikely)
Check if `CONFIG_SEGGER_RTT_CUSTOM_ID` or similar exists to force underscore prefix.
Current finding: No such config exists in Zephyr 4.3.99.

## Verification Commands

```bash
# Dump RAM via EAB
eabctl memdump --chip stm32l432kc --probe openocd 0x20000000 65536 /tmp/ram.bin

# Search for RTT signature
python3 << 'EOF'
data = open('/tmp/ram.bin', 'rb').read()
idx = data.find(b"SEGGER RTT")
if idx != -1:
    print(f"Found at offset 0x{idx:04x} (address 0x{0x20000000+idx:08x})")
    print(f"Data: {data[idx:idx+32].hex()}")
EOF
```

## Recommendation

**For production use**: Use J-Link transport (`--transport jlink`)
**For probe-rs development**: Track upstream issue or implement Option 2/3

## Related Files

- `eab/cli/debug/gdb_cmds.py` - EAB's GDB integration (used for memdump)
- `eab-probe-rs/src/lib.rs` - probe-rs Rust extension
- `eab/rtt_transport.py` - RTT transport backends
- Zephyr SEGGER RTT: `~/zephyrproject/modules/debug/segger/SEGGER/SEGGER_RTT.c`
- Zephyr wrapper: `~/zephyrproject/zephyr/modules/segger/SEGGER_RTT_zephyr.c`

## Timeline

- **2026-02-15**: Issue discovered via GDB memory inspection
- **Hardware tested**: STM32L432KC (Cortex-M4), nRF5340 DK, FRDM-MCXN947
- **Firmware**: Zephyr 4.3.99 with CONFIG_USE_SEGGER_RTT=y

---

**Status**: Documented, J-Link transport verified working as alternative
