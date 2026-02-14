"""Backtrace decoding commands for eabctl."""

from __future__ import annotations

import sys
from typing import Optional

from eab.backtrace import BacktraceDecoder
from eab.cli.helpers import _print


def cmd_decode_backtrace(
    *,
    elf: str,
    text: Optional[str],
    arch: str,
    toolchain: Optional[str],
    show_raw: bool,
    json_mode: bool,
) -> int:
    """Decode backtrace addresses to source locations using addr2line.
    
    Supports multiple backtrace formats:
    - ESP-IDF: Backtrace:0x400d1234:0x3ffb5678 0x400d5678:0x3ffb9abc
    - Zephyr: E: r15/pc: 0x0000xxxx or E: Faulting instruction address (r15/pc): 0x0000xxxx
    - GDB: #0  0x0000xxxx in func_name () at file.c:123
    
    Args:
        elf: Path to ELF file with debug symbols.
        text: Backtrace text to decode (if None, reads from stdin).
        arch: Architecture hint (arm, xtensa, riscv, esp32, nrf, stm32, etc.).
        toolchain: Optional explicit path to addr2line binary.
        show_raw: Include raw backtrace lines in human-readable output.
        json_mode: Emit machine-parseable JSON output.
    
    Returns:
        Exit code: 0 on success, 1 on error.
    """
    # Read input text
    if text is None:
        input_text = sys.stdin.read()
    else:
        input_text = text
    
    if not input_text.strip():
        if json_mode:
            _print({"error": "no input text provided"}, json_mode=True)
        else:
            print("ERROR: no input text provided (use --text or pipe to stdin)")
        return 1
    
    # Create decoder
    decoder = BacktraceDecoder(
        elf_path=elf,
        arch=arch,
        toolchain_path=toolchain,
    )
    
    # Decode backtrace
    result = decoder.decode(input_text)
    
    if json_mode:
        # JSON output
        json_out = {
            "schema_version": 1,
            "format": result.format,
            "entries": [
                {
                    "address": f"0x{e.address:08x}",
                    "pc_address": f"0x{e.pc_address:08x}" if e.pc_address else None,
                    "function": e.function,
                    "file": e.file,
                    "line": e.line,
                    "raw_line": e.raw_line,
                }
                for e in result.entries
            ],
        }
        if result.error:
            json_out["error"] = result.error
        
        _print(json_out, json_mode=True)
    else:
        # Human-readable output
        output = decoder.format_result(result, show_raw=show_raw)
        print(output)
    
    return 0 if not result.error else 1
