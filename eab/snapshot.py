"""Snapshot / coredump pipeline for embedded targets.

Orchestrates a full ELF core capture from a live Cortex-M target:

    capture_snapshot()
        -> _parse_elf_load_segments()  – find RAM ranges from firmware ELF
        -> _read_registers()           – halt target, read all Cortex-M regs
        -> _read_memory_regions()      – dump each RAM range via GDB Python
        -> _write_elf_core()           – produce an ELF32 ET_CORE file
        -> return SnapshotResult
"""

from __future__ import annotations

import logging
import re
import struct
import tempfile
from dataclasses import dataclass, field
from datetime import datetime
from pathlib import Path
from typing import Optional

# ---------------------------------------------------------------------------
# pyelftools – optional, same guard pattern as eab/cli/dwt/_helpers.py
# ---------------------------------------------------------------------------
try:
    from elftools.elf.elffile import ELFFile

    _PYELFTOOLS_AVAILABLE = True
except ImportError:
    _PYELFTOOLS_AVAILABLE = False

from eab.gdb_bridge import generate_memory_dump_script, run_gdb_batch, run_gdb_python

logger = logging.getLogger(__name__)

# ---------------------------------------------------------------------------
# ELF / Linux ABI constants
# ---------------------------------------------------------------------------
_ET_CORE = 4
_EM_ARM = 40
_EV_CURRENT = 1
_PT_LOAD = 1
_PT_NOTE = 4
_PF_R = 0x4
_PF_W = 0x2
_NT_PRSTATUS = 1

# ARM elf_prstatus total descriptor size (see plan for layout breakdown)
_PRSTATUS_DESC_SIZE = 148

# ---------------------------------------------------------------------------
# GDB register parsing – same regex as fault_analyzer._parse_gdb_registers
# ---------------------------------------------------------------------------
_GDB_REG_RE = re.compile(r"^(\w+)\s+(0x[0-9a-fA-F]+)\s", re.MULTILINE)
# Matches output of `p/x $<reg>`, e.g. "$1 = 0x0"
_GDB_PRINT_RE = re.compile(r"\$\d+\s*=\s*(0x[0-9a-fA-F]+)")


# =============================================================================
# Public data structures
# =============================================================================


@dataclass(frozen=True)
class MemoryRegion:
    """A contiguous range of target memory to include in the snapshot.

    Attributes:
        start: Virtual start address of the region.
        size:  Size of the region in bytes.
    """

    start: int
    size: int


@dataclass
class SnapshotResult:
    """Result produced by capture_snapshot().

    Attributes:
        output_path: Filesystem path of the written ELF core file.
        regions:     Memory regions that were captured.
        registers:   Register name → value mapping captured from the target.
        total_size:  Total bytes written to the core file.
        timestamp:   UTC timestamp when the snapshot was taken.
    """

    output_path: str
    regions: list[MemoryRegion] = field(default_factory=list)
    registers: dict[str, int] = field(default_factory=dict)
    total_size: int = 0
    timestamp: datetime = field(default_factory=datetime.utcnow)


# =============================================================================
# Private helpers
# =============================================================================


def _parse_elf_load_segments(elf_path: str) -> list[MemoryRegion]:
    """Extract LOAD segments from a firmware ELF file.

    Uses pyelftools to iterate PT_LOAD program headers and return each
    non-empty segment as a MemoryRegion sorted by start address.

    Args:
        elf_path: Path to the ELF firmware file.

    Returns:
        List of MemoryRegion objects, sorted by start address.

    Raises:
        ValueError: If elf_path does not exist.
        ImportError: If pyelftools is not installed.
    """
    if not _PYELFTOOLS_AVAILABLE:
        raise ImportError(
            "pyelftools is required for ELF parsing. "
            "Install it with: pip install pyelftools"
        )

    path = Path(elf_path)
    if not path.exists():
        raise ValueError(f"ELF file not found: {elf_path}")

    regions: list[MemoryRegion] = []
    with open(path, "rb") as f:
        elf = ELFFile(f)
        for seg in elf.iter_segments():
            if seg["p_type"] == "PT_LOAD" and seg["p_memsz"] > 0:
                regions.append(
                    MemoryRegion(start=seg["p_vaddr"], size=seg["p_memsz"])
                )

    return sorted(regions, key=lambda r: r.start)


def _parse_gdb_registers(output: str) -> dict[str, int]:
    """Parse ``info registers`` GDB output into a name→value dict."""
    regs: dict[str, int] = {}
    for m in _GDB_REG_RE.finditer(output):
        try:
            regs[m.group(1)] = int(m.group(2), 16)
        except ValueError:
            pass
    return regs


