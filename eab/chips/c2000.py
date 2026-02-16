"""
TI C2000 DSP chip profile for Embedded Agent Bridge.

Supports TI C2000 family (TMS320F280039C, etc.) using TI's dslite CLI
for flashing, reset, and debug. The C2000 uses the C28x DSP ISA — not ARM —
so standard ARM tooling (OpenOCD, probe-rs, GDB) does not apply.

Requires TI Code Composer Studio (CCS) installed for dslite and CCXML configs.
"""

from __future__ import annotations

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


# Common CCS installation paths on macOS (Rosetta) and Linux
_CCS_SEARCH_PATHS = [
    # macOS CCS 20.4.x (versioned install dir, runs under Rosetta on Apple Silicon)
    Path("/Applications/ti/ccs2041/ccs"),
    Path("/Applications/ti/ccs2040/ccs"),
    Path("/Applications/ti/ccs/ccs"),
    Path.home() / "ti/ccs2041/ccs",
    Path.home() / "ti/ccs/ccs",
    # Linux
    Path("/opt/ti/ccs2041/ccs"),
    Path("/opt/ti/ccs/ccs"),
    Path.home() / "ti/ccs1280/ccs",
    Path.home() / "ti/ccs1271/ccs",
]


def _find_dslite() -> Optional[str]:
    """Find the DSLite executable from CCS installation or PATH.

    The binary is named 'DSLite' (case-sensitive on macOS/Linux) and lives at
    <ccs>/ccs_base/DebugServer/bin/DSLite. It must be run from the ccs_base
    directory so it can find its support files.

    Returns:
        Path to DSLite binary, or None if not found.
    """
    # Check PATH first (both casings)
    for name in ("DSLite", "dslite"):
        found = shutil.which(name)
        if found:
            return found

    # Search CCS installations — actual location is ccs_base/DebugServer/bin/DSLite
    for ccs_path in _CCS_SEARCH_PATHS:
        candidate = ccs_path / "ccs_base" / "DebugServer" / "bin" / "DSLite"
        if candidate.exists():
            return str(candidate)

    return None


def _find_ccxml(variant: str = "TMS320F280039C") -> Optional[str]:
    """Find the CCXML configuration file for the target.

    CCXML files configure the XDS110 probe + target connection.
    They ship with CCS or can be user-generated.

    Args:
        variant: Target device name (default: TMS320F280039C).

    Returns:
        Path to CCXML file, or None if not found.
    """
    # Check for user-provided CCXML in common locations
    user_ccxml_dirs = [
        Path.cwd(),
        Path.cwd() / "targetConfigs",
        Path.home() / ".eab" / "ccxml",
    ]
    for d in user_ccxml_dirs:
        for ccxml in d.glob(f"*{variant}*.ccxml"):
            return str(ccxml)

    # Search CCS target configurations
    for ccs_path in _CCS_SEARCH_PATHS:
        target_dir = ccs_path / "ccs_base" / "common" / "targetdb" / "connections"
        if target_dir.exists():
            for ccxml in target_dir.rglob(f"*{variant}*.ccxml"):
                return str(ccxml)

    return None


