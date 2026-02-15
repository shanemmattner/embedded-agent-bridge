#!/bin/bash
#
# Device Detection Script
# Automatically identifies which USB port belongs to which board
#

set -e

echo "=== Detecting Connected Devices ==="
echo ""

# Output file for device map
DEVICE_MAP="/tmp/eab-device-map.json"

# Start JSON array
echo "[" > "$DEVICE_MAP"
FIRST=true

# Function to identify device
identify_device() {
    local port=$1
    local device_type="unknown"
    local chip="unknown"
    local serial=""

    # Try esptool (ESP32 boards)
    if command -v esptool &> /dev/null; then
        local esp_info=$(esptool --port "$port" chip_id 2>&1 || true)
        if echo "$esp_info" | grep -q "Detecting chip type"; then
            if echo "$esp_info" | grep -q "ESP32-C6"; then
                device_type="esp32c6"
                chip="esp32c6"
            elif echo "$esp_info" | grep -q "ESP32-S3"; then
                device_type="esp32s3"
                chip="esp32s3"
            elif echo "$esp_info" | grep -q "ESP32-C3"; then
                device_type="esp32c3"
                chip="esp32c3"
            elif echo "$esp_info" | grep -q "ESP32\$"; then
                device_type="esp32"
                chip="esp32"
            fi
            serial=$(echo "$esp_info" | grep "MAC:" | awk '{print $2}')
        fi
    fi

    # Try J-Link (nRF5340, potentially others)
    if [ "$device_type" = "unknown" ] && command -v JLinkExe &> /dev/null; then
        # Create temp JLink script
        local jlink_script="/tmp/jlink_detect_$$.txt"
        echo "connect" > "$jlink_script"
        echo "?"  >> "$jlink_script"
        echo "exit" >> "$jlink_script"

        local jlink_info=$(JLinkExe -device NRF5340_XXAA_APP -if SWD -speed 4000 -CommandFile "$jlink_script" 2>&1 || true)
        if echo "$jlink_info" | grep -q "nRF5340"; then
            device_type="nrf5340"
            chip="nrf5340"
        fi
        rm -f "$jlink_script"
    fi

    # Try probe-rs (MCXN947, STM32L4)
    if [ "$device_type" = "unknown" ] && command -v probe-rs &> /dev/null; then
        local probe_info=$(probe-rs info --port "$port" 2>&1 || true)
        if echo "$probe_info" | grep -q "MCXN947"; then
            device_type="mcxn947"
            chip="mcxn947"
        elif echo "$probe_info" | grep -q "STM32L4"; then
            device_type="stm32l4"
            chip="stm32l4"
        elif echo "$probe_info" | grep -q "STM32L432"; then
            device_type="stm32l432kc"
            chip="stm32l432kc"
        fi
    fi

    # USB ID detection (fallback)
    if [ "$device_type" = "unknown" ]; then
        # Get USB vendor and product IDs
        local usb_info=$(system_profiler SPUSBDataType 2>/dev/null | grep -A 10 "$(basename $port)" || true)

        if echo "$usb_info" | grep -q "Espressif"; then
            device_type="esp32_unknown"
        elif echo "$usb_info" | grep -q "SEGGER"; then
            device_type="jlink_device"
        elif echo "$usb_info" | grep -q "STMicroelectronics"; then
            device_type="stm32_unknown"
        elif echo "$usb_info" | grep -q "NXP"; then
            device_type="nxp_device"
        fi
    fi

    # Add to JSON array
    if [ "$FIRST" = true ]; then
        FIRST=false
    else
        echo "," >> "$DEVICE_MAP"
    fi

    cat >> "$DEVICE_MAP" << EOF
  {
    "port": "$port",
    "device_type": "$device_type",
    "chip": "$chip",
    "serial": "$serial",
    "detected_at": "$(date -u +%Y-%m-%dT%H:%M:%SZ)"
  }
EOF

    # Print to console
    printf "%-40s %-20s %-15s\n" "$port" "$device_type" "$chip"
}

# Header
printf "%-40s %-20s %-15s\n" "PORT" "DEVICE TYPE" "CHIP"
printf "%-40s %-20s %-15s\n" "----" "-----------" "----"

# Scan all USB devices
for port in /dev/cu.usbmodem* /dev/cu.usbserial* /dev/cu.SLAB*; do
    if [ -e "$port" ]; then
        identify_device "$port"
    fi
done

# Close JSON array
echo "" >> "$DEVICE_MAP"
echo "]" >> "$DEVICE_MAP"

echo ""
echo "Device map saved to: $DEVICE_MAP"
echo ""

# Show summary
echo "=== Summary ==="
echo "Total devices: $(grep -c '"port":' "$DEVICE_MAP" || echo 0)"
echo ""
echo "ESP32 devices: $(grep -c '"device_type": "esp32' "$DEVICE_MAP" || echo 0)"
echo "nRF devices: $(grep -c '"device_type": "nrf' "$DEVICE_MAP" || echo 0)"
echo "STM32 devices: $(grep -c '"device_type": "stm32' "$DEVICE_MAP" || echo 0)"
echo "NXP devices: $(grep -c '"device_type": "nxp' "$DEVICE_MAP" || echo 0 || grep -c '"device_type": "mcxn' "$DEVICE_MAP" || echo 0)"
echo "Unknown devices: $(grep -c '"device_type": "unknown' "$DEVICE_MAP" || echo 0)"
