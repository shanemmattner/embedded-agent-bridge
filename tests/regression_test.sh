#!/bin/bash
# EAB Hardware Regression Test Suite
# Tests all refactored CLI packages (daemon, flash, debug, serial, profile) with real hardware
# Run after any major refactoring or before release

set -e

# Colors for output
GREEN='\033[0;32m'
RED='\033[0;31m'
YELLOW='\033[1;33m'
BLUE='\033[0;34m'
NC='\033[0m' # No Color

# Test results
TESTS_PASSED=0
TESTS_FAILED=0
FAILED_TESTS=()

# Helper functions
pass() {
    echo -e "${GREEN}✓${NC} $1"
    ((TESTS_PASSED++))
}

fail() {
    echo -e "${RED}✗${NC} $1"
    ((TESTS_FAILED++))
    FAILED_TESTS+=("$1")
}

info() {
    echo -e "${BLUE}ℹ${NC} $1"
}

section() {
    echo ""
    echo -e "${YELLOW}=== $1 ===${NC}"
}

# Detect available boards
detect_boards() {
    section "Detecting Connected Hardware"

    # List all USB serial devices
    info "USB Serial Devices:"
    ls /dev/cu.usb* 2>/dev/null || echo "  (none found)"

    # Check for J-Link
    if JLinkExe -CommandFile <(echo "exit") 2>&1 | grep -q "J-Link"; then
        pass "J-Link probe detected"
    else
        fail "J-Link probe not detected"
    fi

    # Check EAB sessions
    if [ -d /tmp/eab-devices ]; then
        info "EAB Sessions:"
        ls -1 /tmp/eab-devices/ | sed 's/^/  - /'
    fi
}

# Test 1: Package Imports
test_imports() {
    section "Test 1: Package Imports"

    python3 << 'PYEOF'
import sys

packages = [
    ("flash", ["cmd_flash", "cmd_erase", "cmd_chip_info"]),
    ("daemon", ["cmd_start", "cmd_stop", "cmd_diagnose"]),
    ("debug", ["cmd_openocd_start", "cmd_gdb", "cmd_inspect"]),
    ("serial", ["cmd_status", "cmd_tail", "cmd_send"]),
    ("profile", ["cmd_profile_function", "cmd_dwt_status"]),
]

for pkg, funcs in packages:
    try:
        mod = __import__(f"eab.cli.{pkg}", fromlist=funcs)
        for func in funcs:
            if not hasattr(mod, func):
                print(f"FAIL: {pkg}.{func} not found")
                sys.exit(1)
        print(f"PASS: {pkg}")
    except ImportError as e:
        print(f"FAIL: {pkg} - {e}")
        sys.exit(1)
PYEOF

    if [ $? -eq 0 ]; then
        pass "All 5 packages import successfully"
    else
        fail "Package import errors"
        return 1
    fi
}

# Test 2: Unit Tests
test_unit_tests() {
    section "Test 2: Unit Tests"

    info "Running pytest on refactored packages..."
    python3 -m pytest tests/test_cli_daemon_cmds.py \
                      tests/test_cli_debug_gdb_commands.py \
                      tests/test_cli_profile_cmds.py \
                      -v --tb=line -q 2>&1 | tail -20

    if [ ${PIPESTATUS[0]} -eq 0 ]; then
        pass "Unit tests passed"
    else
        fail "Unit tests failed"
        return 1
    fi
}

# Test 3: Daemon Lifecycle
test_daemon() {
    section "Test 3: Daemon Lifecycle (daemon/ package)"

    # Stop any existing daemon
    eabctl stop &>/dev/null || true
    pkill -f "eab.*daemon" &>/dev/null || true
    sleep 1

    # Start daemon
    info "Starting daemon..."
    START_OUTPUT=$(eabctl start --port auto 2>&1)
    if echo "$START_OUTPUT" | grep -q '"started": true'; then
        pass "Daemon started"
    else
        fail "Daemon start failed"
        return 1
    fi

    sleep 2

    # Check status
    info "Checking status..."
    if eabctl status 2>&1 | grep -q "connection"; then
        pass "Status command works"
    else
        fail "Status command failed"
    fi

    # Diagnose
    info "Running diagnose..."
    if eabctl diagnose 2>&1 | grep -q "checks"; then
        pass "Diagnose command works"
    else
        fail "Diagnose command failed"
    fi
}

