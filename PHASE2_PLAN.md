# Phase 2: Host Tools Integration

**Status:** Ready to Start
**Estimated Time:** 1-2 days
**Dependencies:** Phase 0 & 1 Complete ✅

## Objectives

Integrate existing trace decoder tools into EAB for automated trace export to Perfetto JSON.

**Key Principle:** Don't write custom decoders - wrap existing tools!

## Tasks

### Task 1: ESP32 SystemView Integration

#### 1.1 Locate and Test sysviewtrace_proc.py
- **File:** `$IDF_PATH/tools/esp_app_trace/sysviewtrace_proc.py`
- **Already found:** ✅ `research/phase0/source-examples/esp-idf/tools/esp_app_trace/sysviewtrace_proc.py`

**Test manually:**
```bash
# Capture SystemView trace
$IDF_PATH/tools/esp_app_trace/sysviewtrace_proc.py /dev/ttyACM0 -o /tmp/trace.svdat

# Convert to Perfetto JSON
$IDF_PATH/tools/esp_app_trace/sysviewtrace_proc.py /tmp/trace.svdat -p -o /tmp/trace.json

# Verify in Perfetto UI
open https://ui.perfetto.dev
```

#### 1.2 Integrate into eabctl
**Goal:** `eabctl trace export` auto-detects SystemView format

```python
# In eab/cli/trace/export.py or new file

import subprocess
import os
from pathlib import Path

def export_systemview_to_perfetto(input_file: str, output_file: str) -> bool:
    """Export ESP32 SystemView trace to Perfetto JSON"""

    # Find sysviewtrace_proc.py
    idf_path = os.environ.get('IDF_PATH')
    if not idf_path:
        raise RuntimeError("ESP-IDF not found (IDF_PATH not set)")

    tool = Path(idf_path) / "tools/esp_app_trace/sysviewtrace_proc.py"
    if not tool.exists():
        raise RuntimeError(f"sysviewtrace_proc.py not found at {tool}")

    # Run conversion
    cmd = ["python3", str(tool), input_file, "-p", "-o", output_file]
    result = subprocess.run(cmd, capture_output=True, text=True)

    if result.returncode != 0:
        raise RuntimeError(f"Conversion failed: {result.stderr}")

    return True
```

**Integration:**
```python
# In existing eabctl trace export command

def export_trace(input_file, output_file, format="perfetto"):
    """Export trace to specified format"""

    # Auto-detect trace format
    trace_format = detect_trace_format(input_file)

    if trace_format == "systemview":
        export_systemview_to_perfetto(input_file, output_file)
    elif trace_format == "ctf":
        export_ctf_to_perfetto(input_file, output_file)
    else:
        # Fallback: line-based log export
        export_logs_to_perfetto(input_file, output_file)
```

**Format Detection:**
```python
def detect_trace_format(input_file: str) -> str:
    """Detect trace file format"""

    with open(input_file, 'rb') as f:
        header = f.read(16)

    # SystemView magic bytes
    if b'SEGGER' in header or b'SystemView' in header:
        return "systemview"

    # CTF magic bytes
    if header[:4] == b'\xC1\x1F\xFC\xC1':  # CTF magic
        return "ctf"

    # Check for metadata.txt (Zephyr CTF)
    parent = Path(input_file).parent
    if (parent / "metadata").exists():
        return "ctf"

    # Default to log-line format
    return "log"
```

### Task 2: Zephyr CTF Integration

#### 2.1 Install and Test babeltrace
```bash
# macOS
brew install babeltrace

# Ubuntu
sudo apt-get install babeltrace

# Test
babeltrace /path/to/ctf-trace/
```

#### 2.2 Test CTF to Perfetto Conversion
**Option A:** Use babeltrace + custom parser
```bash
babeltrace /tmp/trace.ctf --format json > /tmp/trace-ctf.json
# Then convert JSON to Perfetto format
```

