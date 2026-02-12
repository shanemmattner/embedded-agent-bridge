"""
ESP32 chip profile for Embedded Agent Bridge.

Supports ESP32, ESP32-S2, ESP32-S3, ESP32-C3, ESP32-C6 and other Espressif chips.
Uses esptool for flashing and esp_usb_jtag for OpenOCD.
"""

from __future__ import annotations

import logging
import re
import shutil
from pathlib import Path
from typing import Optional

from .base import (
    ChipFamily,
    ChipProfile,
    FlashCommand,
    OpenOCDConfig,
    ResetSequence,
)

logger = logging.getLogger(__name__)


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
        return "esptool"

    @staticmethod
    def find_espressif_openocd() -> str | None:
        """Find the Espressif OpenOCD binary (has ESP32 board configs).

        The standard Homebrew OpenOCD does NOT include esp32c6-builtin.cfg
        or the esp_usb_jtag interface driver. Only the Espressif fork works.

        Returns:
            Path to openocd binary, or None if not found.
        """
        # Check ESP-IDF tools directory (installed by install.sh)
        home = Path.home()
        espressif_dir = home / ".espressif" / "tools" / "openocd-esp32"
        if espressif_dir.exists():
            # Find newest version
            versions = sorted(espressif_dir.iterdir(), reverse=True)
            for ver_dir in versions:
                ocd_bin = ver_dir / "openocd-esp32" / "bin" / "openocd"
                if ocd_bin.exists():
                    logger.info("Found Espressif OpenOCD: %s", ocd_bin)
                    return str(ocd_bin)

        # Check if openocd in PATH has esp32 support
        ocd_path = shutil.which("openocd")
        if ocd_path:
            # Quick check: does it have esp32c6-builtin.cfg?
            ocd_dir = Path(ocd_path).parent.parent / "share" / "openocd" / "scripts" / "board"
            if (ocd_dir / "esp32c6-builtin.cfg").exists():
                return ocd_path

        return None

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

    @staticmethod
    def parse_flash_args(build_dir: Path) -> list[tuple[str, str]] | None:
        """Parse ESP-IDF flash_args file for multi-partition layout.

        Args:
            build_dir: Path to ESP-IDF build directory containing flash_args.

        Returns:
            List of (address, filepath) tuples, or None if flash_args not found.
        """
        flash_args_file = build_dir / "flash_args"
        if not flash_args_file.exists():
            return None

        logger = logging.getLogger(__name__)
        partitions: list[tuple[str, str]] = []
        try:
            for line in flash_args_file.read_text().splitlines():
                line = line.strip()
                if not line or line.startswith("--"):
                    continue
                parts = line.split()
                if len(parts) == 2:
                    addr, rel_path = parts
                    abs_path = build_dir / rel_path
                    if abs_path.exists():
                        partitions.append((addr, str(abs_path)))
                    else:
                        logger.warning("flash_args: file not found: %s", abs_path)
        except OSError:
            return None

        return partitions if partitions else None

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

        If firmware_path is a directory containing flash_args (ESP-IDF build dir),
        all partitions (bootloader, partition table, app) are flashed in one command.

        Args:
            firmware_path: Path to .bin file or ESP-IDF build directory
            port: Serial port
            address: Flash address (default 0x10000 for app, ignored for build dirs)
            baud: Baud rate for flashing
            chip: Chip type (esp32, esp32s3, etc.)
            no_stub: Use ROM bootloader instead of RAM stub (slower but more reliable)
        """
        chip = chip or self.variant or "auto"
        usb_jtag = self.is_usb_jtag_port(port)

        # USB-JTAG benefits from usb-reset and lower baud
        before_mode = "usb-reset" if usb_jtag else "default-reset"

        args = ["--chip", chip]

        if no_stub:
            args.append("--no-stub")

        args += [
            "--port", port,
            "--baud", str(baud),
            "--before", before_mode,
            "--after", "hard-reset",
            "write-flash",
            "--flash-mode", "dio",
            "--flash-size", "detect",
        ]

        # Check if firmware_path is a build directory with flash_args
        fw_path = Path(firmware_path)
        partitions = None
        if fw_path.is_dir():
            partitions = self.parse_flash_args(fw_path)
            if not partitions:
                # Try build/ subdirectory
                partitions = self.parse_flash_args(fw_path / "build")

        if partitions:
            # Multi-partition flash: add all addr/file pairs
            for addr, fpath in partitions:
                args.extend([addr, fpath])
        else:
            # Single binary flash
            args.extend([address, firmware_path])

        # Longer timeout when using --no-stub (ROM loader is ~10x slower)
        timeout = 300.0 if no_stub else 120.0

        return FlashCommand(
            tool="esptool",
            args=args,
            timeout=timeout,
        )

    def get_erase_command(self, port: str, **kwargs) -> FlashCommand:
        """Build esptool erase_flash command."""
        chip = kwargs.get("chip") or self.variant or "auto"

        return FlashCommand(
            tool="esptool",
            args=[
                "--chip", chip,
                "--port", port,
                "erase-flash",
            ],
            timeout=60.0,
        )

    def get_chip_info_command(self, port: str, **kwargs) -> FlashCommand:
        """Build esptool chip_id command."""
        return FlashCommand(
            tool="esptool",
            args=["--port", port, "chip-id"],
            timeout=30.0,
        )

    def get_openocd_flash_command(
        self,
        firmware_path: str,
        address: str = "0x10000",
        board_cfg: str | None = None,
        **kwargs,
    ) -> FlashCommand | None:
        """Build OpenOCD program_esp command for flashing via JTAG.

        Uses the JTAG transport instead of the serial bootloader protocol.
        This is MUCH more reliable for ESP32-C6 USB-JTAG than esptool,
        which uses the serial data stream that drops during large transfers.

        Args:
            firmware_path: Path to .bin file or ESP-IDF build directory.
            address: Flash address (default 0x10000 for app, ignored for build dirs).
            board_cfg: OpenOCD board config (default: auto-detected from variant).

        Returns:
            FlashCommand or None if Espressif OpenOCD is not installed.
        """
        openocd = self.find_espressif_openocd()
        if not openocd:
            logger.warning("Espressif OpenOCD not found — cannot flash via JTAG")
            return None

        # Determine board config
        if not board_cfg:
            variant = self.variant or "esp32c6"
            board_cfg = f"board/{variant}-builtin.cfg"

        args = ["-f", board_cfg]

        # Check if firmware_path is a build directory with flash_args
        fw_path = Path(firmware_path)
        partitions = None
        if fw_path.is_dir():
            partitions = self.parse_flash_args(fw_path)
            if not partitions:
                partitions = self.parse_flash_args(fw_path / "build")

        if partitions:
            # Multi-partition flash: program_esp each partition
            for addr, fpath in partitions:
                args.extend(["-c", f"program_esp {fpath} {addr} verify"])
        else:
            # Single binary flash
            args.extend(["-c", f"program_esp {firmware_path} {address} verify"])

        # Reset and exit
        args.extend(["-c", "reset run", "-c", "shutdown"])

        return FlashCommand(
            tool=openocd,
            args=args,
            timeout=120.0,
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

    # =========================================================================
    # ESP-IDF Project Detection
    # =========================================================================

    @staticmethod
    def detect_chip_from_sdkconfig(project_dir: Path) -> str | None:
        """Detect chip variant from sdkconfig or sdkconfig.defaults.

        Args:
            project_dir: Path to ESP-IDF project directory.

        Returns:
            Chip variant string (e.g., "esp32c6") or None if not found.
        """
        # Try sdkconfig first, then sdkconfig.defaults
        for config_file in ["sdkconfig", "sdkconfig.defaults"]:
            config_path = project_dir / config_file
            if not config_path.exists():
                continue

            try:
                content = config_path.read_text()
                # Look for CONFIG_IDF_TARGET="esp32c6" or CONFIG_IDF_TARGET=esp32c6
                match = re.search(r'CONFIG_IDF_TARGET\s*=\s*"?([^"\s]+)"?', content)
                if match:
                    chip = match.group(1).strip()
                    logger.debug("Detected chip %s from %s", chip, config_path)
                    return chip
            except OSError as e:
                logger.warning("Failed to read %s: %s", config_path, e)
                continue

        return None

    @staticmethod
    def detect_esp_idf_project(path: str) -> dict | None:
        """Detect if path is an ESP-IDF project and extract project info.

        Checks for ESP-IDF project markers:
        - sdkconfig or sdkconfig.defaults
        - CMakeLists.txt with idf_component_register or project()
        - build/flash_args (indicates project is built)

        Args:
            path: Path to potential ESP-IDF project directory.

        Returns:
            Dict with project info or None if not an ESP-IDF project:
            {
                "chip": "esp32c6",           # Chip variant from sdkconfig
                "build_dir": "/path/build",  # Build directory path
                "has_flash_args": True       # Whether flash_args exists
            }
        """
        project_path = Path(path)
        if not project_path.is_dir():
            return None

        # Check for ESP-IDF project markers
        has_sdkconfig = (project_path / "sdkconfig").exists()
        has_sdkconfig_defaults = (project_path / "sdkconfig.defaults").exists()
        has_cmakelists = (project_path / "CMakeLists.txt").exists()

        # Must have either sdkconfig file or CMakeLists.txt
        if not (has_sdkconfig or has_sdkconfig_defaults or has_cmakelists):
            return None

        # If CMakeLists.txt exists, verify it's an ESP-IDF project
        # (unless we have sdkconfig files which are sufficient on their own)
        if has_cmakelists and not (has_sdkconfig or has_sdkconfig_defaults):
            try:
                cmake_content = (project_path / "CMakeLists.txt").read_text()
                # Look for ESP-IDF specific CMake functions
                is_esp_idf = (
                    "idf_component_register" in cmake_content
                    or "IDF_PATH" in cmake_content
                )
                if not is_esp_idf:
                    # Has CMakeLists.txt but doesn't look like ESP-IDF and no sdkconfig
                    return None
            except OSError as e:
                logger.warning("Could not read CMakeLists.txt in %s: %s", project_path, e)

        # Detect chip variant from sdkconfig
        chip = ESP32Profile.detect_chip_from_sdkconfig(project_path)
        if not chip and not (has_sdkconfig or has_sdkconfig_defaults):
            # No chip info and no sdkconfig files - not an ESP-IDF project
            return None

        # Check for build directory and flash_args
        build_dir = project_path / "build"
        has_flash_args = False
        if build_dir.exists() and build_dir.is_dir():
            flash_args_path = build_dir / "flash_args"
            has_flash_args = flash_args_path.exists()
        else:
            build_dir = None

        return {
            "chip": chip,
            "build_dir": str(build_dir) if build_dir else None,
            "has_flash_args": has_flash_args,
        }
