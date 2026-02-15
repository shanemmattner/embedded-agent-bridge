"""ELF/MAP symbol discovery and GDB variable introspection.

Parses ELF symbol tables and GNU ld MAP files to discover global/static
variables with their addresses, sizes, types, and memory sections. Uses
existing toolchain binaries (nm, readelf) — no new Python dependencies.

Also generates GDB Python scripts for batch variable reading and
variable listing from DWARF debug info on a live target.
"""

from __future__ import annotations

import logging
import re
import subprocess
from dataclasses import dataclass
from typing import Optional

from eab.toolchain import which_or_sdk as _which_or_sdk

logger = logging.getLogger(__name__)

# Symbol type codes that represent data (not functions/text)
_DATA_SYM_TYPES = frozenset("DdBbRrGg")


@dataclass(frozen=True)
class ElfSymbol:
    """A symbol parsed from ELF via nm."""

    name: str
    address: int
    size: int  # 0 if unknown
    sym_type: str  # 'D'=data, 'B'=bss, 'R'=rodata, etc.
    section: str  # .data, .bss, .rodata (inferred from sym_type)


@dataclass(frozen=True)
class MapSymbol:
    """A symbol parsed from GNU ld MAP file."""

    name: str
    address: int
    size: int
    region: str  # DRAM, IRAM, FLASH, etc.
    section: str  # .data, .bss, .rodata


def _infer_section(sym_type: str) -> str:
    """Infer ELF section name from nm symbol type character."""
    mapping = {
        "D": ".data",
        "d": ".data",
        "B": ".bss",
        "b": ".bss",
        "R": ".rodata",
        "r": ".rodata",
        "G": ".sdata",
        "g": ".sdata",
    }
    return mapping.get(sym_type, ".unknown")


def _resolve_nm() -> str:
    """Find nm binary on PATH or in SDK directories.

    Returns:
        Path to nm binary.

    Raises:
        FileNotFoundError: If no nm binary found.
    """
    # ARM Cortex-M, ESP32 RISC-V, ESP32 Xtensa, then system fallback
    for name in (
        "arm-none-eabi-nm",
        "arm-zephyr-eabi-nm",
        "riscv32-esp-elf-nm",
        "xtensa-esp32s3-elf-nm",
        "xtensa-esp32-elf-nm",
        "nm",  # GNU binutils system nm reads any ELF
    ):
        p = _which_or_sdk(name)
        if p:
            return p
    raise FileNotFoundError(
        "No nm binary found (tried arm-none-eabi-nm, riscv32-esp-elf-nm, "
        "xtensa-esp32s3-elf-nm, system nm). Install a toolchain or GNU binutils."
    )


def parse_symbols(elf_path: str) -> list[ElfSymbol]:
    """Parse global/static data symbols from an ELF file.

    Uses ``arm-none-eabi-nm -S -C --defined-only`` to extract symbols
    with sizes, then filters to data symbol types (D, d, B, b, R, r, G, g).

    Args:
        elf_path: Path to ELF binary with debug symbols.

    Returns:
        List of ElfSymbol sorted by address.

    Raises:
        FileNotFoundError: If nm binary is not found.
        subprocess.CalledProcessError: If nm execution fails.
    """
    nm = _resolve_nm()

    result = subprocess.run(
        [nm, "-S", "-C", "--defined-only", elf_path],
        capture_output=True,
        text=True,
        timeout=30.0,
        check=True,
    )

    symbols: list[ElfSymbol] = []
    for line in result.stdout.splitlines():
        parts = line.strip().split()
        if not parts:
            continue

        # nm -S output formats:
        #   "20000100 00000004 D g_counter"       (with size)
        #   "20000100 D g_counter"                (without size)
        if len(parts) >= 4:
            # Has size: addr size type name
            try:
                addr = int(parts[0], 16)
                size = int(parts[1], 16)
                sym_type = parts[2]
                name = " ".join(parts[3:])  # Handle demangled names with spaces
            except ValueError:
                continue
        elif len(parts) == 3:
            # No size: addr type name
            try:
                addr = int(parts[0], 16)
                sym_type = parts[1]
                name = parts[2]
                size = 0
            except ValueError:
                continue
        else:
            continue

        if sym_type not in _DATA_SYM_TYPES:
            continue

        symbols.append(
            ElfSymbol(
                name=name,
                address=addr,
                size=size,
                sym_type=sym_type,
                section=_infer_section(sym_type),
            )
        )

    symbols.sort(key=lambda s: s.address)
    return symbols


