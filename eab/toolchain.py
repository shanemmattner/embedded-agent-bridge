"""Toolchain binary resolution for cross-platform SDK support.

Searches PATH and known SDK directories (Zephyr SDK, ESP-IDF) for
toolchain binaries like GDB, nm, objdump that may not be on PATH.
"""

from __future__ import annotations

import shutil
from pathlib import Path
from typing import Optional


def _find_in_sdk_dirs(name: str) -> Optional[str]:
    """Search for a tool in known SDK directories beyond PATH.

    Checks Zephyr SDK and ESP-IDF toolchain install locations that may
    not be on the user's PATH.

    Args:
        name: Binary name to search for (e.g., arm-zephyr-eabi-gdb-py).

    Returns:
        Absolute path to the binary, or None if not found.
    """
    home = Path.home()
    # Zephyr SDK (glob for version-numbered dirs)
    for sdk_dir in sorted(home.glob("zephyr-sdk-*"), reverse=True):
        candidate = sdk_dir / "arm-zephyr-eabi" / "bin" / name
        if candidate.is_file():
            return str(candidate)
    # ESP-IDF RISC-V GDB
    for tool_dir in sorted(
        home.glob(".espressif/tools/riscv32-esp-elf-gdb/*/riscv32-esp-elf-gdb/bin"),
        reverse=True,
    ):
        candidate = tool_dir / name
        if candidate.is_file():
            return str(candidate)
    # ESP-IDF Xtensa GDB
    for tool_dir in sorted(
        home.glob(".espressif/tools/xtensa-*-elf-gdb/*/xtensa-*-elf-gdb/bin"),
        reverse=True,
    ):
        candidate = tool_dir / name
        if candidate.is_file():
            return str(candidate)
    return None


def which_or_sdk(name: str) -> Optional[str]:
    """Find a toolchain binary on PATH or in known SDK directories.

    Tries ``shutil.which`` first, then searches Zephyr SDK and ESP-IDF
    install directories for the binary.

    Args:
        name: Binary name to search for.

    Returns:
        Absolute path to the binary, or None if not found.
    """
    return shutil.which(name) or _find_in_sdk_dirs(name)
