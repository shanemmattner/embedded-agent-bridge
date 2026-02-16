"""C2000 type decoder — raw bytes to typed values.

C2000 uses 16-bit word-addressed memory. Address 0xC002 means word 0xC002
(2 bytes), not byte 0xC002. DSLite returns bytes but addresses are word
addresses. The size parameter to memory_read is in bytes.

Supports standard C types and TI IQ fixed-point formats:
- IQ24: 32-bit signed, 24 fractional bits → value / 2^24
- IQ20: 32-bit signed, 20 fractional bits → value / 2^20
- IQ15: 32-bit signed, 15 fractional bits → value / 2^15
- IQ10: 32-bit signed, 10 fractional bits → value / 2^10
"""

from __future__ import annotations

import struct
from dataclasses import dataclass
from enum import Enum


class C2000Type(Enum):
    """Supported C2000 data types."""

    INT16 = "int16"
    UINT16 = "uint16"
    INT32 = "int32"
    UINT32 = "uint32"
    FLOAT32 = "float32"
    FLOAT64 = "float64"
    IQ24 = "iq24"
    IQ20 = "iq20"
    IQ15 = "iq15"
    IQ10 = "iq10"


@dataclass(frozen=True)
class TypeInfo:
    """Metadata for a C2000 type."""

    c2000_type: C2000Type
    word_size: int  # Size in 16-bit words (not bytes)
    byte_size: int  # Size in bytes (for memory_read)
    description: str = ""


# Type metadata lookup
_TYPE_INFO: dict[C2000Type, TypeInfo] = {
    C2000Type.INT16: TypeInfo(C2000Type.INT16, 1, 2, "16-bit signed integer"),
    C2000Type.UINT16: TypeInfo(C2000Type.UINT16, 1, 2, "16-bit unsigned integer"),
    C2000Type.INT32: TypeInfo(C2000Type.INT32, 2, 4, "32-bit signed integer"),
    C2000Type.UINT32: TypeInfo(C2000Type.UINT32, 2, 4, "32-bit unsigned integer"),
    C2000Type.FLOAT32: TypeInfo(C2000Type.FLOAT32, 2, 4, "32-bit IEEE 754 float"),
    C2000Type.FLOAT64: TypeInfo(C2000Type.FLOAT64, 4, 8, "64-bit IEEE 754 double"),
    C2000Type.IQ24: TypeInfo(C2000Type.IQ24, 2, 4, "TI IQ24 fixed-point (24 fractional bits)"),
    C2000Type.IQ20: TypeInfo(C2000Type.IQ20, 2, 4, "TI IQ20 fixed-point (20 fractional bits)"),
    C2000Type.IQ15: TypeInfo(C2000Type.IQ15, 2, 4, "TI IQ15 fixed-point (15 fractional bits)"),
    C2000Type.IQ10: TypeInfo(C2000Type.IQ10, 2, 4, "TI IQ10 fixed-point (10 fractional bits)"),
}

# IQ format fractional bit counts
_IQ_FRAC_BITS: dict[C2000Type, int] = {
    C2000Type.IQ24: 24,
    C2000Type.IQ20: 20,
    C2000Type.IQ15: 15,
    C2000Type.IQ10: 10,
}


def type_info(c2000_type: C2000Type) -> TypeInfo:
    """Get size and metadata for a C2000 type."""
    return _TYPE_INFO[c2000_type]


def word_size(c2000_type: C2000Type) -> int:
    """Return size in 16-bit words."""
    return _TYPE_INFO[c2000_type].word_size


def byte_size(c2000_type: C2000Type) -> int:
    """Return size in bytes (for memory_read size parameter)."""
    return _TYPE_INFO[c2000_type].byte_size


def decode_value(data: bytes, c2000_type: C2000Type, byteorder: str = "little") -> int | float:
    """Decode raw bytes to a typed value.

    Args:
        data: Raw bytes from memory read.
        c2000_type: Target data type.
        byteorder: Byte order ("little" for C2000).

    Returns:
        Decoded value as int or float.

    Raises:
        ValueError: If data is too short for the type.
    """
    expected = byte_size(c2000_type)
    if len(data) < expected:
        raise ValueError(
            f"Need {expected} bytes for {c2000_type.value}, got {len(data)}"
        )
    raw = data[:expected]

    if c2000_type == C2000Type.INT16:
        return struct.unpack("<h" if byteorder == "little" else ">h", raw)[0]

    if c2000_type == C2000Type.UINT16:
        return struct.unpack("<H" if byteorder == "little" else ">H", raw)[0]

    if c2000_type == C2000Type.INT32:
        return struct.unpack("<i" if byteorder == "little" else ">i", raw)[0]

    if c2000_type == C2000Type.UINT32:
        return struct.unpack("<I" if byteorder == "little" else ">I", raw)[0]

    if c2000_type == C2000Type.FLOAT32:
        return struct.unpack("<f" if byteorder == "little" else ">f", raw)[0]

    if c2000_type == C2000Type.FLOAT64:
        return struct.unpack("<d" if byteorder == "little" else ">d", raw)[0]

    # IQ fixed-point formats
    if c2000_type in _IQ_FRAC_BITS:
        frac_bits = _IQ_FRAC_BITS[c2000_type]
        # Read as signed 32-bit integer, then divide by 2^frac_bits
        raw_int = struct.unpack("<i" if byteorder == "little" else ">i", raw)[0]
        return raw_int / (1 << frac_bits)

    raise ValueError(f"Unsupported type: {c2000_type}")


def parse_type_string(type_str: str) -> C2000Type:
    """Parse a type string to C2000Type enum.

    Accepts: "int16", "uint16", "int32", "uint32", "float32", "float64",
             "iq24", "iq20", "iq15", "iq10", "IQ24", etc.
    """
    try:
        return C2000Type(type_str.lower())
    except ValueError:
        valid = ", ".join(t.value for t in C2000Type)
        raise ValueError(f"Unknown type '{type_str}'. Valid: {valid}")
