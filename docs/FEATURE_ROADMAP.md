# EAB Feature Roadmap

Advanced debugging, HIL, and AI-integration features. EAB is RTOS/chip-agnostic —
these features target Cortex-M broadly (nRF5340, STM32, NXP MCX, etc.) with
Zephyr as the primary reference environment since most new embedded work is moving there.

---

## Feature Index

| # | Feature | Status | Effort | Value |
|---|---------|--------|--------|-------|
| F1 | [Fault Analyze + RTT Context](#f1-fault-analyze--rtt-context) | Pieces exist, not connected | Small | High — demo-able now |
| F2 | [HIL as First-Class Citizen (pytest plugin)](#f2-hil-as-first-class-citizen) | Regression runner exists | Medium | High |
| F3 | [DWT Watchpoint Daemon](#f3-dwt-watchpoint-daemon) | DWT profiling exists | Medium | Novel |
| F4 | [Debug Monitor Mode](#f4-debug-monitor-mode) | Not started | Medium | Critical for BLE |
| F5 | [BLE HIL Steps](#f5-ble-hil-steps) | Not started | Large | Interview wow factor |
| F6 | [MCP Server](#f6-mcp-server) | Not started | Small | Ecosystem reach |
| F7 | [Anomaly Detection](#f7-anomaly-detection) | Pattern matcher exists | Large | Long-term |

---

## F1: Fault Analyze + RTT Context

### Problem

`eabctl fault-analyze` already decodes CFSR/HFSR/MMFAR/BFAR/SFSR fault registers and
parses the exception stack frame. But the output is the crash state only — no context
about what the firmware was doing in the seconds before the crash.

An RTT log capture is almost always running in parallel (`eabctl rtt start`). These two
data streams are never connected.

### Solution

1. **Auto-capture RTT context window** — when `fault-analyze` runs, read the last N lines
   from the RTT log file before the crash timestamp and include them in the report.
2. **AI prompt integration** — pipe fault registers + backtrace + RTT context into a
   structured LLM prompt. Return a `root_cause_hypothesis` field in the JSON output.
3. **Auto-trigger on crash** — the RTT daemon already detects crash patterns
   (`backtrace_patterns.py`). Wire that into an automatic `fault-analyze` invocation,
   so the full report appears in the event stream without any manual steps.

### What Exists

- `eab/fault_analyzer.py` — full pipeline: GDB server → fault registers → decode → FaultReport
- `eab/fault_decoders/cortex_m.py` — CFSR/HFSR/MMFAR/BFAR/SFSR/SFAR bitfields, M33 TrustZone
- `eab/backtrace_patterns.py` — crash detection regexes
- `eab/jlink_rtt.py` + RTT log files in `/tmp/eab-devices/<device>/rtt.log`
- `eab/session_logger.py` — already captures timestamped log lines

### What to Build

```
eab/fault_analyzer.py
  → add: _load_rtt_context(device, lines=100) -> list[str]
  → FaultReport: add context_window: list[str] field
  → add: generate_ai_prompt(report) -> str  (for LLM consumption)

eab/daemon.py (or backtrace_patterns.py)
  → on crash_detected event: auto-invoke analyze_fault(), emit fault_report event

eabctl fault-analyze --json
  → output now includes context_window + ai_prompt fields
```

### CLI Change

```bash
# Today
eabctl fault-analyze --device NRF5340_XXAA_APP --json

# After F1
eabctl fault-analyze --device NRF5340_XXAA_APP --rtt-context 100 --json
# JSON output gains:
# {
#   "fault": { "cfsr": ..., "hfsr": ..., "decoded": [...] },
#   "backtrace": "...",
#   "context_window": ["[00:00:10.123] BT_ERR: ...", ...],
#   "ai_prompt": "You are debugging a Cortex-M33 crash..."
# }
```

### Chip Coverage

All Cortex-M targets. Fault register map is identical across M0+/M3/M4/M7/M23/M33.
C2000 decoder (`fault_decoders/c2000.py`) already handles non-ARM case.

### References

- [ARM Cortex-M Fault Exceptions — Interrupt (Memfault)](https://interrupt.memfault.com/blog/cortex-m-fault-debug)
- `eab/fault_decoders/cortex_m.py` — existing bitfield defs
- `docs/eab-improvements-plan.md` — related G1/G2 improvements

---

## F2: HIL as First-Class Citizen

### Problem

The regression runner (`eab/cli/regression/`) works but feels like a CI script bolted
on top of eabctl. HIL tests aren't pytest tests — they can't use fixtures, parametrize,
share setup/teardown, or integrate with coverage tools. You can't run a single HIL test
with `pytest tests/hw/test_ble.py::test_advertising` the way you would a unit test.

### Solution

A pytest plugin (`eab_pytest`) that:
1. Provides a `hil_device` fixture — manages device lifecycle (flash, reset, teardown)
2. Lets you write HIL tests as normal pytest functions with `assert`
3. Captures RTT output per-test and attaches it to the pytest report on failure
4. Integrates with `--json` output for CI
5. Optional: DWT PC sampling → per-test firmware coverage map

### Design

```python
# tests/hw/test_ble_peripheral.py
import pytest

def test_ble_advertising(hil_device):
    hil_device.flash("examples/nrf5340-ble-peripheral")
    hil_device.reset()
    hil_device.wait("BLE initialized", timeout=10)
    hil_device.wait("Advertising as: EAB-Peripheral", timeout=5)
    hil_device.assert_no_fault()

def test_ble_shell_commands(hil_device):
    hil_device.send("ble status")
    line = hil_device.wait_pattern(r"notify_count=(\d+)", timeout=5)
    assert int(line.group(1)) >= 0

@pytest.mark.parametrize("mode,interval", [
    ("fast", 100), ("slow", 1000)
])
def test_notify_intervals(hil_device, mode, interval):
    hil_device.send(f"ble {mode}")
    # ... check timing via RTT timestamps
```

### pytest Plugin Structure

```
eab/
  pytest_plugin.py          # entry_points: pytest11 = eab = eab.pytest_plugin
  hil/
    __init__.py
    device_fixture.py       # hil_device fixture — wraps HilDevice
    hil_device.py           # HilDevice class: flash/reset/wait/send/assert_no_fault
    rtt_capture.py          # per-test RTT log capture + attach to report
    coverage.py             # DWT PC sampling → coverage.py-compatible .coverage file
```

### conftest.py Setup

```python
# conftest.py (repo root)
import pytest
from eab.hil import HilDevice

@pytest.fixture(scope="session")
def hil_device():
    dev = HilDevice(device="NRF5340_XXAA_APP", probe="jlink")
    yield dev
    dev.teardown()
```

### CI Integration

```yaml
# .github/workflows/hil.yml
- name: Run HIL tests
  run: pytest tests/hw/ --json-report --json-report-file=hil-report.json -v
```

### YAML Runner Compatibility

Existing YAML regression files continue to work via `eabctl regression`. The pytest
plugin is additive — you can mix both styles in the same repo.

### Firmware Coverage (stretch)

DWT has a PC sampling mode: every N cycles, sample the program counter. EAB can
enable this, collect samples, map them to source lines via the ELF, and emit a
`coverage.py`-compatible `.coverage` file. First-ever firmware line coverage from
hardware execution.

### References

- [pytest plugin authoring](https://docs.pytest.org/en/stable/how-to/writing_plugins.html)
- [Memfault firmware test automation](https://interrupt.memfault.com/blog/test-automation-for-embedded-systems)
- `eab/cli/regression/runner.py` — existing runner to wrap
- `eab/cli/regression/steps.py` — step implementations to reuse

---

## F3: DWT Watchpoint Daemon

### Problem

`eabctl profile-function` uses one DWT comparator for cycle counting. The Cortex-M33
(nRF5340) has 4 DWT comparators. The other 3 can watch memory addresses for
read/write access with zero CPU overhead. This is the most powerful debugging capability
most firmware engineers never use.

Current GDB-based approaches require halting the CPU to check watchpoints, which breaks
BLE timing. We want non-halting watchpoints that stream events.

### Solution

A persistent watchpoint daemon mode: EAB programs DWT comparators to watch specified
addresses, polls the DWT_MATCHED status bit via J-Link (without halting), and streams
hit events as JSONL.

```bash
# Watch a variable — stream events when it changes
eabctl dwt watch --device NRF5340_XXAA_APP \
  --address 0x20001234 --size 4 --mode write \
  --label "conn_interval"

# Output (JSONL stream):
{"ts": 1234567, "label": "conn_interval", "addr": "0x20001234", "value": "0x0018"}
{"ts": 1234668, "label": "conn_interval", "addr": "0x20001234", "value": "0x0050"}

# Watch with ELF symbol resolution
eabctl dwt watch --device NRF5340_XXAA_APP \
  --symbol "current_conn_interval" \
  --elf build/zephyr/zephyr.elf \
  --mode write
```

### DWT Comparator Register Map (per comparator n)

```
DWT_COMPn   0xE0001020 + (n*16)  Comparator value
DWT_MASKn   0xE0001024 + (n*16)  Address mask (ignore low bits)
DWT_FUNCTn  0xE0001028 + (n*16)  Function config (read/write/access/PC)
```

`DWT_FUNCTn` encoding:
- `0b0101` = data read watchpoint
- `0b0110` = data write watchpoint
- `0b0111` = data read/write watchpoint
- `0b1100` = PC watchpoint (instruction address)
- bit 24 `MATCHED` = set when comparator fires, cleared on read

### Non-halting Poll Strategy

J-Link can read memory without halting via `JLink.memory_read()`. EAB polls
`DWT_FUNCTn.MATCHED` at ~100Hz — when set, reads the comparator address value
and emits an event. This works while the CPU is running.

For value capture, a second read immediately after MATCHED fires gets the new value.

### GDB Python Watchpoints (halting, conditional)

For cases where you *want* to halt but with filtering:

```bash
# Halt only when conn_interval changes by >20% from previous value
eabctl dwt watch --symbol "conn_interval" --elf zephyr.elf \
  --condition "abs(new - prev) / prev > 0.20" \
  --mode halt
```

This generates a GDB Python watchpoint script and loads it into a persistent GDB session:

```python
# Generated GDB Python script
import gdb

class FilteredWatchpoint(gdb.Breakpoint):
    def __init__(self, symbol, condition_fn):
        super().__init__(symbol, gdb.BP_WATCHPOINT, gdb.WP_WRITE)
        self._prev = None
        self._condition = condition_fn

    def stop(self):
        val = int(gdb.parse_and_eval(self.expression))
        if self._prev is not None and self._condition(val, self._prev):
            print(f"WATCHPOINT HIT: {self.expression} = {val:#x} (prev={self._prev:#x})")
            self._prev = val
            return True   # halt
        self._prev = val
        return False      # continue silently
```

### CLI

```bash
eabctl dwt watch   # non-halting stream mode
eabctl dwt halt    # halting watchpoint with optional condition
eabctl dwt list    # show active comparators
eabctl dwt clear   # release all comparators
```

### References

- [Faster Debugging with Watchpoints — Memfault/Interrupt](https://interrupt.memfault.com/blog/cortex-m-watchpoints)
- [ARM DWT Architecture Reference Manual](https://developer.arm.com/documentation/ddi0403/latest/)
- [GDB Python Watchpoints API](https://sourceware.org/gdb/current/onlinedocs/gdb.html/Breakpoints-In-Python.html)
- `eab/dwt_profiler.py` — existing DWT register access via pylink
- `eab/gdb_bridge.py` — existing GDB batch execution

---

## F4: Debug Monitor Mode

### Problem

Standard Cortex-M debugging halts the entire CPU when a breakpoint fires. For BLE
firmware, this kills the radio timing — the link layer misses connection events and
the central declares supervision timeout. You can't set a breakpoint inside a GATT
callback without disconnecting.

### Solution

Debug Monitor mode runs the debug handler as a Cortex-M exception (configurable
priority, default lowest). Breakpoints fire the `DebugMonitor` exception handler
instead of halting. The CPU keeps running other exceptions at higher priority —
including the BLE Link Layer running at the highest interrupt priority.

On nRF5340: BLE LL runs in the net core (separate CPU). The app core runs the host.
Debug Monitor on the app core keeps app-side BLE host + GATT stack alive. The LL
(net core) is completely unaffected.

### Enabling Debug Monitor

```c
// Zephyr: CONFIG_DEBUG_MONITOR=y in prj.conf
// This enables the DebugMonitor exception and connects it to GDB

// Or manually via DEMCR register:
// DEMCR bit 16 (MON_EN) = enable DebugMonitor exception
// DEMCR bit 17 (MON_PEND) = pend DebugMonitor on next instruction
// DEMCR bit 18 (MON_STEP) = single-step via DebugMonitor
```

J-Link also has a "monitor mode debugging" feature (ARMv8-M, added 2025):
- Configures J-Link to use monitor mode instead of halt mode automatically
- No firmware changes needed if using J-Link GDB server

### EAB Integration

```bash
# Enable monitor mode for a debug session
eabctl debug-monitor enable --device NRF5340_XXAA_APP

# Auto-detect BLE builds and suggest monitor mode
# (check if CONFIG_BT=y in build/zephyr/.config)
eabctl preflight --ble-safe  # warns if BLE build + halt-mode debugging

# Regression YAML
setup:
  - flash:
      firmware: examples/nrf5340-ble-peripheral
      runner: jlink
      debug_mode: monitor  # enables DEMCR MON_EN after flash
```

### Priority Configuration

DebugMonitor exception priority must be lower than BLE LL interrupts
(SWI5, RADIO IRQ, etc. on nRF5340 — typically priority 0-2). Set to 3 or lower.

```bash
eabctl debug-monitor enable --priority 3 --device NRF5340_XXAA_APP
```

### What to Build

```
eab/debug_monitor.py          # enable/disable via DEMCR, configure priority
eab/cli/debug/monitor_cmds.py # eabctl debug-monitor enable/disable/status
```

Wire into:
- `eabctl preflight` — warn when BLE build detected + halt mode active
- Regression YAML `setup:` flash step — `debug_mode: monitor` option
- `eabctl fault-analyze` — fault-analyze should not switch to halt mode if monitor mode active

### References

- [Debug Monitor Mode — Interrupt (Memfault)](https://interrupt.memfault.com/blog/cortex-m-debug-monitor)
- [SEGGER J-Link Monitor Mode Debugging (ARMv8-M)](https://www.segger.com/products/debug-probes/j-link/technology/monitor-mode-debugging/)
- [Zephyr CONFIG_DEBUG_MONITOR](https://docs.nordicsemi.com/bundle/ncs-2.4.3/page/zephyr/services/debugging/debugmon.html)
- ARM ARM: DEMCR register at 0xE000EDFC, MON_EN bit 16

---

## F5: BLE HIL Steps

### Problem

The current HIL regression tests verify the peripheral side only — did it boot, did it
advertise, did it crash? There's no way to test the central side: did a client
successfully connect, subscribe to notifications, receive valid data, send a write
and get the right response?

### Solution

BLE HIL steps that simulate a central (phone/gateway) in regression tests. Two approaches:

#### Option A: Second nRF5340 DK as BLE Central

Flash the second DK with an EAB central fixture firmware. Control it via RTT shell.

```yaml
# tests/hw/test_ble_e2e.yaml
devices:
  peripheral: NRF5340_XXAA_APP
  central: NRF5340_XXAA_APP_2

setup:
  - flash:
      firmware: examples/nrf5340-ble-peripheral
      device: peripheral
  - flash:
      firmware: examples/nrf5340-ble-central-fixture
      device: central

steps:
  - wait:
      pattern: "Advertising as: EAB-Peripheral"
      device: peripheral
      timeout: 10
  - ble_scan:
      device: central
      target_name: "EAB-Peripheral"
      timeout: 10
  - ble_connect:
      device: central
      timeout: 10
  - expect_notify:
      device: central
      char_uuid: "EAB20002"
      count: 5
      timeout: 10
  - ble_write:
      device: central
      char_uuid: "EAB20003"
      value: "01"  # fast mode
  - wait:
      pattern: "mode=fast"
      device: peripheral
      timeout: 5
```

#### Option B: BlueZ on Linux Host

Use the host machine's Bluetooth adapter as the central via BlueZ D-Bus API (Python `dbus`
or `bleak`). No second DK needed — any laptop/RPi with BT adapter works.

```python
# eab/hil/ble_central.py
from bleak import BleakClient, BleakScanner

class BleHilCentral:
    async def scan(self, name, timeout=10) -> BLEDevice: ...
    async def connect(self, device) -> BleakClient: ...
    async def subscribe_notify(self, client, uuid, callback): ...
    async def write(self, client, uuid, value: bytes): ...
    async def read(self, client, uuid) -> bytes: ...
```

```yaml
# tests/hw/test_ble_notify.yaml
steps:
  - ble_central_scan:
      transport: bleak     # uses host BT adapter
      target_name: "EAB-Peripheral"
      timeout: 10
  - ble_central_connect: {}
  - ble_central_subscribe:
      uuid: "EAB20002"
      expect_count: 10
      timeout: 15
  - ble_central_write:
      uuid: "EAB20003"
      value: [0x02]
  - ble_central_read:
      uuid: "EAB20004"
      expect_fields:
        connection_count: {gte: 1}
```

**Recommendation**: Build Option B first (no extra hardware), add Option A as an
extension for multi-device test rigs.

### Dependencies

- `bleak` — cross-platform BLE in Python, works on macOS/Linux/Windows
  - `pip install bleak` — wraps CoreBluetooth / BlueZ / WinRT
  - [https://github.com/hbldh/bleak](https://github.com/hbldh/bleak)
- For Option A: EAB central fixture firmware (new Zephyr example)
  - `examples/nrf5340-ble-central-fixture/` — minimal central that scans, connects, exercises GATT

### What to Build

```
eab/hil/ble_central.py            # BleHilCentral wrapping bleak
eab/cli/regression/ble_steps.py   # ble_central_* YAML step handlers
examples/nrf5340-ble-central-fixture/  # Zephyr central firmware for Option A
```

### References

- [bleak — Bluetooth Low Energy platform-agnostic client](https://github.com/hbldh/bleak)
- [BlueZ D-Bus API](https://git.kernel.org/pub/scm/bluetooth/bluez.git/tree/doc)
- nRF5340 as central: `CONFIG_BT_CENTRAL=y` in Zephyr prj.conf

---

## F6: MCP Server

### Problem

Claude Desktop, Cursor, and any MCP-capable tool can't use eabctl today without
subprocess hacks. An MCP server makes EAB a first-class hardware tool for AI assistants.

### Solution

A thin MCP server that wraps `eabctl --json` commands. One MCP tool per eabctl subcommand.
Server reads JSON output from subprocess and returns it as tool results.

```bash
eabctl mcp serve --port 8888
# Starts MCP server exposing all eabctl commands as tools
```

### Tool Mapping

| MCP Tool | eabctl command | Description |
|---|---|---|
| `flash_firmware` | `eabctl flash` | Flash firmware to device |
| `read_rtt` | `eabctl rtt tail` | Read RTT output |
| `send_command` | `eabctl send` | Send shell command via RTT |
| `fault_analyze` | `eabctl fault-analyze --json` | Decode fault registers + RTT context |
| `get_status` | `eabctl status --json` | Device + daemon health |
| `reset_device` | `eabctl reset` | Reset target |
| `run_regression` | `eabctl regression --json` | Run HIL test suite |
| `read_variable` | `eabctl read-vars` | Read live variable via GDB |
| `dwt_watch` | `eabctl dwt watch` | Set hardware watchpoint |
| `profile_function` | `eabctl profile-function` | Measure function execution time |
| `wait_pattern` | `eabctl wait` | Block until pattern in RTT output |
| `get_alerts` | `eabctl alerts --json` | Recent crash/error events |

### Implementation

```python
# eab/mcp_server.py
from mcp.server import Server
from mcp.types import Tool, TextContent
import subprocess, json

server = Server("eab")

@server.list_tools()
async def list_tools():
    return [
        Tool(name="flash_firmware",
             description="Flash firmware to embedded target",
             inputSchema={...}),
        ...
    ]

@server.call_tool()
async def call_tool(name: str, arguments: dict):
    cmd = _build_eabctl_cmd(name, arguments)
    result = subprocess.run(cmd, capture_output=True, text=True)
    return [TextContent(type="text", text=result.stdout)]
```

### Dependencies

- `mcp` Python SDK: `pip install mcp`
- [MCP Python SDK](https://github.com/modelcontextprotocol/python-sdk)
- [MCP spec](https://modelcontextprotocol.io/introduction)

### What to Build

```
eab/mcp_server.py          # server definition + tool handlers
eab/cli/mcp_cmd.py         # eabctl mcp serve
```

Install extra: `pip install embedded-agent-bridge[mcp]`

---

## F7: Anomaly Detection

### Problem

RTT log streams contain rich timing and state information, but no tooling currently
watches for statistical deviations — only exact pattern matches. Issues that manifest
as "things got weird" (interrupt latency drift, BLE event spacing, slow GATT responses)
are invisible to current alerting.

### Solution

Two-phase approach:

#### Phase 1: Baseline + Diff (no ML)

Record a "golden run" — a reference RTT trace of known-good firmware behavior.
On subsequent runs, compare timing distributions and event frequencies.

```bash
# Record golden baseline
eabctl anomaly record --device NRF5340_XXAA_APP \
  --duration 60 --output baselines/ble_peripheral_nominal.json

# Compare live run against baseline
eabctl anomaly compare --device NRF5340_XXAA_APP \
  --baseline baselines/ble_peripheral_nominal.json \
  --duration 30 --json
```

What to baseline:
- Message frequency per log module (BT/ATT, BT/CONN, BT/SMP per second)
- Event inter-arrival times (connection events, notification sends)
- Warning/error rate (WRN/ERR lines per minute)
- Specific numeric values extracted from log lines (counter=N, interval=N ms)

#### Phase 2: Streaming Anomaly Detection (lightweight ML)

Run a simple EWMA (Exponentially Weighted Moving Average) or isolation forest on
the RTT event stream in real-time. No model upload required — computed locally.

```bash
eabctl anomaly watch --device NRF5340_XXAA_APP \
  --metric "bt_notification_interval_ms" \
  --threshold 2.5sigma  # alert if >2.5 std devs from rolling mean
```

### Event Extraction Schema

```python
# Extend eab/pattern_matcher.py with numeric extraction
METRIC_PATTERNS = {
    "bt_notify_count":    r"notify_count=(\d+)",
    "bt_conn_interval":   r"Interval:\s+(\d+)\s+ms",
    "bt_mtu":             r"MTU exchanged:\s+(\d+)",
    "bt_backpressure":    r"TX buffer full",          # count occurrences
    "zephyr_heap_free":   r"heap_free=(\d+)",
    "rtt_timestamp_ms":   r"^\[(\d+):(\d+):(\d+\.\d+)\]",  # for timing
}
```

### HIL Integration

Anomaly detection as a regression step:

```yaml
steps:
  - reset: {}
  - wait:
      pattern: "Advertising as: EAB-Peripheral"
  - anomaly_watch:
      duration: 30
      baseline: tests/baselines/ble_nominal.json
      max_sigma: 2.0
      fail_on_anomaly: true
```

### References

- [Continuous Observability for RTOS Firmware — embedded.com](https://www.embedded.com/continuous-observability-for-debugging-rtos-based-firmware/)
- [Memfault — fleet observability](https://memfault.com/)
- [AI-Assisted Debugging 2026 — Promwad](https://promwad.com/news/ai-assisted-debugging-2026-anomaly-detection-firmware)
- `eab/pattern_matcher.py` — existing pattern matching infrastructure
- `eab/analyzers/perfetto_export.py` — timestamped event stream already available

---

## Implementation Notes

### Chip Agnosticism

All features should work across:
- **nRF5340** (Cortex-M33, J-Link SWD, Zephyr)
- **STM32** (Cortex-M4/M7/M33, OpenOCD + ST-Link, Zephyr or bare-metal)
- **NXP MCX** (Cortex-M33, OpenOCD CMSIS-DAP, Zephyr)
- **nRF52840** (Cortex-M4, J-Link SWD, Zephyr or SoftDevice)

DWT register map is identical across all Cortex-M3/M4/M7/M33 — one implementation covers all.
Debug Monitor mode requires ARMv7-M or ARMv8-M (all of the above).

### Zephyr-Specific Notes

Zephyr is the primary reference environment because:
- `prj.conf` is machine-parseable — EAB can auto-detect BLE builds, debug configs
- Zephyr shell via RTT is already implemented
- `CONFIG_DEBUG_MONITOR` exists upstream
- West + MCUboot + dual-core flash is all handled by EAB already

Non-Zephyr targets get the same features; just no prj.conf auto-detection.

### Dependency Strategy

Keep core EAB minimal. Gate optional dependencies behind extras:

```toml
[project.optional-dependencies]
jlink   = ["pylink-square"]          # DWT, fault-analyze, watchpoints
bleak   = ["bleak"]                  # BLE HIL central (F5)
mcp     = ["mcp"]                    # MCP server (F6)
anomaly = ["scipy", "numpy"]         # Phase 2 anomaly detection (F7)
hil     = ["pytest", "pytest-json-report"]  # HIL pytest plugin (F2)
```

---

## Branch Strategy

Each feature gets its own branch off `main`:

| Branch | Feature |
|---|---|
| `feat/fault-rtt-context` | F1 |
| `feat/hil-pytest-plugin` | F2 |
| `feat/dwt-watchpoint-daemon` | F3 |
| `feat/debug-monitor-mode` | F4 |
| `feat/ble-hil-steps` | F5 |
| `feat/mcp-server` | F6 |
| `feat/anomaly-detection` | F7 |
