"""
Zephyr RTOS chip profile for Embedded Agent Bridge.

Supports Zephyr RTOS builds for various targets including nRF52/53, STM32, ESP32, RP2040.
Uses west for flashing and board-specific debug tools (jlink, openocd, pyocd).
"""

from __future__ import annotations

import re
import subprocess
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
        "mcxn947": {"board": "frdm_mcxn947/mcxn947/cpu0", "runner": "linkserver"},
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
        elif "mcx" in variant_lower:
            # NXP MCX series — Cortex-M33, same debug family as nRF53
            return ChipFamily.NRF52

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
            **kwargs: Additional arguments (net_core_firmware, net_build_dir for dual-core targets)

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
        else:
            # Fallback: read ZEPHYR_BASE from CMakeCache.txt in the build dir.
            # This handles out-of-tree builds (e.g., west build --build-dir /tmp/build).
            zephyr_base = self._read_zephyr_base_from_cmake(build_path)
            if zephyr_base:
                env["ZEPHYR_BASE"] = str(zephyr_base)

        return FlashCommand(
            tool="west",
            args=args,
            env=env,
            timeout=120.0,
        )

    def get_flash_commands(
        self,
        firmware_path: str,
        port: str,
        address: str = "0x0",
        board: str | None = None,
        runner: str | None = None,
        build_dir: str | None = None,
        net_core_firmware: str | None = None,
        net_build_dir: str | None = None,
        **kwargs,
    ) -> list[FlashCommand]:
        """
        Build ordered list of flash commands for multi-core targets.

        For nRF5340 dual-core targets, returns [NET core flash, APP core flash].
        For single-core targets, returns [single flash command].

        Args:
            firmware_path: Path to APP core firmware binary or build directory
            port: Serial port (used for ESP32 serial flashing)
            address: Flash address (not used by west, kept for compatibility)
            board: Zephyr board name override
            runner: Flash runner override (jlink, openocd, nrfjprog, pyocd)
            build_dir: APP core build directory path (auto-detected if not specified)
            net_core_firmware: Path to NET core firmware or build directory (nRF5340 only)
            net_build_dir: NET core build directory path (auto-detected from net_core_firmware)
            **kwargs: Additional arguments

        Returns:
            List of FlashCommand objects in the order they should be executed
        """
        board = board or self.board
        runner = runner or self.runner
        variant_lower = (self.variant or "").lower()

        # Check if this is an nRF5340 dual-core target
        is_nrf5340 = "nrf5340" in variant_lower or (board and "nrf5340" in board.lower())

        if is_nrf5340 and net_core_firmware:
            # Dual-core flash: NET core first, then APP core
            commands = []

            # 1. NET core flash command
            net_path = Path(net_core_firmware)
            if net_build_dir:
                net_build_path = Path(net_build_dir)
            elif net_path.is_dir():
                net_build_path = net_path
            elif net_path.parent.name == "zephyr" and (net_path.parent.parent / "CMakeCache.txt").exists():
                net_build_path = net_path.parent.parent
            else:
                # Try to detect from sibling directory pattern: build/app and build/net
                app_path = Path(firmware_path)
                if app_path.is_dir() and app_path.name in ["app", "cpuapp"]:
                    # Check for sibling net/cpunet directory
                    net_build_path = app_path.parent / "net"
                    if not net_build_path.exists():
                        net_build_path = app_path.parent / "cpunet"
                    if not net_build_path.exists():
                        net_build_path = net_path  # Fallback to net firmware path
                else:
                    net_build_path = net_path

            # Detect workspace for NET core
            env: dict[str, str] = {}
            workspace = self._find_workspace(net_build_path)
            if workspace:
                env["ZEPHYR_BASE"] = str(workspace / "zephyr")
            else:
                zephyr_base = self._read_zephyr_base_from_cmake(net_build_path)
                if zephyr_base:
                    env["ZEPHYR_BASE"] = str(zephyr_base)

            # Try west flash first for NET core
            net_args = ["flash", "--no-rebuild", "--build-dir", str(net_build_path)]
            if runner:
                net_args.extend(["--runner", runner])

            commands.append(FlashCommand(
                tool="west",
                args=net_args,
                env=env,
                timeout=120.0,
            ))

            # 2. APP core flash command (use existing get_flash_command)
            app_cmd = self.get_flash_command(
                firmware_path=firmware_path,
                port=port,
                address=address,
                board=board,
                runner=runner,
                build_dir=build_dir,
                **kwargs,
            )
            commands.append(app_cmd)

            return commands
        else:
            # Single-core target: return single command
            return [self.get_flash_command(
                firmware_path=firmware_path,
                port=port,
                address=address,
                board=board,
                runner=runner,
                build_dir=build_dir,
                **kwargs,
            )]

    @staticmethod
    def _read_zephyr_base_from_cmake(build_path: Path) -> Path | None:
        """Read ZEPHYR_BASE from CMakeCache.txt in the build directory.

        Handles out-of-tree builds where the build dir is outside the Zephyr
        workspace (e.g., ``west build --build-dir /tmp/build-nrf5340``).

        Args:
            build_path: Path to the Zephyr build directory containing CMakeCache.txt.

        Returns:
            Path to ZEPHYR_BASE directory, or None if not found, unreadable, or invalid.
        """
        cmake_cache = build_path / "CMakeCache.txt"
        if not cmake_cache.exists():
            return None
        try:
            content = cmake_cache.read_text()
            match = re.search(r'^ZEPHYR_BASE:PATH=(.+)$', content, re.MULTILINE)
            if match:
                zb = Path(match.group(1).strip())
                if zb.is_dir():
                    return zb
        except (OSError, UnicodeDecodeError):
            # Silently fail — flash should proceed even if CMakeCache is unreadable
            pass
        return None

    @staticmethod
    def _find_workspace(start: Path) -> Path | None:
        """Walk up from *start* looking for a directory containing ``.west/``.
        
        WHY 20: Safety limit to prevent infinite loops if start path is malformed
        or filesystem has unusual structure. 20 levels is deeper than any reasonable
        Zephyr workspace nesting (typical depth is 2-4 from build dir to workspace root).
        """
        current = start.resolve()
        for _ in range(20):  # safety limit
            if (current / ".west").is_dir():
                return current
            parent = current.parent
            if parent == current:
                break
            current = parent
        return None

    def get_jlink_flash_command(
        self,
        firmware_path: str,
        device: str,
        reset_after: bool = True,
        **kwargs,
    ) -> FlashCommand:
        """
        Build J-Link Commander (JLinkExe) flash command using batch mode.

        For environments without a full Zephyr workspace (no west installed,
        or flashing a pre-built hex/bin file), this provides a direct J-Link
        flash path using JLinkExe with loadfile.

        Args:
            firmware_path: Path to firmware file (.hex or .bin)
            device: J-Link device string (e.g., "NRF5340_XXAA_APP", "NRF5340_XXAA_NET")
            reset_after: Whether to reset and run after flashing (default: True).
                        Set to False for NET core (cannot independently reset).
            **kwargs: Additional arguments (ignored)

        Returns:
            FlashCommand with JLinkExe batch mode configuration

        Raises:
            ValueError: If firmware file doesn't exist or has unsupported format
        """
        import tempfile
        
        path = Path(firmware_path)
        if not path.exists():
            raise ValueError(f"Firmware file not found: {firmware_path}")
        
        # Detect firmware format
        suffix = path.suffix.lower()
        if suffix not in [".hex", ".bin"]:
            raise ValueError(
                f"Unsupported firmware format: {suffix}. "
                "JLinkExe supports .hex and .bin files."
            )
        
        # Create temporary J-Link script file
        # Using delete=False so we can reference it in the command
        # We'll clean it up in the flash command handler
        fd, script_path = tempfile.mkstemp(prefix="jlink_", suffix=".jlink", text=True)
        
        try:
            # Build J-Link script commands
            script_lines = [
                f"connect",
                f"device {device}",
                "si SWD",
                "speed 4000",
            ]
            
            # Add loadfile command with address for .bin files
            if suffix == ".bin":
                # Binary files need explicit address (0x00000000 for nRF chips)
                script_lines.append(f"loadfile {path.absolute()} 0x00000000")
            else:
                # .hex files have embedded address information
                script_lines.append(f"loadfile {path.absolute()}")
            
            # Add reset and go commands if requested
            if reset_after:
                script_lines.append("r")  # reset
                script_lines.append("g")  # go (resume execution)
            
            script_lines.append("exit")
            
            # Write script to temp file
            with open(script_path, "w") as f:
                for line in script_lines:
                    f.write(line + "\n")
        except Exception:
            # Clean up temp file if script creation fails
            try:
                import os
                os.unlink(script_path)
            except Exception:
                pass
            raise
        finally:
            # Close the file descriptor
            try:
                import os
                os.close(fd)
            except Exception:
                pass
        
        # Return FlashCommand that runs JLinkExe with the script
        return FlashCommand(
            tool="JLinkExe",
            args=["-CommanderScript", script_path],
            env={"JLINK_SCRIPT_PATH": script_path},  # Track for cleanup
            timeout=120.0,
        )

    def get_erase_command(self, port: str, runner: str | None = None, core: str = "app", **kwargs) -> FlashCommand:
        """
        Build erase command for Zephyr target.

        Args:
            port: Serial port (ignored for most targets)
            runner: Flash runner override
            core: Target core for multi-core chips ("app" or "net", default: "app")
            **kwargs: Additional chip-specific options

        Returns:
            FlashCommand for erasing flash

        Raises:
            NotImplementedError: If erase not supported for this variant
            RuntimeError: If attempting unsafe erase operation (e.g., nRF5340 NET core)
        """
        runner = runner or self.runner
        variant_lower = (self.variant or "").lower()
        
        # nRF targets: use nrfjprog --recover
        if "nrf" in variant_lower:
            # nRF5340 NET core: block erase due to APPROTECT re-enabling
            if "5340" in variant_lower and core.lower() == "net":
                raise RuntimeError(
                    "CRITICAL: Cannot erase nRF5340 NET core - this re-enables APPROTECT, "
                    "requiring ~30s recovery and potentially bricking the debug session. "
                    "Use 'west flash' instead, which performs sector-erase via loadfile "
                    "(safe and does not re-enable APPROTECT)."
                )
            
            # APP core or other nRF variants: proceed with recover
            args = ["--recover"]
            
            # Add --coprocessor for nRF5340 NET core (though blocked above, this shows intent)
            if "5340" in variant_lower and core.lower() == "net":
                args.append("--coprocessor")
                args.append("CP_NETWORK")
            
            return FlashCommand(
                tool="nrfjprog",
                args=args,
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

    def check_approtect(self, core: str = "app") -> dict[str, bool | str]:
        """
        Check APPROTECT status on nRF5340 using nrfjprog.

        APPROTECT is a security feature on Nordic chips that prevents debugger access
        to flash and RAM. When enabled, it requires a full chip erase (--recover) to
        disable, which takes ~30 seconds and erases all flash contents.

        The UICR register at 0x00FF8000 controls APPROTECT:
        - 0xFFFFFF00: APPROTECT disabled (factory default)
        - Any other value: APPROTECT enabled

        Args:
            core: Target core ("app" or "net", default: "app")

        Returns:
            dict with keys:
                - enabled: bool indicating if APPROTECT is enabled
                - status: str with human-readable status
                - raw_value: str with hex value from UICR (if available)
                - error: str with error message (if check failed)

        Note:
            Only works for nRF chips with nrfjprog installed.
            Returns error status for non-nRF variants.
        """
        variant_lower = (self.variant or "").lower()
        
        # Only nRF chips have APPROTECT
        if "nrf" not in variant_lower:
            return {
                "enabled": False,
                "status": f"APPROTECT check not applicable for {self.variant}",
                "error": None,
            }
        
        # Build nrfjprog command to read UICR
        args = ["nrfjprog", "--memrd", "0x00FF8000", "--n", "4"]
        
        # Add --coprocessor for NET core on nRF5340
        if "5340" in variant_lower and core.lower() == "net":
            args.extend(["--coprocessor", "CP_NETWORK"])
        
        try:
            result = subprocess.run(
                args,
                capture_output=True,
                text=True,
                timeout=10.0,
            )
            
            if result.returncode != 0:
                # Could be APPROTECT is enabled and blocking access
                stderr_lower = result.stderr.lower()
                if "readback protection" in stderr_lower or "approtect" in stderr_lower:
                    return {
                        "enabled": True,
                        "status": "APPROTECT is enabled (readback protection active)",
                        "error": None,
                    }
                
                return {
                    "enabled": None,
                    "status": "Failed to read APPROTECT status",
                    "error": result.stderr.strip(),
                }
            
            # Parse output: "0x00FF8000: FFFFFFFF"
            # APPROTECT disabled if value is 0xFFFFFF00
            # Any other value means APPROTECT is enabled
            output = result.stdout.strip()
            
            # Try to extract hex value from output
            # Format: "0x00FF8000: FFFFFFFF" - match the value after the colon
            # First try to match address: value format
            hex_match = re.search(r'0x[0-9A-Fa-f]{8}:\s*([0-9A-Fa-f]{8})', output)
            if not hex_match:
                # Fallback: just match any 8-digit hex value (might be just the value)
                hex_match = re.search(r'\b([0-9A-Fa-f]{8})\b', output)
            
            if not hex_match:
                return {
                    "enabled": None,
                    "status": "Could not parse UICR value",
                    "error": f"Unexpected output format: {output}",
                }
            
            raw_value = hex_match.group(1).upper()
            raw_value_int = int(raw_value, 16)
            
            # Check if APPROTECT is disabled (0xFFFFFF00 or all 0xFF)
            # Lower byte can be 0x00 when disabled
            approtect_disabled = (raw_value_int & 0xFFFFFF00) == 0xFFFFFF00
            
            if approtect_disabled:
                return {
                    "enabled": False,
                    "status": "APPROTECT is disabled",
                    "raw_value": f"0x{raw_value}",
                    "error": None,
                }
            else:
                return {
                    "enabled": True,
                    "status": "APPROTECT is enabled",
                    "raw_value": f"0x{raw_value}",
                    "error": None,
                }
                
        except subprocess.TimeoutExpired:
            return {
                "enabled": None,
                "status": "Timeout reading APPROTECT status",
                "error": "nrfjprog command timed out after 10s",
            }
        except FileNotFoundError:
            return {
                "enabled": None,
                "status": "nrfjprog not found",
                "error": "nrfjprog not installed or not in PATH",
            }
        except Exception as e:
            return {
                "enabled": None,
                "status": "Unexpected error checking APPROTECT",
                "error": str(e),
            }

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

    def get_reset_command(self, device: str | None = None, **kwargs) -> FlashCommand:
        """
        Build reset command for Zephyr target.

        Reset strategies by platform:
        - nRF targets: Use nrfjprog --reset (Nordic's official tool)
        - MCXN947: Use west flash with runner for reset
        - Generic J-Link fallback: Generate JLinkExe script with reset sequence

        Args:
            device: J-Link device string (e.g., "NRF5340_XXAA_APP", "MCXN947")
                   Required for J-Link-based reset methods
            **kwargs: Additional chip-specific options

        Returns:
            FlashCommand for resetting the target

        Raises:
            NotImplementedError: If reset not supported for this variant
            ValueError: If device string required but not provided
        """
        import tempfile
        
        variant_lower = (self.variant or "").lower()
        runner = kwargs.get("runner") or self.runner
        
        # nRF targets: Use nrfjprog --reset (most reliable for Nordic chips)
        if "nrf" in variant_lower:
            return FlashCommand(
                tool="nrfjprog",
                args=["--reset"],
                timeout=30.0,
            )
        
        # MCXN947: Use OpenOCD (default runner is linkserver which doesn't support reset command)
        if "mcx" in variant_lower:
            # Always use OpenOCD for MCXN947 reset (linkserver doesn't have standalone reset)
            # OpenOCD reset via TCL command
            return FlashCommand(
                tool="openocd",
                args=[
                    "-f", "interface/cmsis-dap.cfg",
                    "-c", "adapter speed 1000",
                    "-c", "transport select swd",
                    "-c", "swd newdap mcxn947 cpu -dp-id 0",
                    "-c", "dap create mcxn947.dap -chain-position mcxn947.cpu",
                    "-c", "target create mcxn947.cpu cortex_m -dap mcxn947.dap -ap-num 0",
                    "-c", "init",
                    "-c", "reset run",
                    "-c", "shutdown",
                ],
                timeout=30.0,
            )
        
        # Generic J-Link fallback for other Zephyr targets
        # Requires device string to connect to target
        if device:
            # Create temporary J-Link script file
            try:
                fd, script_path = tempfile.mkstemp(prefix="jlink_reset_", suffix=".jlink", text=True)
                with open(fd, "w") as f:
                    f.write(f"connect\n")
                    f.write(f"device {device}\n")
                    f.write(f"si SWD\n")
                    f.write(f"speed 4000\n")
                    f.write(f"r\n")  # Reset
                    f.write(f"g\n")  # Go (resume execution)
                    f.write(f"exit\n")
                
                return FlashCommand(
                    tool="JLinkExe",
                    args=["-CommandFile", script_path],
                    timeout=30.0,
                )
            except OSError as e:
                raise RuntimeError(f"Failed to create J-Link script: {e}")
        
        # No reset method available
        raise NotImplementedError(
            f"Reset not implemented for Zephyr variant '{self.variant}'. "
            f"Provide --device argument for J-Link reset, or use board-specific tools."
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

        # NXP MCX: Use CMSIS-DAP (MCU-Link on-board) with inline SWD config
        # OpenOCD 0.12 has no stock target/mcxn947.cfg
        if "mcx" in variant_lower:
            return OpenOCDConfig(
                interface_cfg="interface/cmsis-dap.cfg",
                target_cfg=None,
                transport="swd",
                extra_commands=[
                    "adapter speed 1000",
                    "swd newdap mcxn947 cpu -dp-id 0",
                    "dap create mcxn947.dap -chain-position mcxn947.cpu",
                    "target create mcxn947.cpu cortex_m -dap mcxn947.dap -ap-num 0",
                    "cortex_m reset_config sysresetreq",
                ],
            )

        # STM32 family — ST-Link uses HLA driver, no transport select needed.
        # connect_assert_srst is required for reliable target examination
        # (STM32 chips in low-power or protection states need reset-connect).
        stm32_extra = [
            "reset_config srst_only srst_nogate connect_assert_srst",
        ]
        if "stm32l4" in variant_lower:
            return OpenOCDConfig(
                interface_cfg="interface/stlink.cfg",
                target_cfg="target/stm32l4x.cfg",
                transport=None,
                extra_commands=stm32_extra,
                halt_command="reset halt",
            )
        if "stm32h7" in variant_lower:
            return OpenOCDConfig(
                interface_cfg="interface/stlink.cfg",
                target_cfg="target/stm32h7x.cfg",
                transport=None,
                extra_commands=stm32_extra,
                halt_command="reset halt",
            )

        # Fallback: ST-Link with STM32F4 (generic Cortex-M)
        return OpenOCDConfig(
            interface_cfg="interface/stlink.cfg",
            target_cfg="target/stm32f4x.cfg",
            transport=None,
            extra_commands=stm32_extra,
            halt_command="reset halt",
        )
