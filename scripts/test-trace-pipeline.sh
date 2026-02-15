#!/bin/bash
#
# Trace Pipeline Tests (no hardware required)
# Tests: Format detection, export routing, error handling, JSON mode
#

set -o pipefail

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
REPO_ROOT="$(dirname "$SCRIPT_DIR")"
TMPDIR_TEST=""
PASS_COUNT=0
FAIL_COUNT=0

# Colors
GREEN='\033[0;32m'
RED='\033[0;31m'
YELLOW='\033[0;33m'
NC='\033[0m'

cleanup() {
    if [ -n "$TMPDIR_TEST" ] && [ -d "$TMPDIR_TEST" ]; then
        rm -rf "$TMPDIR_TEST"
    fi
}
trap cleanup EXIT

pass() {
    echo -e "  ${GREEN}PASS${NC}: $1"
    ((PASS_COUNT++))
}

fail() {
    echo -e "  ${RED}FAIL${NC}: $1"
    ((FAIL_COUNT++))
}

skip() {
    echo -e "  ${YELLOW}SKIP${NC}: $1"
}

echo "=== Trace Pipeline Tests ==="
echo "Started: $(date)"
echo ""

# Create temp directory with synthetic test files
TMPDIR_TEST="$(mktemp -d)"

# --- Synthetic test files ---

# Mock .rttbin file (just needs extension for detection)
echo -n "RTTBIN_MOCK_DATA" > "$TMPDIR_TEST/trace.rttbin"

# Mock .svdat file (SystemView)
printf 'SEGGER SystemView' > "$TMPDIR_TEST/trace.svdat"

# Mock .log file
echo "[00:00:01.000] boot: kernel started" > "$TMPDIR_TEST/trace.log"

# Mock CTF directory with metadata file
mkdir -p "$TMPDIR_TEST/ctf_trace"
echo "/* CTF 1.8 */" > "$TMPDIR_TEST/ctf_trace/metadata"
printf '\xC1\xFC\x1F\xC1' > "$TMPDIR_TEST/ctf_trace/channel0_0"

# Mock binary with SystemView magic bytes (no extension)
printf 'SEGGER\x00\x00\x00\x00' > "$TMPDIR_TEST/unknown_sv"

# Mock binary with CTF magic bytes (no extension)
printf '\xC1\xFC\x1F\xC1' > "$TMPDIR_TEST/unknown_ctf"

# Empty file (should default)
touch "$TMPDIR_TEST/empty_file"

# --- Test 1: Format detection via Python ---
echo "--- Format Auto-Detection ---"

cd "$REPO_ROOT"

