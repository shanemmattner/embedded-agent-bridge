#!/usr/bin/env python3
"""GDB utilities for EAB.

We keep this intentionally minimal for now:
- run one-shot GDB command batches against an OpenOCD server

This provides a "GDB through EAB" workflow without requiring a persistent MI wrapper yet.
"""

from __future__ import annotations

import shutil
import subprocess
from dataclasses import dataclass
from pathlib import Path
from typing import Optional


@dataclass(frozen=True)
class GDBResult:
    success: bool
    stdout: str
    stderr: str
    returncode: int
    gdb_path: str


def _default_gdb_for_chip(chip: str) -> Optional[str]:
    chip = chip.lower()
    if chip in ("esp32s3", "esp32s2", "esp32"):
        # ESP32/ESP32S2/ESP32S3 use Xtensa.
        for name in ("xtensa-esp32s3-elf-gdb", "xtensa-esp32s2-elf-gdb", "xtensa-esp32-elf-gdb"):
            p = shutil.which(name)
            if p:
                return p
    if chip in ("esp32c3", "esp32c6", "esp32h2"):
        p = shutil.which("riscv32-esp-elf-gdb")
        if p:
            return p
    # STM32 ARM Cortex-M
    if chip.startswith("stm32"):
        for name in ("arm-none-eabi-gdb", "gdb-multiarch"):
            p = shutil.which(name)
            if p:
                return p
    # nRF / Zephyr ARM Cortex-M
    if chip.startswith("nrf") or chip.startswith("zephyr"):
        for name in ("arm-none-eabi-gdb", "gdb-multiarch"):
            p = shutil.which(name)
            if p:
                return p
    # NXP MCX (Cortex-M33)
    if chip.startswith("mcx"):
        for name in ("arm-none-eabi-gdb", "gdb-multiarch"):
            p = shutil.which(name)
            if p:
                return p
    # Fall back to system gdb if present.
    return shutil.which("gdb")


def run_gdb_batch(
    *,
    chip: str,
    target: str = "localhost:3333",
    elf: Optional[str] = None,
    gdb_path: Optional[str] = None,
    commands: list[str],
    timeout_s: float = 60.0,
) -> GDBResult:
    gdb = gdb_path or _default_gdb_for_chip(chip) or "gdb"
    argv = [gdb, "-q"]
    if elf:
        argv.append(str(Path(elf)))
    argv += ["-ex", f"target remote {target}"]
    for cmd in commands:
        argv += ["-ex", cmd]
    argv += ["-ex", "detach", "-ex", "quit"]

    proc = subprocess.run(
        argv, capture_output=True, text=True, timeout=timeout_s,
        start_new_session=True,
    )
    return GDBResult(
        success=proc.returncode == 0,
        stdout=proc.stdout,
        stderr=proc.stderr,
        returncode=proc.returncode,
        gdb_path=gdb,
    )

