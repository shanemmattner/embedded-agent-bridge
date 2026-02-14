"""Backtrace decoding with addr2line for multi-target embedded systems.

Automatically detects backtrace patterns from:
- ESP-IDF (ESP32): Backtrace:0x400d1234:0x3ffb5678 0x400d5678:0x3ffb9abc
- Zephyr fatal errors (nRF, STM32, NXP): E: r15/pc: 0x0000xxxx
- Generic GDB backtraces: #0 0x0000xxxx in func_name () at file.c:123

Uses toolchain-specific addr2line binaries to resolve addresses to source file:line.
"""

from __future__ import annotations

import logging
import re
import subprocess
from dataclasses import dataclass
from pathlib import Path
from typing import Optional

from .toolchain import which_or_sdk

logger = logging.getLogger(__name__)


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

# ESP-IDF: Backtrace:0x400d1234:0x3ffb5678 0x400d5678:0x3ffb9abc
_ESP_BACKTRACE_RE = re.compile(
    r'Backtrace:\s*((?:0x[0-9a-fA-F]+:0x[0-9a-fA-F]+\s*)+)',
    re.IGNORECASE
)
_ESP_ADDR_PAIR_RE = re.compile(r'(0x[0-9a-fA-F]+):(0x[0-9a-fA-F]+)')

# Zephyr fatal error register dump: E: r0/a1: 0x00000000 or E: Faulting instruction address (r15/pc): 0x0000xxxx
_ZEPHYR_PC_RE = re.compile(
    r'(?:E:|ERROR:).*?(?:r15|pc).*?:\s*(0x[0-9a-fA-F]+)',
    re.IGNORECASE
)
_ZEPHYR_REG_RE = re.compile(
    r'(?:E:|ERROR:).*?r\d+.*?:\s*(0x[0-9a-fA-F]+)',
    re.IGNORECASE
)

# GDB backtrace: #0  0x0000xxxx in func_name () at file.c:123
# Also matches: #0  func_name () at file.c:123 (no address)
# Allow leading whitespace for indented output
_GDB_FRAME_RE = re.compile(
    r'^\s*#\d+\s+(?:(?:0x([0-9a-fA-F]+)\s+)?in\s+)?(\S+)\s*\([^)]*\)(?:\s+at\s+([^:]+):(\d+))?',
    re.MULTILINE
)


# =============================================================================
# Toolchain Discovery
# =============================================================================

def _get_addr2line_for_arch(arch: str, toolchain_path: Optional[str] = None) -> Optional[str]:
    """Find addr2line binary for the given architecture.
    
    Args:
        arch: Architecture hint ('arm', 'xtensa', 'riscv', 'esp32', 'nrf', 'stm32', etc.)
        toolchain_path: Optional explicit path to addr2line binary.
    
    Returns:
        Path to addr2line binary, or None if not found.
    """
    if toolchain_path:
        return toolchain_path if Path(toolchain_path).exists() else None
    
    arch_lower = arch.lower()
    
    # ESP32 Xtensa
    if 'xtensa' in arch_lower or arch_lower in ('esp32', 'esp32s2', 'esp32s3'):
        for name in ('xtensa-esp32s3-elf-addr2line', 'xtensa-esp32s2-elf-addr2line', 'xtensa-esp32-elf-addr2line'):
            path = which_or_sdk(name)
            if path:
                return path
    
    # ESP32 RISC-V
    if 'riscv' in arch_lower or arch_lower in ('esp32c3', 'esp32c6', 'esp32h2'):
        path = which_or_sdk('riscv32-esp-elf-addr2line')
        if path:
            return path
    
    # ARM Cortex-M (nRF, STM32, NXP MCX, etc.)
    if 'arm' in arch_lower or 'cortex' in arch_lower or arch_lower.startswith(('nrf', 'stm32', 'mcx')):
        for name in ('arm-zephyr-eabi-addr2line', 'arm-none-eabi-addr2line'):
            path = which_or_sdk(name)
            if path:
                return path
    
    # Fallback to generic addr2line
    return which_or_sdk('addr2line')


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
    # (only include if they look like code addresses, typically 0x0800xxxx or 0x0000xxxx)
    for reg_match in _ZEPHYR_REG_RE.finditer(text):
        addr = int(reg_match.group(1), 16)
        # Filter out obvious data addresses (very high or very low values)
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


# =============================================================================
# BacktraceDecoder
# =============================================================================

