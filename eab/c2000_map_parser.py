"""TI C2000 MAP file parser for variable address lookup.

CCS generates MAP files with a different format than GNU ld.
TI linker MAP files have sections like:

    GLOBAL SYMBOLS: SORTED ALPHABETICALLY BY Name

    address    name
    --------   ----
    00000000   $O$C
    0000c002   _motorVars_M1

This parser extracts symbol names and addresses from TI linker MAP files,
enabling variable reading via XDS110 memory read operations.
"""

from __future__ import annotations

import re
from dataclasses import dataclass
from pathlib import Path


@dataclass(frozen=True)
class C2000Symbol:
    """A symbol from a TI C2000 MAP file."""

    name: str
    address: int
    size: int = 0  # TI MAP files don't always include size


# Pattern for TI linker MAP symbol lines:
# "0000c002   _motorVars_M1" or "00000000   $O$C"
_TI_MAP_SYMBOL = re.compile(
    r"^\s*([0-9a-fA-F]{8})\s+(\S+)\s*$"
)

# Pattern for TI linker MAP memory allocation entries:
# "  _motorVars_M1      0000c002  00000120  RAMLS4"
_TI_MAP_ALLOC = re.compile(
    r"^\s+(\S+)\s+([0-9a-fA-F]{8})\s+([0-9a-fA-F]{8})\s+(\S+)"
)


def parse_ti_map_file(map_path: str) -> list[C2000Symbol]:
    """Parse a TI C2000 linker MAP file for symbols.

    Extracts symbol names, addresses, and sizes from the MAP file.
    Handles both the GLOBAL SYMBOLS table and MEMORY ALLOCATION sections.

    Args:
        map_path: Path to .map file from CCS build.

    Returns:
        List of C2000Symbol sorted by address.

    Raises:
        FileNotFoundError: If map file doesn't exist.
    """
    path = Path(map_path)
    if not path.exists():
        raise FileNotFoundError(f"MAP file not found: {map_path}")

    symbols: dict[str, C2000Symbol] = {}

    with open(map_path, "r", errors="replace") as f:
        lines = f.readlines()

    in_global_symbols = False
    in_memory_alloc = False

    for line in lines:
        stripped = line.strip()

        # Detect section headers
        if "GLOBAL SYMBOLS" in stripped and "SORTED" in stripped:
            in_global_symbols = True
            in_memory_alloc = False
            continue
        elif "MEMORY ALLOCATION" in stripped or "MODULE SUMMARY" in stripped:
            in_global_symbols = False
            in_memory_alloc = "MEMORY ALLOCATION" in stripped
            continue
        elif stripped.startswith("SECTION ALLOCATION"):
            in_global_symbols = False
            in_memory_alloc = False
            continue

        # Parse global symbols table
        if in_global_symbols:
            m = _TI_MAP_SYMBOL.match(line)
            if m:
                addr = int(m.group(1), 16)
                name = m.group(2)
                # Skip compiler internal symbols
                if name.startswith("$") or name.startswith("."):
                    continue
                # Strip leading underscore (TI C compiler adds _ prefix)
                display_name = name.lstrip("_") if name.startswith("_") else name
                symbols[display_name] = C2000Symbol(
                    name=display_name,
                    address=addr,
                )

        # Parse memory allocation for sizes
        if in_memory_alloc:
            m = _TI_MAP_ALLOC.match(line)
            if m:
                name = m.group(1)
                addr = int(m.group(2), 16)
                size = int(m.group(3), 16)
                display_name = name.lstrip("_") if name.startswith("_") else name
                if display_name in symbols:
                    # Update with size info
                    existing = symbols[display_name]
                    symbols[display_name] = C2000Symbol(
                        name=existing.name,
                        address=existing.address,
                        size=size,
                    )
                elif size > 0:
                    symbols[display_name] = C2000Symbol(
                        name=display_name,
                        address=addr,
                        size=size,
                    )

    result = list(symbols.values())
    result.sort(key=lambda s: s.address)
    return result


def find_symbol(symbols: list[C2000Symbol], name: str) -> C2000Symbol | None:
    """Find a symbol by name, supporting dotted paths for struct members.

    For dotted names like "motorVars_M1.motorState", finds "motorVars_M1"
    and returns it (the offset into the struct must be resolved separately
    from the type information or known offsets).

    Args:
        symbols: List of parsed symbols.
        name: Symbol name or dotted path.

    Returns:
        Matching C2000Symbol or None.
    """
    # Exact match
    for s in symbols:
        if s.name == name:
            return s

    # Try base name (before first dot)
    base_name = name.split(".")[0]
    for s in symbols:
        if s.name == base_name:
            return s

    return None
