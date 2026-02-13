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
    "zephyr_mcxn947": ZephyrProfile,
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

    # Alias mapping: bare chip names to zephyr_ prefixed versions
    # Check if chip name matches any key in ZephyrProfile.BOARD_DEFAULTS
    if chip_lower in ZephyrProfile.BOARD_DEFAULTS:
        chip_lower = f"zephyr_{chip_lower}"

    # Special handling for Zephyr profiles
    if chip_lower.startswith("zephyr_"):
        variant_part = chip_lower[len("zephyr_"):]  # e.g., "nrf5340"
        defaults = ZephyrProfile.BOARD_DEFAULTS.get(variant_part, {})
        return ZephyrProfile(
            variant=variant_part,
            board=defaults.get("board"),
            runner=defaults.get("runner"),
        )
    elif chip_lower == "zephyr":
        return ZephyrProfile(variant=variant)

    if chip_lower not in _PROFILES:
        # Build list of supported chips from _PROFILES and bare Zephyr chip names
        profile_base_names = set(k.split("_")[0] for k in _PROFILES.keys())
        zephyr_bare_names = set(ZephyrProfile.BOARD_DEFAULTS.keys())
        supported = ", ".join(sorted(profile_base_names | zephyr_bare_names))
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

    # ESP32 detection patterns (check BEFORE Zephyr to catch ESP32+Zephyr)
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

    # STM32 detection patterns (check BEFORE Zephyr to catch STM32+Zephyr)
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

    # nRF52 detection (check BEFORE Zephyr to catch nRF+Zephyr)
    nrf_indicators = ["nrf52", "nrf5340", "softdevice", "nordic"]
    if any(ind in line_lower for ind in nrf_indicators):
        return ChipFamily.NRF52

    # Zephyr detection (AFTER chip-specific checks to allow chip detection first)
    # If we see Zephyr but no chip-specific indicators, return ZEPHYR sentinel
    # indicating Zephyr RTOS detected but architecture unknown
    zephyr_indicators = ["booting zephyr", "zephyr version", "zephyr fatal error"]
    if any(ind in line_lower for ind in zephyr_indicators):
        return ChipFamily.ZEPHYR

    return None
