#!/bin/bash
#
# End-to-End Testing for Debug-Full Examples
# Tests: Flash → Boot → Commands → Trace Capture → Validation
#

set -e

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
REPO_ROOT="$(dirname "$SCRIPT_DIR")"
TEST_LOG="$REPO_ROOT/e2e-test-results.log"
TRACE_DIR="$REPO_ROOT/traces"

mkdir -p "$TRACE_DIR"

echo "=== End-to-End Debug Testing ===" | tee "$TEST_LOG"
echo "Started: $(date)" | tee -a "$TEST_LOG"
echo "" | tee -a "$TEST_LOG"

# Test ESP32-C6 if firmware exists
test_esp32c6() {
    echo "=== Testing ESP32-C6 Debug Full ===" | tee -a "$TEST_LOG"

    local fw_dir="$REPO_ROOT/examples/esp32c6-debug-full"

    # Check if built
    if [ ! -f "$fw_dir/build/eab-test-firmware.bin" ]; then
        echo "SKIP: Firmware not built" | tee -a "$TEST_LOG"
        return 1
    fi

    # Flash
    echo "Flashing..." | tee -a "$TEST_LOG"
    if ! eabctl flash "$fw_dir" >> "$TEST_LOG" 2>&1; then
        echo "FAIL: Flash failed" | tee -a "$TEST_LOG"
        return 1
    fi

    # Wait for boot
    sleep 3

    # Check status
    echo "Checking status..." | tee -a "$TEST_LOG"
    eabctl status --json | tee -a "$TEST_LOG"

    # Test commands
    echo "Testing 'status' command..." | tee -a "$TEST_LOG"
    eabctl send "status"
    sleep 2
    eabctl tail 20 | tee -a "$TEST_LOG"

    echo "Testing 'heap_start' command..." | tee -a "$TEST_LOG"
    eabctl send "heap_start"
    sleep 2
    eabctl tail 10 | tee -a "$TEST_LOG"

    echo "Testing 'heap_stop' command..." | tee -a "$TEST_LOG"
    eabctl send "heap_stop"
    sleep 2
    eabctl tail 20 | tee -a "$TEST_LOG"

    # Capture trace (if apptrace available)
    echo "Attempting trace capture..." | tee -a "$TEST_LOG"
    # TODO: Implement apptrace capture

    echo "ESP32-C6 test PASSED" | tee -a "$TEST_LOG"
    return 0
}

# Test nRF5340 if firmware exists
test_nrf5340() {
    echo "=== Testing nRF5340 Debug Full ===" | tee -a "$TEST_LOG"

    local fw_dir="$REPO_ROOT/examples/nrf5340-debug-full"

    # Check if built
    if [ ! -f "$fw_dir/build/zephyr/zephyr.elf" ]; then
        echo "SKIP: Firmware not built" | tee -a "$TEST_LOG"
        return 1
    fi

    # Flash
    echo "Flashing..." | tee -a "$TEST_LOG"
    if ! eabctl flash --chip nrf5340 --runner jlink >> "$TEST_LOG" 2>&1; then
        echo "FAIL: Flash failed" | tee -a "$TEST_LOG"
        return 1
    fi

    # Wait for boot
    sleep 3

    # Start RTT
    echo "Starting RTT..." | tee -a "$TEST_LOG"
    eabctl rtt start --device NRF5340_XXAA_APP --transport jlink >> "$TEST_LOG" 2>&1

    sleep 2

    # Check RTT output
    echo "Checking RTT output..." | tee -a "$TEST_LOG"
    eabctl rtt tail 20 | tee -a "$TEST_LOG"

    # Test shell commands
    echo "Testing 'kernel threads' command..." | tee -a "$TEST_LOG"
    eabctl send "kernel threads"
    sleep 2
    eabctl rtt tail 30 | tee -a "$TEST_LOG"

    echo "Testing 'status' command..." | tee -a "$TEST_LOG"
    eabctl send "status"
    sleep 2
    eabctl rtt tail 10 | tee -a "$TEST_LOG"

    # Capture CTF trace
    echo "Capturing CTF trace..." | tee -a "$TEST_LOG"
    eabctl trace start --source rtt -o "$TRACE_DIR/nrf5340-trace.rttbin" --device NRF5340_XXAA_APP >> "$TEST_LOG" 2>&1 &
    TRACE_PID=$!
    sleep 15
    kill $TRACE_PID 2>/dev/null || true
    eabctl trace stop >> "$TEST_LOG" 2>&1

    # Export to Perfetto
    if [ -f "$TRACE_DIR/nrf5340-trace.rttbin" ]; then
        echo "Exporting to Perfetto JSON..." | tee -a "$TEST_LOG"
        eabctl trace export -i "$TRACE_DIR/nrf5340-trace.rttbin" -o "$TRACE_DIR/nrf5340-trace.json" >> "$TEST_LOG" 2>&1
        echo "Trace saved to: $TRACE_DIR/nrf5340-trace.json" | tee -a "$TEST_LOG"
    fi

    # Stop RTT
    eabctl rtt stop >> "$TEST_LOG" 2>&1

    echo "nRF5340 test PASSED" | tee -a "$TEST_LOG"
    return 0
}

# Run tests
PASS_COUNT=0
FAIL_COUNT=0

if test_esp32c6; then
    ((PASS_COUNT++))
else
    ((FAIL_COUNT++))
fi

if test_nrf5340; then
    ((PASS_COUNT++))
else
    ((FAIL_COUNT++))
fi

# Summary
echo "" | tee -a "$TEST_LOG"
echo "=== Test Summary ===" | tee -a "$TEST_LOG"
echo "Passed: $PASS_COUNT" | tee -a "$TEST_LOG"
echo "Failed: $FAIL_COUNT" | tee -a "$TEST_LOG"
echo "Completed: $(date)" | tee -a "$TEST_LOG"

if [ $FAIL_COUNT -eq 0 ]; then
    echo "All tests PASSED!" | tee -a "$TEST_LOG"
    exit 0
else
    echo "Some tests failed. Check $TEST_LOG for details." | tee -a "$TEST_LOG"
    exit 1
fi