def _read_registers(
    chip: str,
    target: str,
    elf: Optional[str],
) -> dict[str, int]:
    """Read Cortex-M registers from the target via GDB.

    Captures R0–R15, xPSR, MSP, PSP, and the special Cortex-M system
    registers CONTROL, FAULTMASK, BASEPRI, and PRIMASK.

    Args:
        chip:   Chip family for GDB binary selection (e.g. "nrf5340").
        target: GDB remote target string (e.g. "localhost:3333").
        elf:    Optional path to the ELF file for symbol resolution.

    Returns:
        Dict mapping register names to integer values.  Missing registers
        (e.g. when the GDB binary does not support a special register) are
        simply absent from the returned dict rather than raising an error.
    """
    special_regs = ["control", "faultmask", "basepri", "primask"]
    commands = [
        "monitor halt",
        "info registers",
        "p/x $msp",
        "p/x $psp",
    ] + [f"p/x ${r}" for r in special_regs]

    result = run_gdb_batch(
        chip=chip,
        target=target,
        elf=elf,
        commands=commands,
    )

    if not result.success:
        logger.warning(
            "GDB register read returned non-zero exit code %d; "
            "register data may be incomplete.",
            result.returncode,
        )

    regs = _parse_gdb_registers(result.stdout)

    # Parse p/x outputs for MSP, PSP, and special registers in order
    print_names = ["msp", "psp"] + special_regs
    print_vals = _GDB_PRINT_RE.findall(result.stdout)
    for name, hex_val in zip(print_names, print_vals):
        try:
            regs[name] = int(hex_val, 16)
        except ValueError:
            pass

    return regs


def _read_memory_regions(
    chip: str,
    target: str,
    regions: list[MemoryRegion],
    elf: Optional[str],
) -> list[tuple[MemoryRegion, bytes]]:
    """Dump each memory region from the target using GDB Python scripting.

    For each region a temporary binary file is used as the dump destination.
    Regions that cannot be read (e.g. ROM or unmapped) are replaced with
    zero-filled bytes and a warning is logged.

    Args:
        chip:    Chip family for GDB binary selection.
        target:  GDB remote target string.
        regions: Memory regions to dump.
        elf:     Optional ELF path for symbol resolution.

    Returns:
        List of (MemoryRegion, bytes) tuples in the same order as *regions*.
    """
    results: list[tuple[MemoryRegion, bytes]] = []

    for region in regions:
        dump_path = ""
        try:
            with tempfile.NamedTemporaryFile(
                suffix=".bin", delete=False
            ) as tmp:
                dump_path = tmp.name

            script_content = generate_memory_dump_script(
                region.start, region.size, dump_path
            )

            with tempfile.NamedTemporaryFile(
                mode="w", suffix=".py", delete=False
            ) as script_tmp:
                script_tmp.write(script_content)
                script_path = script_tmp.name

            try:
                gdb_result = run_gdb_python(
                    chip=chip,
                    script_path=script_path,
                    target=target,
                    elf=elf,
                )
            finally:
                Path(script_path).unlink(missing_ok=True)

            dump_file = Path(dump_path)
            if (
                gdb_result.success
                and dump_file.exists()
                and dump_file.stat().st_size > 0
            ):
                data = dump_file.read_bytes()
                # Pad or trim to exact region size
                if len(data) < region.size:
                    data = data + b"\x00" * (region.size - len(data))
                else:
                    data = data[: region.size]
            else:
                logger.warning(
                    "Failed to read memory region 0x%08x+%d "
                    "(returncode=%d); substituting zeros.",
                    region.start,
                    region.size,
                    gdb_result.returncode,
                )
                data = b"\x00" * region.size

        except Exception as exc:  # pragma: no cover – hardware-specific paths
            logger.warning(
                "Unexpected error reading region 0x%08x+%d: %s; substituting zeros.",
                region.start,
                region.size,
                exc,
            )
            data = b"\x00" * region.size
        finally:
            if dump_path:
                Path(dump_path).unlink(missing_ok=True)

        results.append((region, data))

    return results


