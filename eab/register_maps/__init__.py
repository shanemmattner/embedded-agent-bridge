"""Register map loader — loads per-chip JSON into RegisterMap dataclasses.

Usage:
    from eab.register_maps import load_register_map

    regmap = load_register_map("f28003x")
    nmi_reg = regmap.get_register("fault_registers", "NMIFLG")
"""

from __future__ import annotations

import json
from pathlib import Path

from .base import BitField, Register, RegisterGroup, RegisterMap

__all__ = [
    "load_register_map",
    "RegisterMap",
    "RegisterGroup",
    "Register",
    "BitField",
]

# Directory containing JSON register map files
_MAPS_DIR = Path(__file__).parent


def _parse_bit_field(name: str, definition: dict) -> BitField:
    """Parse a bit field definition from JSON."""
    bit = definition.get("bit")
    bits_raw = definition.get("bits")
    bits = tuple(bits_raw) if bits_raw else None
    return BitField(
        name=name,
        bit=bit,
        bits=bits,
        description=definition.get("description", ""),
        values=definition.get("values"),
    )


def _parse_register(name: str, definition: dict) -> Register:
    """Parse a register definition from JSON."""
    address_raw = definition.get("address", "0x0")
    if isinstance(address_raw, str):
        address = int(address_raw, 16)
    else:
        address = int(address_raw)

    bit_fields = []
    bits_section = definition.get("bits", {})
    for bf_name, bf_def in bits_section.items():
        bit_fields.append(_parse_bit_field(bf_name, bf_def))

    return Register(
        name=name,
        address=address,
        size=definition.get("size", 2),
        description=definition.get("description", ""),
        bit_fields=bit_fields,
    )


def _parse_register_group(name: str, group_data: dict) -> RegisterGroup:
    """Parse a register group from JSON.

    A group is a dict where keys starting with '_' are metadata
    and other keys are register definitions (dicts with 'address').
    """
    description = group_data.get("_description", "")
    registers: dict[str, Register] = {}

    for key, value in group_data.items():
        if key.startswith("_"):
            continue
        if not isinstance(value, dict):
            continue
        if "address" not in value:
            continue
        registers[key] = _parse_register(key, value)

    return RegisterGroup(
        name=name,
        registers=registers,
        description=description,
    )


def load_register_map(chip: str) -> RegisterMap:
    """Load a register map from a JSON file.

    Args:
        chip: Chip name matching a JSON file (e.g., "f28003x").

    Returns:
        RegisterMap with all groups and registers loaded.

    Raises:
        FileNotFoundError: If no JSON file exists for the chip.
        json.JSONDecodeError: If the JSON is malformed.
    """
    json_path = _MAPS_DIR / f"{chip}.json"
    if not json_path.exists():
        raise FileNotFoundError(
            f"No register map for '{chip}'. "
            f"Expected: {json_path}"
        )

    with open(json_path) as f:
        data = json.load(f)

    # Top-level keys that aren't register groups
    meta_keys = {"chip", "family", "cpu_freq_hz"}

    groups: dict[str, RegisterGroup] = {}
    for key, value in data.items():
        if key in meta_keys:
            continue
        if not isinstance(value, dict):
            continue
        group = _parse_register_group(key, value)
        if group.registers:  # Skip groups with no parseable registers
            groups[key] = group

    return RegisterMap(
        chip=data.get("chip", chip),
        family=data.get("family", "unknown"),
        cpu_freq_hz=data.get("cpu_freq_hz", 0),
        groups=groups,
    )


def available_maps() -> list[str]:
    """List available register map chip names."""
    return [p.stem for p in _MAPS_DIR.glob("*.json")]
