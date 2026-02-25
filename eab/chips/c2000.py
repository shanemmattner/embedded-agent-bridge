"""
TI C2000 DSP chip profile for Embedded Agent Bridge.

Supports TI C2000 family (TMS320F280039C, etc.) using TI's dslite CLI
for flashing, reset, and debug. The C2000 uses the C28x DSP ISA — not ARM —
so standard ARM tooling (OpenOCD, probe-rs, GDB) does not apply.

Requires TI Code Composer Studio (CCS) installed for dslite and CCXML configs.
"""

from __future__ import annotations

import platform
import shutil
import tempfile
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


def _find_ccs_root() -> Optional[Path]:
    """Return the first CCS installation directory that exists on disk.

    Checks ``_CCS_SEARCH_PATHS`` in order and returns the first entry whose
    path is an existing directory.

    Returns:
        Path to CCS root (e.g. ``/Applications/ti/ccs2041/ccs``), or None.
    """
    for p in _CCS_SEARCH_PATHS:
        if p.exists():
            return p
    return None


def _find_ccs_java(ccs_root: Path) -> Optional[Path]:
    """Find the bundled JRE ``java`` binary inside a CCS installation.

    Checks the macOS app-bundle JRE first, then common Linux locations.

    Args:
        ccs_root: CCS installation root (e.g. ``/Applications/ti/ccs2041/ccs``).

    Returns:
        Path to ``java`` binary, or None if not found.
    """
    candidates = [
        # macOS CCS 20.x bundled JRE (x86_64 app bundle)
        ccs_root / "ccs-server.app" / "jre" / "Contents" / "Home" / "bin" / "java",
        # Linux CCS common location
        ccs_root / "jre" / "bin" / "java",
        # Older CCS on Linux (Eclipse-based)
        ccs_root / "eclipse" / "jre" / "bin" / "java",
    ]
    for candidate in candidates:
        if candidate.exists():
            return candidate
    return None


# JavaScript template for DSS-based flashing.
# Placeholders ``{firmware_path}`` and ``{ccxml_path}`` are substituted at
# runtime before writing to a temporary file.
_DSS_JS_TEMPLATE = """\
var outFile = "{firmware_path}";
var ccxmlFile = "{ccxml_path}";
var script = Packages.com.ti.ccstudio.scripting.environment.ScriptingEnvironment.instance();
var ds = script.getServer("DebugServer.1");
ds.setConfig(ccxmlFile);
var session = ds.openSession("*", "*");
session.target.connect();
session.target.reset();
session.memory.loadProgram(outFile);
session.target.runAsynch();
java.lang.Thread.sleep(2000);
session.target.disconnect();
ds.stop();
"""


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

    def get_dss_flash_command(
        self,
        firmware_path: str,
        **kwargs,
    ) -> FlashCommand:
        """Build a DSS (Debug Server Scripting) flash command for C2000.

        Uses TI's Java-based DSS runtime shipped with CCS to flash the target
        over JTAG (XDS110).  This mirrors the ``make flash`` workflow used by
        the FOC firmware project.

        The method:
        1. Locates the CCS installation and its bundled JRE.
        2. Writes a temporary JavaScript flash script with the firmware and
           CCXML paths substituted in.
        3. Builds the Java command with the correct classpath and library path.
        4. On Apple Silicon (arm64 macOS) prefixes the command with
           ``arch -x86_64`` because the CCS JRE is x86_64-only.

        The path of the temporary JS file is stored in
        ``FlashCommand.env["_TEMP_JS"]`` so that callers can clean it up after
        the flash operation completes.

        Args:
            firmware_path: Path to the firmware ``.out`` (ELF/COFF) file.
            **kwargs: Optional ``ccxml`` override.

        Returns:
            FlashCommand configured for DSS Java flash.

        Raises:
            RuntimeError: If CCS, the JRE, or the CCXML file cannot be found.
        """
        ccs_root = _find_ccs_root()
        if ccs_root is None:
            raise RuntimeError(
                "CCS installation not found. Install TI Code Composer Studio "
                "and ensure it is in one of the expected locations."
            )

        java_path = _find_ccs_java(ccs_root)
        if java_path is None:
            raise RuntimeError(
                f"CCS JRE not found under {ccs_root}. "
                "Ensure CCS is fully installed (ccs-server.app/jre must exist)."
            )

        ccxml = kwargs.get("ccxml") or self.ccxml
        if ccxml is None:
            raise RuntimeError(
                "No CCXML configuration file found. "
                "Place a .ccxml file in the current directory or "
                "targetConfigs/, or pass --ccxml explicitly."
            )

        # --- Build Java classpath ---
        debug_server_pkgs = ccs_root / "ccs_base" / "DebugServer" / "packages"
        cp_jars = [
            str(debug_server_pkgs / "ti" / "dss" / "java" / "js.jar"),
            str(debug_server_pkgs / "ti" / "dss" / "java" / "dss.jar"),
            str(ccs_root / "ccs_base" / "dvt" / "scripting" / "dvt_scripting.jar"),
        ]
        # Use OS-appropriate classpath separator
        import os as _os
        classpath = _os.pathsep.join(cp_jars)
        lib_path = str(ccs_root / "ccs_base" / "DebugServer" / "bin")

        # --- Write temporary JS flash script ---
        js_content = _DSS_JS_TEMPLATE.format(
            # Forward slashes are safe for both macOS/Linux and Java on Windows
            firmware_path=firmware_path.replace("\\", "/"),
            ccxml_path=ccxml.replace("\\", "/"),
        )
        tmp_js = tempfile.NamedTemporaryFile(
            suffix=".js", delete=False, mode="w", encoding="utf-8"
        )
        tmp_js.write(js_content)
        tmp_js.flush()
        tmp_js.close()
        tmp_js_path = tmp_js.name

        # --- Build Java argument list ---
        java_args = [
            f"-Djava.library.path={lib_path}",
            "-cp", classpath,
            "org.mozilla.javascript.tools.shell.Main",
            tmp_js_path,
        ]

        # --- Handle Apple Silicon (arm64 macOS) ---
        # The CCS JRE is x86_64-only; run it via Rosetta 2 on ARM Macs.
        is_arm64_mac = (
            platform.machine() == "arm64" and platform.system() == "Darwin"
        )
        if is_arm64_mac:
            tool = "arch"
            args = ["-x86_64", str(java_path)] + java_args
        else:
            tool = str(java_path)
            args = java_args

        return FlashCommand(
            tool=tool,
            args=args,
            env={"_TEMP_JS": tmp_js_path},
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
