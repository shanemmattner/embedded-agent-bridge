# MCXN947 Debug Full Example

Complete debugging demonstration for MCXN947 (ARM Cortex-M33) with all EAB Zephyr features enabled.

## Features Enabled

### ✅ CTF Task Tracing via RTT
- Thread scheduling visualization in CTF format
- Custom event markers for profiling
- Precise timestamps
- **Capture:** `eabctl trace start --source rtt`
- **Export:** Perfetto JSON via `babeltrace` or Perfetto CTF importer

### ✅ Runtime Shell Commands
- `kernel threads` - List all threads with state, priority, stack
- `kernel stacks` - Show stack usage for all threads
- `kernel uptime` - System uptime in milliseconds
- `status` - System status and counters
- `fault null/div0/stack` - Trigger faults for testing
- **Access:** via RTT (shell backend)

### ✅ Coredump Generation
- Logging backend (prints to console)
- Register dumps and stack traces
- **Trigger:** Shell commands `fault null`, `fault div0`, `fault stack`
- **Decode:** Automatically printed to log output

### ✅ Stack Protection
- MPU stack guard (hardware protection)
- Stack sentinel (software canary)
- **Trigger:** `fault stack` command or actual overflow

### ✅ Thread Monitoring
- Runtime statistics (CPU usage per thread)
- Stack usage tracking
- Thread state monitoring

## Hardware Required

- MCXN947 DK (FRDM-MCXN947)
- probe-rs compatible debug probe
- USB cable

## Build and Flash

```bash
# Set ZEPHYR_BASE if not already set
export ZEPHYR_BASE=~/zephyrproject/zephyr

# From EAB repo root
cd examples/mcxn947-debug-full

# Build (Zephyr west)
west build -b mcxn947dk_mcxn947_cpuapp

# Flash via EAB (recommended)
eabctl flash --chip mcxn947 --runner openocd

# Or flash with west
west flash --runner openocd
```

## Usage

### 1. Start RTT Monitoring

```bash
# Via EAB RTT
eabctl rtt start --device MCXN947 --transport jlink
eabctl rtt tail 100

# Or use J-Link RTT Viewer directly
```

### 2. Available Shell Commands

Type commands into the RTT shell:

| Command | Action |
|---------|--------|
| `kernel threads` | List all threads |
| `kernel stacks` | Show stack usage |
| `kernel uptime` | System uptime |
| `status` | Print system status |
| `fault null` | Trigger NULL pointer fault |
| `fault div0` | Trigger divide-by-zero |
| `fault stack` | Trigger stack overflow (MPU) |
| `help` | Show all available commands |

### 3. Capture CTF Trace

```bash
# Start RTT trace capture
eabctl trace start --source rtt -o /tmp/mcxn947-trace.rttbin --device MCXN947

# ... let it run for 10-15 seconds ...

# Stop capture
eabctl trace stop

# Export to Perfetto JSON
eabctl trace export -i /tmp/mcxn947-trace.rttbin -o /tmp/mcxn947-trace.json
```

### 4. Analyze Coredump

Coredump is automatically printed to RTT log when a fault occurs:

```
> fault null
[00:00:10.000,000] <inf> debug_full: Triggering NULL pointer fault...
[00:00:10.100,000] <err> os: ***** MPU FAULT *****
[00:00:10.100,000] <err> os: Faulting instruction address: 0x000xxxxx
[00:00:10.100,000] <err> os: r0/a1:  0x00000000  r1/a2:  0x00000000
...
[00:00:10.150,000] <err> os: ***** Coredump *****
```

### 5. Visualize in Perfetto

Open https://ui.perfetto.dev and load `/tmp/mcxn947-trace.json` to see:
- Thread scheduling timeline
- CPU utilization per thread
- Custom event markers (compute_work, io_operation, alloc_event)
- Thread state transitions

## Expected Output

### Boot Messages (via RTT)
```
[00:00:00.000,000] <inf> debug_full: ========================================
[00:00:00.001,000] <inf> debug_full: MCXN947 Debug Full Example
[00:00:00.002,000] <inf> debug_full: ========================================
[00:00:00.003,000] <inf> debug_full: Features enabled:
[00:00:00.004,000] <inf> debug_full:   - CTF task tracing via RTT
[00:00:00.005,000] <inf> debug_full:   - Shell commands (type 'help')
[00:00:00.006,000] <inf> debug_full:   - Coredump generation
[00:00:00.007,000] <inf> debug_full:   - MPU stack guard
[00:00:00.008,000] <inf> debug_full: ========================================
[00:00:00.010,000] <inf> debug_full: Compute thread started
[00:00:00.011,000] <inf> debug_full: I/O thread started
[00:00:00.012,000] <inf> debug_full: Alloc thread started
[00:00:00.013,000] <inf> debug_full: All threads created. Ready for debugging!
```

