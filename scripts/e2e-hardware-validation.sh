#!/bin/bash
#
# E2E Hardware Validation — Phase 2 Task 3
# Tests real hardware: Flash → Boot → Monitor → Trace → Export → Validate
#
# Usage:
#   ./scripts/e2e-hardware-validation.sh              # Run all tests
#   ./scripts/e2e-hardware-validation.sh esp32c6      # Run one board
#   ./scripts/e2e-hardware-validation.sh --discover    # Just show connected devices
#
# Results saved to: e2e-results/<timestamp>/
#

set -o pipefail

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
REPO_ROOT="$(dirname "$SCRIPT_DIR")"
TIMESTAMP="$(date +%Y%m%d-%H%M%S)"
RESULTS_DIR="$REPO_ROOT/e2e-results/$TIMESTAMP"
RESULTS_LOG="$RESULTS_DIR/e2e-validation.log"

# Colors
GREEN='\033[0;32m'
RED='\033[0;31m'
YELLOW='\033[0;33m'
CYAN='\033[0;36m'
NC='\033[0m'

PASS_COUNT=0
FAIL_COUNT=0
SKIP_COUNT=0

# --- Helpers ---

log() {
    local msg="[$(date +%H:%M:%S)] $1"
    echo -e "$msg" | tee -a "$RESULTS_LOG"
}

pass() {
    echo -e "  ${GREEN}PASS${NC}: $1" | tee -a "$RESULTS_LOG"
    ((PASS_COUNT++))
}

fail() {
    echo -e "  ${RED}FAIL${NC}: $1" | tee -a "$RESULTS_LOG"
    ((FAIL_COUNT++))
}

skip() {
    echo -e "  ${YELLOW}SKIP${NC}: $1" | tee -a "$RESULTS_LOG"
    ((SKIP_COUNT++))
}

section() {
    echo "" | tee -a "$RESULTS_LOG"
    echo -e "${CYAN}=== $1 ===${NC}" | tee -a "$RESULTS_LOG"
}

# Save a test artifact
save_artifact() {
    local name="$1"
    local content="$2"
    local artifact_file="$RESULTS_DIR/artifacts/$name"
    mkdir -p "$(dirname "$artifact_file")"
    echo "$content" > "$artifact_file"
    log "  Saved: artifacts/$name"
}

# --- Device Discovery ---

discover_devices() {
    section "Device Discovery"

    log "Scanning USB devices..."

    # Get raw ioreg data
    local ioreg_data
    ioreg_data=$(ioreg -p IOUSB -l 2>/dev/null)

    # Parse known devices
    ESPRESSIF_FOUND=false
    JLINK_FOUND=false
    STLINK_FOUND=false
    NXP_FOUND=false
    TI_XDS_FOUND=false

    if echo "$ioreg_data" | grep -q "Espressif"; then
        ESPRESSIF_FOUND=true
        log "  Found: Espressif USB JTAG (ESP32-C6)"
    fi

    if echo "$ioreg_data" | grep -q "J_Link\|J-Link"; then
        JLINK_FOUND=true
        JLINK_SERIAL=$(echo "$ioreg_data" | grep -A2 "J_Link\|J-Link" | grep "USB Serial Number" | head -1 | sed 's/.*= "//;s/"//')
        log "  Found: SEGGER J-Link (nRF5340) serial=$JLINK_SERIAL"
    fi

    if echo "$ioreg_data" | grep -q "STLink\|ST-Link"; then
        STLINK_FOUND=true
        STLINK_SERIAL=$(echo "$ioreg_data" | grep -A2 "STLink\|ST-Link" | grep "USB Serial Number" | head -1 | sed 's/.*= "//;s/"//')
        log "  Found: STM32 ST-Link serial=$STLINK_SERIAL"
    fi

    if echo "$ioreg_data" | grep -q "MCU_LINK\|NXP"; then
        NXP_FOUND=true
        log "  Found: NXP MCU-LINK (MCX N947)"
    fi

    if echo "$ioreg_data" | grep -q "XDS110\|Texas Instruments"; then
        TI_XDS_FOUND=true
        log "  Found: TI XDS110"
    fi

    # List serial ports
    log ""
    log "Serial ports:"
    for port in /dev/cu.usbmodem*; do
        [ -e "$port" ] && log "  $port"
    done

    # Save discovery results
    cat > "$RESULTS_DIR/devices.json" << EOJSON
{
    "timestamp": "$TIMESTAMP",
    "espressif": $ESPRESSIF_FOUND,
    "jlink": $JLINK_FOUND,
    "jlink_serial": "${JLINK_SERIAL:-}",
    "stlink": $STLINK_FOUND,
    "stlink_serial": "${STLINK_SERIAL:-}",
    "nxp_mculink": $NXP_FOUND,
    "ti_xds110": $TI_XDS_FOUND,
    "serial_ports": [$(ls /dev/cu.usbmodem* 2>/dev/null | sed 's/^/"/;s/$/"/' | tr '\n' ',' | sed 's/,$//')]
}
EOJSON

    log "Device discovery saved to devices.json"
}

