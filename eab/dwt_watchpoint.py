"""DWT Watchpoint Daemon for ARM Cortex-M targets.

Provides non-halting memory watchpoint streaming via DWT comparators.
Polls DWT_FUNCTn.MATCHED at configurable rate and emits JSONL hit events.

Architecture:
    ComparatorAllocator — tracks which DWT comparator slots are in use
    DwtWatchpointDaemon — background poll thread that streams hit events
"""

from __future__ import annotations

import json
import logging
import threading
import time
from dataclasses import asdict, dataclass
from typing import Any, Optional

logger = logging.getLogger(__name__)

# Import pylink optionally (same pattern as dwt_profiler.py)
try:
    import pylink
except ImportError:
    pylink = None  # type: ignore

# =============================================================================
# DWT Register Constants
# =============================================================================

# DWT Control register (for NUMCOMP field)
DWT_CTRL_ADDR = 0xE0001000

# DWT Comparator register bases
DWT_COMP_BASE   = 0xE0001020   # DWT_COMP0
DWT_MASK_BASE   = 0xE0001024   # DWT_MASK0
DWT_FUNCT_BASE  = 0xE0001028   # DWT_FUNCT0
DWT_COMP_STRIDE = 16           # each comparator slot is 16 bytes apart

# DWT_FUNCTn field definitions
DWT_FUNCT_MATCHED   = (1 << 24)  # read-only: set when comparator fired
DWT_FUNCT_DATAVMATCH = (1 << 8)  # enable data value matching (M33 only)

# Function codes for DWT_FUNCTn[3:0]
DWT_FUNC_DISABLED  = 0b0000
DWT_FUNC_PC_SAMPLE = 0b0001   # PC sample (not a data watchpoint)
DWT_FUNC_READ      = 0b0101   # data read watchpoint
DWT_FUNC_WRITE     = 0b0110   # data write watchpoint
DWT_FUNC_RW        = 0b0111   # data read/write watchpoint
DWT_FUNC_LINKED    = 0b1100   # linked watchpoint (PC)

MODE_TO_FUNC = {
    "read":  DWT_FUNC_READ,
    "write": DWT_FUNC_WRITE,
    "rw":    DWT_FUNC_RW,
}

# =============================================================================
# Exceptions
# =============================================================================

class ComparatorExhaustedError(Exception):
    """Raised when all DWT comparator slots are in use."""


class SymbolNotFoundError(Exception):
    """Raised when a symbol cannot be found in the ELF."""


# =============================================================================
# Data Classes
# =============================================================================

@dataclass
class Comparator:
    """Represents one allocated DWT comparator slot."""
    index: int            # 0-3
    comp_addr: int        # DWT_COMPn address
    mask_addr: int        # DWT_MASKn address
    funct_addr: int       # DWT_FUNCTn address
    watch_addr: int       # target memory address being watched
    label: str            # human label (symbol name)
    mode: str             # "read"/"write"/"rw"
    size_bytes: int       # 1/2/4 (determines MASK bits)


# =============================================================================
# ComparatorAllocator
# =============================================================================

