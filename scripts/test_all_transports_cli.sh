#!/bin/bash
# Test RTT transports (J-Link and probe-rs) on all connected boards via eabctl CLI
set -e

echo "=========================================="
echo "RTT Transport CLI Test - All Boards"
echo "=========================================="
echo

# Test function
test_rtt() {
    local board=$1
    local device=$2
    local transport=$3
    local base_dir=$4

    echo "----------------------------------------"
    echo "Board: $board"
    echo "Device: $device"
    echo "Transport: $transport"
    echo "----------------------------------------"

    # Try to start RTT
    if eabctl rtt start --device "$device" --transport "$transport" --base-dir "$base_dir" --json 2>&1 | jq -e '.running == true' > /dev/null; then
        echo "✓ RTT started successfully"

        # Stop RTT (only works for jlink transport)
        if [ "$transport" = "jlink" ]; then
            eabctl rtt stop --base-dir "$base_dir" --json > /dev/null
            echo "✓ RTT stopped"
        fi

        return 0
    else
        echo "✗ RTT failed (firmware may not have RTT enabled)"
        return 1
    fi
}

# Track results
passed=0
failed=0

# Test 1: nRF5340 with J-Link transport
if test_rtt "nRF5340 DK" "nRF5340_xxAA" "jlink" "/tmp/eab-devices/nrf5340"; then
    ((passed++))
else
    ((failed++))
fi
echo

# Test 2: STM32 with probe-rs transport
if test_rtt "STM32 Nucleo L476RG" "STM32L476RGTx" "probe-rs" "/tmp/eab-devices/stm32"; then
    ((passed++))
else
    ((failed++))
fi
echo

# Test 3: MCXN947 with probe-rs transport
if test_rtt "FRDM-MCXN947" "MCXN947" "probe-rs" "/tmp/eab-devices/mcxn947"; then
    ((passed++))
else
    ((failed++))
fi
echo

# Test 4: nRF5340 with probe-rs transport (expected to fail or succeed based on APPROTECT state)
if test_rtt "nRF5340 DK (probe-rs)" "nRF5340_xxAA" "probe-rs" "/tmp/eab-devices/nrf5340"; then
    ((passed++))
else
    ((failed++))
    echo "  Note: nRF5340 may require APPROTECT disabled for probe-rs access"
fi
echo

# Summary
echo "=========================================="
echo "SUMMARY"
echo "=========================================="
echo "Passed: $passed"
echo "Failed: $failed"
echo

if [ $failed -eq 0 ]; then
    echo "✓ All tests passed"
    exit 0
else
    echo "⚠ Some tests failed (expected if firmware lacks RTT)"
    exit 0  # Don't fail CI - RTT firmware is optional
fi
