# ESP32-C6 Apptrace Test Firmware

High-speed trace streaming demo using OpenOCD's `esp_apptrace` feature.

## What is Apptrace?

ESP-IDF's apptrace is a high-speed bidirectional communication channel between firmware and host PC via JTAG. It's faster than UART and doesn't block the CPU.

**Use cases:**
- Performance profiling (function timing, heap usage)
- High-volume logging without UART bottleneck
- Real-time data streaming (sensor data, network traffic)
- SystemView OS profiling integration

**Advantages over UART/USB:**
- **10-100x faster** than UART (JTAG clock is MHz, UART is typically 115200 baud)
- **Non-blocking** - Uses DMA and hardware buffers, minimal CPU overhead
- **Separate from console** - Debug logs on UART, trace data on JTAG simultaneously
- **Bidirectional** - Host can send commands to firmware (not shown in this example)

## Features

- Periodic heartbeat via apptrace (10 Hz = 100ms intervals)
- High-throughput JTAG streaming (proven: 2KB in 5 seconds)
- Dual logging: JTAG apptrace + USB-Serial console
- Ready for Perfetto visualization (future EAB integration)

## Build and Flash

```bash
# From repo root
eabctl flash examples/esp32c6-apptrace-test
```

## CRITICAL: RISC-V ESP32 Quirks (C6, C3, H2, C5)

**These chips have unique apptrace requirements compared to Xtensa ESP32:**

### 1. Reset AFTER OpenOCD Connects (Semihosting Handshake)

**Why:** During boot, firmware calls `esp_apptrace_advertise_ctrl_block()` which uses RISC-V semihosting (`ebreak` instruction) to tell OpenOCD where the trace buffer is in memory. If OpenOCD isn't running when firmware boots, this handshake fails and OpenOCD can't find the buffer.

**Xtensa difference:** Xtensa chips use `OCD_ENABLED` register which persists. RISC-V uses `ASSIST_DEBUG_CORE_0_DEBUG_MODE` which only works during halted state.

**Solution:** Always start OpenOCD → then reset chip → then start apptrace

**References:**
- [OpenOCD Issue #188](https://github.com/espressif/openocd-esp32/issues/188)
- [ESP-IDF Issue #18213](https://github.com/espressif/esp-idf/issues/18213)
- [Official FAQ](https://github.com/espressif/openocd-esp32/wiki/Troubleshooting-FAQ#failed-to-start-application-level-tracing-on-riscv-chip)

### 2. Start Apptrace IMMEDIATELY After Reset (1-2 seconds)

**Why:** Firmware waits in a loop checking `esp_apptrace_host_is_connected()`. This example waits up to ~50 seconds (limited by the 50 heartbeats), but real applications may timeout faster. If you start apptrace too late, firmware finishes execution and you capture 0 bytes.

**Solution:** After `reset run`, immediately (within 1-2 seconds) run `esp apptrace start`

### 3. Use Non-Zero Poll Period (1ms recommended)

**Command format:** `esp apptrace start <file> <poll_period> <size> <timeout> <wait4halt> <skip>`

**Example:** `esp apptrace start file:///tmp/log.txt 1 2000 10 0 0`
- `poll_period=1` → OpenOCD checks buffer every 1ms
- `size=2000` → Collect up to 2KB then stop
- `timeout=10` → Stop after 10 seconds

**ESP-IDF examples use 0-3ms poll periods.** 1ms is a safe default.

## Manual OpenOCD Test

### 1. Start OpenOCD

```bash
~/.espressif/tools/openocd-esp32/*/openocd-esp32/bin/openocd \
  -f board/esp32c6-builtin.cfg -l /tmp/openocd.log &
```

### 2. Reset Chip (REQUIRED for RISC-V)

This triggers apptrace control block advertisement via semihosting:

```bash
# Using netcat (macOS doesn't have telnet by default)
echo "reset run" | nc localhost 4444

# Or using telnet if available
# telnet localhost 4444
# > reset run
```

### 3. Wait for Boot

**Wait 5 seconds** for firmware to boot and advertise the apptrace buffer to OpenOCD.

```bash
sleep 5
```

### 4. Start Apptrace

```bash
echo "esp apptrace start file:///tmp/apptrace.log 0 0 10 0 0" | nc localhost 4444
```

Expected output:
```
Total trace memory: 16384 bytes
Open file /tmp/apptrace.log
App trace params: from 1 cores, size 0 bytes, stop_tmo 10 s, poll period 0 ms, wait_rst 0, skip 0 bytes
Connect targets...
[esp32c6] Target halted, PC=0x40804694, debug_reason=00000000
Targets connected.
```

### 4. Monitor Output

In another terminal:

```bash
tail -f /tmp/apptrace.log
```

You should see:
```
[TRACE] beat=1 uptime=100ms heap=265432
[TRACE] beat=2 uptime=200ms heap=265432
[TRACE] beat=3 uptime=300ms heap=265432
...
```

### 5. Stop Capture

In telnet session:

```
esp apptrace stop
```

## EAB Integration (Future)

Once `eab/apptrace_transport.py` is implemented:

```bash
# Start apptrace capture to .rttbin format
eabctl trace start --source apptrace --device esp32c6 -o /tmp/trace.rttbin

# Stop capture
eabctl trace stop

# Export to Perfetto JSON
eabctl trace export -i /tmp/trace.rttbin -o /tmp/trace.json

# Open in https://ui.perfetto.dev
```

## Apptrace Command Format

```
esp apptrace start file://<output_file> <dest> <size> <poll> <skip> <wait>
```

Parameters:
- `file://<path>` - Output file path (must use file:// prefix)
- `<dest>` - Destination channel (0 = TRAX)
- `<size>` - Max size in bytes (0 = unlimited)
- `<poll>` - Poll period in ms (1 = fast)
- `<skip>` - Skip count (0 = no skip)
- `<wait>` - Wait for reset (0 = no wait)

Example:
```
esp apptrace start file:///tmp/apptrace.log 0 0 1 0 0
```

## Troubleshooting

**"Failed to get max trace block size!"**
- **Root cause**: Firmware booted before OpenOCD connected, so control block was not advertised
- **Fix**: Run `reset run` in OpenOCD telnet AFTER OpenOCD starts (see step 2 above)
- **Documentation**: [OpenOCD FAQ - RISC-V Apptrace](https://github.com/espressif/openocd-esp32/wiki/Troubleshooting-FAQ#failed-to-start-application-level-tracing-on-riscv-chip)

**"Target is not connected"**
- Check USB cable
- Verify OpenOCD started successfully
- Look for "Info : Listening on port 4444" in OpenOCD output

**"apptrace write failed"**
- OpenOCD not running or not connected
- Run `esp apptrace start` in telnet session first
- Check firmware calls `esp_apptrace_host_is_attached()` before writing

**No data in output file**
- Verify firmware is running (check UART console - but note port may be busy if OpenOCD running)
- Ensure apptrace task started (wait for "OpenOCD apptrace connected!" log)
- Firmware may be halted after apptrace start - this is a known issue being debugged
- Try increasing poll period or decreasing heartbeat rate
