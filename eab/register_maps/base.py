"""Register map data model for chip-agnostic debug operations.

Provides dataclasses for register definitions loaded from per-chip JSON files.
The same structures describe C2000 NMI/ERAD registers, ARM Cortex-M SCB/CFSR,
or any other chip — the analyzer code is generic.
"""

from __future__ import annotations

from dataclasses import dataclass, field


@dataclass(frozen=True)
class BitField:
    """A named bit or bit range within a register."""

    name: str
    bit: int | None = None  # Single bit position
    bits: tuple[int, int] | None = None  # (low, high) bit range
    description: str = ""
    values: dict[str, str] | None = None  # Enum mapping: {"0": "disabled", "1": "enabled"}

    @property
    def mask(self) -> int:
        """Compute bitmask for this field."""
        if self.bit is not None:
            return 1 << self.bit
        if self.bits is not None:
            low, high = self.bits
            return ((1 << (high - low + 1)) - 1) << low
        return 0

    @property
    def shift(self) -> int:
        """Bit position of the LSB."""
        if self.bit is not None:
            return self.bit
        if self.bits is not None:
            return self.bits[0]
        return 0

    def extract(self, raw: int) -> int:
        """Extract this field's value from a raw register value."""
        return (raw & self.mask) >> self.shift

    def decode(self, raw: int) -> str | int:
        """Extract and decode to enum string if available, else raw int."""
        val = self.extract(raw)
        if self.values:
            return self.values.get(str(val), f"unknown({val})")
        return val


@dataclass(frozen=True)
class Register:
    """A memory-mapped register with optional bit field definitions."""

    name: str
    address: int
    size: int = 2  # bytes (C2000 default: 16-bit words)
    description: str = ""
    bit_fields: list[BitField] = field(default_factory=list)

    def decode(self, raw: int) -> dict[str, str | int]:
        """Decode all bit fields from a raw register value.

        Returns:
            Dict mapping field name to decoded value.
        """
        result: dict[str, str | int] = {}
        for bf in self.bit_fields:
            result[bf.name] = bf.decode(raw)
        return result

    def active_flags(self, raw: int) -> list[str]:
        """Return names of single-bit fields that are set (== 1)."""
        active = []
        for bf in self.bit_fields:
            if bf.bit is not None and bf.extract(raw) == 1:
                active.append(bf.name)
        return active


@dataclass
class RegisterGroup:
    """A named group of related registers (e.g., fault_registers, erad, watchdog)."""

    name: str
    registers: dict[str, Register] = field(default_factory=dict)
    description: str = ""


@dataclass
class RegisterMap:
    """Complete register map for a chip, loaded from JSON."""

    chip: str
    family: str
    cpu_freq_hz: int = 0
    groups: dict[str, RegisterGroup] = field(default_factory=dict)

    def get_register(self, group: str, name: str) -> Register | None:
        """Look up a register by group and name."""
        grp = self.groups.get(group)
        if grp:
            return grp.registers.get(name)
        return None

    def get_group(self, name: str) -> RegisterGroup | None:
        """Get a register group by name."""
        return self.groups.get(name)

    def all_registers(self) -> list[Register]:
        """Flat list of all registers across all groups."""
        regs = []
        for grp in self.groups.values():
            regs.extend(grp.registers.values())
        return regs
