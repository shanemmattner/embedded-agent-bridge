"""Debug Monitor Mode control for ARM Cortex-M targets.

Enables DebugMonitor exception-based debugging instead of CPU halt-mode.
For BLE firmware on nRF5340, this allows the BLE Link Layer (net core)
and BLE Host/GATT (app core) to keep running while breakpoints fire as
lower-priority exceptions on the app core.

Architecture:
    enable()  → sets MON_EN + TRCENA in DEMCR, sets priority in SHPR3
    disable() → clears MON_EN in DEMCR
    status()  → reads DEMCR, returns DebugMonitorStatus

ARM CoreSight Register Map:
    DEMCR    0xE000EDFC  Debug Exception and Monitor Control Register
    SHPR3    0xE000ED20  System Handler Priority Register 3
"""

from __future__ import annotations

import logging
from dataclasses import dataclass
from typing import Any

logger = logging.getLogger(__name__)

# Import pylink optionally
try:
    import pylink
except ImportError:
    pylink = None  # type: ignore


# =============================================================================
# Register Constants
# =============================================================================

DEMCR_ADDR = 0xE000EDFC   # Debug Exception and Monitor Control Register
SHPR3_ADDR = 0xE000ED20   # System Handler Priority Register 3

# DEMCR bit masks
MON_EN   = 1 << 16   # bit16: Enable debug monitor exception
MON_PEND = 1 << 17   # bit17: Pend debug monitor exception
MON_STEP = 1 << 18   # bit18: Single-step on resume
TRCENA   = 1 << 24   # bit24: Enable trace system (DWT, ITM, etc.)


# =============================================================================
# Data Classes
# =============================================================================

@dataclass
class DebugMonitorStatus:
    """Current state of the ARM Debug Monitor exception."""
    enabled: bool
    mon_step: bool
    mon_pend: bool
    priority: int        # 0–255 (lower = higher priority in ARM)
    raw_demcr: int       # Raw DEMCR register value


# =============================================================================
# DebugMonitor Class
# =============================================================================

class DebugMonitor:
    """Control ARM Cortex-M Debug Monitor exception via J-Link.

    Uses pylink-square (pylink.JLink) to read/write ARM CoreSight registers.

    Example::

        import pylink
        jl = pylink.JLink()
        jl.open()
        jl.set_tif(pylink.enums.JLinkInterfaces.SWD)
        jl.connect("NRF5340_XXAA_APP")

        dm = DebugMonitor(jl)
        dm.enable(priority=3)
        status = dm.status()
        print(status.enabled)  # True
        dm.disable()
    """

    def __init__(self, jlink: Any) -> None:
        """Initialise DebugMonitor.

        Args:
            jlink: A connected pylink.JLink instance.
        """
        self._jl = jlink
        self._ensure_pylink()

    # ------------------------------------------------------------------
    # Public API
    # ------------------------------------------------------------------

    def enable(self, priority: int = 3) -> None:
        """Enable debug monitor mode.

        Sets MON_EN and TRCENA in DEMCR and programs the debug monitor
        exception priority in SHPR3.

        Args:
            priority: ARM exception priority (0–7 maps to NVIC priority
                      levels; lower = higher priority).  Default 3.
        """
        self._ensure_pylink()
        demcr = self._read_demcr()
        demcr |= MON_EN | TRCENA
        self._write_demcr(demcr)
        self._set_priority(priority)
        logger.debug(
            "Debug monitor enabled: DEMCR=0x%08X priority=%d", demcr, priority
        )

    def disable(self) -> None:
        """Disable debug monitor mode (clears MON_EN in DEMCR)."""
        self._ensure_pylink()
        demcr = self._read_demcr()
        demcr &= ~MON_EN
        self._write_demcr(demcr)
        logger.debug("Debug monitor disabled: DEMCR=0x%08X", demcr)

    def status(self) -> DebugMonitorStatus:
        """Read and return current debug monitor status.

        Returns:
            DebugMonitorStatus with current register state.
        """
        self._ensure_pylink()
        raw_demcr = self._read_demcr()
        priority = self._read_priority()
        return DebugMonitorStatus(
            enabled=bool(raw_demcr & MON_EN),
            mon_step=bool(raw_demcr & MON_STEP),
            mon_pend=bool(raw_demcr & MON_PEND),
            priority=priority,
            raw_demcr=raw_demcr,
        )

    # ------------------------------------------------------------------
    # Private helpers
    # ------------------------------------------------------------------

    def _ensure_pylink(self) -> None:
        """Raise helpful ImportError if pylink is not installed."""
        if pylink is None:
            raise ImportError(
                "pylink module not found. Install with: pip install pylink-square"
            )

    def _read_demcr(self) -> int:
        """Read the DEMCR register value."""
        return self._jl.memory_read32(DEMCR_ADDR, 1)[0]

    def _write_demcr(self, val: int) -> None:
        """Write a value to the DEMCR register."""
        self._jl.memory_write32(DEMCR_ADDR, [val])

    def _set_priority(self, priority: int) -> None:
        """Program the debug monitor exception priority in SHPR3.

        SHPR3 encodes the DebugMonitor priority in bits [23:16] (byte 2).
        ARM stores priority in the top bits of the priority byte; we
        shift ``priority`` into bits [7:5] of byte 2 (i.e. << 5+16 = << 21).

        Args:
            priority: Priority value (0–7).
        """
        shpr3 = self._jl.memory_read32(SHPR3_ADDR, 1)[0]
        # Clear existing DebugMonitor priority field (bits [23:16])
        shpr3 &= ~(0xFF << 16)
        # Write new priority value (shifted into bits [23:21])
        shpr3 |= ((priority & 0x7) << 5) << 16
        self._jl.memory_write32(SHPR3_ADDR, [shpr3])
        logger.debug("SHPR3 set to 0x%08X (priority=%d)", shpr3, priority)

    def _read_priority(self) -> int:
        """Read the current debug monitor priority from SHPR3.

        Returns:
            Priority value (0–7) decoded from bits [23:16] of SHPR3.
        """
        shpr3 = self._jl.memory_read32(SHPR3_ADDR, 1)[0]
        # Extract byte 2 (bits [23:16]) and decode top 3 bits
        byte2 = (shpr3 >> 16) & 0xFF
        return (byte2 >> 5) & 0x7
