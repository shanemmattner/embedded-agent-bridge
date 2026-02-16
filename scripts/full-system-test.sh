#!/bin/bash
# Full System Test - Build, Flash, and Stress Test All Boards
# Runs complete end-to-end validation from scratch

set -e

# Colors for output
GREEN='\033[0;32m'
RED='\033[0;31m'
YELLOW='\033[1;33m'
BLUE='\033[0;34m'
NC='\033[0m' # No Color

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
REPO_ROOT="$(cd "$SCRIPT_DIR/.." && pwd)"

# Source ESP-IDF environment
if [ -f ~/esp/esp-idf/export.sh ]; then
    source ~/esp/esp-idf/export.sh >/dev/null
fi

echo -e "${BLUE}========================================${NC}"
echo -e "${BLUE}EAB Full System Test${NC}"
echo -e "${BLUE}========================================${NC}"
echo ""

# ============================================================================
# Phase 1: Build All Firmware
# ============================================================================
echo -e "${GREEN}[Phase 1/4] Building all firmware...${NC}"
echo ""

# C2000 - Docker build
echo -e "${YELLOW}Building C2000 firmware (Docker)...${NC}"
cd "$REPO_ROOT/examples/c2000-stress-test"
./docker-build.sh
if [ ! -f "Debug/launchxl_ex1_f280039c_demo.out" ]; then
    echo -e "${RED}ERROR: C2000 build failed${NC}"
    exit 1
fi
echo -e "${GREEN}✓ C2000 firmware built${NC}"
echo ""

# ESP32-S3 - ESP-IDF build
echo -e "${YELLOW}Building ESP32-S3 firmware...${NC}"
cd "$REPO_ROOT/examples/esp32s3-debug-full"
idf.py build
if [ ! -f "build/esp32s3-debug-full.bin" ]; then
    echo -e "${RED}ERROR: ESP32-S3 build failed${NC}"
    exit 1
fi
echo -e "${GREEN}✓ ESP32-S3 firmware built${NC}"
echo ""

# ESP32-C6 - ESP-IDF build (apptrace-test)
echo -e "${YELLOW}Building ESP32-C6 firmware...${NC}"
cd "$REPO_ROOT/examples/esp32c6-apptrace-test"
idf.py build
if [ ! -f "build/main.bin" ]; then
    echo -e "${RED}ERROR: ESP32-C6 build failed${NC}"
    exit 1
fi
echo -e "${GREEN}✓ ESP32-C6 firmware built${NC}"
echo ""

# ESP32-P4 - ESP-IDF build
echo -e "${YELLOW}Building ESP32-P4 firmware...${NC}"
cd "$REPO_ROOT/examples/esp32p4-stress-test"
idf.py build
if [ ! -f "build/main.bin" ]; then
    echo -e "${RED}ERROR: ESP32-P4 build failed${NC}"
    exit 1
fi
echo -e "${GREEN}✓ ESP32-P4 firmware built${NC}"
echo ""

# nRF5340 - Zephyr build
echo -e "${YELLOW}Building nRF5340 firmware...${NC}"
cd "$REPO_ROOT/examples/nrf5340-rtt-binary-blast"
west build -b nrf5340dk_nrf5340_cpuapp --pristine
if [ ! -f "build/zephyr/zephyr.elf" ]; then
    echo -e "${RED}ERROR: nRF5340 build failed${NC}"
    exit 1
fi
echo -e "${GREEN}✓ nRF5340 firmware built${NC}"
echo ""

# MCXN947 - Zephyr build
echo -e "${YELLOW}Building MCXN947 firmware...${NC}"
cd "$REPO_ROOT/examples/mcxn947-debug-full"
west build -b frdm_mcxn947 --pristine
if [ ! -f "build/zephyr/zephyr.elf" ]; then
    echo -e "${RED}ERROR: MCXN947 build failed${NC}"
    exit 1
fi
echo -e "${GREEN}✓ MCXN947 firmware built${NC}"
echo ""

# STM32L4 - Zephyr build
echo -e "${YELLOW}Building STM32L4 firmware...${NC}"
cd "$REPO_ROOT/examples/stm32l4-debug-full"
west build -b nucleo_l476rg --pristine
if [ ! -f "build/zephyr/zephyr.elf" ]; then
    echo -e "${RED}ERROR: STM32L4 build failed${NC}"
    exit 1
