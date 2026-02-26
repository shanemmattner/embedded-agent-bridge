"""Shared helpers for the DWT CLI commands.

Provides:
  - _resolve_symbol(): ELF symbol lookup (pyelftools → nm fallback)
  - _open_jlink():     Open and connect a pylink.JLink instance
"""

from __future__ import annotations

import logging
import subprocess
from typing import Optional

logger = logging.getLogger(__name__)

# ---------------------------------------------------------------------------
# pyelftools — optional
# ---------------------------------------------------------------------------

try:
    from elftools.elf.elffile import ELFFile
    from elftools.elf.sections import SymbolTableSection
    _PYELFTOOLS_AVAILABLE = True
except ImportError:
    _PYELFTOOLS_AVAILABLE = False

# ---------------------------------------------------------------------------
# pylink — optional (same pattern as dwt_profiler.py)
# ---------------------------------------------------------------------------

try:
    import pylink as _pylink
except ImportError:
    _pylink = None  # type: ignore

from eab.dwt_watchpoint import SymbolNotFoundError


# ---------------------------------------------------------------------------
# Symbol resolution
# ---------------------------------------------------------------------------

# Symbol types that indicate a data variable (BSS, data, rodata, small-data …)
_DATA_SYMBOL_TYPES = frozenset("BbDdRrGgSs")
_NM_DATA_TYPES = ("B", "b", "D", "d", "R", "r", "G", "g", "S", "s")


def _resolve_symbol(
    symbol_name: str,
    elf_path: str,
) -> tuple[int, int]:
    """Return (address, size_bytes) for a data symbol in the ELF.

    Lookup order:
      1. pyelftools (ELFFile + iter_symbols) — works offline, no toolchain.
      2. arm-none-eabi-nm / arm-zephyr-eabi-nm fallback.

    Args:
        symbol_name: Exact symbol name (e.g., "conn_interval").
        elf_path:    Path to ELF binary.

    Returns:
        (address, size_bytes) — address is the load VA; size_bytes from the
        symbol table (defaults to 4 if unknown / zero).

    Raises:
        SymbolNotFoundError: If symbol is absent from ELF.
        FileNotFoundError:   If elf_path does not exist.
    """
    if _PYELFTOOLS_AVAILABLE:
        try:
            return _resolve_via_pyelftools(symbol_name, elf_path)
        except SymbolNotFoundError:
            pass  # fall through to nm

    # nm fallback
    return _resolve_via_nm(symbol_name, elf_path)


def _resolve_via_pyelftools(symbol_name: str, elf_path: str) -> tuple[int, int]:
    """Resolve symbol using pyelftools."""
    with open(elf_path, "rb") as f:
        elf = ELFFile(f)
        for section in elf.iter_sections():
            if not isinstance(section, SymbolTableSection):
                continue
            for sym in section.iter_symbols():
                if sym.name == symbol_name:
                    addr = sym.entry.st_value
                    if addr != 0:
                        size = sym.entry.st_size or 4
                        return (addr, size)
    raise SymbolNotFoundError(
        f"Symbol '{symbol_name}' not found in {elf_path}. "
        "Try: (1) compile with -O0 or -Og, (2) use 'volatile' qualifier, "
        "(3) pass --addr <hex> directly."
    )


def _resolve_via_nm(symbol_name: str, elf_path: str) -> tuple[int, int]:
    """Resolve symbol via arm-none-eabi-nm / arm-zephyr-eabi-nm.

    Returns (address, size_bytes). Size is parsed from -S output if available,
    otherwise defaults to 4.
    """
    from eab.toolchain import which_or_sdk as _which_or_sdk

    nm_tool = (
        _which_or_sdk("arm-none-eabi-nm")
        or _which_or_sdk("arm-zephyr-eabi-nm")
        or _which_or_sdk("nm")
    )
    if nm_tool is None:
        raise SymbolNotFoundError(
            f"Cannot resolve symbol '{symbol_name}': "
            "neither pyelftools nor arm-none-eabi-nm is available."
        )

    try:
        result = subprocess.run(
            [nm_tool, "-S", "-C", elf_path],
            capture_output=True,
            text=True,
            timeout=15.0,
            check=True,
        )
    except (subprocess.CalledProcessError, FileNotFoundError) as exc:
        raise SymbolNotFoundError(
            f"nm failed for '{symbol_name}': {exc}"
        ) from exc

    # nm -S output: "00001234 00000004 D symbol_name"
    # or (no size):  "00001234 D symbol_name"
    for line in result.stdout.splitlines():
        parts = line.strip().split()
        if len(parts) < 3:
            continue
        # Last token is the symbol name
        if parts[-1] != symbol_name:
            continue
        sym_type = parts[-2]
        if sym_type not in _NM_DATA_TYPES:
            continue
        try:
            addr = int(parts[0], 16)
        except ValueError:
            continue
        # Try to parse size (second field in -S output)
        size = 4
        if len(parts) == 4:
            try:
                size = int(parts[1], 16) or 4
            except ValueError:
                size = 4
        return (addr, size)

    raise SymbolNotFoundError(
        f"Symbol '{symbol_name}' not found in {elf_path} (nm search). "
        "Try: (1) compile with -O0 or -Og, (2) use 'volatile' qualifier, "
        "(3) pass --addr <hex> directly."
    )


# ---------------------------------------------------------------------------
# J-Link helper
# ---------------------------------------------------------------------------

def _open_jlink(
    device: str,
    probe_selector: Optional[str] = None,
    interface: str = "SWD",
    speed: int = 4000,
) -> "pylink.JLink":  # type: ignore[name-defined]
    """Open and connect a pylink.JLink instance.

    Args:
        device:         J-Link device string (e.g., "NRF5340_XXAA_APP").
        probe_selector: Optional serial number for multi-probe setups.
        interface:      Debug interface ("SWD" or "JTAG").
        speed:          Interface speed in kHz (default: 4000).

    Returns:
        Connected pylink.JLink instance.

    Raises:
        ImportError: If pylink-square is not installed.
        RuntimeError: If J-Link connection fails.
    """
    if _pylink is None:
        raise ImportError(
            "pylink-square is required for J-Link access. "
            "Install with: pip install pylink-square"
        )

    jlink = _pylink.JLink()

    open_kwargs: dict = {}
    if probe_selector:
        open_kwargs["serial_no"] = int(probe_selector)

    jlink.open(**open_kwargs)
    jlink.set_tif(_pylink.enums.JLinkInterfaces.SWD if interface == "SWD"
                  else _pylink.enums.JLinkInterfaces.JTAG)
    jlink.connect(device, speed=speed)
    logger.debug("Connected to %s via J-Link", device)
    return jlink
