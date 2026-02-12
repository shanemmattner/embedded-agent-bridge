"""
ESP32 chip profile for Embedded Agent Bridge.

Supports ESP32, ESP32-S2, ESP32-S3, ESP32-C3, ESP32-C6 and other Espressif chips.
Uses esptool for flashing and esp_usb_jtag for OpenOCD.
"""

from __future__ import annotations

import re
from typing import Optional

from .base import (
    ChipFamily,
    ChipProfile,
    FlashCommand,
    OpenOCDConfig,
    ResetSequence,
)


class ESP32Profile(ChipProfile):
    """
    Profile for ESP32 family chips.

    Supports all ESP-IDF based development with esptool flashing
    and OpenOCD debugging via USB-JTAG or external adapters.
    """

    @property
    def family(self) -> ChipFamily:
        return ChipFamily.ESP32

    @property
    def name(self) -> str:
        if self.variant:
            return f"ESP32 ({self.variant.upper()})"
        return "ESP32"

    # =========================================================================
    # Pattern Definitions (extracted from chip_recovery.py)
    # =========================================================================

    @property
    def boot_patterns(self) -> list[str]:
        """ESP-IDF boot indicators."""
        return [
            "rst:0x",
            "boot:0x",
            "ESP-ROM:",
            "Chip Revision:",
            "ESP-IDF",
            "boot: ESP32",
            "configsip:",
        ]

    @property
    def crash_patterns(self) -> list[str]:
        """
        Comprehensive crash patterns from ESP-IDF Fatal Errors documentation.

        Reference: https://docs.espressif.com/projects/esp-idf/en/latest/esp32/api-guides/fatal-errors.html
        """
        return [
            # Core panic types
            "Guru Meditation",
            "Backtrace:",
            "abort()",
            "panic'ed",
            # CPU exceptions (LoadProhibited, StoreProhibited, etc.)
            "LoadProhibited",
            "StoreProhibited",
            "InstrFetchProhibited",
            "LoadStoreAlignment",
            "LoadStoreError",
            "IllegalInstruction",
            "IntegerDivideByZero",
            "Unhandled debug exception",
            # Cache errors (common with ISR issues)
            "Cache disabled but cached memory region accessed",
            "cache err",
            "cache_err",
            # Memory corruption
            "CORRUPT HEAP",
            "heap_caps_alloc",
            "heap corrupt",
            "Stack smashing",
            "stack overflow",
            "Out of memory",
            "alloc failed",
            # Assert failures
            "assert failed",
            "assertion",
            "ESP_ERROR_CHECK",
            # FreeRTOS panics
            "vApplicationStackOverflowHook",
            "configASSERT",
            # Brownout
            "Brownout detector",
            "brownout",
            # Double exception (very bad)
            "Double exception",
            # SPI flash errors
            "flash read err",
        ]

    @property
    def bootloader_patterns(self) -> list[str]:
        """Patterns indicating ESP32 is in download/bootloader mode."""
        return [
            "waiting for download",
            "download mode",
            "boot mode.*DOWNLOAD",
            "DOWNLOAD(USB/UART0)",
            "boot:0x0",  # Download mode boot
            "serial flasher",
        ]

    @property
    def watchdog_patterns(self) -> list[str]:
        """ESP32 watchdog trigger patterns."""
        return [
            "Task watchdog got triggered",
            "Interrupt wdt timeout",
            "RTC_WDT",
            "INT_WDT",
            "wdt reset",
            "TG0WDT_SYS_RST",
            "TG1WDT_SYS_RST",
            "RTCWDT_RTC_RST",
        ]

    @property
    def running_patterns(self) -> list[str]:
        """Patterns indicating application is running."""
        return [
            "app_main()",
            "Returned from app_main",
            "main_task:",
            "heap_init:",  # Early but indicates successful boot
        ]

    @property
    def error_patterns(self) -> dict[str, str]:
        """ESP-IDF specific error patterns for alert matching."""
        return {
            # General errors
            "ERROR": r"\bE\s*\(\d+\)|error",
            "FAIL": r"fail",
            "DISCONNECT": r"disconnect",
            "TIMEOUT": r"timeout|timed?\s*out",
            # ESP32 crash patterns
            "CRASH": r"crash|guru\s*meditation|Backtrace:",
            "PANIC": r"panic|abort\(\)|Rebooting\.\.\.",
            "ASSERT": r"assert\s*failed|ESP_ERROR_CHECK",
            # ESP32 memory issues
            "MEMORY": r"heap|out\s*of\s*memory|alloc\s*failed|stack\s*overflow",
            # ESP32 watchdog
            "WATCHDOG": r"wdt|watchdog|Task\s+watchdog",
            # ESP32 boot issues
            "BOOT": r"rst:0x|boot:0x|flash\s*read\s*err",
            # ESP32 Wi-Fi/BLE
            "WIFI": r"wifi:.*fail|WIFI_EVENT_STA_DISCONNECTED",
            "BLE": r"BLE.*error|GAP.*fail|GATT.*fail",
        }

    # =========================================================================
    # Reset Sequences
    # =========================================================================

    @property
    def reset_sequences(self) -> dict[str, list[ResetSequence]]:
        """ESP32 reset sequences using DTR/RTS."""
        return {
            # Hard reset (most ESP32 boards)
            "hard_reset": [
                ResetSequence(dtr=False, rts=True, delay=0.1),
                ResetSequence(dtr=False, rts=False, delay=0.0),
            ],
            # Enter bootloader (GPIO0 low during reset)
            "bootloader": [
                ResetSequence(dtr=False, rts=True, delay=0.1),
                ResetSequence(dtr=True, rts=False, delay=0.05),
                ResetSequence(dtr=False, rts=False, delay=0.0),
            ],
            # Soft reset (just toggle RTS)
            "soft_reset": [
                ResetSequence(dtr=None, rts=True, delay=0.1),
                ResetSequence(dtr=None, rts=False, delay=0.0),
            ],
        }

    # =========================================================================
    # Flash Tool Integration
    # =========================================================================

    @property
    def flash_tool(self) -> str:
        return "esptool.py"

    @staticmethod
    def is_usb_jtag_port(port: str) -> bool:
        """Check if port looks like a USB-JTAG/Serial connection (not external UART bridge).

        USB-JTAG ports on macOS show up as /dev/cu.usbmodemXXXX (no "serial" in name).
        External USB-UART bridges show up as /dev/cu.usbserial-XXXX or /dev/cu.SLAB_USBtoUART.
        """
        if not port:
            return False
        port_lower = port.lower()
        # USB-JTAG: usbmodem (macOS), ttyACM (Linux)
        if "usbmodem" in port_lower or "ttyacm" in port_lower:
            return True
        return False

    def get_flash_command(
        self,
        firmware_path: str,
        port: str,
        address: str = "0x10000",
        baud: int = 921600,
        chip: str | None = None,
        no_stub: bool = False,
        **kwargs,
    ) -> FlashCommand:
        """
        Build esptool flash command.

        Args:
            firmware_path: Path to .bin file
            port: Serial port
            address: Flash address (default 0x10000 for app)
            baud: Baud rate for flashing
            chip: Chip type (esp32, esp32s3, etc.)
            no_stub: Use ROM bootloader instead of RAM stub (slower but more reliable)
        """
        chip = chip or self.variant or "auto"
        usb_jtag = self.is_usb_jtag_port(port)

        # USB-JTAG benefits from usb-reset and lower baud
        before_mode = "usb-reset" if usb_jtag else "default_reset"

        args = ["--chip", chip]

        if no_stub:
            args.append("--no-stub")

        args += [
            "--port", port,
            "--baud", str(baud),
            "--before", before_mode,
            "--after", "hard_reset",
            "write_flash",
            "--flash_mode", "dio",
            "--flash_size", "detect",
            address, firmware_path,
        ]

        # Longer timeout when using --no-stub (ROM loader is ~10x slower)
        timeout = 300.0 if no_stub else 120.0

        return FlashCommand(
            tool="esptool.py",
            args=args,
            timeout=timeout,
        )

    def get_erase_command(self, port: str, **kwargs) -> FlashCommand:
        """Build esptool erase_flash command."""
        chip = kwargs.get("chip") or self.variant or "auto"

        return FlashCommand(
            tool="esptool.py",
            args=[
                "--chip", chip,
                "--port", port,
                "erase_flash",
            ],
            timeout=60.0,
        )

    def get_chip_info_command(self, port: str, **kwargs) -> FlashCommand:
        """Build esptool chip_id command."""
        return FlashCommand(
            tool="esptool.py",
            args=["--port", port, "chip_id"],
            timeout=30.0,
        )

    # =========================================================================
    # OpenOCD Configuration
    # =========================================================================

    def get_openocd_config(
        self,
        vid: str = "0x303a",
        pid: str = "0x1001",
        **kwargs,
    ) -> OpenOCDConfig:
        """
        Get OpenOCD configuration for ESP32 USB-JTAG.

        Args:
            vid: USB Vendor ID (default: Espressif 0x303a)
            pid: USB Product ID (default: USB Serial/JTAG 0x1001)
        """
        # Determine target config based on variant
        variant = self.variant or "esp32s3"
        target_map = {
            "esp32": "target/esp32.cfg",
            "esp32s2": "target/esp32s2.cfg",
            "esp32s3": "target/esp32s3.cfg",
            "esp32c3": "target/esp32c3.cfg",
            "esp32c6": "target/esp32c6.cfg",
        }
        target_cfg = target_map.get(variant, "target/esp32s3.cfg")

        return OpenOCDConfig(
            interface_cfg="interface/esp_usb_jtag.cfg",
            target_cfg=target_cfg,
            adapter_driver="esp_usb_jtag",
            extra_commands=[
                f"espusbjtag vid_pid {vid} {pid}",
            ],
        )

    # =========================================================================
    # Utility Methods
    # =========================================================================

    def parse_reset_reason(self, line: str) -> Optional[str]:
        """Parse ESP32 reset reason from boot message."""
        # Format: rst:0x1 (POWERON),boot:0x8 (SPI_FAST_FLASH_BOOT)
        rst_match = re.search(r'rst:0x(\w+)\s*\(([^)]+)\)', line, re.IGNORECASE)
        if rst_match:
            return rst_match.group(2)
        return None

    def parse_boot_mode(self, line: str) -> Optional[str]:
        """Parse ESP32 boot mode from boot message."""
        boot_match = re.search(r'boot:0x(\w+)\s*\(([^)]+)\)', line, re.IGNORECASE)
        if boot_match:
            return boot_match.group(2)
        return None
