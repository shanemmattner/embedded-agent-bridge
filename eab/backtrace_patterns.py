"""Backtrace pattern matching and parsing for multi-target embedded systems.

Regex patterns and parsers for extracting backtrace addresses from:
- ESP-IDF (ESP32): Backtrace:0x400d1234:0x3ffb5678 0x400d5678:0x3ffb9abc
- Zephyr fatal errors (nRF, STM32, NXP): E: r15/pc: 0x0000xxxx
- Generic GDB backtraces: #0 0x0000xxxx in func_name () at file.c:123
"""

from __future__ import annotations

import re
from dataclasses import dataclass
from typing import Optional


@dataclass
class BacktraceEntry:
    """A single backtrace address with optional decoded source location."""
    address: int
    """Raw address value."""

    pc_address: Optional[int] = None
    """Stack pointer address (ESP32 backtrace format: PC:SP)."""

    function: Optional[str] = None
    """Function name from addr2line."""

    file: Optional[str] = None
    """Source file path from addr2line."""

    line: Optional[int] = None
    """Source line number from addr2line."""

    raw_line: Optional[str] = None
    """Original backtrace line from serial output."""


@dataclass
class BacktraceResult:
    """Full backtrace decode result."""
    entries: list[BacktraceEntry]
    """List of decoded backtrace entries."""

    format: str
    """Detected format: 'esp-idf', 'zephyr', 'gdb', or 'unknown'."""

    error: Optional[str] = None
    """Error message if decoding failed."""


# =============================================================================
# Pattern Matchers
# =============================================================================

# ESP-IDF crash handler prints PC:SP pairs on one line after "Backtrace:"
# Format: Backtrace:0x400d1234:0x3ffb5678 0x400d5678:0x3ffb9abc
_ESP_BACKTRACE_RE = re.compile(
    r'Backtrace:\s*((?:0x[0-9a-fA-F]+:0x[0-9a-fA-F]+\s*)+)',
    re.IGNORECASE
)
# Extracts individual PC:SP address pairs from the backtrace line
_ESP_ADDR_PAIR_RE = re.compile(r'(0x[0-9a-fA-F]+):(0x[0-9a-fA-F]+)')

# Zephyr fatal error register dump outputs PC as "r15/pc:" in the register listing
# Matches both "E:" and "ERROR:" prefixes used across Zephyr versions
_ZEPHYR_PC_RE = re.compile(
    r'(?:E:|ERROR:).*?(?:r15|pc).*?:\s*(0x[0-9a-fA-F]+)',
    re.IGNORECASE
)
# Zephyr register dump lines: "E: r0/a1: 0x00000000" — any register value
# Used to extract additional potential code addresses from the dump
_ZEPHYR_REG_RE = re.compile(
    r'(?:E:|ERROR:).*?r\d+.*?:\s*(0x[0-9a-fA-F]+)',
    re.IGNORECASE
)

# GDB backtrace frames: "#0  0x0000xxxx in func_name () at file.c:123"
# Also handles frames without addresses (optimized out) and without source info
# Allows leading whitespace for indented output from nested GDB commands
_GDB_FRAME_RE = re.compile(
    r'^\s*#\d+\s+(?:(?:0x([0-9a-fA-F]+)\s+)?in\s+)?(\S+)\s*\([^)]*\)(?:\s+at\s+([^:]+):(\d+))?',
    re.MULTILINE
)


# =============================================================================
# Backtrace Parsers
# =============================================================================

def _parse_esp_backtrace(text: str) -> list[BacktraceEntry]:
    """Parse ESP-IDF backtrace format: Backtrace:0x400d1234:0x3ffb5678 0x400d5678:0x3ffb9abc"""
    entries: list[BacktraceEntry] = []

    match = _ESP_BACKTRACE_RE.search(text)
    if not match:
        return entries

    backtrace_str = match.group(1)
    for addr_match in _ESP_ADDR_PAIR_RE.finditer(backtrace_str):
        pc = int(addr_match.group(1), 16)
        sp = int(addr_match.group(2), 16)
        entries.append(BacktraceEntry(
            address=pc,
            pc_address=sp,
            raw_line=addr_match.group(0)
        ))

    return entries


def _parse_zephyr_backtrace(text: str) -> list[BacktraceEntry]:
    """Parse Zephyr fatal error register dump for PC and register values."""
    entries: list[BacktraceEntry] = []

    # Look for PC register first
    pc_match = _ZEPHYR_PC_RE.search(text)
    if pc_match:
        pc = int(pc_match.group(1), 16)
        entries.append(BacktraceEntry(
            address=pc,
            raw_line=pc_match.group(0)
        ))

    # Extract other register values as potential addresses
    for reg_match in _ZEPHYR_REG_RE.finditer(text):
        addr = int(reg_match.group(1), 16)
        # Filter register values to plausible code addresses:
        # - Below 0x1000: likely zero/null registers, not code pointers
        # - Above 0xFFFF_FFFF: impossible on 32-bit targets
        if 0x1000 <= addr <= 0xFFFF_FFFF and addr not in [e.address for e in entries]:
            entries.append(BacktraceEntry(
                address=addr,
                raw_line=reg_match.group(0)
            ))

    return entries


def _parse_gdb_backtrace(text: str) -> list[BacktraceEntry]:
    """Parse GDB backtrace format: #0  0x0000xxxx in func_name () at file.c:123"""
    entries: list[BacktraceEntry] = []

    for frame_match in _GDB_FRAME_RE.finditer(text):
        addr_str = frame_match.group(1)
        func = frame_match.group(2)
        file_path = frame_match.group(3)
        line_str = frame_match.group(4)

        # GDB frames may not always have an address (e.g., optimized out)
        addr = int(addr_str, 16) if addr_str else None
        line_num = int(line_str) if line_str else None

        entry = BacktraceEntry(
            address=addr or 0,
            function=func,
            file=file_path,
            line=line_num,
            raw_line=frame_match.group(0).strip()
        )
        entries.append(entry)

    return entries