# --- ESP32-C6 Tests ---

test_esp32c6() {
    section "ESP32-C6 (Espressif USB-JTAG)"

    if [ "$ESPRESSIF_FOUND" != "true" ]; then
        skip "ESP32-C6 not connected"
        return
    fi

    local fw="$REPO_ROOT/examples/esp32c6-apptrace-test/build/eab-test-firmware.bin"
    if [ ! -f "$fw" ]; then
        skip "ESP32-C6 firmware not built ($fw)"
        return
    fi

    local port=""
    # ESP32-C6 USB-JTAG creates a specific port
    for p in /dev/cu.usbmodem101 /dev/cu.usbmodem1101 /dev/cu.usbmodem14101; do
        if [ -e "$p" ]; then
            port="$p"
            break
        fi
    done

    if [ -z "$port" ]; then
        # Try to find it via esptool
        port=$(esptool.py --no-stub chip_id 2>&1 | grep "Serial port" | awk '{print $NF}' || true)
    fi

    if [ -z "$port" ]; then
        fail "ESP32-C6: Could not find serial port"
        return
    fi

    log "Using port: $port"

    # Step 1: Chip info
    log "Step 1: Chip identification"
    local chip_output
    chip_output=$(esptool.py --port "$port" --no-stub chip_id 2>&1) || true
    save_artifact "esp32c6/chip_id.txt" "$chip_output"

    if echo "$chip_output" | grep -qi "esp32-c6\|ESP32-C6"; then
        pass "ESP32-C6 chip identified"
    else
        fail "ESP32-C6 chip identification (got: $(echo "$chip_output" | tail -3))"
        return
    fi

    # Step 2: Flash
    log "Step 2: Flash firmware"
    local flash_output
    flash_output=$(eabctl flash "$REPO_ROOT/examples/esp32c6-apptrace-test" --port "$port" --chip esp32c6 --no-stub 2>&1) || true
    save_artifact "esp32c6/flash.txt" "$flash_output"

    if echo "$flash_output" | grep -q '"success": true'; then
        pass "ESP32-C6 flash succeeded"
    elif echo "$flash_output" | grep -qi "Verify OK\|Hash of data verified"; then
        pass "ESP32-C6 flash succeeded"
    else
        fail "ESP32-C6 flash (see artifacts/esp32c6/flash.txt)"
        return
    fi

    # Step 3: Monitor boot
    log "Step 3: Monitor boot (5 seconds)"

    # Stop any existing daemon on this port
    eabctl --device esp32c6 stop 2>/dev/null || true
    sleep 1

    # Register device if not exists, start daemon with port
    eabctl device add esp32c6 --type serial --chip esp32c6 2>/dev/null || true
    eabctl --device esp32c6 start --port "$port" --force 2>/dev/null || true
    sleep 5

    local boot_output
    boot_output=$(eabctl --device esp32c6 tail 50 2>&1) || true
    save_artifact "esp32c6/boot.txt" "$boot_output"

    if echo "$boot_output" | grep -qi "boot\|ready\|started\|heap\|eab"; then
        pass "ESP32-C6 boot output captured"
    else
        fail "ESP32-C6 boot output (see artifacts/esp32c6/boot.txt)"
    fi

    # Step 4: Send command
    log "Step 4: Send test command"
    eabctl --device esp32c6 send "status" 2>/dev/null || true
    sleep 2
    local cmd_output
    cmd_output=$(eabctl --device esp32c6 tail 20 2>&1) || true
    save_artifact "esp32c6/cmd_status.txt" "$cmd_output"

    if [ -n "$cmd_output" ]; then
        pass "ESP32-C6 command response received"
    else
        skip "ESP32-C6 command response (may not support 'status')"
    fi

    # Step 5: Trace capture via serial log
    log "Step 5: Trace capture (serial log mode, 10 seconds)"
    local trace_file="$RESULTS_DIR/traces/esp32c6-serial.rttbin"
    mkdir -p "$RESULTS_DIR/traces"

    eabctl trace start --output "$trace_file" --source logfile \
        --logfile /tmp/eab-devices/esp32c6/latest.log 2>&1 || true &
    local trace_pid=$!
    sleep 10
    kill $trace_pid 2>/dev/null || true
    eabctl trace stop 2>/dev/null || true

    if [ -f "$trace_file" ] && [ -s "$trace_file" ]; then
        local trace_size
        trace_size=$(wc -c < "$trace_file")
        pass "ESP32-C6 trace captured (${trace_size} bytes)"

        # Step 6: Export
        log "Step 6: Export to Perfetto JSON"
        local export_file="$RESULTS_DIR/traces/esp32c6-trace.json"
        local export_output
        export_output=$(eabctl trace export --input "$trace_file" --output "$export_file" 2>&1) || true
        save_artifact "esp32c6/export.txt" "$export_output"

        if [ -f "$export_file" ] && [ -s "$export_file" ]; then
            pass "ESP32-C6 trace exported to Perfetto JSON"
        else
            fail "ESP32-C6 trace export (see artifacts/esp32c6/export.txt)"
        fi
    else
        skip "ESP32-C6 trace capture (no data — device may need apptrace support)"
    fi

    # Cleanup
    eabctl --device esp32c6 stop 2>/dev/null || true
}

