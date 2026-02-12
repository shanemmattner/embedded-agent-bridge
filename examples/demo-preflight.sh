#!/usr/bin/env bash
# ============================================================================
# EAB Cross-Board Pre-flight Check
# ============================================================================
# Verifies all 4 demo boards are connected and responding.
# Run before demo.sh to catch disconnected boards early.
#
# Usage: bash examples/demo-preflight.sh

set -euo pipefail

SCRIPT_DIR="$(cd "$(dirname "$0")" && pwd)"
EAB_ROOT="$(cd "$SCRIPT_DIR/.." && pwd)"
CLI="python3 -m eab.cli"

# ── Toolchain PATH setup ────────────────────────────────────────────────────
# Zephyr SDK ARM GDB (for nRF5340, STM32L4, MCXN947)
export PATH="$HOME/zephyr-sdk-0.17.0/arm-zephyr-eabi/bin:$PATH"
# Espressif RISC-V GDB (for ESP32-C6)
export PATH="$HOME/.espressif/tools/riscv32-esp-elf-gdb/14.2_20240403/riscv32-esp-elf-gdb/bin:$PATH"

# Espressif OpenOCD
ESP_OCD="$HOME/.espressif/tools/openocd-esp32/v0.12.0-esp32-20241016/openocd-esp32/bin/openocd"
ESP_SCRIPTS="$HOME/.espressif/tools/openocd-esp32/v0.12.0-esp32-20241016/openocd-esp32/share/openocd/scripts"

RED='\033[0;31m'
GREEN='\033[0;32m'
CYAN='\033[0;36m'
NC='\033[0m'

PASS=0
FAIL=0

check() {
    local label="$1"
    shift
    printf "  %-30s" "$label"
    if output=$(eval "$@" 2>&1); then
        printf "${GREEN}OK${NC}\n"
        ((PASS++))
    else
        printf "${RED}FAIL${NC}\n"
        # Show last meaningful error line
        echo "$output" | tail -3 | sed 's/^/    /'
        ((FAIL++))
    fi
}

echo ""
echo -e "${CYAN}EAB Demo Pre-flight Check${NC}"
echo "─────────────────────────────────────────"

# ── Toolchain checks ────────────────────────────────────────────────────────

echo ""
echo "Toolchain:"
check "ARM GDB (Zephyr SDK)" "which arm-zephyr-eabi-gdb"
check "RISC-V GDB (Espressif)" "which riscv32-esp-elf-gdb"
check "J-Link GDB Server" "which JLinkGDBServerCLExe"
check "OpenOCD (Homebrew)" "which openocd"
check "OpenOCD (Espressif)" "test -x '$ESP_OCD'"

# ── Board checks ────────────────────────────────────────────────────────────

echo ""
echo "Boards:"

# nRF5340 DK — J-Link probe (fault-analyze manages GDB server lifecycle)
check "nRF5340 DK (J-Link)" \
    "cd '$EAB_ROOT' && $CLI --json fault-analyze --device NRF5340_XXAA_APP --chip nrf5340 --probe jlink"

# STM32L4 — OpenOCD + ST-Link
check "STM32L4 (ST-Link)" \
    "cd '$EAB_ROOT' && $CLI --json fault-analyze --chip stm32l4 --probe openocd"

# NXP MCXN947 — OpenOCD + CMSIS-DAP
check "MCXN947 (CMSIS-DAP)" \
    "cd '$EAB_ROOT' && $CLI --json fault-analyze --device MCXN947 --chip mcxn947 --probe openocd"

# ESP32-C6 — Espressif OpenOCD batch register dump
check "ESP32-C6 (USB-JTAG)" \
    "'$ESP_OCD' -s '$ESP_SCRIPTS' -f board/esp32c6-builtin.cfg \
        -c 'init' -c 'halt' -c 'reg pc' -c 'resume' -c 'shutdown' 2>&1 | grep -q 'pc'"

# ── Summary ──────────────────────────────────────────────────────────────────

echo ""
echo "─────────────────────────────────────────"
if [ "$FAIL" -eq 0 ]; then
    echo -e "${GREEN}All $PASS checks passed. Ready for demo.${NC}"
else
    echo -e "${RED}$FAIL check(s) failed. Fix before running demo.${NC}"
    exit 1
fi
echo ""
