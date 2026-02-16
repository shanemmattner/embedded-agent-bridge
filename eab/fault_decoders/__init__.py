"""Pluggable fault decoder registry.

Mirrors the pattern in eab/chips/__init__.py — an ABC + registry dict + factory.
Add a new architecture by dropping in one file and registering it here.
"""

from .base import FaultDecoder, FaultReport
from .c2000 import C2000Decoder
from .cortex_m import CortexMDecoder

__all__ = [
    "FaultDecoder",
    "FaultReport",
    "C2000Decoder",
    "CortexMDecoder",
    "get_fault_decoder",
]

# Registry: chip name -> decoder class
_DECODERS: dict[str, type[FaultDecoder]] = {
    "nrf5340": CortexMDecoder,
    "nrf52840": CortexMDecoder,
    "nrf52833": CortexMDecoder,
    "stm32": CortexMDecoder,
    "stm32f1": CortexMDecoder,
    "stm32f3": CortexMDecoder,
    "stm32f4": CortexMDecoder,
    "stm32l4": CortexMDecoder,
    "stm32h7": CortexMDecoder,
    "mcxn947": CortexMDecoder,
    "c2000": C2000Decoder,
    "c2000_f280039c": C2000Decoder,
    "c2000_f28379d": C2000Decoder,
    # Future:
    # "esp32c6": RiscVDecoder,
    # "esp32s3": XtensaDecoder,
}


def get_fault_decoder(chip: str) -> FaultDecoder:
    """Get fault decoder for a chip. Defaults to CortexMDecoder for unknown chips."""
    cls = _DECODERS.get(chip.lower(), CortexMDecoder)
    return cls()