class BacktraceDecoder:
    """Decode backtraces from multiple embedded RTOS/target formats.
    
    Supports:
    - ESP-IDF backtraces (Backtrace:0xADDR:0xSP ...)
    - Zephyr fatal error dumps (E: r15/pc: 0xADDR)
    - GDB backtrace output (#0 0xADDR in func () at file.c:123)
    
    Usage:
        decoder = BacktraceDecoder(elf_path="build/app.elf", arch="esp32c6")
        result = decoder.decode(serial_output_text)
        for entry in result.entries:
            print(f"{entry.address:#010x} -> {entry.file}:{entry.line} ({entry.function})")
    """
    
    def __init__(
        self,
        elf_path: Optional[str] = None,
        arch: str = 'arm',
        toolchain_path: Optional[str] = None,
    ):
        """Initialize BacktraceDecoder.
        
        Args:
            elf_path: Path to ELF file with debug symbols (required for addr2line).
            arch: Architecture hint ('arm', 'xtensa', 'riscv', 'esp32', 'nrf', etc.).
            toolchain_path: Optional explicit path to addr2line binary.
        """
        self.elf_path = elf_path
        self.arch = arch
        self._addr2line = toolchain_path or _get_addr2line_for_arch(arch)
        
        if not self._addr2line:
            logger.warning("addr2line not found for arch=%s (source decoding disabled)", arch)
    
    def detect_format(self, text: str) -> str:
        """Detect backtrace format from text.
        
        Returns:
            'esp-idf', 'zephyr', 'gdb', or 'unknown'.
        """
        if _ESP_BACKTRACE_RE.search(text):
            return 'esp-idf'
        if _ZEPHYR_PC_RE.search(text):
            return 'zephyr'
        if _GDB_FRAME_RE.search(text):
            return 'gdb'
        return 'unknown'
    
    def parse(self, text: str) -> BacktraceResult:
        """Parse backtrace text and extract addresses (without resolving symbols).
        
        Args:
            text: Serial output or crash dump containing backtrace.
        
        Returns:
            BacktraceResult with raw addresses and detected format.
        """
        fmt = self.detect_format(text)
        entries: list[BacktraceEntry] = []
        
        if fmt == 'esp-idf':
            entries = _parse_esp_backtrace(text)
        elif fmt == 'zephyr':
            entries = _parse_zephyr_backtrace(text)
        elif fmt == 'gdb':
            entries = _parse_gdb_backtrace(text)
        
        return BacktraceResult(entries=entries, format=fmt)
    
    def resolve_addresses(self, entries: list[BacktraceEntry]) -> None:
        """Resolve addresses to source locations using addr2line (in-place).
        
        Args:
            entries: List of BacktraceEntry objects to resolve.
        """
        if not self.elf_path or not Path(self.elf_path).exists():
            logger.warning("ELF file not found: %s (cannot resolve addresses)", self.elf_path)
            return
        
        if not self._addr2line:
            logger.warning("addr2line not available (cannot resolve addresses)")
            return
        
        # Batch all addresses for a single addr2line invocation
        addresses = [f"0x{e.address:x}" for e in entries if e.address]
        if not addresses:
            return
        
        try:
            # Run addr2line with -f (function names) and -C (demangle)
            # Format: function\nfile:line for each address
            result = subprocess.run(
                [self._addr2line, '-e', self.elf_path, '-f', '-C'] + addresses,
                capture_output=True,
                text=True,
                timeout=10.0,
            )
            
            if result.returncode != 0:
                logger.warning("addr2line failed: %s", result.stderr)
                return
            
            lines = result.stdout.strip().split('\n')
            # addr2line outputs 2 lines per address: function name, then file:line
            for i, entry in enumerate(entries):
                if not entry.address:
                    continue
                
                idx = i * 2
                if idx + 1 >= len(lines):
                    break
                
                func_line = lines[idx].strip()
                loc_line = lines[idx + 1].strip()
                
                # Parse function name (skip if "??" unknown)
                if func_line and func_line != '??':
                    entry.function = func_line
                
                # Parse file:line (skip if "??:0" unknown)
                if ':' in loc_line and not loc_line.startswith('??'):
                    parts = loc_line.rsplit(':', 1)
                    if len(parts) == 2:
                        entry.file = parts[0]
                        try:
                            entry.line = int(parts[1])
                        except ValueError:
                            pass
        
        except subprocess.TimeoutExpired:
            logger.error("addr2line timed out")
        except Exception as e:
            logger.error("addr2line failed: %s", e)
    
    def decode(self, text: str) -> BacktraceResult:
        """Parse and decode a backtrace from text (parse + resolve in one step).
        
        Args:
            text: Serial output or crash dump containing backtrace.
        
        Returns:
            BacktraceResult with decoded entries.
        """
        result = self.parse(text)
        self.resolve_addresses(result.entries)
        return result
    
    def format_result(self, result: BacktraceResult, show_raw: bool = False) -> str:
        """Format BacktraceResult as human-readable text.
        
        Args:
            result: BacktraceResult to format.
            show_raw: Include raw backtrace lines in output.
        
        Returns:
            Formatted multi-line string.
        """
        lines = []
        lines.append(f"BACKTRACE DECODE ({result.format.upper()})")
        lines.append("=" * 60)
        
        if result.error:
            lines.append(f"ERROR: {result.error}")
            return "\n".join(lines)
        
        if not result.entries:
            lines.append("(no backtrace entries found)")
            return "\n".join(lines)
        
        for i, entry in enumerate(result.entries):
            addr_str = f"0x{entry.address:08x}"
            
            # Format: [#N] 0xADDR -> file:line (function)
            parts = [f"[#{i}]", addr_str]
            
            if entry.file and entry.line:
                parts.append(f"-> {entry.file}:{entry.line}")
                if entry.function:
                    parts.append(f"({entry.function})")
            elif entry.function:
                parts.append(f"-> {entry.function}")
            else:
                parts.append("-> ??")
            
            lines.append("  " + " ".join(parts))
            
            if show_raw and entry.raw_line:
                lines.append(f"    raw: {entry.raw_line}")
        
        lines.append("=" * 60)
        return "\n".join(lines)