def _build_prstatus_note(registers: dict[str, int]) -> bytes:
    """Serialise an NT_PRSTATUS note for the given Cortex-M register set.

    Args:
        registers: Register name → value mapping (as returned by
            _read_registers).  Missing entries default to 0.

    Returns:
        Raw bytes for the complete ELF note (header + name + descriptor).
    """

    def _r(name: str) -> int:
        return registers.get(name, 0)

    # ARM elf_gregset_t: r0–r15, orig_r0 (0), cpsr/xpsr – 18 × 4 bytes = 72
    gr = [
        _r("r0"), _r("r1"), _r("r2"), _r("r3"),
        _r("r4"), _r("r5"), _r("r6"), _r("r7"),
        _r("r8"), _r("r9"), _r("r10"), _r("r11"),
        _r("r12"),
        _r("sp") if "sp" in registers else _r("r13"),   # SP / r13
        _r("lr") if "lr" in registers else _r("r14"),   # LR / r14
        _r("pc") if "pc" in registers else _r("r15"),   # PC / r15
        0,                                               # orig_r0 (unused)
        _r("xpsr") if "xpsr" in registers else _r("cpsr"),  # CPSR
    ]

    # elf_prstatus descriptor (148 bytes):
    #   pr_info (3×i=12), pr_cursig (h=2), pad (H=2),
    #   pr_sigpend/hold (2×I=8), pr_pid/ppid/pgrp/sid (4×I=16),
    #   pr_utime/stime/cutime/cstime (4×2I=32), pr_reg (18×I=72),
    #   pr_fpvalid (I=4)
    desc = struct.pack(
        "<3ihH2I4I8I18II",
        0, 0, 0,           # pr_info.si_signo/code/errno
        5,                 # pr_cursig  (SIGTRAP = 5, conventional for breakpoint)
        0,                 # padding
        0, 0,              # pr_sigpend, pr_sighold
        0, 0, 0, 0,        # pr_pid, pr_ppid, pr_pgrp, pr_sid
        0, 0,              # pr_utime (tv_sec, tv_usec)
        0, 0,              # pr_stime
        0, 0,              # pr_cutime
        0, 0,              # pr_cstime
        *gr,               # pr_reg (18 × uint32)
        0,                 # pr_fpvalid
    )
    assert len(desc) == _PRSTATUS_DESC_SIZE, (
        f"prstatus descriptor is {len(desc)} bytes, expected {_PRSTATUS_DESC_SIZE}"
    )

    # Note name: "CORE\0" padded to 4-byte boundary → 8 bytes
    name_raw = b"CORE\x00"
    name_padded = name_raw + b"\x00" * (
        (4 - len(name_raw) % 4) % 4
    )  # → 8 bytes

    note_header = struct.pack(
        "<III",
        len(name_raw),       # namesz = 5
        len(desc),           # descsz = 148
        _NT_PRSTATUS,        # type   = 1
    )
    return note_header + name_padded + desc


def _write_elf_core(
    output_path: str,
    regions_data: list[tuple[MemoryRegion, bytes]],
    registers: dict[str, int],
) -> int:
    """Write an ELF32 core file loadable by arm-none-eabi-gdb.

    Layout:
      - ELF32 header (52 bytes)
      - Program headers: 1 PT_NOTE + N PT_LOAD  (each 32 bytes)
      - NT_PRSTATUS note data
      - Memory region data (one blob per PT_LOAD)

    Args:
        output_path:  Destination file path.
        regions_data: List of (MemoryRegion, bytes) pairs from
            _read_memory_regions.
        registers:    Cortex-M register dict from _read_registers.

    Returns:
        Total number of bytes written to *output_path*.

    Raises:
        ValueError: If output_path cannot be created/written.
    """
    n_load = len(regions_data)
    n_phdrs = 1 + n_load  # PT_NOTE + N × PT_LOAD

    elf_hdr_size = 52
    phdr_size = 32

    note_bytes = _build_prstatus_note(registers)
    note_offset = elf_hdr_size + n_phdrs * phdr_size
    note_filesz = len(note_bytes)

    # Compute PT_LOAD offsets
    load_offset = note_offset + note_filesz
    offsets: list[int] = []
    for _, data in regions_data:
        offsets.append(load_offset)
        load_offset += len(data)

    total_size = load_offset  # final cursor position

    # --- ELF header ---
    e_ident = (
        b"\x7fELF"      # magic
        b"\x01"         # EI_CLASS  = ELFCLASS32
        b"\x01"         # EI_DATA   = ELFDATA2LSB (little-endian)
        b"\x01"         # EI_VERSION
        b"\x00"         # EI_OSABI
        + b"\x00" * 8   # padding
    )
    elf_header = e_ident + struct.pack(
        "<HHIIIIIHHHHHH",
        _ET_CORE,           # e_type
        _EM_ARM,            # e_machine
        _EV_CURRENT,        # e_version
        0,                  # e_entry
        elf_hdr_size,       # e_phoff (program headers immediately follow)
        0,                  # e_shoff (no section headers)
        0x05000000,         # e_flags (ARM EABI version 5)
        elf_hdr_size,       # e_ehsize
        phdr_size,          # e_phentsize
        n_phdrs,            # e_phnum
        40,                 # e_shentsize (conventional even when shnum=0)
        0,                  # e_shnum
        0,                  # e_shstrndx
    )
    assert len(elf_header) == elf_hdr_size

    # --- PT_NOTE program header ---
    ph_note = struct.pack(
        "<IIIIIIII",
        _PT_NOTE,           # p_type
        note_offset,        # p_offset
        0,                  # p_vaddr
        0,                  # p_paddr
        note_filesz,        # p_filesz
        note_filesz,        # p_memsz
        0,                  # p_flags
        4,                  # p_align
    )

    # --- PT_LOAD program headers ---
    ph_loads = b""
    for (region, data), off in zip(regions_data, offsets):
        ph_loads += struct.pack(
            "<IIIIIIII",
            _PT_LOAD,                   # p_type
            off,                        # p_offset
            region.start,               # p_vaddr
            region.start,               # p_paddr
            len(data),                  # p_filesz
            region.size,                # p_memsz
            _PF_R | _PF_W,             # p_flags
            4,                          # p_align
        )

    # --- Write file ---
    output = Path(output_path)
    try:
        output.parent.mkdir(parents=True, exist_ok=True)
        with output.open("wb") as f:
            f.write(elf_header)
            f.write(ph_note)
            f.write(ph_loads)
            f.write(note_bytes)
            for _, data in regions_data:
                f.write(data)
    except OSError as exc:
        raise ValueError(f"Cannot write core file to {output_path}: {exc}") from exc

    return total_size