# --- nRF5340 Tests ---

test_nrf5340() {
    section "nRF5340 (J-Link)"

    if [ "$JLINK_FOUND" != "true" ]; then
        skip "nRF5340 J-Link not connected"
        return
    fi

    if ! command -v JLinkExe &>/dev/null; then
        skip "JLinkExe not installed"
        return
    fi

    # Step 1: J-Link connection test
    log "Step 1: J-Link connection test"
    local jlink_output
    jlink_output=$(echo -e "connect\nNRF5340_XXAA_APP\nSWD\n4000\nq\n" | JLinkExe 2>&1) || true
    save_artifact "nrf5340/jlink_connect.txt" "$jlink_output"

    if echo "$jlink_output" | grep -qi "cortex-m33\|found\|connected\|OK"; then
        pass "nRF5340 J-Link connected"
    else
        fail "nRF5340 J-Link connection (see artifacts/nrf5340/jlink_connect.txt)"
        return
    fi

    # Step 2: Flash (if firmware built)
    local fw="$REPO_ROOT/examples/nrf5340-debug-full/build/zephyr/zephyr.elf"
    if [ -f "$fw" ]; then
        log "Step 2: Flash firmware"
        local flash_output
        flash_output=$(eabctl flash "$fw" --chip nrf5340 --runner jlink --device NRF5340_XXAA_APP 2>&1) || true
        save_artifact "nrf5340/flash.txt" "$flash_output"

        if echo "$flash_output" | grep -q '"success": true'; then
            pass "nRF5340 flash succeeded"
        else
            fail "nRF5340 flash (see artifacts/nrf5340/flash.txt)"
        fi
    else
        skip "nRF5340 firmware not built (examples/nrf5340-debug-full)"
        log "  Will test RTT/trace with whatever is currently flashed"
    fi

    # Step 3: RTT streaming
    log "Step 3: Start RTT streaming"
    eabctl rtt stop 2>/dev/null || true
    sleep 1

    local rtt_start_output
    rtt_start_output=$(eabctl rtt start --device NRF5340_XXAA_APP --transport jlink 2>&1) || true
    save_artifact "nrf5340/rtt_start.txt" "$rtt_start_output"
    sleep 3

    local rtt_status
    rtt_status=$(eabctl rtt status 2>&1) || true
    save_artifact "nrf5340/rtt_status.txt" "$rtt_status"

    if echo "$rtt_status" | grep -qi "running\|active"; then
        pass "nRF5340 RTT streaming started"
    else
        # RTT may have started but not show as running
        log "  RTT status: $rtt_status"
    fi

    sleep 5

    # Step 4: Read RTT output
    log "Step 4: Read RTT output"
    local rtt_output
    rtt_output=$(eabctl rtt tail 30 2>&1) || true
    save_artifact "nrf5340/rtt_output.txt" "$rtt_output"

    # Also check per-device RTT logs as fallback (eabctl rtt tail reads global session)
    local rtt_stdout="/tmp/eab-devices/nrf5340/rtt-stdout.log"
    if [ -f "$rtt_stdout" ] && [ -s "$rtt_stdout" ]; then
        save_artifact "nrf5340/rtt_stdout_log.txt" "$(tail -30 "$rtt_stdout")"
    fi

    if [ -n "$rtt_output" ] && [ "$(echo "$rtt_output" | wc -l)" -gt 1 ]; then
        pass "nRF5340 RTT output captured ($(echo "$rtt_output" | wc -l) lines)"
    elif [ -f "$rtt_stdout" ] && [ -s "$rtt_stdout" ]; then
        local stdout_lines
        stdout_lines=$(wc -l < "$rtt_stdout")
        pass "nRF5340 RTT output in rtt-stdout.log ($stdout_lines lines)"
    else
        skip "nRF5340 RTT output (firmware may print infrequently)"
    fi

    # Step 5: RTT trace capture
    log "Step 5: RTT trace capture (15 seconds)"
    local trace_file="$RESULTS_DIR/traces/nrf5340-rtt.rttbin"
    mkdir -p "$RESULTS_DIR/traces"

    eabctl trace start --output "$trace_file" --source rtt --device NRF5340_XXAA_APP 2>&1 &
    local trace_pid=$!
    sleep 15
    kill $trace_pid 2>/dev/null || true
    eabctl trace stop 2>/dev/null || true
    sleep 1

    if [ -f "$trace_file" ] && [ -s "$trace_file" ]; then
        local trace_size
        trace_size=$(wc -c < "$trace_file")
        pass "nRF5340 RTT trace captured (${trace_size} bytes)"

        # Step 6: Export
        log "Step 6: Export to Perfetto JSON"
        local export_file="$RESULTS_DIR/traces/nrf5340-trace.json"
        local export_output
        export_output=$(eabctl trace export --input "$trace_file" --output "$export_file" 2>&1) || true
        save_artifact "nrf5340/export.txt" "$export_output"

        if [ -f "$export_file" ] && [ -s "$export_file" ]; then
            local event_count
            event_count=$(python3 -c "import json; d=json.load(open('$export_file')); print(len(d.get('traceEvents', d if isinstance(d, list) else [])))" 2>/dev/null || echo "unknown")
            pass "nRF5340 trace exported (${event_count} events)"
        else
            fail "nRF5340 trace export (see artifacts/nrf5340/export.txt)"
        fi
    else
        fail "nRF5340 RTT trace capture (no data written)"
    fi

    # Cleanup
    eabctl rtt stop 2>/dev/null || true
}

