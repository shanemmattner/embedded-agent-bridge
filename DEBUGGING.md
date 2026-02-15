# EAB Debugging Guide

Comprehensive guide to debugging embedded targets using EAB's built-in tools. All examples use `eabctl` - no direct access to GDB/OpenOCD needed.

## Table of Contents

- [Philosophy](#philosophy)
- [Quick Reference](#quick-reference)
- [Memory Inspection](#memory-inspection)
- [Fault Analysis](#fault-analysis)
- [Variable Reading](#variable-reading)
- [Performance Profiling](#performance-profiling)
- [RTT Debugging](#rtt-debugging)
- [Real-World Examples](#real-world-examples)

---

## Philosophy

**Use EAB for ALL debugging** - don't access debug probes directly. EAB provides:
- Unified interface across all probe types (J-Link, OpenOCD, probe-rs)
- JSON output for automation
- Proper resource management (no zombie processes or locked ports)
- Integration with EAB's device registry and daemon

**Never use these directly**: `openocd`, `JLinkGDBServer`, `gdb`, `arm-none-eabi-gdb`
**Always use**: `eabctl gdb`, `eabctl memdump`, `eabctl fault-analyze`, etc.

---

## Quick Reference

| Task | Command | Use When |
|------|---------|----------|
| **Crash analysis** | `eabctl fault-analyze` | Device crashed, need register dump |
| **Memory dump** | `eabctl memdump` | Need to inspect RAM/Flash contents |
| **Read variables** | `eabctl read-vars` | Check specific variable values |
| **Inspect struct** | `eabctl inspect` | View struct fields and values |
| **Profile function** | `eabctl profile-function` | Measure execution time |
| **One-shot GDB** | `eabctl gdb` | Run custom GDB commands |
| **GDB script** | `eabctl gdb-script` | Complex GDB workflows |
| **Thread info** | `eabctl threads` | Check FreeRTOS/Zephyr thread states |
| **Watch variable** | `eabctl watch` | Monitor variable changes |

---

## Memory Inspection

### Dump RAM Region

```bash
# Dump 64KB of STM32 RAM to file
eabctl memdump --chip stm32l432kc --probe openocd 0x20000000 65536 /tmp/ram.bin --json

# Output:
{
  "bytes_written": 65536,
  "output_path": "/tmp/ram.bin",
  "success": true,
  "start_addr": "0x20000000",
  "size": 65536
}
```

### Search Memory Dump

```python
# Search for a pattern in RAM dump
import struct

with open('/tmp/ram.bin', 'rb') as f:
    ram = f.read()

# Search for RTT control block signature
signature = b"SEGGER RTT"
idx = ram.find(signature)
if idx != -1:
    addr = 0x20000000 + idx
    print(f"Found at 0x{addr:08x}")

    # Parse structure
    data = ram[idx:idx+32]
    max_up = struct.unpack('<I', data[16:20])[0]
    max_down = struct.unpack('<I', data[20:24])[0]
    print(f"Up channels: {max_up}, Down channels: {max_down}")
```

### Use Cases

- **Find RTT control block**: Search for "SEGGER RTT" signature
- **Locate data structures**: Search for known patterns/magic values
- **Verify firmware**: Check if expected strings are in memory
- **Debug memory corruption**: Compare dumps before/after crash

---

## Fault Analysis

### Analyze Cortex-M Crash

```bash
# Basic fault analysis
eabctl fault-analyze --device NRF5340_XXAA_APP --json

# With custom chip/probe
eabctl fault-analyze --device MCXN947 --probe openocd --chip mcxn947 --json

# Output:
{
  "fault_detected": true,
  "fault_type": "HardFault",
  "cfsr": {
    "IACCVIOL": true,   # Instruction access violation
    "PC": "0x08004532"  # Faulting instruction address
  },
  "stacked_registers": {
    "PC": "0x08004532",
    "LR": "0x080023f1",
    "SP": "0x20003f80"
  }
}
```

### Interpret Results

- **IACCVIOL**: Tried to execute from invalid address (null pointer jump)
- **DACCVIOL**: Data access violation (null pointer dereference)
- **PRECISERR**: Bus fault at known address
- **IMPRECISERR**: Bus fault (address lost due to async behavior)
- **STKERR**: Stack overflow (stack pointer invalid)

### Use Cases

- **Device reset loop**: Check for continuous faults
- **Null pointer bugs**: Look for PC/address near 0x00000000
- **Stack overflow**: Check SP value and STKERR flag
- **Memory corruption**: DACCVIOL at unexpected address

---

## Variable Reading

### Read Specific Variables

```bash
# Read single variable
eabctl read-vars --elf build/zephyr/zephyr.elf --device STM32L432KC --probe openocd error_count --json

# Read multiple variables
eabctl read-vars --elf build/app.elf --device NRF5340_XXAA_APP \
  error_count heap_free task_state --json

# Output:
{
  "variables": {
    "error_count": {"value": 0, "type": "uint32_t"},
    "heap_free": {"value": 4096, "type": "size_t"},
    "task_state": {"value": 2, "type": "enum TaskState"}
  }
}
```

### Inspect Struct

```bash
# View struct with all fields
eabctl inspect --elf build/app.elf --device NRF5340_XXAA_APP device_config --json

# Output:
{
  "struct": "device_config",
  "fields": {
    "magic": "0xDEADBEEF",
    "version": 1,
    "enabled": true,
    "name": "sensor-01"
  }
}
```

### Use Cases

- **Verify configuration**: Check if config loaded correctly
- **Debug state machines**: Read current state variable
- **Memory leak detection**: Monitor heap_free over time
- **Watchdog investigation**: Check task_alive counters

---

## Performance Profiling

### Profile Function (DWT-based)

```bash
# Profile function by name
eabctl profile-function --function main \
  --device NRF5340_XXAA_APP \
  --elf build/zephyr/zephyr.elf \
  --json

# Output:
{
  "function": "main",
  "cycles": 12840,
  "time_us": 100.31,
  "cpu_freq_mhz": 128
}
```

### Profile Memory Region

```bash
# Profile specific address range
eabctl profile-region --start 0x1000 --end 0x1100 \
  --device NRF5340_XXAA_APP \
  --cpu-freq 128000000 \
  --json
```

### DWT Status

```bash
# Check if DWT is available and configured
eabctl dwt-status --device NRF5340_XXAA_APP --json

# Output:
{
  "dwt_available": true,
  "cycle_counter_enabled": true,
  "comparators": 4
}
```

### Use Cases

- **Optimize hot paths**: Measure function execution time
- **Interrupt latency**: Profile ISR handlers
- **Real-time validation**: Ensure functions meet timing requirements
- **Algorithm comparison**: A/B test different implementations

---

## RTT Debugging

### Start RTT Streaming

```bash
# J-Link transport (recommended for production)
eabctl rtt start --device NRF5340_XXAA_APP --transport jlink --json

# probe-rs transport (experimental, all probe types)
eabctl rtt start --device STM32L476RG --transport probe-rs --json
```

### RTT Not Found? Debug It

**Step 1: Verify firmware has RTT**
```bash
# Check if SEGGER_RTT.c was compiled
west build -b nucleo_l432kc app | grep -i segger
```

**Step 2: Dump RAM and search for control block**
```bash
# Dump RAM
eabctl memdump --chip stm32l432kc --probe openocd 0x20000000 65536 /tmp/ram.bin

# Search for signature
python3 << 'EOF'
data = open('/tmp/ram.bin', 'rb').read()
idx = data.find(b"SEGGER RTT")
if idx != -1:
    print(f"RTT control block at 0x{0x20000000+idx:08x}")
else:
    print("RTT not initialized - firmware issue or timing problem")
EOF
```

**Step 3: Check RTT config**
```bash
# For Zephyr, verify prj.conf has:
cat prj.conf | grep RTT

# Expected:
# CONFIG_USE_SEGGER_RTT=y
# CONFIG_RTT_CONSOLE=y
# CONFIG_LOG_BACKEND_RTT=y
```

### Use Cases

- **High-speed logging**: No UART bandwidth limits
- **Real-time data**: Minimal CPU overhead
- **Binary data**: Stream sensor data, not just text

---

## Real-World Examples

### Example 1: Finding RTT Control Block

**Problem**: `probe-rs` can't find RTT control block even though firmware has RTT compiled in.

**Investigation**:
```bash
# 1. Dump RAM
eabctl memdump --chip stm32l432kc --probe openocd 0x20000000 65536 /tmp/ram.bin --json

# 2. Search for signature
python3 << 'EOF'
import struct
ram = open('/tmp/ram.bin', 'rb').read()
sig = b"SEGGER RTT"
idx = ram.find(sig)

if idx != -1:
    addr = 0x20000000 + idx
    print(f"✓ RTT control block at 0x{addr:08x}")

    # Parse structure
    data = ram[idx:idx+32]
    max_up = struct.unpack('<I', data[16:20])[0]
    max_down = struct.unpack('<I', data[20:24])[0]
    up_ptr = struct.unpack('<I', data[24:28])[0]

    print(f"  Up channels: {max_up}")
    print(f"  Down channels: {max_down}")
    print(f"  Up buffer ptr: 0x{up_ptr:08x}")
else:
    print("✗ RTT not found - check timing or config")
EOF
```

**Result**: Found control block at `0x20001010`, verified structure is valid.

**Solution**: Use explicit address in probe-rs or switch to J-Link transport.

---

### Example 2: Debugging Null Pointer Dereference

**Problem**: Device resets randomly.

**Investigation**:
```bash
# 1. Check for fault
eabctl fault-analyze --device STM32L432KC --probe openocd --json

# Output shows:
{
  "fault_detected": true,
  "cfsr": {
    "DACCVIOL": true,  # Data access violation
    "MMARVALID": true
  },
  "mmfar": "0x00000004",  # Tried to access 0x00000004
  "stacked_pc": "0x08004532"
}

# 2. Find the faulting code
# Load zephyr.elf in addr2line:
addr2line -e build/zephyr/zephyr.elf 0x08004532

# Output: src/sensor.c:45 (sensor_read function)
```

**Root Cause**: Dereferencing null pointer + 4 bytes (likely a struct member).

**Fix**: Add null check before `sensor->config->enable`.

---

### Example 3: Stack Overflow Detection

**Problem**: Device crashes under heavy load.

**Investigation**:
```bash
# 1. Analyze fault
eabctl fault-analyze --device NRF5340_XXAA_APP --json

# Output:
{
  "cfsr": {
    "STKERR": true  # Stack error during exception stacking
  },
  "sp": "0x20000008",  # SP way too low
  "psp": "0x20000008"
}

# 2. Check stack usage
eabctl threads --device NRF5340_XXAA_APP --json

# Output shows task with 128-byte stack:
{
  "threads": [
    {
      "name": "sensor_task",
      "stack_size": 128,
      "stack_used": 124,  # 97% utilization!
      "state": "ready"
    }
  ]
}
```

**Root Cause**: Task stack too small (128 bytes).

**Fix**: Increase `sensor_task` stack to 512 bytes in `prj.conf`.

---

### Example 4: Performance Regression

**Problem**: New firmware release is slower than previous version.

**Investigation**:
```bash
# Profile critical function
eabctl profile-function --function process_data \
  --device NRF5340_XXAA_APP \
  --elf build/new/zephyr.elf \
  --json > new_profile.json

# Compare with old version
eabctl profile-function --function process_data \
  --device NRF5340_XXAA_APP \
  --elf build/old/zephyr.elf \
  --json > old_profile.json

# Results:
# Old: 850 µs
# New: 1240 µs (46% slower!)
```

**Investigation continues**:
```bash
# Profile sub-regions to narrow down
eabctl profile-region --start 0x00008400 --end 0x00008480 \
  --device NRF5340_XXAA_APP --json

# Found: New code added division operation (expensive on Cortex-M without FPU)
```

**Fix**: Replace `/` with bit shift `>>` for power-of-2 divisions.

---

## Common Patterns

### Pattern 1: "Is firmware running?"

```bash
# Read a counter variable
eabctl read-vars --elf build/app.elf --device TARGET loop_count --json

# Run twice, 1 second apart
# If value changes → firmware is running
# If value same → firmware stuck or not started
```

### Pattern 2: "Why did it reset?"

```bash
# 1. Check for fault
eabctl fault-analyze --device TARGET --json

# 2. If no fault, check reset reason register
eabctl gdb --device TARGET --probe openocd \
  --command "print /x *(uint32_t*)0x40000400" \
  --json
```

### Pattern 3: "Memory leak?"

```bash
# Monitor heap over time
while true; do
  eabctl read-vars --elf build/app.elf --device TARGET heap_free
  sleep 5
done

# If heap_free decreases over time → leak
```

---

## Troubleshooting

### "No debug probe found"

```bash
# Check EAB device registry first
eabctl devices --json

# Check USB devices
system_profiler SPUSBDataType | grep -i "jlink\|stlink\|cmsis"
```

### "GDB server failed to start"

```bash
# Kill existing instances
killall openocd JLinkGDBServer

# Retry command
```

### "Symbol not found in ELF"

```bash
# Verify ELF file matches flashed firmware
eabctl flash build/app.hex  # Flash first
eabctl read-vars --elf build/app.elf --device TARGET my_var  # Then read
```

### "Probe is busy"

```bash
# Check what's using it
lsof | grep -i "jlink\|openocd"

# Stop EAB daemon if needed
eabctl stop --base-dir /tmp/eab-devices/nrf5340
```

---

## Best Practices

1. **Always use `--json` in automation** - Easier to parse than human-readable output
2. **Flash before reading vars** - Ensure ELF matches firmware
3. **Check `eabctl devices` first** - Don't guess which boards are connected
4. **Use memdump for complex searches** - Faster than repeated GDB reads
5. **Profile before optimizing** - Measure, don't guess
6. **Document your findings** - Add examples to this guide!

---

## See Also

- **CLAUDE.md**: Full `eabctl` command reference
- **docs/rtt-signature-mismatch.md**: RTT debugging case study
- **docs/regression.md**: Automated hardware testing

---

**Last Updated**: 2026-02-15
**Maintainers**: Add your debugging discoveries here!
