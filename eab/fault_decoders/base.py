"""Base fault decoder ABC and universal FaultReport dataclass.

New architecture decoders implement FaultDecoder to provide:
- GDB commands for reading fault state
- Parsing + decoding of architecture-specific registers
- Human-readable fault descriptions and suggestions
"""

from __future__ import annotations

from abc import ABC, abstractmethod
from dataclasses import dataclass, field
from typing import Optional


@dataclass
class FaultReport:
    """Architecture-neutral structured result from fault register analysis.

    Decoders populate fault_registers with whatever registers are relevant
    (CFSR/HFSR for ARM, mcause/mtval for RISC-V, etc.).
    """

    arch: str = ""
    fault_registers: dict[str, int] = field(default_factory=dict)
    core_regs: dict[str, int] = field(default_factory=dict)
    stacked_pc: Optional[int] = None
    backtrace: str = ""
    faults: list[str] = field(default_factory=list)
    suggestions: list[str] = field(default_factory=list)
    raw_gdb_output: str = ""


class FaultDecoder(ABC):
    """Base class for architecture-specific fault decoders."""

    @property
    @abstractmethod
    def name(self) -> str:
        """Human-readable name, e.g. 'ARM Cortex-M'."""

    @abstractmethod
    def gdb_commands(self) -> list[str]:
        """GDB commands to read fault state (run between 'monitor halt' and 'bt')."""

    @abstractmethod
    def parse_and_decode(self, gdb_output: str) -> FaultReport:
        """Parse raw GDB output into a structured, decoded FaultReport."""
