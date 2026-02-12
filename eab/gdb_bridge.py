#!/usr/bin/env python3
"""GDB utilities for EAB.

We keep this intentionally minimal for now:
- run one-shot GDB command batches against an OpenOCD server
- run GDB Python scripts and capture JSON results

This provides a "GDB through EAB" workflow without requiring a persistent MI wrapper yet.
"""

from __future__ import annotations

import json
import shutil
import subprocess
import tempfile
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Optional


@dataclass(frozen=True)
class GDBResult:
    success: bool
    stdout: str
    stderr: str
    returncode: int
    gdb_path: str
    json_result: Optional[dict[str, Any]] = None


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

    proc = subprocess.run(argv, capture_output=True, text=True, timeout=timeout_s)
    return GDBResult(
        success=proc.returncode == 0,
        stdout=proc.stdout,
        stderr=proc.stderr,
        returncode=proc.returncode,
        gdb_path=gdb,
    )


def run_gdb_python(
    *,
    chip: str,
    script_path: str,
    target: str = "localhost:3333",
    elf: Optional[str] = None,
    gdb_path: Optional[str] = None,
    timeout_s: float = 60.0,
) -> GDBResult:
    """Execute a GDB Python script and capture JSON results.

    The Python script should write its results to a JSON file whose path
    is provided via the GDB convenience variable $result_file.

    Example Python script:
        ```python
        import gdb
        import json
        
        result_file = gdb.convenience_variable("result_file")
        result = {"registers": {}, "status": "ok"}
        with open(result_file, "w") as f:
            json.dump(result, f)
        ```

    Args:
        chip: Chip type for GDB selection (e.g., "nrf5340", "esp32s3")
        script_path: Path to the Python script to execute
        target: GDB remote target (default: "localhost:3333")
        elf: Optional path to ELF file for symbols
        gdb_path: Optional explicit GDB executable path
        timeout_s: Timeout in seconds (default: 60.0)

    Returns:
        GDBResult with json_result populated if the script wrote valid JSON

    Raises:
        FileNotFoundError: If script_path does not exist
        subprocess.TimeoutExpired: If execution exceeds timeout_s
    """
    script = Path(script_path)
    if not script.exists():
        raise FileNotFoundError(f"GDB Python script not found: {script_path}")

    gdb = gdb_path or _default_gdb_for_chip(chip) or "gdb"
    
    # Create temp file for JSON results
    with tempfile.NamedTemporaryFile(mode="w", suffix=".json", delete=False) as tmp:
        result_file = tmp.name

    try:
        argv = [gdb, "-q", "-batch"]
        if elf:
            argv.append(str(Path(elf)))
        argv += ["-ex", f"target remote {target}"]
        # Set convenience variable for script to access
        argv += ["-ex", f"set $result_file = \"{result_file}\""]
        # Execute the Python script
        argv += ["-x", str(script)]
        argv += ["-ex", "detach", "-ex", "quit"]

        proc = subprocess.run(argv, capture_output=True, text=True, timeout=timeout_s)
        
        # Try to read JSON result
        json_result = None
        result_path = Path(result_file)
        if result_path.exists() and result_path.stat().st_size > 0:
            try:
                with open(result_path, "r") as f:
                    json_result = json.load(f)
            except (json.JSONDecodeError, IOError):
                # Script didn't write valid JSON, continue without it
                pass

        return GDBResult(
            success=proc.returncode == 0,
            stdout=proc.stdout,
            stderr=proc.stderr,
            returncode=proc.returncode,
            gdb_path=gdb,
            json_result=json_result,
        )
    finally:
        # Clean up temp file
        try:
            Path(result_file).unlink(missing_ok=True)
        except Exception:
            pass