### Shell Session Example
```
uart:~$ kernel threads
Scheduler: 2500 since last call
Threads:
 0x20000a00 compute
        options: 0x0, priority: 7 timeout: 0
        state: pending
        stack size 2048, unused 1624, usage 424 / 2048 (20 %)

 0x20000b00 io
        options: 0x0, priority: 8 timeout: 0
        state: pending
        stack size 1024, unused 768, usage 256 / 1024 (25 %)

...

uart:~$ status
=== System Status ===
Uptime: 15243 ms
Cycle count: 1953504000
Event counter: 304
```

## Threads in Firmware

| Thread | Priority | Stack | Purpose |
|--------|----------|-------|---------|
| `idle` | 15 (lowest) | default | Zephyr idle thread |
| `alloc` | 9 | 2048 | Memory allocation patterns |
| `io` | 8 | 1024 | I/O simulation |
| `compute` | 7 | 2048 | CPU-intensive work |
| `logging` | 0 | default | Deferred logging thread |
| `sysworkq` | 10 | default | System work queue |

## Configuration Details

All features are enabled in `prj.conf`. Key settings:

```ini
# CTF Tracing
CONFIG_TRACING=y
CONFIG_TRACING_CTF=y
CONFIG_TRACING_BACKEND_RTT=y

# Shell
CONFIG_SHELL=y
CONFIG_SHELL_BACKEND_RTT=y
CONFIG_KERNEL_SHELL=y

# Coredump
CONFIG_DEBUG_COREDUMP=y
CONFIG_DEBUG_COREDUMP_BACKEND_LOGGING=y

# MPU Protection
CONFIG_MPU_STACK_GUARD=y
CONFIG_STACK_SENTINEL=y
```

## Troubleshooting

### RTT Issues
- **No output:** Check J-Link connection, ensure `--device MCXN947`
- **Buffer overflow:** Increase `CONFIG_SEGGER_RTT_BUFFER_SIZE_UP` in prj.conf

### Shell Issues
- **No prompt:** Ensure shell backend is RTT (`CONFIG_SHELL_BACKEND_RTT=y`)
- **Commands don't work:** Check spelling, use `help` to list all commands

### Trace Capture Issues
- **No trace data:** Verify `CONFIG_TRACING=y` and `CONFIG_TRACING_BACKEND_RTT=y`
- **CTF decode failed:** Use `babeltrace` or Perfetto's CTF importer

## Platform-Specific Notes

### MCXN947 vs Other Platforms

| Feature | MCXN947 | ESP32-C6 | ESP32-S3 |
|---------|---------|----------|----------|
| Trace Format | CTF | SystemView | SystemView |
| Shell | ✅ RTT | ❌ | ❌ |
| Heap Profiling | ⚠️ Limited | ✅ Full | ✅ Full |
| Stack Guard | ✅ MPU | ✅ Watchpoint | ✅ Watchpoint |
| Coredump | ✅ Logging | ✅ Flash | ✅ Flash |

## Next Steps

1. **Test with EAB regression framework:**
   ```bash
   eabctl regression --test tests/hw/mcxn947_debug_full.yaml
   ```

2. **Create test YAML** (see `tests/hw/mcxn947_debug_full.yaml`)

3. **Verify CTF → Perfetto pipeline** works end-to-end

4. **Try `babeltrace` directly:**
   ```bash
   babeltrace /tmp/mcxn947-trace.rttbin
   ```

## References

- [Zephyr Tracing Guide](https://docs.zephyrproject.org/latest/services/tracing/index.html)
- [Zephyr Shell Guide](https://docs.zephyrproject.org/latest/services/shell/index.html)
- [Zephyr Coredump Guide](https://docs.zephyrproject.org/latest/services/debugging/coredump.html)
- [MCXN947 DK User Guide](https://infocenter.nordicsemi.com/topic/ug_mcxn947_dk/UG/mcxn947_DK/intro.html)
- [Perfetto UI](https://ui.perfetto.dev)
