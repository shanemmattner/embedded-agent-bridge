"""
Chip-specific profiles for Embedded Agent Bridge.

This module provides abstractions for different microcontroller families,
allowing EAB to work with ESP32, STM32, nRF52, and other chips.

Usage:
    from eab.chips import get_chip_profile, ESP32Profile, STM32Profile

    # Auto-detect from serial output
    profile = get_chip_profile("auto", serial_output)

    # Or specify explicitly
    profile = get_chip_profile("stm32")
"""

from .base import ChipProfile, ChipFamily
from .esp32 import ESP32Profile
from .stm32 import STM32Profile
from .zephyr import ZephyrProfile

__all__ = [
    "ChipProfile",
    "ChipFamily",
    "ESP32Profile",
    "STM32Profile",
    "ZephyrProfile",
    "get_chip_profile",
    "detect_chip_family",
]


# Registry of chip profiles
_PROFILES: dict[str, type[ChipProfile]] = {
    "esp32": ESP32Profile,
    "esp32s2": ESP32Profile,
    "esp32s3": ESP32Profile,
    "esp32c3": ESP32Profile,
    "esp32c6": ESP32Profile,
    "stm32": STM32Profile,
    "stm32f4": STM32Profile,
    "stm32l4": STM32Profile,
    "stm32h7": STM32Profile,
    "stm32f1": STM32Profile,
    "stm32f3": STM32Profile,
    "zephyr_nrf5340": ZephyrProfile,
    "zephyr_nrf52840": ZephyrProfile,
    "zephyr_nrf52833": ZephyrProfile,
    "zephyr_rp2040": ZephyrProfile,
    "zephyr": ZephyrProfile,
}


def get_chip_profile(chip: str, variant: str | None = None) -> ChipProfile:
    """
    Get a chip profile instance.

    Args:
        chip: Chip family name (esp32, stm32, etc.) or "auto"
        variant: Specific variant (esp32s3, stm32f4, etc.)

    Returns:
        ChipProfile instance configured for the chip

    Raises:
        ValueError: If chip family is not supported
    """
    chip_lower = chip.lower()

    if chip_lower == "auto":
        # Return ESP32 as default for now - detection happens via serial output
        return ESP32Profile(variant=variant)

    # Special handling for Zephyr profiles
    if chip_lower.startswith("zephyr_"):
        variant_part = chip_lower[len("zephyr_"):]  # e.g., "nrf5340"
        board_map = {
            "nrf5340": "nrf5340dk/nrf5340/cpuapp",
            "nrf52840": "nrf52840dk/nrf52840",
            "nrf52833": "nrf52833dk/nrf52833",
            "rp2040": "rpi_pico",
        }
        return ZephyrProfile(
            variant=variant_part,
            board=board_map.get(variant_part),
            runner="jlink" if "nrf" in variant_part else None
        )
    elif chip_lower == "zephyr":
        return ZephyrProfile(variant=variant)

    if chip_lower not in _PROFILES:
        supported = ", ".join(sorted(set(k.split("_")[0] for k in _PROFILES.keys())))
        raise ValueError(f"Unsupported chip: {chip}. Supported: {supported}")

    profile_class = _PROFILES[chip_lower]
    return profile_class(variant=variant or chip_lower)


def detect_chip_family(line: str) -> ChipFamily | None:
    """
    Detect chip family from a line of serial output.

    Args:
        line: A line from serial output

    Returns:
        ChipFamily enum or None if not detected
    """
    line_lower = line.lower()

    # Zephyr detection (before chip-specific checks)
    zephyr_indicators = ["booting zephyr", "zephyr version", "zephyr fatal error"]
    if any(ind in line_lower for ind in zephyr_indicators):
        return ChipFamily.NRF52  # Default to NRF52 for Zephyr

    # ESP32 detection patterns
    esp32_indicators = [
        "esp-idf",
        "esp32",
        "esp-rom:",
        "rst:0x",
        "boot:0x",
        "configsip:",
        "xtensa",
    ]
    if any(ind in line_lower for ind in esp32_indicators):
        return ChipFamily.ESP32

    # STM32 detection patterns
    stm32_indicators = [
        "stm32",
        "hal_init",
        "systemcoreclockupdate",
        "hardfault_handler",
        "stlink",
        "cortex-m",
        "arm-none-eabi",
    ]
    if any(ind in line_lower for ind in stm32_indicators):
        return ChipFamily.STM32

    # nRF52 detection
    nrf_indicators = ["nrf52", "nrf5340", "softdevice", "nordic"]
    if any(ind in line_lower for ind in nrf_indicators):
        return ChipFamily.NRF52

    return None
