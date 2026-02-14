# EAB Hardware Regression Test Plan

**Purpose:** Validate all refactored CLI packages work correctly with real hardware after code changes.

**Frequency:** Run before every release, after major refactorings, or when modifying CLI packages.

---

## Prerequisites

### Hardware Requirements

| Board | Connection | Port Pattern | Purpose |
|-------|-----------|--------------|---------|
| ESP32-C6 DevKit | USB Serial/JTAG | `/dev/cu.usbmodem*` | Serial I/O, Flash |
| STM32L4 + ST-Link | USB ST-Link | `/dev/cu.usbmodem*` | Flash, Debug |
| nRF5340 DK | J-Link SWD | Detected by `JLinkExe` | RTT, DWT Profiling |
| FRDM-MCXN947 | OpenOCD CMSIS-DAP | `/dev/cu.usbmodem*` | Debug, Profiling |

**Minimum:** At least 1 board with serial I/O (ESP32-C6 or similar) for basic testing.

### Software Requirements

```bash
# Check prerequisites
which eabctl
which python3
which JLinkExe  # For J-Link tests
which openocd   # For OpenOCD tests
pip show embedded-agent-bridge
```

### Clean State

```bash
# Stop any running daemons
eabctl stop
pkill -f "eab.*daemon"

# Pull latest main
git checkout main
git pull origin main
git status  # Verify clean

# Reinstall from source
python3 -m pip install -e . --force-reinstall --no-deps --break-system-packages
```

---

## Test Categories

### 1. Package Imports (5 packages)

**Purpose:** Verify all refactored packages install and import correctly.

**Test:**
```bash
python3 << 'EOF'
packages = [
    ("flash", ["cmd_flash", "cmd_erase", "cmd_chip_info"]),
    ("daemon", ["cmd_start", "cmd_stop", "cmd_diagnose"]),
    ("debug", ["cmd_openocd_start", "cmd_gdb", "cmd_inspect"]),
    ("serial", ["cmd_status", "cmd_tail", "cmd_send"]),
    ("profile", ["cmd_profile_function", "cmd_dwt_status"]),
]

for pkg, funcs in packages:
    mod = __import__(f"eab.cli.{pkg}", fromlist=funcs)
    for func in funcs:
        assert hasattr(mod, func), f"{pkg}.{func} not found"
    print(f"✓ {pkg}")
EOF
```

**Expected:** All 5 packages import without errors.

---

### 2. Unit Tests

**Purpose:** Verify refactored code passes all unit tests.

**Test:**
```bash
python3 -m pytest tests/test_cli_daemon_cmds.py \
                  tests/test_cli_debug_gdb_commands.py \
                  tests/test_cli_profile_cmds.py \
                  -v --tb=line
```

**Expected:**
- `test_cli_daemon_cmds.py`: 10+ tests pass
- `test_cli_debug_gdb_commands.py`: 12+ tests pass
- `test_cli_profile_cmds.py`: 43 tests pass

**Acceptable failures:** Pre-existing failures (check TESTING.md for known issues).

---

### 3. Daemon Lifecycle (daemon/ package)

**Purpose:** Verify daemon can start, monitor, and stop.

**Test:**
```bash
# Start daemon
eabctl start --port auto

# Check status
eabctl status --json

# Diagnose
eabctl diagnose

# Stop daemon
eabctl stop
```

**Expected:**
- Start returns `"started": true` with PID
- Status shows `"connection.status": "connected"`
- Diagnose lists checks with pass/fail status
- Stop returns `"stopped": true`

---

### 4. Serial I/O (serial/ package)

**Purpose:** Verify serial monitoring and interaction commands.

**Test:**
```bash
# Start daemon first
eabctl start --port auto
sleep 2

# Monitor output
eabctl tail 10

# Send command
eabctl send "help"

# View alerts
eabctl alerts 5

# View events
eabctl events 5
```

**Expected:**
- `tail` shows recent device output
- `send` prints "sent: <command>"
- `alerts` shows error/warning lines (or empty if none)
- `events` shows JSONL event stream

---

### 5. Flash Operations (flash/ package)

**Purpose:** Verify flash commands work (without actually flashing to preserve device state).

**Test:**
```bash
# Preflight check
eabctl preflight-hw

# Chip info (ESP32 only)
eabctl chip-info

# NOTE: Do NOT run full flash during regression test
# (preserves device firmware)
```

**Expected:**
- `preflight-hw` lists readiness checks
- `chip-info` shows chip type, MAC, features (ESP32 only)

