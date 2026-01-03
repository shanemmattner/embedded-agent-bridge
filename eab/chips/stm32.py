"""
STM32 chip profile for Embedded Agent Bridge.

Supports STM32F1, STM32F3, STM32F4, STM32L4, STM32H7, and other STM32 families.
Uses st-flash or STM32CubeProgrammer for flashing, and ST-Link for debugging.

References:
- HardFault debugging: https://interrupt.memfault.com/blog/cortex-m-hardfault-debug
- ST-Link tools: https://github.com/stlink-org/stlink
- OpenOCD STM32: https://openocd.org/doc/pdf/openocd.pdf
"""

from __future__ import annotations

import glob
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


def _find_stm32_programmer_cli() -> str:
    """
    Find STM32_Programmer_CLI executable.

    Searches in PATH first, then common installation locations on macOS.

    Returns:
        Path to STM32_Programmer_CLI or "STM32_Programmer_CLI" if not found
        (will fail gracefully with "tool not found" error).
    """
    # Check PATH first
    path = shutil.which("STM32_Programmer_CLI")
    if path:
        return path

    # Common locations on macOS (STM32CubeIDE installs here)
    search_patterns = [
        "/Applications/STM32CubeIDE.app/Contents/Eclipse/plugins/com.st.stm32cube.ide.mcu.externaltools.cubeprogrammer.*/tools/bin/STM32_Programmer_CLI",
        "/Applications/STMicroelectronics/STM32Cube/STM32CubeProgrammer/STM32CubeProgrammer.app/Contents/MacOs/bin/STM32_Programmer_CLI",
        str(Path.home() / "STMicroelectronics/STM32Cube/STM32CubeProgrammer/bin/STM32_Programmer_CLI"),
    ]

    for pattern in search_patterns:
        matches = glob.glob(pattern)
        if matches:
            # Return the most recent version (sorted by path)
            return sorted(matches)[-1]

    # Not found - return bare name and let subprocess fail with clear error
    return "STM32_Programmer_CLI"


