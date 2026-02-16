# EAB Modular Test Suite

Isolated, modular tests for each device type. Each test can run standalone or be orchestrated together.

## Philosophy

1. **Isolated** - Each device test is independent, no shared state
2. **Modular** - Add new device tests without touching existing ones
3. **Discoverable** - Auto-detect connected hardware
4. **Composable** - Run individually or orchestrated together

## Structure

```
tests/
├── device_discovery.py      # Auto-detect connected devices
├── test_esp32.py             # ESP32 family tests (C6, P4, S3)
├── test_nrf.py               # nRF5340 tests
├── test_stm32.py             # STM32 family tests (TODO)
├── test_nxp.py               # NXP MCX family tests (TODO)
├── test_c2000.py             # TI C2000 tests (TODO)
└── run_all_tests.py          # Main orchestrator
```

## Usage

### Discover Devices

```bash
# List all connected devices
python3 tests/device_discovery.py

# Find specific chip
python3 tests/device_discovery.py --chip esp32c6

# JSON output
python3 tests/device_discovery.py --json
```

### Test Individual Device

```bash
# ESP32-C6
python3 tests/test_esp32.py --chip esp32c6 --duration 30

# ESP32-P4
python3 tests/test_esp32.py --chip esp32p4 --duration 30

# nRF5340
python3 tests/test_nrf.py --duration 30

# JSON output
python3 tests/test_esp32.py --chip esp32c6 --json
```

### Run All Tests

```bash
# Test all connected devices
python3 tests/run_all_tests.py

# Test specific devices only
python3 tests/run_all_tests.py --devices esp32c6,nrf5340

# Custom duration
python3 tests/run_all_tests.py --duration 60

# JSON output
python3 tests/run_all_tests.py --json
```

## Adding a New Device Test

1. Create `test_<family>.py` (copy template from `test_esp32.py`)
2. Implement test class with these methods:
   - `flash()` - Flash firmware
   - `collect_data(duration)` - Collect debug output
   - `run_full_test(duration)` - Full test sequence
3. Add import and case to `run_all_tests.py`
4. Update `device_discovery.py` with chip identification logic

## Test Output

Each test saves output to `/tmp/eab-test-<chip>.log`

All tests aggregate results to `/tmp/eab-test-results.json`

## Examples

### Quick ESP32-C6 smoke test
```bash
python3 tests/test_esp32.py --chip esp32c6 --duration 10
```

### Overnight stress test
```bash
python3 tests/run_all_tests.py --duration 3600
```

### CI/CD integration
```bash
python3 tests/run_all_tests.py --json && cat /tmp/eab-test-results.json
```