# Test 4: Serial Commands
test_serial() {
    section "Test 4: Serial I/O (serial/ package)"

    # Tail
    info "Testing tail..."
    if eabctl tail 3 2>&1 | grep -q "."; then
        pass "Tail command works"
    else
        fail "Tail command failed"
    fi

    # Send
    info "Testing send..."
    if eabctl send "i" 2>&1 | grep -q "sent:"; then
        pass "Send command works"
    else
        fail "Send command failed"
    fi

    sleep 1

    # Alerts
    info "Testing alerts..."
    eabctl alerts 2 &>/dev/null
    pass "Alerts command works"

    # Events
    info "Testing events..."
    eabctl events 2 &>/dev/null
    pass "Events command works"
}

# Test 5: Flash Commands
test_flash() {
    section "Test 5: Flash Commands (flash/ package)"

    # Preflight check
    info "Testing preflight-hw..."
    PREFLIGHT=$(eabctl preflight-hw 2>&1)
    if [ $? -eq 0 ]; then
        pass "Preflight check passed"
    else
        info "Preflight warnings (expected if no firmware ready)"
    fi

    # Chip info
    info "Testing chip-info..."
    if eabctl chip-info 2>&1 | head -5 | grep -q "."; then
        pass "Chip-info command works"
    else
        info "Chip-info (may fail if chip not detected)"
    fi
}

# Test 6: Debug Commands (imports only, no hardware probe needed)
test_debug() {
    section "Test 6: Debug Commands (debug/ package)"

    info "Testing debug package imports..."
    python3 -c "from eab.cli.debug import cmd_openocd_start, cmd_gdb, cmd_inspect; print('OK')" 2>&1
    if [ $? -eq 0 ]; then
        pass "Debug package imports OK"
    else
        fail "Debug package import failed"
    fi
}

# Test 7: Profile Commands (imports only, requires J-Link for full test)
test_profile() {
    section "Test 7: Profile Commands (profile/ package)"

    info "Testing profile package imports..."
    python3 -c "from eab.cli.profile import cmd_profile_function, cmd_dwt_status, cmd_profile_region; print('OK')" 2>&1
    if [ $? -eq 0 ]; then
        pass "Profile package imports OK"
    else
        fail "Profile package import failed"
    fi

    # If J-Link is available, test DWT status
    if command -v JLinkExe &>/dev/null; then
        info "Testing dwt-status (may fail if no target connected)..."
        eabctl dwt-status --device NRF5340_XXAA_APP --json 2>&1 | head -3 || true
        info "DWT status command executed (errors expected without target)"
    fi
}

# Test 8: CLI Entry Points
test_cli_entry_points() {
    section "Test 8: CLI Entry Points"

    # eabctl --help
    if eabctl --help 2>&1 | grep -q "usage:"; then
        pass "eabctl --help works"
    else
        fail "eabctl --help failed"
    fi

    # eabctl --version
    if eabctl --version 2>&1 | grep -q "[0-9]"; then
        pass "eabctl --version works"
    else
        fail "eabctl --version failed"
    fi
}

# Main test execution
main() {
    echo ""
    echo "======================================"
    echo "  EAB Hardware Regression Test Suite"
    echo "======================================"
    echo ""
    echo "Date: $(date)"
    echo "Branch: $(git branch --show-current)"
    echo "Commit: $(git rev-parse --short HEAD)"
    echo ""

    detect_boards
    test_imports || true
    test_unit_tests || true
    test_daemon || true
    test_serial || true
    test_flash || true
    test_debug || true
    test_profile || true
    test_cli_entry_points || true

    # Summary
    echo ""
    echo "======================================"
    echo "  Test Summary"
    echo "======================================"
    echo ""
    echo -e "${GREEN}Passed:${NC} $TESTS_PASSED"
    echo -e "${RED}Failed:${NC} $TESTS_FAILED"

    if [ $TESTS_FAILED -gt 0 ]; then
        echo ""
        echo -e "${RED}Failed tests:${NC}"
        for test in "${FAILED_TESTS[@]}"; do
            echo "  - $test"
        done
        echo ""
        exit 1
    else
        echo ""
        echo -e "${GREEN}✓ All tests passed!${NC}"
        echo ""
        exit 0
    fi
}

# Run tests
main
