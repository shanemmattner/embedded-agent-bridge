"""Generic register decoder — chip-agnostic.

Takes raw bytes from any memory read transport (XDS110, J-Link, OpenOCD)
and decodes them using register definitions from a RegisterMap JSON.
"""

from __future__ import annotations

import struct
from dataclasses import dataclass, field

from .base import Register, RegisterGroup, RegisterMap


@dataclass
class DecodedField:
    """A single decoded bit field."""

    name: str
    raw_value: int
    decoded: str | int
    description: str = ""
    is_flag: bool = False  # True if single-bit field
    is_set: bool = False  # True if flag and value == 1


@dataclass
class DecodedRegister:
    """A fully decoded register with all bit fields resolved."""

    name: str
    address: int
    raw_value: int
    size: int
    description: str = ""
    fields: list[DecodedField] = field(default_factory=list)
    active_flags: list[str] = field(default_factory=list)

    @property
    def hex_value(self) -> str:
        """Format raw value as hex string matching register size."""
        width = self.size * 2  # 2 hex chars per byte
        return f"0x{self.raw_value:0{width}X}"


def bytes_to_int(data: bytes, size: int, byteorder: str = "little") -> int:
    """Convert raw bytes to integer.

    Args:
        data: Raw bytes from memory read.
        size: Expected size in bytes.
        byteorder: "little" (default, ARM/C2000) or "big".

    Returns:
        Integer value.
    """
    if len(data) < size:
        # Pad with zeros if short read
        data = data + b"\x00" * (size - len(data))
    return int.from_bytes(data[:size], byteorder=byteorder)


def decode_register(register: Register, raw_value: int) -> DecodedRegister:
    """Decode a raw register value using its definition.

    Args:
        register: Register definition with bit fields.
        raw_value: Integer value read from hardware.

    Returns:
        DecodedRegister with all fields resolved.
    """
    fields = []
    active_flags = []

    for bf in register.bit_fields:
        extracted = bf.extract(raw_value)
        decoded = bf.decode(raw_value)
        is_flag = bf.bit is not None and bf.values is None
        is_set = is_flag and extracted == 1

        fields.append(DecodedField(
            name=bf.name,
            raw_value=extracted,
            decoded=decoded,
            description=bf.description,
            is_flag=is_flag,
            is_set=is_set,
        ))

        if is_set:
            active_flags.append(bf.name)

    return DecodedRegister(
        name=register.name,
        address=register.address,
        raw_value=raw_value,
        size=register.size,
        description=register.description,
        fields=fields,
        active_flags=active_flags,
    )


def decode_register_bytes(register: Register, data: bytes, byteorder: str = "little") -> DecodedRegister:
    """Decode raw bytes into a DecodedRegister.

    Convenience wrapper that handles bytes-to-int conversion.

    Args:
        register: Register definition.
        data: Raw bytes from memory read.
        byteorder: Byte order for conversion.

    Returns:
        DecodedRegister with all fields resolved.
    """
    raw_value = bytes_to_int(data, register.size, byteorder)
    return decode_register(register, raw_value)


def decode_group(
    group: RegisterGroup,
    memory_reader,
    byteorder: str = "little",
) -> list[DecodedRegister]:
    """Decode all registers in a group by reading memory.

    Args:
        group: RegisterGroup with register definitions.
        memory_reader: Callable(address, size) -> bytes | None.
        byteorder: Byte order for conversion.

    Returns:
        List of DecodedRegister for each successfully read register.
    """
    results = []
    for reg in group.registers.values():
        data = memory_reader(reg.address, reg.size)
        if data is not None:
            results.append(decode_register_bytes(reg, data, byteorder))
    return results
