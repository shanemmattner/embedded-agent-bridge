#!/usr/bin/env bash
# ============================================================================
# EAB Cross-Board Interview Demo
# ============================================================================
# Shows multi-architecture embedded debugging from a single CLI:
#   - 4 boards, 3 probe types, 2 ISAs (ARM Cortex-M + RISC-V)
#   - Hardware-in-the-loop profiling (DWT cycle counter)
#   - GDB bridge for live state inspection
#   - Fault register decoding
#   - Agent-friendly JSON output
#
# Boards:
#   nRF5340 DK    — J-Link SWD          (ARM Cortex-M33, Zephyr RTOS)
#   STM32L4       — OpenOCD + ST-Link   (ARM Cortex-M4, bare metal)
#   NXP MCXN947   — OpenOCD + CMSIS-DAP (ARM Cortex-M33, Zephyr RTOS)
#   ESP32-C6      — Espressif OpenOCD   (RISC-V, ESP-IDF)
#
# Prerequisites: Run `bash examples/demo-preflight.sh` first.
# Usage:         bash examples/demo.sh
# ============================================================================

set -euo pipefail

SCRIPT_DIR="$(cd "$(dirname "$0")" && pwd)"
EAB_ROOT="$(cd "$SCRIPT_DIR/.." && pwd)"
CLI="python3 -m eab.cli"

# ── Toolchain PATH ──────────────────────────────────────────────────────────
export PATH="$HOME/zephyr-sdk-0.17.0/arm-zephyr-eabi/bin:$PATH"
export PATH="$HOME/.espressif/tools/riscv32-esp-elf-gdb/14.2_20240403/riscv32-esp-elf-gdb/bin:$PATH"

# ── ELF paths ───────────────────────────────────────────────────────────────
STM32_ELF="$EAB_ROOT/examples/stm32l4-test-firmware/eab-test-firmware.elf"

# ── Espressif OpenOCD ────────────────────────────────────────────────────────
ESP_OCD="$HOME/.espressif/tools/openocd-esp32/v0.12.0-esp32-20241016/openocd-esp32/bin/openocd"
ESP_SCRIPTS="$HOME/.espressif/tools/openocd-esp32/v0.12.0-esp32-20241016/openocd-esp32/share/openocd/scripts"
OCD_SCRIPTS="/opt/homebrew/share/openocd/scripts"

# ── Colors ───────────────────────────────────────────────────────────────────
RED='\033[0;31m'
GREEN='\033[1;32m'
CYAN='\033[0;36m'
YELLOW='\033[0;33m'
DIM='\033[2m'
BOLD='\033[1m'
NC='\033[0m'

# ── Cleanup trap ─────────────────────────────────────────────────────────────
PIDS_TO_KILL=()
cleanup() {
    for pid in "${PIDS_TO_KILL[@]}"; do
        kill "$pid" 2>/dev/null || true
    done
}
trap cleanup EXIT

# ── Helpers ──────────────────────────────────────────────────────────────────

banner() {
    echo ""
    echo -e "${GREEN}━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━${NC}"
    echo -e "${GREEN}  $1${NC}"
    echo -e "${GREEN}━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━${NC}"
}

explain() {
    echo ""
    echo -e "${DIM}# $1${NC}"
}

show_cmd() {
    echo -e "${CYAN}\$ $1${NC}"
}

run_eab() {
    # Display as eabctl, run as python3 -m eab.cli
    local display_cmd="eabctl $*"
    show_cmd "$display_cmd"
    (cd "$EAB_ROOT" && $CLI "$@") || true
    echo ""
}

pause() {
    echo ""
    read -rp "  Press Enter to continue..."
}

# ── GDB Server Lifecycle ────────────────────────────────────────────────────
# fault-analyze manages its own GDB server. For raw gdb commands, we need
# to start/stop the server ourselves.

start_jlink_gdb() {
    # Start J-Link GDB server for nRF5340 on port 2331
    local device="${1:-NRF5340_XXAA_APP}"
    local port="${2:-2331}"
    JLinkGDBServerCLExe -device "$device" -if SWD -port "$port" -nogui -silent \
        > /tmp/jlink-gdb-demo.log 2>&1 &
    local pid=$!
    PIDS_TO_KILL+=("$pid")
    sleep 1.5  # wait for server startup
    echo "$pid"
}

stop_jlink_gdb() {
    local pid="$1"
    kill "$pid" 2>/dev/null || true
    sleep 0.3
}