**For full flash test** (destructive - requires reflashing after):
```bash
# Build test firmware first
cd examples/esp32c6-test-firmware
idf.py build
cd ../..

# Flash
eabctl flash examples/esp32c6-test-firmware
```

---

### 6. Debug Commands (debug/ package)

**Purpose:** Verify debug package imports (full debug tests require OpenOCD/GDB setup).

**Test:**
```bash
# Import test
python3 -c "from eab.cli.debug import cmd_openocd_start, cmd_gdb, cmd_inspect; print('OK')"

# OpenOCD start (requires target connected)
# eabctl openocd start --chip stm32l4

# GDB batch (requires ELF + probe)
# eabctl gdb batch --chip stm32l4 --elf build/firmware.elf --command "info registers"
```

**Expected:**
- Imports succeed
- OpenOCD/GDB tests require hardware setup (optional)

---

### 7. DWT Profiling (profile/ package)

**Purpose:** Verify profiling commands work with J-Link targets.

**Test:**
```bash
# Import test
python3 -c "from eab.cli.profile import cmd_profile_function, cmd_dwt_status; print('OK')"

# DWT status (requires J-Link + nRF/STM32 target)
eabctl dwt-status --device NRF5340_XXAA_APP --json

# Profile function (requires ELF + target running)
# eabctl profile-function --function main --device NRF5340_XXAA_APP --elf build/zephyr.elf
```

**Expected:**
- Imports succeed
- `dwt-status` shows DWT register state (if J-Link connected)
- Full profiling tests require running firmware

---

### 8. CLI Entry Points

**Purpose:** Verify CLI binaries are installed correctly.

**Test:**
```bash
# Help
eabctl --help

# Version
eabctl --version

# Invalid command (should show error)
eabctl nonexistent 2>&1 | grep "invalid choice"
```

**Expected:**
- `--help` shows usage
- `--version` shows version number
- Invalid commands show helpful error

---

## Quick Regression Test Script

For rapid validation, use the automated script:

```bash
# Run full regression suite
bash tests/regression_test.sh

# Expected output:
# ✓ J-Link probe detected
# ✓ All 5 packages import successfully
# ✓ Unit tests passed
# ✓ Daemon started
# ✓ Tail command works
# ✓ Send command works
# ...
# ✓ All tests passed!
```

The script tests all packages with minimal hardware requirements (1 USB serial board).

---

## Test Results Template

```markdown
## Regression Test Results

**Date:** YYYY-MM-DD
**Branch:** main
**Commit:** <hash>
**Tester:** <name>

### Hardware
- [ ] ESP32-C6 DevKit
- [ ] STM32L4 + ST-Link
- [ ] nRF5340 DK
- [ ] FRDM-MCXN947

### Results
- [ ] Package imports (5/5)
- [ ] Unit tests (pass/fail)
- [ ] Daemon lifecycle
- [ ] Serial I/O
- [ ] Flash commands
- [ ] Debug commands
- [ ] Profile commands
- [ ] CLI entry points

### Issues Found
(List any failures or unexpected behavior)

### Sign-off
- [ ] All critical tests passed
- [ ] Safe to merge/release
```

---

## Troubleshooting

### "Port is busy"
```bash
# Stop daemon and kill stale processes
eabctl stop
pkill -f "eab.*daemon"
```

### "Package not found"
```bash
# Reinstall EAB
python3 -m pip install -e . --force-reinstall --no-deps --break-system-packages
```

### "No boards detected"
```bash
# List USB devices
ls /dev/cu.usb*

# Check J-Link
JLinkExe -CommandFile <(echo "exit")
```

### "Tests hang"
```bash
# Increase timeout in pytest
python3 -m pytest --timeout=60 tests/

# Check for zombie daemons
ps aux | grep eab
```

---

## Integration with CI/CD

For automated testing (future):

```yaml
# .github/workflows/hardware-test.yml
name: Hardware Regression Tests

on:
  push:
    branches: [ main ]
  pull_request:
    branches: [ main ]

jobs:
  test:
    runs-on: self-hosted  # Requires hardware attached
    steps:
      - uses: actions/checkout@v3
      - name: Install EAB
        run: pip install -e .
      - name: Run regression tests
        run: bash tests/regression_test.sh
```

**Note:** Requires self-hosted runner with boards attached.

---

## Maintenance

**Update this document when:**
- Adding new CLI packages
- Changing test requirements
- Discovering new edge cases
- Adding hardware platforms

**Review schedule:** After each major refactoring or quarterly.
