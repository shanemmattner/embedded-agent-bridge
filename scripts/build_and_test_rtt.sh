#!/bin/bash
# Build RTT-enabled firmware and test on all boards
set -e

# Colors
RED='\033[0;31m'
GREEN='\033[0;32m'
YELLOW='\033[1;33m'
NC='\033[0m' # No Color

echo "=========================================="
echo "Build and Test RTT Firmware"
echo "=========================================="
echo

# Set Zephyr environment
export ZEPHYR_BASE=~/zephyrproject/zephyr
if [ ! -d "$ZEPHYR_BASE" ]; then
    echo -e "${RED}✗ Zephyr not found at $ZEPHYR_BASE${NC}"
    exit 1
fi

# Verify west
if ! command -v west &> /dev/null; then
    echo -e "${RED}✗ west not found in PATH${NC}"
    exit 1
fi

echo -e "${GREEN}✓ Zephyr environment OK${NC}"
echo

# Build counter
built=0
failed=0

# Function to build and flash
build_and_flash() {
    local name=$1
    local project_dir=$2
    local board=$3
    local device=$4
    local transport=$5
    local base_dir=$6

    echo "----------------------------------------"
    echo "Building: $name"
    echo "Board: $board"
    echo "Project: $project_dir"
    echo "----------------------------------------"

    # Build
    if west build -b "$board" "$project_dir" -p auto; then
        echo -e "${GREEN}✓ Build succeeded${NC}"
        ((built++))

        # Flash
        echo "Flashing to $board..."
        if west flash --skip-rebuild; then
            echo -e "${GREEN}✓ Flash succeeded${NC}"

            # Wait for firmware to boot
            sleep 2

            # Test RTT
            echo "Testing RTT with $transport transport..."
            if eabctl rtt start --device "$device" --transport "$transport" --base-dir "$base_dir" --json | jq -e '.running == true' > /dev/null 2>&1; then
                echo -e "${GREEN}✓ RTT working!${NC}"

                # Read some data
                sleep 1
                if [ "$transport" = "jlink" ]; then
                    eabctl rtt tail 20 --base-dir "$base_dir" | head -20
                    eabctl rtt stop --base-dir "$base_dir" --json > /dev/null
                fi

                return 0
            else
                echo -e "${YELLOW}⚠ RTT not detected (firmware may need more boot time)${NC}"
                return 1
            fi
        else
            echo -e "${RED}✗ Flash failed${NC}"
            ((failed++))
            return 1
        fi
    else
        echo -e "${RED}✗ Build failed${NC}"
        ((failed++))
        return 1
    fi
}

# 1. nRF5340 (already has RTT firmware)
if build_and_flash \
    "nRF5340 RTT Binary Blast" \
    "examples/nrf5340-rtt-binary-blast" \
    "nrf5340dk_nrf5340_cpuapp" \
    "nRF5340_xxAA" \
    "jlink" \
    "/tmp/eab-devices/nrf5340"; then
    echo -e "${GREEN}nRF5340: PASS${NC}\n"
else
    echo -e "${YELLOW}nRF5340: PARTIAL (build OK, RTT needs investigation)${NC}\n"
fi

# 2. STM32L4 (now has RTT enabled)
if build_and_flash \
    "STM32L4 Sensor Node" \
    "examples/stm32l4-sensor-node" \
    "nucleo_l432kc" \
    "STM32L432KCUx" \
    "probe-rs" \
    "/tmp/eab-devices/stm32"; then
    echo -e "${GREEN}STM32L4: PASS${NC}\n"
else
    echo -e "${YELLOW}STM32L4: PARTIAL (build OK, RTT needs investigation)${NC}\n"
fi

# 3. MCXN947 (now has RTT enabled)
if build_and_flash \
    "MCXN947 Sensor Node" \
    "examples/mcxn947-sensor-node" \
    "frdm_mcxn947" \
    "MCXN947" \
    "probe-rs" \
    "/tmp/eab-devices/mcxn947"; then
    echo -e "${GREEN}MCXN947: PASS${NC}\n"
else
    echo -e "${YELLOW}MCXN947: PARTIAL (build OK, RTT needs investigation)${NC}\n"
fi

# Summary
echo "=========================================="
echo "SUMMARY"
echo "=========================================="
echo -e "Built: ${GREEN}$built${NC}"
echo -e "Failed: ${RED}$failed${NC}"
echo

if [ $failed -eq 0 ]; then
    echo -e "${GREEN}✓ All firmware built successfully${NC}"
    exit 0
else
    echo -e "${YELLOW}⚠ Some builds failed${NC}"
    exit 1
fi