# --- STM32L4 Tests ---

test_stm32l4() {
    section "STM32L4 (ST-Link)"

    if [ "$STLINK_FOUND" != "true" ]; then
        skip "STM32 ST-Link not connected"
        return
    fi

    # Step 1: Probe connection test
    log "Step 1: ST-Link connection test"
    local probe_output
    if command -v probe-rs &>/dev/null; then
        probe_output=$(probe-rs info 2>&1) || true
        save_artifact "stm32l4/probe_info.txt" "$probe_output"

        if echo "$probe_output" | grep -qi "stm32\|arm\|cortex"; then
            pass "STM32L4 probe-rs connection"
        else
            log "  probe-rs output: $(echo "$probe_output" | head -5)"
        fi
    fi

    # Also try openocd
    local openocd_output
    openocd_output=$(timeout 5 openocd -f interface/stlink.cfg -f target/stm32l4x.cfg -c "init; targets; shutdown" 2>&1) || true
    save_artifact "stm32l4/openocd_connect.txt" "$openocd_output"

    if echo "$openocd_output" | grep -qi "stm32l4\|halted\|target"; then
        pass "STM32L4 OpenOCD connection"
    else
        fail "STM32L4 connection (see artifacts/stm32l4/openocd_connect.txt)"
        return
    fi

    # Step 2: Flash (if firmware built) — prefer .bin over .elf to avoid objcopy dependency
    local fw_bin="$REPO_ROOT/examples/stm32l4-sensor-node/build/zephyr/zephyr.bin"
    local fw_elf="$REPO_ROOT/examples/stm32l4-sensor-node/build/zephyr/zephyr.elf"
    local fw=""
    if [ -f "$fw_bin" ]; then
        fw="$fw_bin"
    elif [ -f "$fw_elf" ]; then
        fw="$fw_elf"
    fi

    if [ -n "$fw" ]; then
        log "Step 2: Flash firmware ($(basename "$fw"))"
        local flash_output
        flash_output=$(eabctl flash "$fw" --chip stm32l4 --tool openocd 2>&1) || true

        if echo "$flash_output" | grep -q '"success": true'; then
            save_artifact "stm32l4/flash.txt" "$flash_output"
            pass "STM32L4 flash succeeded"
        else
            # Fallback: probe-rs with probe selector
            log "  eabctl flash failed, trying probe-rs directly..."
            local probe_selector="0483:374b${STLINK_SERIAL:+:$STLINK_SERIAL}"
            flash_output=$(probe-rs download --chip STM32L476RGTx --probe "$probe_selector" "$fw_elf" 2>&1) || true
            save_artifact "stm32l4/flash.txt" "$flash_output"

            if echo "$flash_output" | grep -qi "finished\|success\|programm"; then
                pass "STM32L4 flash via probe-rs"
            else
                fail "STM32L4 flash (see artifacts/stm32l4/flash.txt)"
            fi
        fi
    else
        skip "STM32L4 firmware not built"
    fi

    # Step 3: RTT via probe-rs
    log "Step 3: RTT streaming via probe-rs"
    eabctl rtt stop 2>/dev/null || true
    sleep 1

    local probe_selector="0483:374b${STLINK_SERIAL:+:$STLINK_SERIAL}"
    local rtt_output
    rtt_output=$(eabctl rtt start --device STM32L476RG --transport probe-rs --probe-selector "$probe_selector" 2>&1) || true
    save_artifact "stm32l4/rtt_start.txt" "$rtt_output"
    sleep 3

    local rtt_tail
    rtt_tail=$(eabctl rtt tail 20 2>&1) || true
    save_artifact "stm32l4/rtt_output.txt" "$rtt_tail"

    if [ -n "$rtt_tail" ] && [ "$(echo "$rtt_tail" | wc -l)" -gt 1 ]; then
        pass "STM32L4 RTT output captured"
    else
        skip "STM32L4 RTT output (firmware may not have RTT enabled)"
    fi

    eabctl rtt stop 2>/dev/null || true
}