**Option B:** Use Perfetto's CTF importer directly
```python
# Perfetto UI can import CTF directly
# Just need to package CTF trace correctly
```

#### 2.3 Integrate into eabctl
```python
def export_ctf_to_perfetto(input_file: str, output_file: str) -> bool:
    """Export Zephyr CTF trace to Perfetto JSON"""

    # Check if babeltrace is available
    if not shutil.which("babeltrace"):
        raise RuntimeError("babeltrace not found. Install: brew install babeltrace")

    # Convert CTF to JSON
    cmd = ["babeltrace", input_file, "--format", "json"]
    result = subprocess.run(cmd, capture_output=True, text=True)

    if result.returncode != 0:
        raise RuntimeError(f"babeltrace failed: {result.stderr}")

    # Parse and convert to Perfetto format
    ctf_json = json.loads(result.stdout)
    perfetto_json = convert_ctf_to_perfetto_format(ctf_json)

    with open(output_file, 'w') as f:
        json.dump(perfetto_json, f)

    return True

def convert_ctf_to_perfetto_format(ctf_json: dict) -> dict:
    """Convert babeltrace JSON to Perfetto JSON format"""

    # Perfetto JSON format structure
    perfetto = {
        "traceEvents": [],
        "displayTimeUnit": "ns",
        "systemTraceEvents": {
            "cpus": []
        }
    }

    # Parse CTF events and convert to Perfetto trace events
    for event in ctf_json.get("events", []):
        perfetto_event = {
            "name": event.get("name", "unknown"),
            "cat": "kernel",
            "ph": "i",  # Instant event
            "ts": event.get("timestamp", 0) / 1000,  # Convert to microseconds
            "pid": event.get("pid", 0),
            "tid": event.get("tid", 0),
            "s": "t"
        }
        perfetto["traceEvents"].append(perfetto_event)

    return perfetto
```

### Task 3: End-to-End Validation

#### 3.1 Test ESP32 Pipeline
```bash
# Flash ESP32-C6 debug-full firmware
eabctl flash examples/esp32c6-debug-full

# Capture SystemView trace (manual for now)
$IDF_PATH/tools/esp_app_trace/logtrace_proc.py /dev/ttyACM0 -o /tmp/esp32-trace.svdat

# Export to Perfetto using new integration
eabctl trace export -i /tmp/esp32-trace.svdat -o /tmp/esp32-trace.json

# Verify
ls -lh /tmp/esp32-trace.json
head -20 /tmp/esp32-trace.json

# Load in Perfetto UI
open https://ui.perfetto.dev
# Upload /tmp/esp32-trace.json
```

**Expected Result:**
- Perfetto shows timeline with multiple tasks
- Task switching events visible
- Custom events (compute, IO, alloc) visible
- CPU utilization metrics

#### 3.2 Test Zephyr Pipeline
```bash
# Flash nRF5340 debug-full firmware
eabctl flash --chip nrf5340 --runner jlink

# Start RTT and capture CTF trace
eabctl rtt start --device NRF5340_XXAA_APP --transport jlink
eabctl trace start --source rtt -o /tmp/nrf-trace.ctf --device NRF5340_XXAA_APP
sleep 15
eabctl trace stop

# Export to Perfetto using new integration
eabctl trace export -i /tmp/nrf-trace.ctf -o /tmp/nrf-trace.json

# Verify
ls -lh /tmp/nrf-trace.json
head -20 /tmp/nrf-trace.json

# Load in Perfetto UI
open https://ui.perfetto.dev
# Upload /tmp/nrf-trace.json
```

**Expected Result:**
- Perfetto shows timeline with multiple threads
- Thread scheduling events visible
- Custom trace events visible
- System work queue activity

### Task 4: Automated Testing

#### 4.1 Create Test Script
**File:** `scripts/test-trace-pipeline.sh`