# Test rttbin detection by extension
result=$(python3 -c "
from eab.cli.trace.formats import detect_trace_format
print(detect_trace_format('$TMPDIR_TEST/trace.rttbin'))
" 2>&1)
if [ "$result" = "rttbin" ]; then
    pass "Detect .rttbin by extension"
else
    fail "Detect .rttbin by extension (got: $result)"
fi

# Test systemview detection by extension
result=$(python3 -c "
from eab.cli.trace.formats import detect_trace_format
print(detect_trace_format('$TMPDIR_TEST/trace.svdat'))
" 2>&1)
if [ "$result" = "systemview" ]; then
    pass "Detect .svdat by extension"
else
    fail "Detect .svdat by extension (got: $result)"
fi

# Test log detection by extension
result=$(python3 -c "
from eab.cli.trace.formats import detect_trace_format
print(detect_trace_format('$TMPDIR_TEST/trace.log'))
" 2>&1)
if [ "$result" = "log" ]; then
    pass "Detect .log by extension"
else
    fail "Detect .log by extension (got: $result)"
fi

# Test CTF detection by metadata directory
result=$(python3 -c "
from eab.cli.trace.formats import detect_trace_format
print(detect_trace_format('$TMPDIR_TEST/ctf_trace/channel0_0'))
" 2>&1)
if [ "$result" = "ctf" ]; then
    pass "Detect CTF by metadata in parent dir"
else
    fail "Detect CTF by metadata in parent dir (got: $result)"
fi

# Test SystemView detection by magic bytes (no extension)
result=$(python3 -c "
from eab.cli.trace.formats import detect_trace_format
print(detect_trace_format('$TMPDIR_TEST/unknown_sv'))
" 2>&1)
if [ "$result" = "systemview" ]; then
    pass "Detect SystemView by magic bytes"
else
    fail "Detect SystemView by magic bytes (got: $result)"
fi

# Test default to rttbin for unknown
result=$(python3 -c "
from eab.cli.trace.formats import detect_trace_format
print(detect_trace_format('$TMPDIR_TEST/empty_file'))
" 2>&1)
if [ "$result" = "rttbin" ]; then
    pass "Default to rttbin for unknown format"
else
    fail "Default to rttbin for unknown format (got: $result)"
fi

# --- Test 2: Export error handling ---
echo ""
echo "--- Export Error Handling ---"

# Test missing input file
output=$(python3 -m eab.cli trace export --input "$TMPDIR_TEST/nonexistent.rttbin" --output "$TMPDIR_TEST/out.json" 2>&1) || true
if echo "$output" | grep -qi "not found\|error"; then
    pass "Missing input file gives error"
else
    fail "Missing input file gives error (got: $output)"
fi

# Test missing input file with --json
output=$(python3 -m eab.cli trace export --input "$TMPDIR_TEST/nonexistent.rttbin" --output "$TMPDIR_TEST/out.json" --json 2>&1) || true
if echo "$output" | python3 -c "import sys,json; d=json.load(sys.stdin); assert 'error' in d" 2>/dev/null; then
    pass "Missing file --json returns error object"
else
    fail "Missing file --json returns error object (got: $output)"
fi

# Test systemview export without IDF_PATH
unset IDF_PATH
output=$(python3 -m eab.cli trace export --input "$TMPDIR_TEST/trace.svdat" --output "$TMPDIR_TEST/out.json" --format systemview 2>&1) || true
if echo "$output" | grep -qi "IDF_PATH\|ESP-IDF\|not found\|error"; then
    pass "SystemView export without IDF_PATH gives clear error"
else
    fail "SystemView export without IDF_PATH gives clear error (got: $output)"
fi

# Test CTF export without babeltrace (if not installed)
if ! command -v babeltrace &>/dev/null && ! command -v babeltrace2 &>/dev/null; then
    output=$(python3 -m eab.cli trace export --input "$TMPDIR_TEST/ctf_trace" --output "$TMPDIR_TEST/out.json" --format ctf 2>&1) || true
    if echo "$output" | grep -qi "babeltrace\|not found\|error"; then
        pass "CTF export without babeltrace gives clear error"
    else
        fail "CTF export without babeltrace gives clear error (got: $output)"
    fi
else
    skip "babeltrace installed - can't test missing tool error"
fi

# --- Test 3: CLI format choices ---
echo ""
echo "--- CLI Format Choices ---"

# Test that all format choices are accepted by argparse
for fmt in auto perfetto tband systemview ctf; do
    output=$(python3 -m eab.cli trace export --input "$TMPDIR_TEST/trace.rttbin" --output "$TMPDIR_TEST/out.json" --format "$fmt" 2>&1) || true
    if echo "$output" | grep -qi "invalid choice"; then
        fail "--format $fmt accepted by parser"
    else
        pass "--format $fmt accepted by parser"
    fi
done

# --- Test 4: Python unit tests ---
echo ""
echo "--- Python Unit Tests ---"

pytest_output=$(python3 -m pytest "$REPO_ROOT/eab/tests/test_trace_formats.py" -v 2>&1)
pytest_rc=$?
if [ $pytest_rc -eq 0 ]; then
    test_count=$(echo "$pytest_output" | grep -oE '[0-9]+ passed' | head -1)
    pass "pytest test_trace_formats.py ($test_count)"
else
    fail "pytest test_trace_formats.py (exit code $pytest_rc)"
    echo "$pytest_output" | tail -10
fi

# --- Summary ---
echo ""
echo "=== Test Summary ==="
TOTAL=$((PASS_COUNT + FAIL_COUNT))
echo -e "Passed: ${GREEN}${PASS_COUNT}${NC}/${TOTAL}"
echo -e "Failed: ${RED}${FAIL_COUNT}${NC}/${TOTAL}"
echo "Completed: $(date)"

if [ $FAIL_COUNT -eq 0 ]; then
    echo -e "${GREEN}All trace pipeline tests PASSED!${NC}"
    exit 0
else
    echo -e "${RED}Some tests failed.${NC}"
    exit 1
fi