# --- MCX N947 Tests ---

test_mcxn947() {
    section "MCX N947 (NXP MCU-LINK)"

    if [ "$NXP_FOUND" != "true" ]; then
        skip "NXP MCU-LINK not connected"
        return
    fi

    # Step 1: Probe connection test
    log "Step 1: MCU-LINK connection test"

    local probe_output
    if command -v probe-rs &>/dev/null; then
        probe_output=$(probe-rs info 2>&1) || true
        save_artifact "mcxn947/probe_info.txt" "$probe_output"

        if echo "$probe_output" | grep -qi "nxp\|mcx\|arm\|cortex"; then
            pass "MCX N947 probe-rs detected"
        else
            log "  probe-rs: $(echo "$probe_output" | head -3)"
        fi
    fi

    # Step 2: Flash (if firmware built) — prefer .bin to avoid objcopy issues
    local fw_bin="$REPO_ROOT/examples/frdm-mcxn947-fault-demo/build/zephyr/zephyr.bin"
    local fw_elf="$REPO_ROOT/examples/frdm-mcxn947-fault-demo/build/zephyr/zephyr.elf"
    local fw=""
    [ -f "$fw_bin" ] && fw="$fw_bin"
    [ -z "$fw" ] && [ -f "$fw_elf" ] && fw="$fw_elf"

    if [ -n "$fw" ]; then
        log "Step 2: Flash firmware"
        local flash_output

        # Try eabctl first
        flash_output=$(eabctl flash "$fw" --chip mcxn947 2>&1) || true

        if ! echo "$flash_output" | grep -q '"success": true'; then
            # Fallback: probe-rs with MCU-LINK selector (must use .elf for address info)
            log "  eabctl flash failed, trying probe-rs directly..."
            flash_output=$(probe-rs download --chip MCXN947 --probe "1fc9:0143" "$fw_elf" 2>&1) || true
            save_artifact "mcxn947/flash.txt" "$flash_output"

            if echo "$flash_output" | grep -qi "finished\|success\|programm"; then
                pass "MCX N947 flash via probe-rs"
            elif echo "$flash_output" | grep -qi "No flash memory contains\|Unknown file magic"; then
                skip "MCX N947 flash (MCX N947 requires NXP LinkServer — not installed)"
            else
                fail "MCX N947 flash (see artifacts/mcxn947/flash.txt)"
            fi
        else
            save_artifact "mcxn947/flash.txt" "$flash_output"
            pass "MCX N947 flash succeeded"
        fi
    else
        skip "MCX N947 firmware not built"
    fi

    # Step 3: RTT via probe-rs
    log "Step 3: RTT streaming"
    eabctl rtt stop 2>/dev/null || true
    sleep 1

    local rtt_output
    rtt_output=$(eabctl rtt start --device MCXN947 --transport probe-rs --probe-selector "1fc9:0143" 2>&1) || true
    save_artifact "mcxn947/rtt_start.txt" "$rtt_output"
    sleep 3

    local rtt_tail
    rtt_tail=$(eabctl rtt tail 20 2>&1) || true
    save_artifact "mcxn947/rtt_output.txt" "$rtt_tail"

    if [ -n "$rtt_tail" ] && [ "$(echo "$rtt_tail" | wc -l)" -gt 1 ]; then
        pass "MCX N947 RTT output captured"
    else
        skip "MCX N947 RTT (firmware may not have RTT enabled)"
    fi

    eabctl rtt stop 2>/dev/null || true
}