# =============================================================================
# MAP File Parsing
# =============================================================================

# Matches a symbol definition line like:
#  .bss.g_sensor_data
# or:
#  .data.g_counter
_MAP_SYMBOL_LINE = re.compile(r"^\s*(\.\w+(?:\.\w+)*)\s*$")

# Matches the address/size line that follows:
#                 0x0000000020001000       0x20 build/sensor.o
_MAP_ADDR_LINE = re.compile(
    r"^\s+(0x[0-9a-fA-F]+)\s+(0x[0-9a-fA-F]+)\s+(\S+)"
)

# Matches single-line entries (common in some map files):
#  .bss.g_sensor_data
#                 0x20001000       0x20 build/sensor.o
# Or inline:
#  *(.bss.g_sensor_data)
#  .bss.g_sensor_data  0x20001000  0x20  build/sensor.o

# Section-to-region mapping for common RTOS configurations
_SECTION_REGION_MAP = {
    ".dram0.bss": "DRAM",
    ".dram0.data": "DRAM",
    ".bss": "RAM",
    ".data": "RAM",
    ".rodata": "FLASH",
    ".iram0.text": "IRAM",
    ".flash.text": "FLASH",
    ".noinit": "RAM",
}


def _infer_region(section: str) -> str:
    """Infer memory region from section name."""
    for prefix, region in _SECTION_REGION_MAP.items():
        if section.startswith(prefix):
            return region
    if "bss" in section or "data" in section or "noinit" in section:
        return "RAM"
    if "rodata" in section or "text" in section:
        return "FLASH"
    return "UNKNOWN"


def _extract_symbol_name(section_line: str) -> Optional[str]:
    """Extract variable name from a MAP file section line.

    Handles formats like:
        .bss.g_sensor_data      ->  g_sensor_data
        .data.my_var            ->  my_var
        .rodata.VERSION         ->  VERSION
        .dram0.bss.g_state      ->  g_state
    """
    section_line = section_line.strip()
    parts = section_line.split(".")
    if len(parts) < 3:
        return None

    # Known section base names that precede the variable name
    _SECTION_BASES = {"bss", "data", "rodata", "sdata", "sbss", "noinit", "text"}

    # Find the last known section base name, everything after is the variable name
    # .dram0.bss.g_state -> skip "dram0", skip "bss", take "g_state"
    # .bss.g_sensor_data -> skip "bss", take "g_sensor_data"
    for i in range(1, len(parts)):
        if parts[i] in _SECTION_BASES and i + 1 < len(parts):
            return ".".join(parts[i + 1:])

    # Fallback: take everything after the first two parts
    # .bss.g_sensor_data -> g_sensor_data
    return ".".join(parts[2:])