# =============================================================================
# Public API
# =============================================================================


def capture_snapshot(
    device: str,
    elf_path: str,
    output_path: str,
    *,
    chip: str = "nrf5340",
    target: str = "localhost:3333",
) -> SnapshotResult:
    """Capture a full memory snapshot from a live embedded target.

    Orchestrates the complete pipeline:
    1. Parse LOAD segments from the firmware ELF to identify RAM ranges.
    2. Halt the target and read all Cortex-M registers via GDB.
    3. Dump each RAM range to a temporary file via GDB Python scripting.
    4. Write an ELF32 ``ET_CORE`` file loadable by ``arm-none-eabi-gdb``.

    Example::

        result = capture_snapshot(
            "NRF5340_XXAA_APP",
            "/build/zephyr/zephyr.elf",
            "/tmp/snapshot.core",
            chip="nrf5340",
        )
        print(f"Core file: {result.output_path} ({result.total_size} bytes)")

    Args:
        device:      J-Link / probe device identifier
            (e.g. ``"NRF5340_XXAA_APP"``).
        elf_path:    Path to the firmware ELF file used to identify memory
            regions.  Must exist.
        output_path: Destination path for the generated ELF core file.
        chip:        Chip family used for GDB binary selection
            (default: ``"nrf5340"``).
        target:      GDB remote target string
            (default: ``"localhost:3333"``).

    Returns:
        :class:`SnapshotResult` containing the output path, captured memory
        regions, register values, total file size, and timestamp.

    Raises:
        ValueError: If *elf_path* does not exist or *output_path* cannot be
            written.
        ImportError: If pyelftools is not installed.
    """
    elf = Path(elf_path)
    if not elf.exists():
        raise ValueError(f"ELF file not found: {elf_path}")

    logger.info(
        "capture_snapshot: device=%s chip=%s target=%s elf=%s -> %s",
        device,
        chip,
        target,
        elf_path,
        output_path,
    )

    # 1 – Identify RAM ranges from the firmware ELF
    regions = _parse_elf_load_segments(elf_path)
    logger.debug("Found %d LOAD segment(s)", len(regions))

    # 2 – Read Cortex-M registers
    registers = _read_registers(chip, target, elf_path)
    logger.debug("Read %d register(s)", len(registers))

    # 3 – Dump memory regions
    regions_data = _read_memory_regions(chip, target, regions, elf_path)

    # 4 – Write ELF core file
    total_size = _write_elf_core(output_path, regions_data, registers)
    logger.info("Core file written: %s (%d bytes)", output_path, total_size)

    return SnapshotResult(
        output_path=output_path,
        regions=regions,
        registers=registers,
        total_size=total_size,
        timestamp=datetime.utcnow(),
    )
