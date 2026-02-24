# EAB Improvement Plan

## Context

During STM32N6 SRAM boot testing, we discovered that serial output works perfectly — the problem was the EAB daemon holding the USB composite device, blocking probe-rs from claiming it. Most of these issues are **general to all composite USB debug probes**, not STM32-specific.

## Findings

- Serial output confirmed working: USART1 PE5/PE6 at 115200 baud, full ml-bench output captured
- Root cause of "never captured": daemon holds VCP side of composite USB, blocking probe-rs on SWD side
- `eabctl pause` / `eabctl resume` already exist and release the serial port — the regression step just doesn't use them
- Gait-bench was loading to wrong SRAM address (0x34000000 vs 0x34180400) — link address mismatch
- GDB `detach` after setting registers doesn't start execution; `continue &` + `sleep` + `disconnect` does

---

## General Improvements (all chips/probes)

### G1: Daemon pause/resume in regression steps

**Problem**: Any regression step that uses a debug probe (probe-rs, OpenOCD, J-Link) on a USB composite device (ST-Link, MCU-Link, J-Link, ESP32 USB-JTAG) conflicts with the daemon holding the VCP serial port. This affects `sram_boot`, and will affect future steps like `trace_capture`, `rtt_stream`, or `fault_inject`.

**Solution**: Add `exclusive_usb: true` parameter to step YAML. The runner calls `eabctl pause` before and `eabctl resume` after any step with this flag.

**Where**: `eab/cli/regression/runner.py` — in `run_step()` or the test loop.

**Implementation**:
```python
# In runner.py, before calling run_step():
if step.params.get("exclusive_usb"):
    cmd_pause(base_dir=base_dir, seconds=timeout + 30, json_mode=False)
    time.sleep(1)  # Wait for daemon to release port

result = run_step(step, ...)

if step.params.get("exclusive_usb"):
    cmd_resume(base_dir=base_dir, json_mode=False)
    time.sleep(2)  # Wait for daemon to reclaim port
```

**YAML usage**:
```yaml
- sram_boot:
    binary: build/zephyr/zephyr.bin
    exclusive_usb: true  # Runner handles daemon pause/resume
```

**Effort**: Small — daemon API already exists, just wire it into the runner.

---

### G2: Auto-detect load address from ELF

**Problem**: `load_address` is hardcoded in YAML. Different Zephyr board configs produce different link addresses (axisram1 at 0x34000000 vs axisram2 at 0x34180400). Mismatch = firmware jumps to garbage. We wasted significant time on this.

**Solution**: If `load_address` is not specified in YAML, read it from the ELF file's program headers. Fall back to the binary's vector table SP/PC as a sanity check.

**Where**: `eab/cli/regression/steps.py` — new helper function + use in `_run_sram_boot()`.

**Implementation**:
```python
def _elf_load_address(binary_path: str) -> Optional[str]:
    """Extract load address from ELF LOAD segment, or None if not ELF."""
    elf_path = binary_path.replace(".bin", ".elf")
    if not os.path.exists(elf_path):
        return None
    result = subprocess.run(
        ["arm-none-eabi-readelf", "-l", elf_path],
        capture_output=True, text=True
    )
    # Parse first LOAD segment physical address
    for line in result.stdout.splitlines():
        if "LOAD" in line:
            parts = line.split()
            return parts[3]  # PhysAddr column
    return None
```

**Effort**: Small — utility function + fallback logic.

---

### G3: Graceful probe-rs cleanup

**Problem**: `gdb_proc.kill()` on line 481 of steps.py uses SIGKILL. On macOS, this corrupts the ST-Link V3 USB state (eUSB2 timing issue). Requires physical USB re-plug to recover.

**Solution**: Always use SIGTERM + wait + configurable delay. Apply to all probe-rs usage across EAB.

**Where**: `eab/cli/regression/steps.py` — `_run_sram_boot()` and any future probe-rs steps.