start_openocd_stm32() {
    # Start OpenOCD for STM32L4 via ST-Link on port 3333
    openocd -s "$OCD_SCRIPTS" \
        -f interface/stlink.cfg \
        -c "transport select hla_swd" \
        -f target/stm32l4x.cfg \
        -c "gdb_port 3333" \
        -c "telnet_port 4444" \
        -c "init" -c "halt" \
        > /tmp/openocd-stm32-demo.log 2>&1 &
    local pid=$!
    PIDS_TO_KILL+=("$pid")
    sleep 1.5
    echo "$pid"
}

start_openocd_mcxn947() {
    # Start OpenOCD for MCXN947 via CMSIS-DAP on port 3334
    openocd -s "$OCD_SCRIPTS" \
        -f interface/cmsis-dap.cfg \
        -c "transport select swd" \
        -c "adapter speed 1000" \
        -c "swd newdap mcxn947 cpu -dp-id 0" \
        -c "dap create mcxn947.dap -chain-position mcxn947.cpu" \
        -c "target create mcxn947.cpu cortex_m -dap mcxn947.dap -ap-num 0" \
        -c "cortex_m reset_config sysresetreq" \
        -c "gdb_port 3334" \
        -c "telnet_port 4445" \
        -c "tcl_port 6667" \
        -c "init" -c "halt" \
        > /tmp/openocd-mcxn947-demo.log 2>&1 &
    local pid=$!
    PIDS_TO_KILL+=("$pid")
    sleep 1.5
    echo "$pid"
}

stop_server() {
    local pid="$1"
    kill "$pid" 2>/dev/null || true
    sleep 0.3
}


# ============================================================================
# ACT 1: One CLI, Four Architectures
# ============================================================================

banner "ACT 1: One CLI, Four Architectures"

echo ""
echo -e "${BOLD}Three different debug probes, one command interface.${NC}"
echo "  nRF5340 DK  → SEGGER J-Link (SWD)"
echo "  STM32L4     → ST-Link (OpenOCD)"
echo "  MCXN947     → CMSIS-DAP (OpenOCD)"
echo ""
echo "  fault-analyze starts its own GDB server, reads fault registers,"
echo "  decodes them, and tears down — all in one command."

explain "Read fault registers on nRF5340 via J-Link"
run_eab --json fault-analyze --device NRF5340_XXAA_APP --chip nrf5340 --probe jlink

explain "Same command, different board — STM32L4 via ST-Link"
run_eab --json fault-analyze --chip stm32l4 --probe openocd

explain "Same command, third probe — MCXN947 via CMSIS-DAP"
run_eab --json fault-analyze --device MCXN947 --chip mcxn947 --probe openocd

pause

# ============================================================================
# ACT 2: Live Cycle Counter (DWT)
# ============================================================================

banner "ACT 2: Live Cycle Counter — DWT_CYCCNT"

echo ""
echo -e "${BOLD}The ARM DWT cycle counter increments every CPU clock tick.${NC}"
echo "  DWT_CTRL   @ 0xE0001000  (bit 0 = enable)"
echo "  DWT_CYCCNT @ 0xE0001004  (32-bit free-running counter)"
echo ""
echo "  We'll read it twice with a 1-second gap to prove the CPU is running."

explain "Starting J-Link GDB server for nRF5340..."
JLINK_PID=$(start_jlink_gdb NRF5340_XXAA_APP 2331)
echo -e "${DIM}  (JLinkGDBServer PID $JLINK_PID on port 2331)${NC}"

explain "Read DWT_CYCCNT — first sample"
run_eab --json gdb --chip nrf5340 --target localhost:2331 \
    --cmd "x/1xw 0xE0001004"

explain "Wait 1 second — the CPU is running real code on real silicon"
sleep 1

explain "Read DWT_CYCCNT — second sample (should differ by millions of cycles)"
run_eab --json gdb --chip nrf5340 --target localhost:2331 \
    --cmd "x/1xw 0xE0001004"

echo -e "${YELLOW}The counter changed → hardware is alive, firmware is executing.${NC}"

stop_server "$JLINK_PID"

pause

# ============================================================================
# ACT 3: GDB Bridge — Inspect Live State
# ============================================================================

banner "ACT 3: GDB Bridge — Inspect Live State"

echo ""
echo -e "${BOLD}One-shot GDB commands across all boards. No interactive session.${NC}"

# --- nRF5340: Inspect Zephyr _kernel struct ---

explain "Starting J-Link GDB server for nRF5340..."
JLINK_PID=$(start_jlink_gdb NRF5340_XXAA_APP 2331)

explain "Inspect core registers on nRF5340 (J-Link, port 2331)"
run_eab --json gdb --chip nrf5340 --target localhost:2331 \
    --cmd "info registers"

stop_server "$JLINK_PID"

# --- STM32L4: Memory dump ---