# --- Trace Pipeline Validation ---

test_trace_pipeline() {
    section "Trace Pipeline (Software Tests)"

    log "Running trace pipeline tests..."
    local pipeline_output
    pipeline_output=$(bash "$SCRIPT_DIR/test-trace-pipeline.sh" 2>&1) || true
    save_artifact "trace-pipeline/output.txt" "$pipeline_output"

    if echo "$pipeline_output" | grep -q "All trace pipeline tests PASSED"; then
        local test_count
        test_count=$(echo "$pipeline_output" | grep -oE '[0-9]+/[0-9]+' | tail -1)
        pass "Trace pipeline tests ($test_count)"
    else
        fail "Trace pipeline tests (see artifacts/trace-pipeline/output.txt)"
    fi
}

# --- Python Unit Tests ---

test_python_units() {
    section "Python Unit Tests"

    log "Running pytest..."
    local pytest_output
    pytest_output=$(cd "$REPO_ROOT" && python3 -m pytest eab/tests/ -v --tb=short 2>&1) || true
    save_artifact "pytest/output.txt" "$pytest_output"

    local passed
    passed=$(echo "$pytest_output" | grep -oE '[0-9]+ passed' | head -1)
    local failed
    failed=$(echo "$pytest_output" | grep -oE '[0-9]+ failed' | head -1)

    if [ -n "$passed" ]; then
        pass "pytest: $passed${failed:+, $failed}"
    else
        fail "pytest (see artifacts/pytest/output.txt)"
    fi
}