def parse_map_file(map_path: str) -> list[MapSymbol]:
    """Parse GNU ld linker MAP file for symbol information.

    Handles ESP-IDF and Zephyr map file formats. Extracts symbol names,
    addresses, sizes, and memory regions.

    Args:
        map_path: Path to .map file generated by GNU ld.

    Returns:
        List of MapSymbol sorted by address.
    """
    symbols: list[MapSymbol] = []

    with open(map_path, "r", errors="replace") as f:
        lines = f.readlines()

    i = 0
    while i < len(lines):
        line = lines[i]

        # Look for section.symbol pattern
        m = _MAP_SYMBOL_LINE.match(line)
        if m:
            full_section = m.group(1)
            name = _extract_symbol_name(full_section)

            if name and i + 1 < len(lines):
                # Next line should have address and size
                m2 = _MAP_ADDR_LINE.match(lines[i + 1])
                if m2:
                    addr = int(m2.group(1), 16)
                    size = int(m2.group(2), 16)
                    # Determine the base section (.bss, .data, .rodata)
                    base_section = "." + full_section.split(".")[1] if "." in full_section else full_section
                    region = _infer_region(full_section)

                    if size > 0:
                        symbols.append(
                            MapSymbol(
                                name=name,
                                address=addr,
                                size=size,
                                region=region,
                                section=base_section,
                            )
                        )
                    i += 2
                    continue

        # Also handle single-line entries:
        # .bss.var  0x20001000  0x20  obj.o
        inline_match = re.match(
            r"^\s+(\.\w+(?:\.\w+)+)\s+(0x[0-9a-fA-F]+)\s+(0x[0-9a-fA-F]+)\s+(\S+)",
            line,
        )
        if inline_match:
            full_section = inline_match.group(1)
            name = _extract_symbol_name(full_section)
            if name:
                addr = int(inline_match.group(2), 16)
                size = int(inline_match.group(3), 16)
                base_section = "." + full_section.split(".")[1] if "." in full_section else full_section
                region = _infer_region(full_section)

                if size > 0:
                    symbols.append(
                        MapSymbol(
                            name=name,
                            address=addr,
                            size=size,
                            region=region,
                            section=base_section,
                        )
                    )

        i += 1

    symbols.sort(key=lambda s: s.address)
    return symbols


# =============================================================================
# GDB Python Script Generators
# =============================================================================


def generate_batch_variable_reader(var_names: list[str]) -> str:
    """Generate a GDB Python script that reads multiple variables at once.

    The script uses ``gdb.parse_and_eval()`` with recursive type walking
    to decode each variable's value, type, and address. Handles int, float,
    struct, array, enum, pointer, and bool types with depth limiting.

    Args:
        var_names: List of variable names to read (e.g., ["g_counter", "g_state"]).

    Returns:
        String containing the complete GDB Python script.
    """
    # JSON-encode the variable list for safe embedding
    import json

    vars_json = json.dumps(var_names)

    return f'''#!/usr/bin/env python3
"""Generated GDB Python script to read multiple variables."""

import gdb
import json

result_file = str(gdb.convenience_variable("result_file")).strip('"')
result = {{"status": "ok", "variables": {{}}}}

MAX_DEPTH = 8
MAX_ARRAY_ELEMENTS = 64

def decode_value(val, depth=0):
    """Recursively decode a GDB value to a Python-serializable type."""
    if depth > MAX_DEPTH:
        return "<max depth exceeded>"

    try:
        t = val.type.strip_typedefs()
        code = t.code
    except gdb.error:
        return str(val)

    # Integer types
    if code == gdb.TYPE_CODE_INT:
        try:
            return int(val)
        except (gdb.error, OverflowError):
            return str(val)

    # Boolean
    if code == gdb.TYPE_CODE_BOOL:
        try:
            return bool(int(val))
        except (gdb.error, ValueError):
            return str(val)

    # Float / double
    if code == gdb.TYPE_CODE_FLT:
        try:
            return float(val)
        except (gdb.error, ValueError):
            return str(val)

    # Enum
    if code == gdb.TYPE_CODE_ENUM:
        return str(val)

    # Pointer
    if code == gdb.TYPE_CODE_PTR:
        try:
            return hex(int(val))
        except (gdb.error, ValueError):
            return str(val)

    # Struct / Union
    if code in (gdb.TYPE_CODE_STRUCT, gdb.TYPE_CODE_UNION):
        fields = {{}}
        try:
            for field in t.fields():
                fname = field.name
                if fname:
                    try:
                        fields[fname] = decode_value(val[fname], depth + 1)
                    except (gdb.error, ValueError):
                        fields[fname] = None
        except gdb.error:
            return str(val)
        return fields

    # Array
    if code == gdb.TYPE_CODE_ARRAY:
        elements = []
        try:
            range_type = t.range()
            low = range_type[0]
            high = min(range_type[1], low + MAX_ARRAY_ELEMENTS - 1)
            for i in range(low, high + 1):
                try:
                    elements.append(decode_value(val[i], depth + 1))
                except (gdb.error, ValueError):
                    elements.append(None)
            if range_type[1] > high:
                elements.append(f"... ({{range_type[1] - high}} more)")
        except (gdb.error, TypeError):
            return str(val)
        return elements

    # Fallback
    return str(val)


vars_to_read = {vars_json}

for name in vars_to_read:
    var_info = {{"name": name}}
    try:
        val = gdb.parse_and_eval(name)
        var_info["type"] = str(val.type)
        try:
            var_info["address"] = hex(int(val.address)) if val.address else None
        except (gdb.error, TypeError):
            var_info["address"] = None
        var_info["value"] = decode_value(val)
        var_info["status"] = "ok"
    except gdb.error as e:
        var_info["status"] = "error"
        var_info["error"] = str(e)
    except Exception as e:
        var_info["status"] = "error"
        var_info["error"] = f"Unexpected: {{str(e)}}"
    result["variables"][name] = var_info

with open(result_file, "w") as f:
    json.dump(result, f, indent=2)
'''