```bash
#!/bin/bash
# Test trace capture and export pipeline

set -e

echo "=== Testing Trace Pipeline ==="

# Test ESP32 SystemView
if [ -f examples/esp32c6-debug-full/build/eab-test-firmware.bin ]; then
    echo "Testing ESP32-C6 trace pipeline..."

    # Flash
    eabctl flash examples/esp32c6-debug-full

    # Capture trace (TODO: integrate apptrace into eabctl)
    # For now, manual capture

    # Export
    if [ -f /tmp/esp32-trace.svdat ]; then
        eabctl trace export -i /tmp/esp32-trace.svdat -o /tmp/esp32-trace.json
        echo "✓ ESP32 trace exported"
    fi
fi

# Test Zephyr CTF
if command -v west &> /dev/null; then
    echo "Testing nRF5340 trace pipeline..."

    # Build and flash
    cd examples/nrf5340-debug-full
    west build -b nrf5340dk/nrf5340/cpuapp
    west flash --runner jlink
    cd ../..

    # Capture trace
    eabctl rtt start --device NRF5340_XXAA_APP --transport jlink
    eabctl trace start --source rtt -o /tmp/nrf-trace.ctf --device NRF5340_XXAA_APP
    sleep 15
    eabctl trace stop
    eabctl rtt stop

    # Export
    eabctl trace export -i /tmp/nrf-trace.ctf -o /tmp/nrf-trace.json
    echo "✓ nRF5340 trace exported"
fi

echo "=== Pipeline Tests Complete ==="
```

#### 4.2 Add to E2E Test Suite
Update `scripts/test-debug-examples-e2e.sh` to include trace export validation.

## Implementation Order

1. **Day 1 Morning:** Task 1 - ESP32 SystemView integration
2. **Day 1 Afternoon:** Task 2 - Zephyr CTF integration
3. **Day 2 Morning:** Task 3 - End-to-end validation
4. **Day 2 Afternoon:** Task 4 - Automated testing

## Success Criteria

- [ ] `eabctl trace export` command works
- [ ] Auto-detects trace format (SystemView, CTF, log)
- [ ] ESP32 traces export to valid Perfetto JSON
- [ ] Zephyr traces export to valid Perfetto JSON
- [ ] Perfetto UI loads and displays traces correctly
- [ ] Timeline shows tasks/threads
- [ ] Custom events visible
- [ ] Automated test script passes

## Files to Create/Modify

```
eab/cli/trace/
├── export.py           (NEW or MODIFY)
├── formats.py          (NEW - format detection)
├── converters/         (NEW)
│   ├── systemview.py   (SystemView → Perfetto)
│   └── ctf.py          (CTF → Perfetto)

scripts/
└── test-trace-pipeline.sh  (NEW)

tests/
└── test_trace_export.py     (NEW - unit tests)
```

## Dependencies

### Required Tools
- [x] ESP-IDF (for sysviewtrace_proc.py)
- [ ] babeltrace (`brew install babeltrace`)
- [x] Python 3.8+
- [x] eabctl

### Required Knowledge
- [x] SystemView format (researched)
- [x] CTF format (researched)
- [x] Perfetto JSON format (need to study)
- [x] Tool locations (documented)

## Risks & Mitigations

**Risk:** Perfetto JSON format complex
**Mitigation:** Start with simple events, add features incrementally

**Risk:** babeltrace output format may vary
**Mitigation:** Test with multiple Zephyr trace versions

**Risk:** SystemView traces may be large
**Mitigation:** Add streaming/chunking support if needed

## Next Phase Preview

After Phase 2, we move to:
- **Phase 3:** Regression test framework with trace validation
- **Phase 4:** Full validation and documentation

## References

- ESP-IDF sysviewtrace_proc.py: `research/phase0/source-examples/esp-idf/tools/esp_app_trace/`
- Zephyr CTF docs: `research/phase0/zephyr-tracing.md`
- Perfetto docs: `research/phase0/perfetto-ctf.md`
- babeltrace man page: `man babeltrace`

## Ready to Start!

All research complete, all tools located, plan documented.
Ready to implement Phase 2 - Host Tools Integration.
