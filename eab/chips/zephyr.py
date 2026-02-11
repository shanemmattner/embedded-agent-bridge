"""
Zephyr RTOS chip profile for Embedded Agent Bridge.

Supports Zephyr RTOS builds for various targets including nRF52/53, STM32, ESP32, RP2040.
Uses west for flashing and board-specific debug tools (jlink, openocd, pyocd).
"""

from __future__ import annotations

import re
from pathlib import Path

from .base import (
    ChipFamily,
    ChipProfile,
    FlashCommand,
    OpenOCDConfig,
    ResetSequence,
)


class ZephyrProfile(ChipProfile):
    """
    Profile for Zephyr RTOS builds.

    Wraps west flash/build commands and provides pattern matching for
    Zephyr-specific boot/crash messages across multiple chip families.
    """

    def __init__(self, variant: str | None = None, board: str | None = None, runner: str | None = None):
        """
        Initialize Zephyr profile.

        Args:
            variant: Chip variant (e.g., "nrf5340", "nrf52840", "stm32", "esp32", "rp2040")
            board: Zephyr board name (e.g., "nrf5340dk/nrf5340/cpuapp")
            runner: Flash runner override (e.g., "jlink", "openocd", "nrfjprog")
        """
        super().__init__(variant)
        self.board = board
        self.runner = runner

    # Default board names for known Zephyr variants (used by get_chip_profile registry)
    BOARD_DEFAULTS: dict[str, dict[str, str | None]] = {
        "nrf5340": {"board": "nrf5340dk/nrf5340/cpuapp", "runner": "jlink"},
        "nrf52840": {"board": "nrf52840dk/nrf52840", "runner": "jlink"},
        "nrf52833": {"board": "nrf52833dk/nrf52833", "runner": "jlink"},
        "rp2040": {"board": "rpi_pico", "runner": None},
    }

    @property
    def family(self) -> ChipFamily:
        """Infer chip family from variant string."""
        if not self.variant:
            return ChipFamily.NRF52  # Default for Zephyr
        
        variant_lower = self.variant.lower()
        
        # Map variant prefixes to chip families
        if "nrf52" in variant_lower or "nrf53" in variant_lower:
            return ChipFamily.NRF52
        elif "stm32" in variant_lower:
            return ChipFamily.STM32
        elif "esp32" in variant_lower:
            return ChipFamily.ESP32
        elif "rp2040" in variant_lower:
            return ChipFamily.RP2040
        
        # Default fallback
        return ChipFamily.NRF52

    @property
    def name(self) -> str:
        """Human-readable name for this profile."""
        if self.board:
            return f"Zephyr ({self.board})"
        elif self.variant:
            return f"Zephyr ({self.variant.upper()})"
        return "Zephyr"

    # =========================================================================
    # Pattern Definitions
    # =========================================================================

    @property
    def boot_patterns(self) -> list[str]:
        """Zephyr boot indicators."""
        return [
            "*** Booting Zephyr",
            "Zephyr version",
            "BUILD: ",
        ]

    @property
    def crash_patterns(self) -> list[str]:
        """
        Zephyr crash and fault patterns.

        Includes Zephyr-specific fatal error handlers and ARM Cortex-M faults.
        """
        return [
            # Zephyr-specific fatal errors
            "FATAL ERROR",
            "Fatal fault",
            "CPU exception",
            ">>> ZEPHYR FATAL ERROR",
            ">>> STACK DUMP",
            "Thread aborted",
            "k_panic",
            "k_oops",
            # ARM Cortex-M faults (common on nRF, STM32)
            "MPU FAULT",
            "HardFault_Handler",
            "MemManage_Handler",
            "BusFault_Handler",
            "UsageFault_Handler",
        ]

    @property
    def bootloader_patterns(self) -> list[str]:
        """Patterns indicating bootloader mode."""
        return [
            "Bootloader",
            "MCUboot",
        ]

    @property
    def watchdog_patterns(self) -> list[str]:
        """Zephyr watchdog trigger patterns."""
        return [
            "Watchdog timeout",
            "WDT",
            "watchdog reset",
        ]

    @property
    def running_patterns(self) -> list[str]:
        """Patterns indicating application is running."""
        return [
            "main: Ready",
            "Shell started",
            "Application started",
        ]

    # =========================================================================
    # Reset Sequences
    # =========================================================================

    @property
    def reset_sequences(self) -> dict[str, list[ResetSequence]]:
        """
        Generic reset sequences for Zephyr targets.

        Note: Most Zephyr boards use JTAG/SWD reset via debugger,
        not DTR/RTS. These are fallback sequences.
        """
        return {
            # Generic hard reset via RTS toggle
            "hard_reset": [
                ResetSequence(dtr=None, rts=True, delay=0.1),
                ResetSequence(dtr=None, rts=False, delay=0.0),
            ],
        }

    # =========================================================================
    # Flash Tool Integration
    # =========================================================================

    @property
    def flash_tool(self) -> str:
        return "west"

    def detect_board_from_build(self, build_dir: str | Path) -> str | None:
        """
        Detect Zephyr board name from CMakeCache.txt in build directory.

        Args:
            build_dir: Path to Zephyr build directory

        Returns:
            Board name string or None if not found
        """
        build_path = Path(build_dir)
        cmake_cache = build_path / "CMakeCache.txt"
        
        if not cmake_cache.exists():
            return None
        
        try:
            content = cmake_cache.read_text()
            # Look for BOARD:STRING=boardname
            match = re.search(r'^BOARD:STRING=(.+)$', content, re.MULTILINE)
            if match:
                return match.group(1).strip()
        except Exception:
            pass
        
        return None

    def get_flash_command(
        self,
        firmware_path: str,
        port: str,
        address: str = "0x0",
        board: str | None = None,
        runner: str | None = None,
        build_dir: str | None = None,
        **kwargs,
    ) -> FlashCommand:
        """
        Build west flash command.

        Args:
            firmware_path: Path to firmware binary or build directory
            port: Serial port (used for ESP32 serial flashing)
            address: Flash address (not used by west, kept for compatibility)
            board: Zephyr board name override
            runner: Flash runner override (jlink, openocd, nrfjprog, pyocd)
            build_dir: Build directory path (auto-detected if not specified)
            **kwargs: Additional arguments (ignored)

        Returns:
            FlashCommand with west flash configuration
        """
        board = board or self.board
        runner = runner or self.runner
        
        # Detect build directory from firmware_path
        path = Path(firmware_path)
        if build_dir:
            build_path = Path(build_dir)
        elif path.is_dir():
            # firmware_path is the build directory
            build_path = path
        elif path.parent.name == "zephyr" and (path.parent.parent / "CMakeCache.txt").exists():
            # firmware_path is build/zephyr/zephyr.elf
            build_path = path.parent.parent
        else:
            # Default to current working directory
            build_path = Path.cwd()

        # Build west flash command
        args = ["flash", "--no-rebuild", "--build-dir", str(build_path)]

        if runner:
            args.extend(["--runner", runner])

        # ESP32 serial: add port argument
        if self.family == ChipFamily.ESP32 and port:
            args.extend(["--", "--esp-device", port])

        # Detect Zephyr workspace so west can find its config.
        # Walk up from build_path looking for .west/ directory.
        env: dict[str, str] = {}
        workspace = self._find_workspace(build_path)
        if workspace:
            env["ZEPHYR_BASE"] = str(workspace / "zephyr")

        return FlashCommand(
            tool="west",
            args=args,
            env=env,
            timeout=120.0,
        )

    @staticmethod
    def _find_workspace(start: Path) -> Path | None:
        """Walk up from *start* looking for a directory containing ``.west/``."""
        current = start.resolve()
        for _ in range(20):  # safety limit
            if (current / ".west").is_dir():
                return current
            parent = current.parent
            if parent == current:
                break
            current = parent
        return None

    def get_erase_command(self, port: str, runner: str | None = None, **kwargs) -> FlashCommand:
        """
        Build erase command for Zephyr target.

        Args:
            port: Serial port (ignored for most targets)
            runner: Flash runner override
            **kwargs: Additional chip-specific options

        Returns:
            FlashCommand for erasing flash

        Raises:
            NotImplementedError: If erase not supported for this variant
        """
        runner = runner or self.runner
        variant_lower = (self.variant or "").lower()
        
        # nRF targets: use nrfjprog --recover
        if "nrf" in variant_lower:
            return FlashCommand(
                tool="nrfjprog",
                args=["--recover"],
                timeout=60.0,
            )
        
        # pyocd-based targets
        if runner == "pyocd" or variant_lower in ["rp2040"]:
            return FlashCommand(
                tool="pyocd",
                args=["erase", "-t", self.variant or "cortex_m", "--chip"],
                timeout=60.0,
            )
        
        # Not implemented for other targets
        raise NotImplementedError(
            f"Erase not implemented for Zephyr variant '{self.variant}'. "
            f"Use 'west flash' to overwrite or consult Zephyr docs for your board."
        )

    def get_chip_info_command(self, port: str, **kwargs) -> FlashCommand:
        """
        Build chip info command for Zephyr target.

        Args:
            port: Serial port (ignored)
            **kwargs: Additional options

        Returns:
            FlashCommand for getting chip info

        Raises:
            NotImplementedError: If chip info not supported for this variant
        """
        variant_lower = (self.variant or "").lower()
        
        # nRF targets: use pyocd info
        if "nrf" in variant_lower:
            return FlashCommand(
                tool="pyocd",
                args=["info"],
                timeout=30.0,
            )
        
        # Not implemented for other targets
        raise NotImplementedError(
            f"Chip info not implemented for Zephyr variant '{self.variant}'. "
            f"Use board-specific tools (nrfjprog, pyocd, openocd)."
        )

    # =========================================================================
    # OpenOCD Configuration
    # =========================================================================

    def get_openocd_config(self, **kwargs) -> OpenOCDConfig:
        """
        Get OpenOCD configuration for Zephyr target.

        Args:
            **kwargs: Chip-specific options

        Returns:
            OpenOCDConfig with interface and target configs
        """
        variant_lower = (self.variant or "").lower()
        
        # nRF52/nRF53: Use J-Link with SWD
        # OpenOCD uses nrf52.cfg for both nRF52 and nRF53 targets (shared Cortex-M33 debug)
        if "nrf52" in variant_lower or "nrf53" in variant_lower:
            return OpenOCDConfig(
                interface_cfg="interface/jlink.cfg",
                target_cfg="target/nrf52.cfg",
                transport="swd",
            )
        
        # RP2040: Use CMSIS-DAP with SWD
        if "rp2040" in variant_lower:
            return OpenOCDConfig(
                interface_cfg="interface/cmsis-dap.cfg",
                target_cfg="target/rp2040.cfg",
                transport="swd",
            )
        
        # Fallback: ST-Link with STM32F4 (generic Cortex-M)
        return OpenOCDConfig(
            interface_cfg="interface/stlink.cfg",
            target_cfg="target/stm32f4x.cfg",
            transport="swd",
        )