class C2000Profile(ChipProfile):
    """
    Profile for TI C2000 DSP family.

    Uses TI's dslite CLI (from CCS) for flash and reset operations.
    The C2000 C28x ISA is not ARM — no OpenOCD/GDB/probe-rs support.
    Debug probe is the XDS110 (on-board on LaunchPad dev kits).
    """

    def __init__(
        self,
        variant: str | None = None,
        ccxml: str | None = None,
        dslite_path: str | None = None,
    ):
        """
        Initialize C2000 profile.

        Args:
            variant: Chip variant (e.g., "f280039c", "f28379d").
            ccxml: Path to CCXML configuration file.
            dslite_path: Explicit path to dslite binary.
        """
        super().__init__(variant)
        self._ccxml = ccxml
        self._dslite_path = dslite_path

    @property
    def dslite(self) -> str:
        """Resolve dslite binary path."""
        if self._dslite_path:
            return self._dslite_path
        found = _find_dslite()
        if found:
            return found
        return "dslite"  # Fall back to PATH

    @property
    def ccxml(self) -> Optional[str]:
        """Resolve CCXML configuration file path."""
        if self._ccxml:
            return self._ccxml
        variant_name = self._variant_to_device_name()
        return _find_ccxml(variant_name)

    def _variant_to_device_name(self) -> str:
        """Map variant string to TI device name."""
        v = (self.variant or "").lower()
        if "280039" in v:
            return "TMS320F280039C"
        if "28379" in v:
            return "TMS320F28379D"
        if "28388" in v:
            return "TMS320F28388D"
        # Default for the LaunchXL-F280039C
        return "TMS320F280039C"

    @property
    def family(self) -> ChipFamily:
        return ChipFamily.C2000

    @property
    def name(self) -> str:
        device = self._variant_to_device_name()
        return f"TI C2000 ({device})"

    # =========================================================================
    # Pattern Definitions
    # =========================================================================

    @property
    def boot_patterns(self) -> list[str]:
        """C2000-specific boot indicators from serial output."""
        return [
            "C2000 Boot",
            "FLASH_BOOT",
            "Boot Mode",
            "SCI Boot",
            "Initialized",
        ]

    @property
    def crash_patterns(self) -> list[str]:
        """C28x fault/crash patterns."""
        return [
            "NMI",
            "Illegal instruction",
            "ITRAP",
            "PIE fault",
            "ESTOP",
            "Watchdog reset",
            "NMIWD",
        ]

    @property
    def bootloader_patterns(self) -> list[str]:
        return [
            "SCI Boot",
            "Boot ROM",
            "Wait Boot",
        ]

    @property
    def watchdog_patterns(self) -> list[str]:
        return [
            "Watchdog reset",
            "WDINT",
            "NMIWD",
        ]

    @property
    def running_patterns(self) -> list[str]:
        return [
            "Application started",
            "Motor control ready",
            "Ready",
        ]

    @property
    def error_patterns(self) -> dict[str, str]:
        return {
            "ERROR": r"\berror\b",
            "FAULT": r"\bfault\b",
            "NMI": r"\bNMI\b",
            "OVERCURRENT": r"overcurrent|over.?current",
            "OVERVOLTAGE": r"overvoltage|over.?voltage",
        }

    # =========================================================================
    # Reset Sequences
    # =========================================================================

    @property
    def reset_sequences(self) -> dict[str, list[ResetSequence]]:
        """C2000 reset via DTR/RTS (XDS110 handles reset via JTAG, not serial lines)."""
        return {
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
        return "dslite"

    def get_flash_command(
        self,
        firmware_path: str,
        port: str,
        address: str = "0x0",
        **kwargs,
    ) -> FlashCommand:
        """
        Build DSLite flash command for C2000.

        DSLite flashes via XDS110 cJTAG — the serial port is not used for flashing.
        The firmware file is typically a .out (COFF/ELF) from CCS.

        DSLite v20.4 syntax: DSLite flash --config=<ccxml> -f <firmware.out>

        Args:
            firmware_path: Path to firmware (.out or .hex).
            port: Serial port (unused for C2000 flashing, kept for interface compat).
            address: Flash address (unused, embedded in .out file).
            **kwargs: ccxml override via kwargs["ccxml"].
        """
        ccxml = kwargs.get("ccxml") or self.ccxml

        args = ["flash"]
        if ccxml:
            args.append(f"--config={ccxml}")

        args.extend(["-f", firmware_path])

        return FlashCommand(
            tool=self.dslite,
            args=args,
            timeout=120.0,
        )

    def get_erase_command(self, port: str, **kwargs) -> FlashCommand:
        """Build erase command for C2000 via DSLite."""
        ccxml = kwargs.get("ccxml") or self.ccxml

        args = ["flash"]
        if ccxml:
            args.append(f"--config={ccxml}")
        args.extend(["-b", "Erase"])

        return FlashCommand(
            tool=self.dslite,
            args=args,
            timeout=60.0,
        )

    def get_chip_info_command(self, port: str, **kwargs) -> FlashCommand:
        """Identify connected XDS110 debug probe."""
        ccxml = kwargs.get("ccxml") or self.ccxml
        args = ["identifyProbe"]
        if ccxml:
            args.append(f"--config={ccxml}")
        return FlashCommand(
            tool=self.dslite,
            args=args,
            timeout=30.0,
        )

    def get_reset_command(self, **kwargs) -> FlashCommand:
        """Reset C2000 target via DSLite.

        DSLite v20.4 doesn't have a standalone reset command.
        Use 'load --config=<ccxml> --reset' to reset without loading.
        """
        ccxml = kwargs.get("ccxml") or self.ccxml

        args = ["load"]
        if ccxml:
            args.append(f"--config={ccxml}")
        args.append("--reset")

        return FlashCommand(
            tool=self.dslite,
            args=args,
            timeout=30.0,
        )

    # =========================================================================
    # OpenOCD Configuration — NOT SUPPORTED for C2000
    # =========================================================================

    def get_openocd_config(self, **kwargs) -> OpenOCDConfig:
        """C2000 uses C28x ISA — OpenOCD does not support it.

        Raises:
            NotImplementedError: Always, since OpenOCD cannot debug C28x.
        """
        raise NotImplementedError(
            "OpenOCD does not support TI C2000 (C28x DSP ISA). "
            "Use dslite or TI CCS for debug operations."
        )
