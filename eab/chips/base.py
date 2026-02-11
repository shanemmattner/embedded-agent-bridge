"""
Base ChipProfile class for Embedded Agent Bridge.

Provides the abstraction layer for chip-specific behaviors:
- Pattern matching for crashes, boots, errors
- Flash tool commands (esptool, st-flash, etc.)
- Reset sequences
- OpenOCD configurations
"""

from __future__ import annotations

from abc import ABC, abstractmethod
from dataclasses import dataclass, field
from enum import Enum
from typing import Optional


class ChipFamily(Enum):
    """Supported chip families."""

    ESP32 = "esp32"
    STM32 = "stm32"
    NRF52 = "nrf52"  # Future
    RP2040 = "rp2040"  # Future


@dataclass
class ResetSequence:
    """A reset sequence step using DTR/RTS lines."""

    dtr: Optional[bool]
    rts: Optional[bool]
    delay: float = 0.0


@dataclass
class FlashCommand:
    """A flash command configuration."""

    tool: str  # esptool, st-flash, etc.
    args: list[str]
    env: dict[str, str] = field(default_factory=dict)
    timeout: float = 120.0


@dataclass
class OpenOCDConfig:
    """OpenOCD configuration for a chip."""

    interface_cfg: str  # e.g., "interface/stlink.cfg"
    target_cfg: str  # e.g., "target/stm32f4x.cfg"
    adapter_driver: Optional[str] = None  # e.g., "hla_swd"
    transport: Optional[str] = None  # e.g., "hla_swd", "dapdirect_swd"
    extra_commands: list[str] = field(default_factory=list)


class ChipProfile(ABC):
    """
    Base class for chip-specific profiles.

    Each chip family (ESP32, STM32, etc.) implements this to provide:
    - Pattern definitions for log analysis
    - Flash tool integration
    - Reset sequences
    - OpenOCD configuration
    """

    def __init__(self, variant: str | None = None):
        """
        Initialize the chip profile.

        Args:
            variant: Specific chip variant (e.g., "esp32s3", "stm32f4")
        """
        self.variant = variant

    @property
    @abstractmethod
    def family(self) -> ChipFamily:
        """Return the chip family."""
        ...

    @property
    @abstractmethod
    def name(self) -> str:
        """Human-readable name for this profile."""
        ...

    # =========================================================================
    # Pattern Definitions
    # =========================================================================

    @property
    @abstractmethod
    def boot_patterns(self) -> list[str]:
        """Patterns indicating device boot/reset."""
        ...

    @property
    @abstractmethod
    def crash_patterns(self) -> list[str]:
        """Patterns indicating crashes/faults."""
        ...

    @property
    @abstractmethod
    def bootloader_patterns(self) -> list[str]:
        """Patterns indicating bootloader mode."""
        ...

    @property
    @abstractmethod
    def watchdog_patterns(self) -> list[str]:
        """Patterns indicating watchdog triggers."""
        ...

    @property
    @abstractmethod
    def running_patterns(self) -> list[str]:
        """Patterns indicating successful boot to application."""
        ...

    @property
    def error_patterns(self) -> dict[str, str]:
        """
        Default pattern matchers for alerts.

        Returns dict of {name: regex_pattern}.
        Override in subclass for chip-specific patterns.
        """
        return {
            "ERROR": r"\berror\b",
            "FAIL": r"\bfail",
            "TIMEOUT": r"timeout|timed?\s*out",
        }

    # =========================================================================
    # Reset Sequences
    # =========================================================================

    @property
    @abstractmethod
    def reset_sequences(self) -> dict[str, list[ResetSequence]]:
        """
        Available reset sequences.

        Returns dict of {name: [ResetSequence, ...]}.
        Standard names: "hard_reset", "soft_reset", "bootloader"
        """
        ...

    # =========================================================================
    # Flash Tool Integration
    # =========================================================================

    @property
    @abstractmethod
    def flash_tool(self) -> str:
        """Name of the flash tool (esptool, st-flash, etc.)."""
        ...

    @abstractmethod
    def get_flash_command(
        self,
        firmware_path: str,
        port: str,
        address: str = "0x0",
        **kwargs,
    ) -> FlashCommand:
        """
        Build the flash command for this chip.

        Args:
            firmware_path: Path to firmware binary
            port: Serial port
            address: Flash address
            **kwargs: Additional chip-specific options

        Returns:
            FlashCommand with tool, args, env, timeout
        """
        ...

    @abstractmethod
    def get_erase_command(self, port: str, **kwargs) -> FlashCommand:
        """Build the erase command for this chip."""
        ...

    @abstractmethod
    def get_chip_info_command(self, port: str, **kwargs) -> FlashCommand:
        """Build the chip info command."""
        ...

    # =========================================================================
    # OpenOCD Configuration
    # =========================================================================

    @abstractmethod
    def get_openocd_config(self, **kwargs) -> OpenOCDConfig:
        """
        Get OpenOCD configuration for this chip.

        Args:
            **kwargs: Chip-specific options (vid, pid, adapter, etc.)

        Returns:
            OpenOCDConfig with interface and target configs
        """
        ...

    # =========================================================================
    # Utility Methods
    # =========================================================================

    def parse_reset_reason(self, line: str) -> Optional[str]:
        """
        Parse reset reason from boot message.

        Override in subclass for chip-specific parsing.
        Returns the reset reason string or None.
        """
        return None

    def parse_boot_mode(self, line: str) -> Optional[str]:
        """
        Parse boot mode from boot message.

        Override in subclass for chip-specific parsing.
        Returns the boot mode string or None.
        """
        return None

    def prepare_firmware(self, firmware_path: str) -> tuple[str, bool]:
        """
        Prepare firmware for flashing, performing any needed conversions.

        For example, STM32 needs ELF-to-binary conversion since st-flash
        doesn't handle ELF natively. ESP32 handles ELF via esptool directly.

        Args:
            firmware_path: Path to firmware file

        Returns:
            Tuple of (possibly-converted path, True if converted)

        Raises:
            FileNotFoundError: If firmware file or required tools not found
            RuntimeError: If conversion fails
        """
        return (firmware_path, False)

    def is_line_crash(self, line: str) -> bool:
        """Check if line indicates a crash."""
        line_lower = line.lower()
        return any(p.lower() in line_lower for p in self.crash_patterns)

    def is_line_boot(self, line: str) -> bool:
        """Check if line indicates a boot."""
        line_lower = line.lower()
        return any(p.lower() in line_lower for p in self.boot_patterns)

    def is_line_bootloader(self, line: str) -> bool:
        """Check if line indicates bootloader mode."""
        line_lower = line.lower()
        return any(p.lower() in line_lower for p in self.bootloader_patterns)

    def is_line_running(self, line: str) -> bool:
        """Check if line indicates application is running."""
        line_lower = line.lower()
        return any(p.lower() in line_lower for p in self.running_patterns)