class ComparatorAllocator:
    """Tracks which of the M33's DWT comparators are in use.

    Reads DWT_CTRL.NUMCOMP (bits [31:28]) at connect time to learn actual count.
    Allocates from highest slot downwards to avoid J-Link RTT conflict (RTT
    typically uses slot 0).

    Args:
        jlink:      Connected pylink.JLink instance.
        state_file: Optional path to persist state JSON (for cross-process list/clear).
    """

    MAX_COMPARATORS = 4  # hard upper bound for Cortex-M33

    def __init__(self, jlink: Any, state_file: Optional[str] = None) -> None:
        self._jlink = jlink
        self._state_file = state_file
        self._slots: dict[int, Comparator] = {}  # index -> Comparator
        self._numcomp: Optional[int] = None

    # ------------------------------------------------------------------
    # Public API
    # ------------------------------------------------------------------

    def detect_numcomp(self) -> int:
        """Read DWT_CTRL[31:28] to get actual comparator count (1–4)."""
        ctrl = self._jlink.memory_read32(DWT_CTRL_ADDR, 1)[0]
        numcomp = (ctrl >> 28) & 0xF
        return max(1, numcomp)  # at least 1

    def _get_numcomp(self) -> int:
        if self._numcomp is None:
            self._numcomp = self.detect_numcomp()
        return self._numcomp

    def allocate(
        self,
        watch_addr: int,
        label: str,
        mode: str,
        size_bytes: int = 4,
    ) -> Comparator:
        """Find a free comparator slot, configure it, return Comparator.

        Allocates from the highest available slot downwards to avoid
        J-Link RTT firmware conflict (RTT uses slot 0).

        Args:
            watch_addr: Target memory address to watch.
            label:      Human-readable label (symbol name).
            mode:       "read", "write", or "rw".
            size_bytes: Variable size (1, 2, or 4 bytes).

        Returns:
            Allocated Comparator.

        Raises:
            ComparatorExhaustedError: If all slots are in use.
            ValueError: If mode is invalid.
        """
        numcomp = self._get_numcomp()
        if mode not in MODE_TO_FUNC:
            raise ValueError(f"Invalid mode '{mode}'. Must be one of: {list(MODE_TO_FUNC)}")

        # Allocate from highest slot downward (avoid RTT slot 0 conflict)
        for idx in range(numcomp - 1, -1, -1):
            if idx not in self._slots:
                comp = self._configure_slot(idx, watch_addr, label, mode, size_bytes)
                self._slots[idx] = comp
                self._write_state()
                return comp

        raise ComparatorExhaustedError(
            f"All {numcomp} DWT comparator slots are in use. "
            "Run 'eabctl dwt clear' to release them."
        )

    def release(self, index: int) -> None:
        """Clear DWT_FUNCTn and mark slot as free.

        Args:
            index: Comparator slot index (0–3).
        """
        funct_addr = DWT_FUNCT_BASE + index * DWT_COMP_STRIDE
        self._jlink.memory_write32(funct_addr, [0])
        self._slots.pop(index, None)
        self._write_state()
        logger.debug("Released DWT comparator slot %d", index)

    def release_all(self) -> None:
        """Clear all comparators and reset state."""
        numcomp = self._get_numcomp()
        for idx in range(numcomp):
            funct_addr = DWT_FUNCT_BASE + idx * DWT_COMP_STRIDE
            self._jlink.memory_write32(funct_addr, [0])
        self._slots.clear()
        self._write_state()
        logger.debug("Released all DWT comparator slots")

    def active(self) -> list[Comparator]:
        """Return list of currently configured comparators."""
        return list(self._slots.values())

    # ------------------------------------------------------------------
    # Internal helpers
    # ------------------------------------------------------------------

    def _configure_slot(
        self,
        index: int,
        watch_addr: int,
        label: str,
        mode: str,
        size_bytes: int,
    ) -> Comparator:
        """Write DWT registers to configure one comparator slot."""
        comp_addr  = DWT_COMP_BASE  + index * DWT_COMP_STRIDE
        mask_addr  = DWT_MASK_BASE  + index * DWT_COMP_STRIDE
        funct_addr = DWT_FUNCT_BASE + index * DWT_COMP_STRIDE

        func_code = MODE_TO_FUNC[mode]

        # Sequence:
        # 1. Disable comparator
        self._jlink.memory_write32(funct_addr, [0])
        # 2. Write target address
        self._jlink.memory_write32(comp_addr, [watch_addr])
        # 3. Exact match (no masking)
        self._jlink.memory_write32(mask_addr, [0])
        # 4. Enable with function code
        self._jlink.memory_write32(funct_addr, [func_code])

        logger.debug(
            "Configured DWT slot %d: addr=0x%08X mode=%s size=%d",
            index, watch_addr, mode, size_bytes,
        )

        return Comparator(
            index=index,
            comp_addr=comp_addr,
            mask_addr=mask_addr,
            funct_addr=funct_addr,
            watch_addr=watch_addr,
            label=label,
            mode=mode,
            size_bytes=size_bytes,
        )

    def _write_state(self) -> None:
        """Persist active comparators to state_file (JSON)."""
        if not self._state_file:
            return
        try:
            data = [asdict(c) for c in self._slots.values()]
            with open(self._state_file, "w") as fh:
                json.dump(data, fh)
        except Exception as exc:
            logger.warning("Failed to write DWT state file: %s", exc)

    def _load_state(self) -> None:
        """Load persisted comparators from state_file."""
        if not self._state_file:
            return
        try:
            with open(self._state_file) as fh:
                data = json.load(fh)
            self._slots = {
                item["index"]: Comparator(**item)
                for item in data
            }
        except FileNotFoundError:
            self._slots = {}
        except Exception as exc:
            logger.warning("Failed to load DWT state file: %s", exc)
            self._slots = {}


# =============================================================================
# DwtWatchpointDaemon
# =============================================================================

