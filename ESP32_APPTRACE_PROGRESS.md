# ESP32 Apptrace Implementation Progress (Issue #105)

**Date**: 2026-02-15
**Status**: Phase 1 Complete, Phase 2 Ready for Testing

## Completed Work

### Phase 1: Test Firmware ✅

Created `examples/esp32c6-apptrace-test/` with:

- ✅ Firmware source (`main/main.c`)
- ✅ CMake configuration
- ✅ sdkconfig with apptrace enabled (`CONFIG_APPTRACE_ENABLE=y`, `CONFIG_APPTRACE_DEST_JTAG=y`)
- ✅ README with usage instructions
- ✅ Build successful (binary: `build/eab-test-firmware.bin`)

**Firmware features:**
- Waits for OpenOCD connection
- Sends heartbeat every 100ms via `esp_apptrace_write()`
- Logs to both apptrace (JTAG) and UART console
- Ready for Perfetto visualization

**Build output:**
```
eab-test-firmware.bin binary size 0x24880 bytes
Smallest app partition is 0x100000 bytes
0xdb780 bytes (86%) free
```

## Next Steps: Phase 2 Manual Testing

### 1. Identify ESP32-C6 Port

Multiple USB ports detected:
```
/dev/tty.usbmodem0010500636591
/dev/tty.usbmodem0010500636593
/dev/tty.usbmodem101
/dev/tty.usbmodem83303
/dev/tty.usbmodemI2WZW2OTY3RUW3
```

**Action needed**: Determine which port is the ESP32-C6.

Try:
```bash
# List devices with descriptions
system_profiler SPUSBDataType | grep -A 10 "ESP32"

# Or try each port with esptool chip_id
esptool.py --port /dev/tty.usbmodem101 chip_id
esptool.py --port /dev/tty.usbmodem83303 chip_id
# etc.
```

### 2. Flash Firmware

Once ESP32-C6 port is identified:

```bash
source ~/esp/esp-idf/export.sh
cd examples/esp32c6-apptrace-test
idf.py -p /dev/tty.usbmodemXXX flash monitor
```

Expected output:
```
========================================
  ESP32-C6 Apptrace Test Firmware
========================================
High-speed trace streaming via OpenOCD

I (XXX) APPTRACE_TEST: Apptrace test firmware started
I (XXX) APPTRACE_TEST: Chip: ESP32-C6, Cores: 1
I (XXX) APPTRACE_TEST: Waiting for OpenOCD apptrace connection...
```

### 3. Start OpenOCD

In a new terminal:

```bash
~/.espressif/tools/openocd-esp32/v0.12.0-esp32-20240821/openocd-esp32/bin/openocd \
  -f board/esp32c6-builtin.cfg
```

Expected output:
```
Open On-Chip Debugger v0.12.0-esp32-20241016
...
Info : Listening on port 4444 for telnet connections
```

### 4. Connect Telnet and Start Apptrace

In another terminal:

```bash
telnet localhost 4444
```

Then in telnet session:

```
esp apptrace start file:///tmp/apptrace.log 0 0 1 0 0
```

Expected:
```
Targets connected.
```

**Firmware should print:**
```
I (XXX) APPTRACE_TEST: OpenOCD apptrace connected! Starting trace stream...
```

### 5. Monitor Apptrace Output

In another terminal:

```bash
tail -f /tmp/apptrace.log
```

Expected output:
```
[TRACE] beat=1 uptime=100ms heap=265432
[TRACE] beat=2 uptime=200ms heap=265432
[TRACE] beat=3 uptime=300ms heap=265432
...
```

### 6. Stop Capture

In telnet session:

```
esp apptrace stop
```

### ✅ Success Criteria

- [ ] OpenOCD starts and connects to ESP32-C6
- [ ] Telnet command `esp apptrace start` succeeds
- [ ] Firmware prints "OpenOCD apptrace connected!"
- [ ] `/tmp/apptrace.log` contains heartbeat messages
- [ ] Data streams at ~10 Hz (10 messages/second)

## Remaining Phases

Once Phase 2 manual test is successful:

### Phase 3: Python OpenOCD Transport Class

Create `eab/apptrace_transport.py`:
- Manage OpenOCD subprocess
- Send telnet commands to port 4444
- Tail apptrace output file

### Phase 4: Trace Worker

Create `eab/cli/trace/_apptrace_worker.py`:
- Subprocess that starts OpenOCD
- Launches apptrace capture
- Writes to `.rttbin` format

### Phase 5: CLI Integration

Extend `eab/cli/trace/cmd_start.py`:
- Add `--source apptrace` option
- Launch apptrace worker subprocess

### Phase 6: Hardware Testing

Test full pipeline:
```bash
eabctl trace start --source apptrace --device esp32c6 -o /tmp/trace.rttbin
eabctl trace stop
eabctl trace export -i /tmp/trace.rttbin -o /tmp/trace.json
# Open https://ui.perfetto.dev and load trace.json
```

### Phase 7: Documentation

- Update CLAUDE.md with apptrace examples
- Update README.md
- Close GitHub issue #105

## Files Created

```
examples/esp32c6-apptrace-test/
├── CMakeLists.txt
├── sdkconfig.defaults
├── README.md
└── main/
    ├── CMakeLists.txt
    └── main.c

.plan.md (comprehensive implementation plan)
```

## Troubleshooting Notes

### Port Selection Issue

The `eabctl flash` command had issues:
1. Required `--chip esp32c6` flag
2. Detected empty port (EAB daemon not configured for ESP32)
3. Didn't auto-detect ESP-IDF project directory

**Workaround**: Use `idf.py flash` directly for now.

**Future fix**: Update `eab/flash.py` to better detect ESP-IDF projects from directory structure.

### Port Busy Error

Port `/dev/tty.usbmodem101` showed "Resource busy" error.

**Possible causes:**
- Previous monitor session still open
- EAB daemon trying to connect
- macOS cdc_acm driver holding port

**Resolution**: Try different ports or kill processes using `lsof | grep tty.usbmodem`.

## Time Estimate Remaining

- Phase 2 (Manual test): 30 minutes
- Phase 3 (Python transport): 2 hours
- Phase 4 (Worker): 1 hour
- Phase 5 (CLI integration): 1 hour
- Phase 6 (Hardware testing): 1 hour
- Phase 7 (Documentation): 30 minutes

**Total remaining**: ~6 hours