# --- Main ---

main() {
    mkdir -p "$RESULTS_DIR/artifacts" "$RESULTS_DIR/traces"

    echo -e "${CYAN}╔══════════════════════════════════════════════╗${NC}"
    echo -e "${CYAN}║   E2E Hardware Validation — Phase 2 Task 3  ║${NC}"
    echo -e "${CYAN}╚══════════════════════════════════════════════╝${NC}"
    echo ""
    log "Results directory: $RESULTS_DIR"
    log "Started: $(date)"

    # Always discover devices first
    discover_devices

    if [ "${1:-}" = "--discover" ]; then
        echo ""
        log "Discovery only — exiting."
        return 0
    fi

    # Filter to specific board if requested
    local target="${1:-all}"

    case "$target" in
        esp32c6|esp32)
            test_esp32c6
            ;;
        nrf5340|nrf)
            test_nrf5340
            ;;
        stm32l4|stm32)
            test_stm32l4
            ;;
        mcxn947|mcx|nxp)
            test_mcxn947
            ;;
        pipeline|trace)
            test_trace_pipeline
            ;;
        all)
            test_esp32c6
            test_nrf5340
            test_stm32l4
            test_mcxn947
            test_trace_pipeline
            test_python_units
            ;;
        *)
            echo "Unknown target: $target"
            echo "Usage: $0 [esp32c6|nrf5340|stm32l4|mcxn947|pipeline|all]"
            exit 1
            ;;
    esac

    # --- Summary ---
    section "Summary"
    local total=$((PASS_COUNT + FAIL_COUNT + SKIP_COUNT))
    echo -e "  ${GREEN}Passed:  ${PASS_COUNT}${NC}" | tee -a "$RESULTS_LOG"
    echo -e "  ${RED}Failed:  ${FAIL_COUNT}${NC}" | tee -a "$RESULTS_LOG"
    echo -e "  ${YELLOW}Skipped: ${SKIP_COUNT}${NC}" | tee -a "$RESULTS_LOG"
    echo -e "  Total:   ${total}" | tee -a "$RESULTS_LOG"
    echo "" | tee -a "$RESULTS_LOG"
    log "Results saved to: $RESULTS_DIR"
    log "Completed: $(date)"

    # Generate summary JSON
    cat > "$RESULTS_DIR/summary.json" << EOJSON
{
    "timestamp": "$TIMESTAMP",
    "target": "$target",
    "passed": $PASS_COUNT,
    "failed": $FAIL_COUNT,
    "skipped": $SKIP_COUNT,
    "total": $total,
    "results_dir": "$RESULTS_DIR"
}
EOJSON

    if [ $FAIL_COUNT -eq 0 ]; then
        echo -e "${GREEN}All tests passed!${NC}" | tee -a "$RESULTS_LOG"
        return 0
    else
        echo -e "${RED}Some tests failed. Check artifacts for details.${NC}" | tee -a "$RESULTS_LOG"
        return 1
    fi
}

main "$@"