class DwtWatchpointDaemon:
    """Non-halting DWT memory watchpoint daemon.

    Configures one DWT comparator for the given symbol/address, then polls
    DWT_FUNCTn.MATCHED at ~100 Hz without halting the target. When MATCHED
    fires, reads the watched memory location and emits a JSONL event to
    stdout and optionally to an events file.

    The MATCHED bit is a sticky read-clear bit: reading DWT_FUNCTn clears it
    on M33 (unlike M4 where a write-zero is required).

    Args:
        jlink:        Connected pylink.JLink instance.
        comparator:   Comparator allocated by ComparatorAllocator.
        poll_hz:      Poll rate (default 100). Keep ≤200 to avoid starving SWD.
        events_file:  Optional path to append JSONL events (in addition to stdout).
        write_to_clear: If True (M4 cores), MATCHED is cleared by writing 0 to
                        DWT_FUNCTn (then re-writing func code). Default False (M33).
    """

    def __init__(
        self,
        jlink: Any,
        comparator: Comparator,
        poll_hz: int = 100,
        events_file: Optional[str] = None,
        write_to_clear: bool = False,
    ) -> None:
        self._jlink = jlink
        self._comp = comparator
        self._poll_interval = 1.0 / poll_hz
        self._events_file = events_file
        self._write_to_clear = write_to_clear
        self._funct_config = MODE_TO_FUNC.get(comparator.mode, DWT_FUNC_WRITE)
        self._stop_event = threading.Event()
        self._thread: Optional[threading.Thread] = None

    def start(self) -> None:
        """Start the background poll thread."""
        self._stop_event.clear()
        self._thread = threading.Thread(
            target=self._poll_loop,
            name=f"dwt-watchpoint-{self._comp.index}",
            daemon=True,
        )
        self._thread.start()

    def stop(self) -> None:
        """Signal the poll thread to stop and wait for it to join."""
        self._stop_event.set()
        if self._thread:
            self._thread.join(timeout=2.0)
            self._thread = None

    def _poll_loop(self) -> None:
        """Main poll loop — runs in background thread.

        Every 1/poll_hz seconds:
          1. Read DWT_FUNCTn.
          2. If MATCHED bit is set, call _handle_hit() then re-read to clear.
          3. Sleep until next interval.

        Runs at least one iteration before checking the stop event, so that
        calling _stop_event.set() before starting still processes one poll.
        """
        while True:
            t_start = time.monotonic()
            try:
                funct = self._jlink.memory_read32(self._comp.funct_addr, 1)[0]
                if funct & DWT_FUNCT_MATCHED:
                    value = self._read_value()
                    self._emit_event(value)
                    if self._write_to_clear:
                        # M4: clear by writing 0, then re-writing func value
                        self._jlink.memory_write32(self._comp.funct_addr, [0])
                        self._jlink.memory_write32(
                            self._comp.funct_addr, [self._funct_config]
                        )
                    else:
                        # M33: clear by re-reading (already cleared on first read)
                        self._jlink.memory_read32(self._comp.funct_addr, 1)
            except Exception as exc:
                logger.warning("DWT poll error: %s", exc)

            # Check stop after processing (ensures at least one iteration)
            if self._stop_event.is_set():
                break

            elapsed = time.monotonic() - t_start
            remaining = self._poll_interval - elapsed
            if remaining > 0:
                self._stop_event.wait(timeout=remaining)
            if self._stop_event.is_set():
                break

    def _read_value(self) -> int:
        """Read current value at the watched address.

        Reads 1, 2, or 4 bytes depending on comparator.size_bytes.
        Returns value as int.
        """
        size = self._comp.size_bytes
        addr = self._comp.watch_addr
        if size == 1:
            return self._jlink.memory_read8(addr, 1)[0]
        elif size == 2:
            raw = self._jlink.memory_read8(addr, 2)
            return raw[0] | (raw[1] << 8)
        else:  # 4
            return self._jlink.memory_read32(addr, 1)[0]

    def _emit_event(self, value: int) -> None:
        """Format and emit a JSONL watchpoint-hit event.

        Output format:
          {"ts": <microseconds>, "label": "<symbol>", "addr": "0x...", "value": "0x..."}
        """
        ts_us = int(time.time() * 1_000_000)
        event = {
            "ts": ts_us,
            "label": self._comp.label,
            "addr": f"0x{self._comp.watch_addr:08X}",
            "value": f"0x{value:0{self._comp.size_bytes * 2}X}",
        }
        line = json.dumps(event)
        print(line, flush=True)
        if self._events_file:
            with open(self._events_file, "a") as fh:
                fh.write(line + "\n")


# =============================================================================
# Helper: detect M4 vs M33 clear semantics
# =============================================================================

def _requires_write_to_clear_matched(device: str) -> bool:
    """Return True for M4 cores (MATCHED cleared by write, not read).

    Args:
        device: J-Link device string (e.g., "NRF5340_XXAA_APP", "STM32F407VG").

    Returns:
        True if write-to-clear is needed (Cortex-M4/M3 style).
    """
    m4_devices = ("stm32f4", "stm32f3", "stm32f2", "nrf52", "nrf51", "lpc43", "sam3")
    device_lower = device.lower()
    return any(d in device_lower for d in m4_devices)
