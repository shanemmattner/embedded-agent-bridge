"""Chip detection and firmware preparation for flash commands."""

from __future__ import annotations

import logging
import os
from typing import Optional

from eab.cli.helpers import _print

logger = logging.getLogger(__name__)


def _detect_esp_idf_project(
    firmware: str, chip: Optional[str], json_mode: bool
) -> tuple[bool, Optional[str], Optional[int]]:
    """Detect ESP-IDF project and auto-detect chip type.
    
    Args:
        firmware: Path to firmware file or build directory.
        chip: Explicit chip override (may be None).
        json_mode: JSON output mode.
    
    Returns:
        (is_esp_idf_project, chip, error_code)
        error_code is None on success, or an int exit code on failure.
    """
    is_esp_idf_project = False

    if os.path.isdir(firmware):
        from eab.chips.esp32 import ESP32Profile
        
        project_info = ESP32Profile.detect_esp_idf_project(firmware)
        
        if project_info is not None:
            is_esp_idf_project = True
            if not project_info.get("has_flash_args"):
                _print(
                    {"error": "ESP-IDF project not built. Run 'idf.py build' first."},
                    json_mode=json_mode
                )
                return is_esp_idf_project, chip, 1

            if chip is None and project_info.get("chip"):
                chip = project_info["chip"]
                logger.info("Auto-detected chip type: %s", chip)
    
    if chip is None:
        if is_esp_idf_project:
            _print(
                {"error": "Could not detect chip from sdkconfig. Specify --chip explicitly."},
                json_mode=json_mode
            )
        elif os.path.isdir(firmware):
            _print(
                {"error": "not an ESP-IDF project. Expected sdkconfig or sdkconfig.defaults in project directory."},
                json_mode=json_mode
            )
        else:
            _print(
                {"error": "--chip is required when flashing a binary file"},
                json_mode=json_mode
            )
        return is_esp_idf_project, chip, 1

    return is_esp_idf_project, chip, None


def _prepare_firmware(firmware: str, profile, json_mode: bool):
    """Prepare firmware file (ELF→BIN conversion if needed).
    
    Args:
        firmware: Path to firmware file or directory.
        profile: Chip profile instance.
        json_mode: JSON output mode.
    
    Returns:
        (firmware_path, temp_bin_path, converted_from_elf, error_code)
        error_code is None on success.
    """
    temp_bin_path = None
    converted_from_elf = False

    if not os.path.isdir(firmware):
        try:
            firmware, converted_from_elf = profile.prepare_firmware(firmware)
            if converted_from_elf:
                temp_bin_path = firmware
        except FileNotFoundError as e:
            _print({"error": str(e)}, json_mode=json_mode)
            return firmware, None, False, 1
        except RuntimeError as e:
            _print({"error": str(e)}, json_mode=json_mode)
            return firmware, None, False, 1
        except Exception as e:
            _print({"error": f"Failed to read firmware file: {e}"}, json_mode=json_mode)
            return firmware, None, False, 1

    return firmware, temp_bin_path, converted_from_elf, None
