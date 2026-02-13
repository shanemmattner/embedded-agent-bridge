#!/usr/bin/env python3
"""
Device Control Module for Embedded Agent Bridge.

Provides:
- Device reset via DTR/RTS
- Bootloader entry
- Flash via esptool
- ANSI escape code handling
"""

import re
import subprocess
import time
from typing import Optional, Callable
from dataclasses import dataclass


# ANSI escape code pattern
ANSI_ESCAPE = re.compile(r'\x1B(?:[@-Z\\-_]|\[[0-?]*[ -/]*[@-~])')


def strip_ansi(text: str) -> str:
    """Remove ANSI escape codes from text."""
    return ANSI_ESCAPE.sub('', text)


@dataclass
class ResetSequence:
    """A reset sequence step."""
    dtr: Optional[bool]
    rts: Optional[bool]
    delay: float = 0.0


# Standard reset sequences
RESET_SEQUENCES = {
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


class DeviceController:
    """
    Controls device reset and flash operations.

    Special commands (via cmd.txt):
    - !RESET - Hard reset the device
    - !RESET:soft - Soft reset
    - !BOOTLOADER - Enter bootloader mode
    - !FLASH:/path/to/firmware.bin - Flash firmware
    - !CHIP_INFO - Get chip info via esptool
    """

    def __init__(
        self,
        serial_port,
        port_name: str,
        baud: int = 115200,
        logger = None,
        on_flash_start: Optional[Callable] = None,
        on_flash_end: Optional[Callable] = None,
    ):
        self._serial = serial_port
        self._port_name = port_name
        self._baud = baud
        self._logger = logger
        self._on_flash_start = on_flash_start
        self._on_flash_end = on_flash_end

    def _log(self, msg: str) -> None:
        if self._logger:
            self._logger.info(msg)
        else:
            print(f"[DeviceControl] {msg}")

    def _log_error(self, msg: str) -> None:
        if self._logger:
            self._logger.error(msg)
        else:
            print(f"[DeviceControl] ERROR: {msg}")

    def is_special_command(self, cmd: str) -> bool:
        """Check if command is a special device control command."""
        return cmd.startswith("!")

    def handle_command(self, cmd: str) -> Optional[str]:
        """
        Handle a special command.

        Returns result message or None if not a special command.
        """
        if not cmd.startswith("!"):
            return None

        parts = cmd[1:].split(":", 1)
        action = parts[0].upper()
        arg = parts[1] if len(parts) > 1 else None

        if action == "RESET":
            return self.reset(arg or "hard_reset")
        elif action == "BOOTLOADER":
            return self.enter_bootloader()
        elif action == "FLASH":
            if not arg:
                return "ERROR: !FLASH requires firmware path"
            return self.flash(arg)
        elif action == "CHIP_INFO":
            return self.get_chip_info()
        elif action == "ERASE":
            return self.erase_flash()
        else:
            return f"ERROR: Unknown command: {action}"

    def reset(self, sequence_name: str = "hard_reset") -> str:
        """Reset the device using the specified sequence."""
        if sequence_name not in RESET_SEQUENCES:
            return f"ERROR: Unknown reset sequence: {sequence_name}"

        sequence = RESET_SEQUENCES[sequence_name]
        self._log(f"Resetting device ({sequence_name})...")

        try:
            for step in sequence:
                if step.dtr is not None:
                    self._serial._serial.setDTR(step.dtr)
                if step.rts is not None:
                    self._serial._serial.setRTS(step.rts)
                if step.delay > 0:
                    time.sleep(step.delay)

            self._log("Device reset complete")
            return "OK: Device reset"
        except Exception as e:
            self._log_error(f"Reset failed: {e}")
            return f"ERROR: Reset failed: {e}"

    def enter_bootloader(self) -> str:
        """Enter bootloader mode."""
        return self.reset("bootloader")

    def flash(self, firmware_path: str, address: str = "0x0") -> str:
        """
        Flash firmware using esptool.

        Args:
            firmware_path: Path to .bin file or .elf file
            address: Flash address (default 0x0 for app, or specific like 0x10000)
        """
        self._log(f"Flashing {firmware_path} to {address}...")

        # Notify that we're starting flash (daemon should release port)
        if self._on_flash_start:
            self._on_flash_start()

        try:
            # Close serial port for esptool
            was_open = self._serial.is_open()
            if was_open:
                self._serial.close()

            # Build esptool command
            cmd = [
                "esptool",
                "--port", self._port_name,
                "--baud", "460800",
                "write-flash",
                address,
                firmware_path,
            ]

            self._log(f"Running: {' '.join(cmd)}")

            result = subprocess.run(
                cmd,
                capture_output=True,
                text=True,
                timeout=120,
            )

            # Reopen serial port
            if was_open:
                time.sleep(0.5)
                self._serial.open(self._port_name, self._baud)

            if result.returncode == 0:
                self._log("Flash complete!")
                if self._on_flash_end:
                    self._on_flash_end(True)
                return "OK: Flash complete"
            else:
                self._log_error(f"Flash failed: {result.stderr}")
                if self._on_flash_end:
                    self._on_flash_end(False)
                return f"ERROR: Flash failed: {result.stderr[:200]}"

        except subprocess.TimeoutExpired:
            self._log_error("Flash timeout")
            if self._on_flash_end:
                self._on_flash_end(False)
            return "ERROR: Flash timeout"
        except FileNotFoundError:
            self._log_error("esptool not found")
            if self._on_flash_end:
                self._on_flash_end(False)
            return "ERROR: esptool not found. Install with: pip install esptool"
        except Exception as e:
            self._log_error(f"Flash error: {e}")
            if self._on_flash_end:
                self._on_flash_end(False)
            return f"ERROR: {e}"

    def get_chip_info(self) -> str:
        """Get chip information via esptool."""
        self._log("Getting chip info...")

        try:
            was_open = self._serial.is_open()
            if was_open:
                self._serial.close()

            cmd = [
                "esptool",
                "--port", self._port_name,
                "chip-id",
            ]

            result = subprocess.run(
                cmd,
                capture_output=True,
                text=True,
                timeout=30,
            )

            if was_open:
                time.sleep(0.5)
                self._serial.open(self._port_name, self._baud)

            if result.returncode == 0:
                # Parse chip info from output
                output = result.stdout
                return f"OK: {output}"
            else:
                return f"ERROR: {result.stderr[:200]}"

        except Exception as e:
            return f"ERROR: {e}"

    def erase_flash(self) -> str:
        """Erase entire flash."""
        self._log("Erasing flash...")

        try:
            was_open = self._serial.is_open()
            if was_open:
                self._serial.close()

            cmd = [
                "esptool",
                "--port", self._port_name,
                "erase-flash",
            ]

            result = subprocess.run(
                cmd,
                capture_output=True,
                text=True,
                timeout=60,
            )

            if was_open:
                time.sleep(0.5)
                self._serial.open(self._port_name, self._baud)

            if result.returncode == 0:
                return "OK: Flash erased"
            else:
                return f"ERROR: {result.stderr[:200]}"

        except Exception as e:
            return f"ERROR: {e}"
