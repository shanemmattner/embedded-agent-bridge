# Regression Testing — Hardware-in-the-Loop

Every embedded team eventually builds bash scripts to validate firmware on real hardware. Flash, reset, wait for output, check variables, repeat. These scripts are fragile, unportable, and produce output that's hard to parse in CI.

`eabctl regression` replaces those scripts. Define tests in YAML, run them against real boards, get structured JSON results. Each step shells out to `eabctl --json` — the same commands you'd run manually — so there's nothing new to learn and nothing that works differently in CI vs. locally.

## Quick Start

```bash
# Install (PyYAML is the only extra dependency)
pip install pyyaml

# Run a single test
eabctl regression --test tests/hw/smoke.yaml --json

# Run all tests in a directory
eabctl regression --suite tests/hw/ --json

# Filter by filename pattern
eabctl regression --suite tests/hw/ --filter "*nrf*" --json
```

## Why YAML, Not Python?

Python test frameworks (pytest, unittest) are great for software. For hardware tests, you want:

1. **Non-programmers can write tests.** A QA engineer or a field tech can edit YAML. They can't debug pytest fixtures.
2. **Tests are data, not code.** You can generate them, template them, diff them, and review them without understanding Python.
3. **CI sees structure.** The JSON output has per-step timing, pass/fail, and error details — no log parsing required.
4. **Same commands everywhere.** Each YAML step maps 1:1 to an `eabctl` command. If you can run it in a terminal, you can put it in a test.

## Writing Tests

A test file is a YAML document with a name, optional device/chip, and three phases: setup, steps, and teardown.

```yaml
name: nRF5340 Hello World
device: nrf5340              # EAB device name (resolves base_dir)
chip: nrf5340                # Passed to flash/reset/fault commands
timeout: 60                  # Default timeout per step (seconds)

setup:
  - flash:
      firmware: samples/hello_world
      runner: jlink

steps:
  - reset: {}
  - wait:
      pattern: "Hello from"
      timeout: 10
  - send:
      text: "status"
      await_ack: true
  - wait:
      pattern: "OK"
      timeout: 5
  - read_vars:
      elf: build/zephyr/zephyr.elf
      vars:
        - name: error_count
          expect_eq: 0
        - name: heap_free
          expect_gt: 1024
  - fault_check:
      elf: build/zephyr/zephyr.elf
      expect_clean: true
  - sleep:
      seconds: 2

teardown:
  - reset: {}
```

### Execution Model

- **Setup** runs first. Any failure stops setup and skips all steps.
- **Steps** run in order. First failure stops execution (remaining steps skipped).
- **Teardown** always runs, even if setup or steps failed. Teardown errors are logged but don't change the test's pass/fail status.

This means your board always gets cleaned up (reset, power-cycled, etc.) regardless of what happened during the test.

## Step Reference

### flash

Flash firmware to the device. Maps to `eabctl flash`.

```yaml
- flash:
    firmware: samples/hello_world    # Path to firmware (project dir or binary)
    chip: nrf5340                    # Target chip (optional if set at test level)
    runner: jlink                    # Flash runner (jlink, openocd, esptool)
    address: "0x08000000"            # Flash address (optional)
```

### reset

Reset the device. Maps to `eabctl reset`.

```yaml
- reset: {}                          # Default reset
- reset:
    chip: nrf5340                    # Override chip
    method: pin                      # Reset method (pin, software)
```

### send

Send a text command to the device. Maps to `eabctl send`.

```yaml
- send:
    text: "status"                   # Text to send
    await_ack: true                  # Wait for command acknowledgment
    timeout: 5                       # Timeout in seconds
```

### wait

Wait for a pattern in serial output. Maps to `eabctl wait`.

```yaml
- wait:
    pattern: "Ready"                 # Regex or literal pattern
    timeout: 10                      # Timeout in seconds
```

### assert_log

Alias for `wait`. Use this name when checking output feels more like an assertion than waiting.

```yaml
- assert_log:
    pattern: "Booted successfully"
    timeout: 5
```

### wait_event

Wait for a structured event in events.jsonl. Maps to `eabctl wait-event`.

```yaml
- wait_event:
    event_type: command_result       # Event type to match
    contains: "OK"                   # Substring match on event JSON
    timeout: 10
```

### sleep

Pause for a fixed duration. No subprocess — just `time.sleep()`.

```yaml
- sleep:
    seconds: 2
```

### read_vars

Read variables from device memory and validate against expectations. Maps to `eabctl read-vars`.

```yaml
- read_vars:
    elf: build/zephyr/zephyr.elf     # ELF file for symbol lookup
    vars:
      - name: error_count
        expect_eq: 0                 # Must equal this value
      - name: heap_free
        expect_gt: 1024              # Must be greater than
      - name: temperature
        expect_lt: 85                # Must be less than
```

All assertions in a single `read_vars` step are checked. If any fail, the step fails and reports which variables didn't match.

### fault_check

Check for Cortex-M fault conditions. Maps to `eabctl fault-analyze`.

```yaml
- fault_check:
    elf: build/zephyr/zephyr.elf     # ELF for crash decoding
    expect_clean: true               # Fail if any fault detected
```

Set `expect_clean: false` if you're testing that a fault *should* occur (e.g., testing a crash handler).

## Output Format

```json
{
  "passed": 2,
  "failed": 1,
  "skipped": 0,
  "duration_ms": 15234,
  "results": [
    {
      "name": "nRF5340 Hello World",
      "file": "tests/hw/nrf5340_hello.yaml",
      "passed": true,
      "duration_ms": 8321,
      "error": null,
      "steps": [
        {
          "step_type": "flash",
          "params": {"firmware": "samples/hello_world", "runner": "jlink"},
          "passed": true,
          "duration_ms": 3200,
          "output": {"ok": true},
          "error": null
        }
      ]
    }
  ]
}
```

Exit code: **0** = all tests passed, **1** = any test failed, **2** = bad arguments.

## CI Integration

```yaml
# GitHub Actions example
- name: Run hardware regression tests
  run: |
    eabctl regression --suite tests/hw/ --json > results.json
  continue-on-error: true

- name: Upload test results
  uses: actions/upload-artifact@v4
  with:
    name: hw-regression-results
    path: results.json
```

The JSON output is designed for machine consumption. Parse it with `jq`, feed it to a dashboard, or use it as a gate in your CI pipeline.

## Tips

- **Start small.** Your first test should be: flash, reset, wait for a known boot message. Add complexity once that works.
- **Use `assert_log` for readability.** It's identical to `wait`, but makes test intent clearer.
- **Teardown is your safety net.** Always reset the board in teardown so the next test starts clean.
- **Timeouts are per-step.** The global `timeout` is a default — individual steps can override it. Set generous timeouts for flash (30s+) and tight ones for expected output (5-10s).
- **Filter for speed.** During development, use `--filter "*my_test*"` to run just what you need.