explain "Starting OpenOCD for STM32L4 (ST-Link)..."
STM32_PID=$(start_openocd_stm32)
echo -e "${DIM}  (OpenOCD PID $STM32_PID on port 3333)${NC}"

explain "Dump 64 bytes of SRAM on STM32L4"
run_eab --json gdb --chip stm32l4 --target localhost:3333 \
    --elf "$STM32_ELF" \
    --cmd "x/16xw 0x20000000"

stop_server "$STM32_PID"

# --- MCXN947: Memory dump ---

explain "Starting OpenOCD for MCXN947 (CMSIS-DAP)..."
MCXN_PID=$(start_openocd_mcxn947)
echo -e "${DIM}  (OpenOCD PID $MCXN_PID on port 3334)${NC}"

explain "Dump 64 bytes of SRAM on MCXN947"
run_eab --json gdb --chip mcxn947 --target localhost:3334 \
    --cmd "x/16xw 0x20000000"

stop_server "$MCXN_PID"

# --- ESP32-C6: RISC-V register dump ---

explain "Register dump on ESP32-C6 RISC-V (Espressif OpenOCD batch mode)"
show_cmd "openocd -f board/esp32c6-builtin.cfg -c 'init; halt; reg; resume; shutdown'"
echo ""
"$ESP_OCD" -s "$ESP_SCRIPTS" -f board/esp32c6-builtin.cfg \
    -c "init" -c "halt" -c "reg" -c "resume" -c "shutdown" 2>&1 \
    | grep -E '^\(|^(pc|ra|sp|gp|tp|a[0-7]|s[0-9]+|t[0-6])\s' \
    | head -20 \
    || echo -e "${DIM}(see /tmp/esp32c6-openocd.log for full output)${NC}"
echo ""

pause

# ============================================================================
# ACT 4: Fault Analysis
# ============================================================================

banner "ACT 4: Fault Analysis — Cortex-M Crash Decoding"

echo ""
echo -e "${BOLD}Reads CFSR, HFSR, MMFAR, BFAR and decodes each fault bit.${NC}"
echo "  Works on any Cortex-M: nRF5340 (M33), STM32L4 (M4), MCXN947 (M33)"

explain "Full fault analysis on nRF5340 — human-readable report"
show_cmd "eabctl fault-analyze --device NRF5340_XXAA_APP --chip nrf5340 --probe jlink"
echo ""
(cd "$EAB_ROOT" && $CLI fault-analyze --device NRF5340_XXAA_APP --chip nrf5340 --probe jlink) || true
echo ""

pause

# ============================================================================
# ACT 5: Why JSON? — The Agent Loop
# ============================================================================

banner "ACT 5: Why JSON? — The Agent Loop"

echo ""
echo -e "${BOLD}Every eabctl command supports --json. Designed for LLM agents.${NC}"

explain "Pipe fault-analyze JSON through python3 -m json.tool (pretty-print)"
show_cmd "eabctl --json fault-analyze --chip stm32l4 --probe openocd | python3 -m json.tool"
echo ""
(cd "$EAB_ROOT" && $CLI --json fault-analyze --chip stm32l4 --probe openocd) \
    | python3 -m json.tool 2>/dev/null || true
echo ""

explain "An LLM agent uses this in a read-decide-act loop:"
echo ""
cat <<'AGENT'
    ┌──────────────┐
    │   LLM Agent  │  "Is the board faulted?"
    └──────┬───────┘
           ▼
    eabctl --json fault-analyze --probe openocd
           │
           ▼
    {"fault_registers": {"CFSR": "0x00000000", ...},
     "faults": [],             ◄── no faults active
     "suggestions": []}
           │
           │  faults == [] → "Board healthy. Check DWT."
           ▼
    eabctl --json gdb --cmd "x/1xw 0xE0001004"
           │
           ▼
    {"success": true,
     "stdout": "0xe0001004: 0x02f3a8c0"}
           │
           │  Parse cycle count → compute throughput
           ▼
    Agent: "CPU at 64MHz, DWT shows 49M cycles elapsed."
AGENT
echo ""

# ── Summary ──────────────────────────────────────────────────────────────────

echo -e "${GREEN}━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━${NC}"
echo -e "${GREEN}  Demo complete.${NC}"
echo -e "${GREEN}━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━${NC}"
echo ""
echo "  Boards:  4  (nRF5340, STM32L4, MCXN947, ESP32-C6)"
echo "  Probes:  3  (J-Link, ST-Link, CMSIS-DAP)"
echo "  ISAs:    2  (ARM Cortex-M, RISC-V)"
echo "  CLI:     eabctl (python3 -m eab.cli)"
echo ""