**Implementation**:
```python
def _graceful_kill(proc: subprocess.Popen, timeout: int = 5, usb_delay: float = 2.0):
    """Stop a process gracefully (SIGTERM), with USB recovery delay."""
    proc.terminate()  # SIGTERM
    try:
        proc.wait(timeout=timeout)
    except subprocess.TimeoutExpired:
        proc.kill()  # Last resort SIGKILL
        proc.wait()
    time.sleep(usb_delay)  # USB recovery
```

**Effort**: Tiny — extract to helper, replace `.kill()` calls.

---

### G4: Fix GDB boot pattern

**Problem**: Current code uses `detach` after setting registers (line 445). Our testing proved this doesn't reliably start execution. The working pattern is `continue &` + `shell sleep 2` + `disconnect`.

**Solution**: Replace the GDB command sequence in `_run_sram_boot()`.

**Where**: `eab/cli/regression/steps.py` lines 435-484.

**Implementation**: Replace the two-phase GDB approach (setup + detach, then separate continue + kill) with a single GDB batch:
```python
gdb_cmds = [
    "target remote localhost:1337",
    "monitor halt",
    f"set $sp = 0x{sp_value:08X}",
    f"set $msp = 0x{sp_value:08X}",
    f"set $pc = 0x{reset_handler:08X}",
    "continue &",
    "shell sleep 2",
    "disconnect",
]
gdb_cmd = [gdb_path, "--batch"]
for cmd in gdb_cmds:
    gdb_cmd.extend(["-ex", cmd])
```

**Effort**: Small — rewrite ~50 lines into ~20 cleaner lines.

---

## STM32N6-Specific Improvements

### S1: `eabctl sram-boot` CLI command

**Problem**: No interactive way to SRAM boot outside of regression tests. Debugging requires manually running 7 steps (halt, load, extract vectors, start probe-rs, GDB, kill probe-rs, read serial).

**Solution**: New `eabctl sram-boot <binary> [--load-address ADDR]` command that automates the full procedure with daemon pause/resume built in.

**Where**: New file `eab/cli/flash/sram_boot_cmd.py` + register in `eab/cli/parser.py`.

**Implementation**: Reuse the same logic as the regression step but with interactive output:
```
$ eabctl sram-boot build-stm32n6-gait/zephyr/zephyr.bin
[1/6] Pausing daemon...
[2/6] Halting core (-hardRst -halt)...
[3/6] Loading 159KB to 0x34180400 (from ELF)...
[4/6] Booting via GDB (SP=0x341B95C8, PC=0x3418632D)...
[5/6] Stopping probe-rs (SIGTERM)...
[6/6] Resuming daemon...
SRAM boot complete. Monitor: eabctl tail 50
```

**Effort**: Medium — new command, but logic already exists in regression step.

---

### S2: Firmware startup delay for SRAM boot

**Problem**: Fast firmware (gait-bench) finishes printing before serial reader connects. The serial reader can only open after probe-rs releases the USB device (~2-3s gap).

**Solution**: Already fixed in firmware (`k_msleep(5000)` at top of main). Document this as a requirement for all STM32N6 SRAM-boot firmware. Consider making it a Kconfig option.

**Where**: Already in `examples/stm32n6-gait-bench/src/main.cpp`. Add to `docs/stm32n6-sram-boot.md`.

**Effort**: Done — just needs documentation.

---

## Implementation Order

| Priority | Item | Effort | Impact |
|----------|------|--------|--------|
| 1 | G1: Daemon pause/resume in runner | Small | Fixes serial capture for ALL debug probe steps |
| 2 | G4: Fix GDB boot pattern | Small | Fixes SRAM boot reliability |
| 3 | G3: Graceful probe-rs cleanup | Tiny | Prevents USB corruption on macOS |
| 4 | G2: Auto-detect load address | Small | Prevents address mismatch bugs |
| 5 | S1: `eabctl sram-boot` command | Medium | Interactive convenience |
| 6 | S2: Document startup delay | Done | Already in firmware |

Items 1-4 can be done in a single PR. Item 5 is a separate feature.

## Validation

After implementing 1-4, run:
```bash
eabctl regression --test tests/hw/stm32n6_ml_bench.yaml --json
eabctl regression --test tests/hw/stm32n6_gait_bench.yaml --json
```

Both should pass with serial output captured end-to-end through EAB.
