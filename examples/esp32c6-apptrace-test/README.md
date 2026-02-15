# ESP32-C6 Apptrace Test Firmware

High-speed trace streaming demo using OpenOCD's `esp_apptrace` feature.

## Features

- Periodic heartbeat via apptrace (10 Hz)
- High-throughput JTAG streaming
- Dual logging: JTAG apptrace + UART console
- Ready for Perfetto visualization

## Build and Flash

```bash
# From repo root
eabctl flash examples/esp32c6-apptrace-test
```

## Manual OpenOCD Test

**CRITICAL**: ESP32-C6 (and all RISC-V ESP chips) require the chip to boot AFTER OpenOCD connects. See [OpenOCD Troubleshooting FAQ](https://github.com/espressif/openocd-esp32/wiki/Troubleshooting-FAQ#failed-to-start-application-level-tracing-on-riscv-chip).

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