def generate_variable_lister(filter_pattern: Optional[str] = None) -> str:
    """Generate a GDB Python script that lists all global variables.

    Uses GDB's symbol table iteration to find all global and file-static
    variables with their types and addresses from DWARF info.

    Args:
        filter_pattern: Optional glob pattern to filter variables
            (e.g., "g_*", "*sensor*"). None lists all.

    Returns:
        String containing the complete GDB Python script.
    """
    import json

    pattern_json = json.dumps(filter_pattern)

    return f'''#!/usr/bin/env python3
"""Generated GDB Python script to list global variables."""

import gdb
import json
import fnmatch

result_file = str(gdb.convenience_variable("result_file")).strip('"')
result = {{"status": "ok", "variables": [], "filter": {pattern_json}}}

filter_pattern = {pattern_json}

try:
    # Use "info variables" to list all global/static variables
    output = gdb.execute("info variables", to_string=True)

    for line in output.splitlines():
        line = line.strip()
        if not line or line.startswith("File ") or line.startswith("Non-debugging"):
            continue

        # Lines look like: "type varname;" or "static type varname;"
        # Skip function declarations
        if "(" in line:
            continue

        # Remove trailing semicolon
        line = line.rstrip(";").strip()
        if not line:
            continue

        # Try to extract name (last token) and type (everything before)
        parts = line.rsplit(None, 1)
        if len(parts) < 2:
            continue

        var_type = parts[0].replace("static ", "")
        var_name = parts[1].rstrip("[]")  # Handle array declarations

        # Apply filter
        if filter_pattern and not fnmatch.fnmatch(var_name, filter_pattern):
            continue

        var_info = {{"name": var_name, "type": var_type}}

        # Try to get address
        try:
            val = gdb.parse_and_eval(var_name)
            if val.address:
                var_info["address"] = hex(int(val.address))
            var_info["size"] = val.type.sizeof
        except gdb.error:
            pass

        result["variables"].append(var_info)

    result["count"] = len(result["variables"])

except gdb.error as e:
    result["status"] = "error"
    result["error"] = str(e)
except Exception as e:
    result["status"] = "error"
    result["error"] = f"Unexpected: {{str(e)}}"

with open(result_file, "w") as f:
    json.dump(result, f, indent=2)
'''