fi
echo -e "${GREEN}✓ STM32L4 firmware built${NC}"
echo ""

# STM32N6 - Zephyr build
echo -e "${YELLOW}Building STM32N6 firmware...${NC}"
cd "$REPO_ROOT/examples/stm32n6-stress-test"
west build -b stm32n6570_dk --pristine
if [ ! -f "build/zephyr/zephyr.elf" ]; then
    echo -e "${RED}ERROR: STM32N6 build failed${NC}"
    exit 1
fi
echo -e "${GREEN}✓ STM32N6 firmware built${NC}"
echo ""

echo -e "${GREEN}[Phase 1 Complete] All firmware built successfully${NC}"
echo ""

# ============================================================================
# Phase 2: Flash All Boards
# ============================================================================
echo -e "${GREEN}[Phase 2/4] Flashing all boards...${NC}"
echo ""

# Use eabctl for all flashing
cd "$REPO_ROOT"

echo -e "${YELLOW}Flashing ESP32-C6...${NC}"
eabctl flash --port /dev/cu.usbmodem101 examples/esp32c6-apptrace-test
echo -e "${GREEN}✓ ESP32-C6 flashed${NC}"
echo ""

echo -e "${YELLOW}Flashing ESP32-P4...${NC}"
eabctl flash --port /dev/cu.usbmodem83201 examples/esp32p4-stress-test
echo -e "${GREEN}✓ ESP32-P4 flashed${NC}"
echo ""

echo -e "${YELLOW}Flashing ESP32-S3...${NC}"
eabctl flash --port /dev/cu.usbmodem5AF71054031 examples/esp32s3-debug-full
echo -e "${GREEN}✓ ESP32-S3 flashed${NC}"
echo ""

echo -e "${YELLOW}Flashing nRF5340...${NC}"
cd examples/nrf5340-rtt-binary-blast
west flash --runner jlink
cd "$REPO_ROOT"
echo -e "${GREEN}✓ nRF5340 flashed${NC}"
echo ""

echo -e "${YELLOW}Flashing MCXN947...${NC}"
cd examples/mcxn947-debug-full
west flash --runner jlink
cd "$REPO_ROOT"
echo -e "${GREEN}✓ MCXN947 flashed${NC}"
echo ""

echo -e "${YELLOW}Flashing STM32L4...${NC}"
cd examples/stm32l4-debug-full
west flash --runner openocd
cd "$REPO_ROOT"
echo -e "${GREEN}✓ STM32L4 flashed${NC}"
echo ""

echo -e "${YELLOW}Flashing STM32N6...${NC}"
cd examples/stm32n6-stress-test
west flash --runner openocd
cd "$REPO_ROOT"
echo -e "${GREEN}✓ STM32N6 flashed${NC}"
echo ""

echo -e "${YELLOW}Flashing C2000...${NC}"
eabctl flash examples/c2000-stress-test
echo -e "${GREEN}✓ C2000 flashed${NC}"
echo ""

echo -e "${GREEN}[Phase 2 Complete] All boards flashed successfully${NC}"
echo ""

# ============================================================================
# Phase 3: Verify All Devices
# ============================================================================
echo -e "${GREEN}[Phase 3/4] Verifying device registration...${NC}"
echo ""

python3 "$REPO_ROOT/scripts/verify_devices.py"

echo -e "${GREEN}[Phase 3 Complete] Device verification passed${NC}"
echo ""

# ============================================================================
# Phase 4: Run Multi-Device Stress Test
# ============================================================================
echo -e "${GREEN}[Phase 4/4] Running multi-device stress test...${NC}"
echo ""

# Run stress test with 180 second duration
python3 "$REPO_ROOT/scripts/multi_device_stress_test.py" \
    --duration 180 \
    --json > /tmp/eab-stress-test-results.json

echo ""
echo -e "${GREEN}========================================${NC}"
echo -e "${GREEN}Full System Test Complete!${NC}"
echo -e "${GREEN}========================================${NC}"
echo ""
echo -e "Results saved to: ${YELLOW}/tmp/eab-stress-test-results.json${NC}"
echo ""
cat /tmp/eab-stress-test-results.json | jq '.'