class STM32Profile(ChipProfile):
    """
    Profile for STM32 family chips (ARM Cortex-M based).

    Supports STM32F1/F3/F4/L4/H7 series with st-flash or STM32CubeProgrammer
    for flashing and ST-Link for debugging via SWD.
    """

    @property
    def family(self) -> ChipFamily:
        return ChipFamily.STM32

    @property
    def name(self) -> str:
        if self.variant:
            return f"STM32 ({self.variant.upper()})"
        return "STM32"

    # =========================================================================
    # Pattern Definitions
    # =========================================================================

    @property
    def boot_patterns(self) -> list[str]:
        """STM32 boot/reset indicators."""
        return [
            # HAL initialization
            "HAL_Init",
            "SystemInit",
            "SystemCoreClock",
            "SystemCoreClockUpdate",
            # Common startup messages
            "Reset_Handler",
            "main()",
            "Starting",
            "Booting",
            "Initializing",
            # Reset sources (if printed by firmware)
            "IWDG reset",
            "WWDG reset",
            "Software reset",
            "Power-on reset",
            "POR/PDR reset",
            "Pin reset",
            "NRST",
            # STM32CubeIDE default prints
            "STM32",
            "Nucleo",
            "Discovery",
        ]

    @property
    def crash_patterns(self) -> list[str]:
        """
        ARM Cortex-M fault patterns.

        References:
        - https://interrupt.memfault.com/blog/cortex-m-hardfault-debug
        - https://community.st.com/t5/stm32-mcus/how-to-debug-a-hardfault-on-an-arm-cortex-m-stm32/ta-p/672235
        """
        return [
            # Cortex-M fault handlers
            "HardFault_Handler",
            "HardFault",
            "Hard Fault",
            "MemManage_Handler",
            "MemManage",
            "Memory Management Fault",
            "BusFault_Handler",
            "BusFault",
            "Bus Fault",
            "UsageFault_Handler",
            "UsageFault",
            "Usage Fault",
            # Fault status register bits (when printed)
            "FORCED",  # Escalated fault
            "VECTTBL",  # Vector table error
            "IBUSERR",  # Instruction bus error
            "PRECISERR",  # Precise data bus error
            "IMPRECISERR",  # Imprecise data bus error
            "UNSTKERR",  # Unstacking error
            "STKERR",  # Stacking error
            "LSPERR",  # Lazy state preservation error
            "UNDEFINSTR",  # Undefined instruction
            "INVSTATE",  # Invalid state
            "INVPC",  # Invalid PC
            "NOCP",  # No coprocessor
            "UNALIGNED",  # Unaligned access
            "DIVBYZERO",  # Division by zero
            # Memory protection
            "IACCVIOL",  # Instruction access violation
            "DACCVIOL",  # Data access violation
            "MUNSTKERR",  # MemManage unstacking
            "MSTKERR",  # MemManage stacking
            "MLSPERR",  # MemManage lazy state
            # Common crash indicators
            "Fault",
            "fault",
            "CFSR",  # Configurable fault status register
            "HFSR",  # HardFault status register
            "MMFAR",  # MemManage fault address
            "BFAR",  # BusFault address
            # Stack overflow (FreeRTOS or custom)
            "Stack overflow",
            "stack overflow",
            "vApplicationStackOverflowHook",
            # Assert/Error
            "assert_failed",
            "Error_Handler",
            "_Error_Handler",
            "assert_param",
            # NMI
            "NMI_Handler",
        ]

    @property
    def bootloader_patterns(self) -> list[str]:
        """Patterns indicating STM32 is in bootloader/DFU mode."""
        return [
            # ST bootloader
            "System memory boot",
            "DFU mode",
            "USB DFU",
            "BOOT0",
            "Bootloader",
            # STM32 USB patterns
            "USB Device",
            "DFU Interface",
        ]

    @property
    def watchdog_patterns(self) -> list[str]:
        """STM32 watchdog trigger patterns."""
        return [
            "IWDG",  # Independent watchdog
            "WWDG",  # Window watchdog
            "Watchdog reset",
            "watchdog timeout",
            "WDG reset",
            "IWDG reset",
            "WWDG reset",
        ]

    @property
    def running_patterns(self) -> list[str]:
        """Patterns indicating application is running normally."""
        return [
            # Common application ready messages
            "Ready",
            "Initialized",
            "Started",
            "Running",
            # FreeRTOS
            "Scheduler started",
            "vTaskStartScheduler",
            # HAL tick running
            "HAL_GetTick",
            # UART ready
            "UART ready",
            "USART ready",
        ]

    @property
    def error_patterns(self) -> dict[str, str]:
        """STM32/Cortex-M specific error patterns for alert matching."""
        return {
            # General errors
            "ERROR": r"\berror\b|Error_Handler",
            "FAIL": r"\bfail",
            "TIMEOUT": r"timeout|timed?\s*out|HAL_TIMEOUT",
            # Cortex-M faults
            "HARDFAULT": r"HardFault|Hard\s*Fault",
            "MEMFAULT": r"MemManage|Memory.*Fault",
            "BUSFAULT": r"BusFault|Bus.*Fault",
            "USAGEFAULT": r"UsageFault|Usage.*Fault",
            # Watchdog
            "WATCHDOG": r"IWDG|WWDG|watchdog|WDG",
            # HAL errors
            "HAL_ERROR": r"HAL_ERROR|HAL_BUSY|HAL_TIMEOUT",
            # Peripheral errors
            "UART_ERROR": r"USART.*error|UART.*error|ORE|FE|NE|PE",
            "I2C_ERROR": r"I2C.*error|NACK|BERR|ARLO|AF",
            "SPI_ERROR": r"SPI.*error|MODF|OVR|CRCERR",
        }

    # =========================================================================
    # Reset Sequences
    # =========================================================================

    @property
    def reset_sequences(self) -> dict[str, list[ResetSequence]]:
        """
        STM32 reset sequences.

        Note: STM32 typically uses NRST pin controlled via ST-Link,
        not DTR/RTS. These sequences are for boards with DTR/RTS wiring
        (like some USB-UART adapters connected to NRST).
        """
        return {
            # Hard reset (if NRST connected to RTS)
            "hard_reset": [
                ResetSequence(dtr=None, rts=True, delay=0.1),
                ResetSequence(dtr=None, rts=False, delay=0.0),
            ],
            # Soft reset (just toggle RTS)
            "soft_reset": [
                ResetSequence(dtr=None, rts=True, delay=0.05),
                ResetSequence(dtr=None, rts=False, delay=0.0),
            ],
            # Enter bootloader (BOOT0 high during reset)
            # Requires BOOT0 connected to DTR
            "bootloader": [
                ResetSequence(dtr=True, rts=True, delay=0.1),
                ResetSequence(dtr=True, rts=False, delay=0.1),
                ResetSequence(dtr=False, rts=False, delay=0.0),
            ],
        }

    # =========================================================================
    # Stock Firmware Registry
    # =========================================================================

    @property
    def stock_firmware_registry(self) -> dict[str, dict[str, str]]:
        """
        Known-good stock firmware paths by board type.

        Used by `preflight-hw` command to verify hardware chain before debugging.
        These are paths relative to project roots where stock firmware can be found.

        Key = board identifier
        Value = dict with:
            - path: Relative path to stock firmware binary
            - address: Flash address for this firmware
            - description: Human-readable description
        """
        return {
            "sensortile": {
                "path": "firmware/fp-sns-allmems1-4.2.0/Projects/STM32L476JG-SensorTile/Applications/ALLMEMS1/Binary/STM32L476JG-SensorTile_ALLMEMS1_v4.2.0.bin",
                "address": "0x08004000",  # App runs after bootloader
                "description": "ST ALLMEMS1 demo firmware v4.2.0",
            },
            "sensortile-bootloader": {
                "path": "firmware/fp-sns-allmems1-4.2.0/Utilities/BootLoader/STM32L476RG/BootLoaderL4.bin",
                "address": "0x08000000",
                "description": "ST bootloader for SensorTile",
            },
            # Add more boards as we encounter them:
            # "nucleo-l476rg": {
            #     "path": "...",
            #     "address": "0x08000000",
            #     "description": "...",
            # },
        }

    def get_stock_firmware(self, board: str) -> Optional[dict[str, str]]:
        """
        Get stock firmware info for a board.

        Args:
            board: Board identifier (e.g., "sensortile", "nucleo-l476rg")

        Returns:
            Dict with path, address, description or None if not found
        """
        return self.stock_firmware_registry.get(board.lower())

    # =========================================================================
    # Flash Tool Integration
    # =========================================================================

    @property
    def flash_tool(self) -> str:
        return "st-flash"

    def get_flash_command(
        self,
        firmware_path: str,
        port: str,  # Not used for st-flash (uses USB)
        address: str = "0x08000000",
        tool: str = "st-flash",
        connect_under_reset: bool = False,
        **kwargs,
    ) -> FlashCommand:
        """
        Build st-flash or STM32_Programmer_CLI flash command.

        Args:
            firmware_path: Path to .bin or .hex file
            port: Serial port (ignored for st-flash, used for serial bootloader)
            address: Flash address (default 0x08000000 for STM32)
            tool: "st-flash" or "stm32programmer"
            connect_under_reset: Use connect-under-reset for crashed chips

        Note:
            st-flash has a known bug (github.com/stlink-org/stlink/issues/1260)
            where it falsely reports "NRST is not connected" even when connected.
            When connect_under_reset is True, we prefer STM32CubeProgrammer
            which handles hardware reset correctly.
        """
        # Prefer STM32CubeProgrammer for connect-under-reset (st-flash has bugs)
        use_cubeprog = tool == "stm32programmer" or connect_under_reset

        if use_cubeprog:
            # STM32CubeProgrammer CLI
            cubeprog = _find_stm32_programmer_cli()
            port_arg = "port=SWD mode=UR reset=HWrst" if connect_under_reset else "port=SWD"
            return FlashCommand(
                tool=cubeprog,
                args=[
                    "-c", port_arg,
                    "-w", firmware_path, address,
                    "-v",  # Verify
                    "-rst",  # Reset after
                ],
                timeout=120.0,
            )
        else:
            # st-flash (stlink-org/stlink) - normal mode only
            return FlashCommand(
                tool="st-flash",
                args=[
                    "--reset",
                    "write",
                    firmware_path,
                    address,
                ],
                timeout=120.0,
            )

    def get_erase_command(
        self,
        port: str,
        tool: str = "st-flash",
        connect_under_reset: bool = False,
        **kwargs,
    ) -> FlashCommand:
        """
        Build st-flash erase command.

        Args:
            port: Serial port (ignored for st-flash)
            tool: "st-flash" or "stm32programmer"
            connect_under_reset: Use connect-under-reset for crashed chips

        Note:
            st-flash has a known bug (github.com/stlink-org/stlink/issues/1260)
            where it falsely reports "NRST is not connected" even when connected.
            When connect_under_reset is True, we prefer STM32CubeProgrammer
            which handles hardware reset correctly.
        """
        # Prefer STM32CubeProgrammer for connect-under-reset (st-flash has bugs)
        use_cubeprog = tool == "stm32programmer" or connect_under_reset

        if use_cubeprog:
            cubeprog = _find_stm32_programmer_cli()
            args = ["-c", "port=SWD"]
            if connect_under_reset:
                args[1] = "port=SWD mode=UR reset=HWrst"  # Under Reset with HW reset
            args.extend(["-e", "all"])
            return FlashCommand(
                tool=cubeprog,
                args=args,
                timeout=60.0,
            )
        else:
            return FlashCommand(
                tool="st-flash",
                args=["erase"],
                timeout=60.0,
            )

    def get_chip_info_command(self, port: str, **kwargs) -> FlashCommand:
        """Build st-info command to get chip info."""
        return FlashCommand(
            tool="st-info",
            args=["--probe"],
            timeout=30.0,
        )

    # =========================================================================
    # OpenOCD Configuration
    # =========================================================================

    def get_openocd_config(
        self,
        adapter: str = "stlink",
        **kwargs,
    ) -> OpenOCDConfig:
        """
        Get OpenOCD configuration for STM32 with ST-Link.

        Args:
            adapter: "stlink" (default), "stlink-v2", "stlink-v3", "jlink"
        """
        # Determine target config based on variant
        variant = (self.variant or "stm32f4").lower()
        target_map = {
            "stm32f1": "target/stm32f1x.cfg",
            "stm32f3": "target/stm32f3x.cfg",
            "stm32f4": "target/stm32f4x.cfg",
            "stm32l4": "target/stm32l4x.cfg",
            "stm32h7": "target/stm32h7x.cfg",
            "stm32g0": "target/stm32g0x.cfg",
            "stm32g4": "target/stm32g4x.cfg",
            "stm32u5": "target/stm32u5x.cfg",
        }

        # Find best match
        target_cfg = "target/stm32f4x.cfg"  # Default
        for prefix, cfg in target_map.items():
            if variant.startswith(prefix):
                target_cfg = cfg
                break

        # Interface config
        interface_map = {
            "stlink": "interface/stlink.cfg",
            "stlink-v2": "interface/stlink.cfg",
            "stlink-v3": "interface/stlink.cfg",
            "jlink": "interface/jlink.cfg",
            "cmsis-dap": "interface/cmsis-dap.cfg",
        }
        interface_cfg = interface_map.get(adapter, "interface/stlink.cfg")

        return OpenOCDConfig(
            interface_cfg=interface_cfg,
            target_cfg=target_cfg,
            transport="hla_swd",  # SWD via ST-Link
            extra_commands=[
                "reset_config srst_only",
            ],
        )

    # =========================================================================
    # Utility Methods
    # =========================================================================

    def parse_reset_reason(self, line: str) -> Optional[str]:
        """
        Parse STM32 reset reason from RCC_CSR register output.

        Common format: "Reset reason: IWDG" or "RCC_CSR: 0x24000000"
        """
        # Direct reason string
        reason_match = re.search(
            r'reset\s*(?:reason|source)[:\s]+(\w+)',
            line,
            re.IGNORECASE
        )
        if reason_match:
            return reason_match.group(1)

        # RCC_CSR register value (would need to decode)
        csr_match = re.search(r'RCC_CSR[:\s]+0x([0-9A-Fa-f]+)', line)
        if csr_match:
            return f"CSR=0x{csr_match.group(1)}"

        return None

    def parse_boot_mode(self, line: str) -> Optional[str]:
        """Parse STM32 boot mode."""
        if "DFU" in line.upper():
            return "DFU"
        if "BOOT0" in line.upper():
            return "System Memory"
        if "main()" in line or "Started" in line:
            return "Flash"
        return None

    def get_fault_registers_pattern(self) -> str:
        """
        Regex pattern to extract fault register dump.

        Matches common HardFault handler output formats.
        """
        return (
            r"(?P<register>R\d+|LR|PC|xPSR|CFSR|HFSR|MMFAR|BFAR)"
            r"\s*[=:]\s*"
            r"(?P<value>0x[0-9A-Fa-f]+|\d+)"
        )
