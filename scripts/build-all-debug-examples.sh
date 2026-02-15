#!/bin/bash
set -eu
#
# Build All Debug-Full Examples
# Automated build script for repeatability
#


SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
REPO_ROOT="$(dirname "$SCRIPT_DIR")"
EXAMPLES_DIR="$REPO_ROOT/examples"
BUILD_LOG="$REPO_ROOT/build-all.log"

echo "=== Building All Debug-Full Examples ===" | tee "$BUILD_LOG"
echo "Started: $(date)" | tee -a "$BUILD_LOG"
echo "" | tee -a "$BUILD_LOG"

# Track results
SUCCESS_COUNT=0
FAIL_COUNT=0
SKIP_COUNT=0

# Function to build ESP-IDF project
build_esp_idf() {
    local name=$1
    local dir=$2

    echo "Building $name..." | tee -a "$BUILD_LOG"

    if ! command -v idf.py &> /dev/null; then
        echo "  SKIP: ESP-IDF not found in PATH" | tee -a "$BUILD_LOG"
        ((SKIP_COUNT++))
        return 1
    fi

    cd "$dir"
    if idf.py build >> "$BUILD_LOG" 2>&1; then
        echo "  SUCCESS: $name built" | tee -a "$BUILD_LOG"
        ((SUCCESS_COUNT++))
        return 0
    else
        echo "  FAIL: $name build failed (see $BUILD_LOG)" | tee -a "$BUILD_LOG"
        ((FAIL_COUNT++))
        return 1
    fi
}

# Function to build Zephyr project
build_zephyr() {
    local name=$1
    local dir=$2
    local board=$3

    echo "Building $name..." | tee -a "$BUILD_LOG"

    if ! command -v west &> /dev/null; then
        echo "  SKIP: Zephyr/west not found" | tee -a "$BUILD_LOG"
        ((SKIP_COUNT++))
        return 1
    fi

    cd "$dir"
    # Check if we're in a Zephyr workspace
    if ! west topdir &> /dev/null; then
        echo "  SKIP: Not in Zephyr workspace (run this from Zephyr project)" | tee -a "$BUILD_LOG"
        ((SKIP_COUNT++))
        return 1
    fi

    if west build -b "$board" >> "$BUILD_LOG" 2>&1; then
        echo "  SUCCESS: $name built" | tee -a "$BUILD_LOG"
        ((SUCCESS_COUNT++))
        return 0
    else
        echo "  FAIL: $name build failed (see $BUILD_LOG)" | tee -a "$BUILD_LOG"
        ((FAIL_COUNT++))
        return 1
    fi
}

# Build ESP32-C6 debug-full
build_esp_idf "ESP32-C6 Debug Full" "$EXAMPLES_DIR/esp32c6-debug-full"

# Build ESP32-S3 debug-full
build_esp_idf "ESP32-S3 Debug Full" "$EXAMPLES_DIR/esp32s3-debug-full"

# Build nRF5340 debug-full
build_zephyr "nRF5340 Debug Full" "$EXAMPLES_DIR/nrf5340-debug-full" "nrf5340dk/nrf5340/cpuapp"

# Build MCXN947 debug-full
build_zephyr "MCXN947 Debug Full" "$EXAMPLES_DIR/mcxn947-debug-full" "frdm_mcxn947"

# Build STM32L4 debug-full
build_zephyr "STM32L4 Debug Full" "$EXAMPLES_DIR/stm32l4-debug-full" "nucleo_l432kc"

# Summary
echo "" | tee -a "$BUILD_LOG"
echo "=== Build Summary ===" | tee -a "$BUILD_LOG"
echo "Successful: $SUCCESS_COUNT" | tee -a "$BUILD_LOG"
echo "Failed:     $FAIL_COUNT" | tee -a "$BUILD_LOG"
echo "Skipped:    $SKIP_COUNT" | tee -a "$BUILD_LOG"
echo "Completed: $(date)" | tee -a "$BUILD_LOG"

if [ $FAIL_COUNT -gt 0 ]; then
    echo "Some builds failed. Check $BUILD_LOG for details."
    exit 1
else
    echo "All builds completed successfully (or skipped due to missing tools)."
    exit 0
fi
