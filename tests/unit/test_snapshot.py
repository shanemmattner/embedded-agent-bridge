"""Unit tests for eab/snapshot.py — no hardware required.

Tests cover:
  - ELF LOAD segment parsing
  - Cortex-M register reading via mocked GDB bridge
  - Memory region reading via mocked GDB bridge
  - ELF core file format validation (ET_CORE, PT_LOAD, PT_NOTE)
  - SnapshotResult metadata
  - Edge cases: missing ELF, GDB failure propagation
"""

from __future__ import annotations

import json
import struct
from pathlib import Path
from typing import Any
from unittest.mock import MagicMock, patch

import pytest

from eab.gdb_bridge import GDBResult
from eab.snapshot import (
    MemoryRegion,
    SnapshotResult,
    _parse_elf_load_segments,
    _read_registers,
    capture_snapshot,
)

# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

# ELF32 LE constants
_ELFMAG = b"\x7fELF"
_ELFCLASS32 = 1
_ELFDATA2LSB = 1
_ET_EXEC = 2
_EM_ARM = 40
_PT_LOAD = 1
_PT_NOTE = 4
_ET_CORE = 4


def _make_minimal_elf(tmp_path: Path, regions: list[tuple[int, int]]) -> Path:
    """Build a minimal ELF32 LE file with one PT_LOAD segment per region.

    Args:
        tmp_path: Directory to write the file into.
        regions:  List of (vaddr, memsz) tuples for each LOAD segment.

    Returns:
        Path to the written ELF file.
    """
    n_phdrs = len(regions)
    elf_hdr_size = 52
    phdr_size = 32

    e_ident = _ELFMAG + bytes([_ELFCLASS32, _ELFDATA2LSB, 1, 0]) + b"\x00" * 8
    elf_header = e_ident + struct.pack(
        "<HHIIIIIHHHHHH",
        _ET_EXEC,  # e_type
        _EM_ARM,  # e_machine
        1,  # e_version
        0,  # e_entry
        elf_hdr_size,  # e_phoff
        0,  # e_shoff
        0,  # e_flags
        elf_hdr_size,  # e_ehsize
        phdr_size,  # e_phentsize
        n_phdrs,  # e_phnum
        40,  # e_shentsize
        0,  # e_shnum
        0,  # e_shstrndx
    )
    assert len(elf_header) == elf_hdr_size

    # Dummy data offset after headers
    data_offset = elf_hdr_size + n_phdrs * phdr_size
    phdrs = b""
    for vaddr, memsz in regions:
        phdrs += struct.pack(
            "<IIIIIIII",
            _PT_LOAD,  # p_type
            data_offset,  # p_offset
            vaddr,  # p_vaddr
            vaddr,  # p_paddr
            memsz,  # p_filesz
            memsz,  # p_memsz
            0x6,  # p_flags (RW)
            4,  # p_align
        )
        data_offset += memsz

    # Minimal dummy region data (all zeros)
    region_data = b"\x00" * sum(s for _, s in regions)

    elf_path = tmp_path / "test.elf"
    elf_path.write_bytes(elf_header + phdrs + region_data)
    return elf_path


def _make_gdb_reg_output(regs: dict[str, int]) -> str:
    """Build a fake ``info registers`` + ``p/x`` GDB stdout string."""
    lines: list[str] = []
    # info registers format: "name   0xVALUE   decimal"
    info_reg_names = [
        "r0",
        "r1",
        "r2",
        "r3",
        "r4",
        "r5",
        "r6",
        "r7",
        "r8",
        "r9",
        "r10",
        "r11",
        "r12",
        "sp",
        "lr",
        "pc",
        "xpsr",
    ]
    for name in info_reg_names:
        val = regs.get(name, 0)
        lines.append(f"{name}            0x{val:08x}   {val}")
    # p/x outputs for msp, psp, control, faultmask, basepri, primask
    print_names = ["msp", "psp", "control", "faultmask", "basepri", "primask"]
    for i, name in enumerate(print_names, start=1):
        val = regs.get(name, 0)
        lines.append(f"${i} = 0x{val:08x}")
    return "\n".join(lines) + "\n"


def _make_success_gdb_result(stdout: str = "") -> GDBResult:
    return GDBResult(
        success=True,
        stdout=stdout,
        stderr="",
        returncode=0,
        gdb_path="mock-gdb",
    )


def _make_failure_gdb_result() -> GDBResult:
    return GDBResult(
        success=False,
        stdout="",
        stderr="error",
        returncode=1,
        gdb_path="mock-gdb",
    )


# ---------------------------------------------------------------------------
# Helper for mocking memory region reads
# ---------------------------------------------------------------------------


class _MemoryDumpMocker:
    """Captures dump_path from generate_memory_dump_script and writes test data.

    Usage::
        mocker = _MemoryDumpMocker({0x20000000: b"\\xAB" * 256})
        with patch("eab.snapshot.generate_memory_dump_script",
                   side_effect=mocker.gen_script), \\
             patch("eab.snapshot.run_gdb_python",
                   side_effect=mocker.run_python):
            ...
    """

    def __init__(self, memory_map: dict[int, bytes]) -> None:
        self.memory_map = memory_map
        self._pending_dump_path: str = ""
        self._pending_addr: int = 0

    def gen_script(self, addr: int, size: int, dump_path: str) -> str:
        self._pending_addr = addr
        self._pending_dump_path = dump_path
        return "# mock script"

    def run_python(self, chip: str, script_path: str, target: str, elf: Any = None) -> GDBResult:
        data = self.memory_map.get(self._pending_addr)
        if data is not None and self._pending_dump_path:
            Path(self._pending_dump_path).write_bytes(data)
        return _make_success_gdb_result()


# ---------------------------------------------------------------------------
# Test classes
# ---------------------------------------------------------------------------


class TestElfParsing:
    """Verify that LOAD segments are correctly extracted from ELF files."""

    def test_single_load_segment(self, tmp_path: Path) -> None:
        elf_path = _make_minimal_elf(tmp_path, [(0x20000000, 0x10000)])
        regions = _parse_elf_load_segments(str(elf_path))
        assert len(regions) == 1
        assert regions[0].start == 0x20000000
        assert regions[0].size == 0x10000

    def test_multiple_load_segments(self, tmp_path: Path) -> None:
        input_regions = [(0x20000000, 0x8000), (0x20010000, 0x4000)]
        elf_path = _make_minimal_elf(tmp_path, input_regions)
        regions = _parse_elf_load_segments(str(elf_path))
        assert len(regions) == 2
        assert regions[0].start == 0x20000000
        assert regions[0].size == 0x8000
        assert regions[1].start == 0x20010000
        assert regions[1].size == 0x4000

    def test_segments_sorted_by_address(self, tmp_path: Path) -> None:
        # Insert in reverse order; should come out sorted ascending
        input_regions = [(0x20010000, 0x2000), (0x20000000, 0x1000)]
        elf_path = _make_minimal_elf(tmp_path, input_regions)
        regions = _parse_elf_load_segments(str(elf_path))
        assert regions[0].start < regions[1].start

    def test_returns_memory_region_objects(self, tmp_path: Path) -> None:
        elf_path = _make_minimal_elf(tmp_path, [(0x20000000, 512)])
        regions = _parse_elf_load_segments(str(elf_path))
        assert all(isinstance(r, MemoryRegion) for r in regions)

    def test_missing_elf_raises_value_error(self, tmp_path: Path) -> None:
        with pytest.raises(ValueError, match="not found"):
            _parse_elf_load_segments(str(tmp_path / "nonexistent.elf"))


class TestRegisterReading:
    """Verify all expected Cortex-M registers are captured via mocked GDB."""

    _ALL_REGS = {
        "r0": 0x00000001,
        "r1": 0x00000002,
        "r2": 0x00000003,
        "r3": 0x00000004,
        "r4": 0x00000005,
        "r5": 0x00000006,
        "r6": 0x00000007,
        "r7": 0x00000008,
        "r8": 0x00000009,
        "r9": 0x0000000A,
        "r10": 0x0000000B,
        "r11": 0x0000000C,
        "r12": 0x0000000D,
        "sp": 0x20008000,  # r13
        "lr": 0xFFFFFFFF,  # r14
        "pc": 0x00080042,  # r15
        "xpsr": 0x61000000,
        "msp": 0x20008000,
        "psp": 0x20006000,
        "control": 0x00000002,
        "faultmask": 0x00000000,
        "basepri": 0x00000000,
        "primask": 0x00000001,
    }

    def test_all_cortex_m_registers_captured(self) -> None:
        stdout = _make_gdb_reg_output(self._ALL_REGS)
        mock_result = _make_success_gdb_result(stdout)

        with patch("eab.snapshot.run_gdb_batch", return_value=mock_result):
            regs = _read_registers("nrf5340", "localhost:3333", None)

        expected_names = {
            "r0",
            "r1",
            "r2",
            "r3",
            "r4",
            "r5",
            "r6",
            "r7",
            "r8",
            "r9",
            "r10",
            "r11",
            "r12",
            "msp",
            "psp",
            "control",
            "faultmask",
            "basepri",
            "primask",
        }
        for name in expected_names:
            assert name in regs, f"Register '{name}' missing from result"

    def test_register_values_are_correct(self) -> None:
        stdout = _make_gdb_reg_output(self._ALL_REGS)
        mock_result = _make_success_gdb_result(stdout)

        with patch("eab.snapshot.run_gdb_batch", return_value=mock_result):
            regs = _read_registers("nrf5340", "localhost:3333", None)

        assert regs["r0"] == 0x00000001
        assert regs["msp"] == 0x20008000
        assert regs["primask"] == 0x00000001
        assert regs["xpsr"] == 0x61000000

    def test_gdb_called_with_monitor_halt(self) -> None:
        mock_result = _make_success_gdb_result(_make_gdb_reg_output({}))
        with patch("eab.snapshot.run_gdb_batch", return_value=mock_result) as mock_gdb:
            _read_registers("nrf5340", "localhost:3333", None)

        call_kwargs = mock_gdb.call_args
        commands = call_kwargs.kwargs.get("commands") or call_kwargs.args[3]
        assert any("monitor halt" in c for c in commands)


class TestMemoryReading:
    """Verify memory regions are read with correct addresses and data."""

    def test_single_region_data_matches(self, tmp_path: Path) -> None:
        elf_path = _make_minimal_elf(tmp_path, [(0x20000000, 256)])
        expected = b"\xab" * 256
        memory_map = {0x20000000: expected}
        mocker = _MemoryDumpMocker(memory_map)
        reg_stdout = _make_gdb_reg_output({})

        with (
            patch("eab.snapshot.run_gdb_batch", return_value=_make_success_gdb_result(reg_stdout)),
            patch("eab.snapshot.generate_memory_dump_script", side_effect=mocker.gen_script),
            patch("eab.snapshot.run_gdb_python", side_effect=mocker.run_python),
        ):
            capture_snapshot(
                device="test-dev",
                elf_path=str(elf_path),
                output_path=str(tmp_path / "out.core"),
            )

        # Parse the written core file and check PT_LOAD data
        from elftools.elf.elffile import ELFFile

        with open(tmp_path / "out.core", "rb") as f:
            core = ELFFile(f)
            load_segs = [s for s in core.iter_segments() if s["p_type"] == "PT_LOAD"]
            assert len(load_segs) == 1
            assert load_segs[0].data() == expected

    def test_two_regions_correct_data(self, tmp_path: Path) -> None:
        regions_spec = [(0x20000000, 128), (0x20010000, 64)]
        elf_path = _make_minimal_elf(tmp_path, regions_spec)
        mem = {
            0x20000000: b"\x11" * 128,
            0x20010000: b"\x22" * 64,
        }
        mocker = _MemoryDumpMocker(mem)
        reg_stdout = _make_gdb_reg_output({})

        with (
            patch("eab.snapshot.run_gdb_batch", return_value=_make_success_gdb_result(reg_stdout)),
            patch("eab.snapshot.generate_memory_dump_script", side_effect=mocker.gen_script),
            patch("eab.snapshot.run_gdb_python", side_effect=mocker.run_python),
        ):
            capture_snapshot(
                device="test-dev",
                elf_path=str(elf_path),
                output_path=str(tmp_path / "out.core"),
            )

        from elftools.elf.elffile import ELFFile

        with open(tmp_path / "out.core", "rb") as f:
            core = ELFFile(f)
            load_segs = sorted(
                [s for s in core.iter_segments() if s["p_type"] == "PT_LOAD"],
                key=lambda s: s["p_vaddr"],
            )
            seg_data = [s.data() for s in load_segs]
        assert len(load_segs) == 2
        assert seg_data[0] == b"\x11" * 128
        assert seg_data[1] == b"\x22" * 64

    def test_region_addresses_in_core_match_elf(self, tmp_path: Path) -> None:
        regions_spec = [(0x20000000, 256), (0x20020000, 128)]
        elf_path = _make_minimal_elf(tmp_path, regions_spec)
        mem = {addr: bytes([addr & 0xFF]) * size for addr, size in regions_spec}
        mocker = _MemoryDumpMocker(mem)
        reg_stdout = _make_gdb_reg_output({})

        with (
            patch("eab.snapshot.run_gdb_batch", return_value=_make_success_gdb_result(reg_stdout)),
            patch("eab.snapshot.generate_memory_dump_script", side_effect=mocker.gen_script),
            patch("eab.snapshot.run_gdb_python", side_effect=mocker.run_python),
        ):
            capture_snapshot(
                device="test-dev",
                elf_path=str(elf_path),
                output_path=str(tmp_path / "out.core"),
            )

        from elftools.elf.elffile import ELFFile

        with open(tmp_path / "out.core", "rb") as f:
            core = ELFFile(f)
            vaddrs = sorted(s["p_vaddr"] for s in core.iter_segments() if s["p_type"] == "PT_LOAD")
        assert vaddrs == [0x20000000, 0x20020000]


class TestCoreFileFormat:
    """End-to-end: verify the output .core file is a valid ELF32 ET_CORE."""

    def _run_capture(
        self,
        tmp_path: Path,
        regions_spec: list[tuple[int, int]],
        regs: dict[str, int] | None = None,
    ) -> Path:
        elf_path = _make_minimal_elf(tmp_path, regions_spec)
        mem = {addr: b"\x00" * size for addr, size in regions_spec}
        mocker = _MemoryDumpMocker(mem)
        reg_stdout = _make_gdb_reg_output(regs or {})
        core_path = tmp_path / "snapshot.core"

        with (
            patch("eab.snapshot.run_gdb_batch", return_value=_make_success_gdb_result(reg_stdout)),
            patch("eab.snapshot.generate_memory_dump_script", side_effect=mocker.gen_script),
            patch("eab.snapshot.run_gdb_python", side_effect=mocker.run_python),
        ):
            capture_snapshot(
                device="test-dev",
                elf_path=str(elf_path),
                output_path=str(core_path),
            )
        return core_path

    def test_elf_type_is_et_core(self, tmp_path: Path) -> None:
        from elftools.elf.elffile import ELFFile

        core_path = self._run_capture(tmp_path, [(0x20000000, 64)])
        with open(core_path, "rb") as f:
            core = ELFFile(f)
            assert core.header["e_type"] == "ET_CORE"

    def test_pt_load_count_matches_regions(self, tmp_path: Path) -> None:
        from elftools.elf.elffile import ELFFile

        core_path = self._run_capture(tmp_path, [(0x20000000, 64), (0x20010000, 32)])
        with open(core_path, "rb") as f:
            core = ELFFile(f)
            loads = [s for s in core.iter_segments() if s["p_type"] == "PT_LOAD"]
        assert len(loads) == 2

    def test_pt_note_segment_present(self, tmp_path: Path) -> None:
        from elftools.elf.elffile import ELFFile

        core_path = self._run_capture(tmp_path, [(0x20000000, 64)])
        with open(core_path, "rb") as f:
            core = ELFFile(f)
            notes = [s for s in core.iter_segments() if s["p_type"] == "PT_NOTE"]
        assert len(notes) == 1

    def test_pt_load_vaddrs_match_elf_segments(self, tmp_path: Path) -> None:
        from elftools.elf.elffile import ELFFile

        spec = [(0x20000000, 64), (0x20008000, 128)]
        core_path = self._run_capture(tmp_path, spec)
        with open(core_path, "rb") as f:
            core = ELFFile(f)
            vaddrs = sorted(s["p_vaddr"] for s in core.iter_segments() if s["p_type"] == "PT_LOAD")
        assert vaddrs == [0x20000000, 0x20008000]

    def test_pt_load_sizes_match(self, tmp_path: Path) -> None:
        from elftools.elf.elffile import ELFFile

        spec = [(0x20000000, 64), (0x20008000, 128)]
        core_path = self._run_capture(tmp_path, spec)
        with open(core_path, "rb") as f:
            core = ELFFile(f)
            loads = sorted(
                [s for s in core.iter_segments() if s["p_type"] == "PT_LOAD"],
                key=lambda s: s["p_vaddr"],
            )
        assert loads[0]["p_filesz"] == 64
        assert loads[1]["p_filesz"] == 128

    def test_pt_note_contains_register_data(self, tmp_path: Path) -> None:
        """PT_NOTE segment should contain non-zero register data."""
        from elftools.elf.elffile import ELFFile

        regs = {"r0": 0xDEADBEEF, "pc": 0x00080042, "xpsr": 0x61000000}
        core_path = self._run_capture(tmp_path, [(0x20000000, 64)], regs)
        with open(core_path, "rb") as f:
            core = ELFFile(f)
            note_seg = next(s for s in core.iter_segments() if s["p_type"] == "PT_NOTE")
            note_data = note_seg.data()
        # The note should contain the packed register value 0xDEADBEEF
        assert struct.pack("<I", 0xDEADBEEF) in note_data

    def test_elf_machine_is_arm(self, tmp_path: Path) -> None:
        from elftools.elf.elffile import ELFFile

        core_path = self._run_capture(tmp_path, [(0x20000000, 64)])
        with open(core_path, "rb") as f:
            core = ELFFile(f)
            assert core.header["e_machine"] == "EM_ARM"


class TestSnapshotResult:
    """Verify SnapshotResult metadata fields are correctly populated."""

    def _capture(self, tmp_path: Path) -> SnapshotResult:
        regions_spec = [(0x20000000, 128), (0x20010000, 64)]
        elf_path = _make_minimal_elf(tmp_path, regions_spec)
        mem = {addr: b"\x00" * size for addr, size in regions_spec}
        mocker = _MemoryDumpMocker(mem)
        reg_stdout = _make_gdb_reg_output({"r0": 1, "pc": 2})

        with (
            patch("eab.snapshot.run_gdb_batch", return_value=_make_success_gdb_result(reg_stdout)),
            patch("eab.snapshot.generate_memory_dump_script", side_effect=mocker.gen_script),
            patch("eab.snapshot.run_gdb_python", side_effect=mocker.run_python),
        ):
            return capture_snapshot(
                device="test-dev",
                elf_path=str(elf_path),
                output_path=str(tmp_path / "out.core"),
            )

    def test_result_is_snapshot_result(self, tmp_path: Path) -> None:
        result = self._capture(tmp_path)
        assert isinstance(result, SnapshotResult)

    def test_timestamp_is_set(self, tmp_path: Path) -> None:
        result = self._capture(tmp_path)
        assert result.timestamp is not None

    def test_regions_list_length(self, tmp_path: Path) -> None:
        result = self._capture(tmp_path)
        assert len(result.regions) == 2

    def test_total_size_positive(self, tmp_path: Path) -> None:
        result = self._capture(tmp_path)
        assert result.total_size > 0

    def test_total_size_matches_file(self, tmp_path: Path) -> None:
        result = self._capture(tmp_path)
        actual_size = Path(result.output_path).stat().st_size
        assert result.total_size == actual_size

    def test_output_path_file_exists(self, tmp_path: Path) -> None:
        result = self._capture(tmp_path)
        assert Path(result.output_path).exists()

    def test_registers_captured(self, tmp_path: Path) -> None:
        result = self._capture(tmp_path)
        assert isinstance(result.registers, dict)
        assert "r0" in result.registers
        assert result.registers["r0"] == 1


class TestEdgeCases:
    """Edge-case and error-path coverage."""

    def test_missing_elf_raises(self, tmp_path: Path) -> None:
        with pytest.raises((ValueError, FileNotFoundError)):
            capture_snapshot(
                device="test-dev",
                elf_path=str(tmp_path / "does_not_exist.elf"),
                output_path=str(tmp_path / "out.core"),
            )

    def test_missing_elf_error_message_mentions_path(self, tmp_path: Path) -> None:
        bad_path = str(tmp_path / "no_such_file.elf")
        with pytest.raises((ValueError, FileNotFoundError)) as exc_info:
            capture_snapshot(
                device="test-dev",
                elf_path=bad_path,
                output_path=str(tmp_path / "out.core"),
            )
        assert "no_such_file.elf" in str(exc_info.value)

    def test_gdb_register_failure_propagates(self, tmp_path: Path) -> None:
        """RuntimeError from run_gdb_batch should propagate out of capture_snapshot."""
        elf_path = _make_minimal_elf(tmp_path, [(0x20000000, 64)])
        with patch("eab.snapshot.run_gdb_batch", side_effect=RuntimeError("GDB connection refused")):
            with pytest.raises(RuntimeError, match="GDB connection refused"):
                capture_snapshot(
                    device="test-dev",
                    elf_path=str(elf_path),
                    output_path=str(tmp_path / "out.core"),
                )

    def test_parse_elf_with_no_load_segments(self, tmp_path: Path) -> None:
        """An ELF with zero LOAD segments should return an empty list."""
        elf_path = _make_minimal_elf(tmp_path, [])
        regions = _parse_elf_load_segments(str(elf_path))
        assert regions == []


# ---------------------------------------------------------------------------
# CLI JSON output
# ---------------------------------------------------------------------------


class TestSnapshotCliJsonOutput:
    """Verify cmd_snapshot --json produces valid JSON with required keys."""

    def _make_mock_result(self) -> SnapshotResult:
        return SnapshotResult(
            output_path="/tmp/snap.core",
            regions=[MemoryRegion(start=0x20000000, size=0x8000)],
            registers={"r0": 1, "pc": 2},
            total_size=65536,
        )

    def test_json_output_contains_required_keys(self, capsys: pytest.CaptureFixture) -> None:
        """JSON output must contain path, regions, registers, and size_bytes."""
        from eab.cli.snapshot_cmd import cmd_snapshot

        mock_result = self._make_mock_result()
        with patch("eab.snapshot.capture_snapshot", return_value=mock_result):
            ret = cmd_snapshot(
                device="NRF5340_XXAA_APP",
                elf="/build/fw.elf",
                output="/tmp/snap.core",
                json_mode=True,
            )

        assert ret == 0
        captured = capsys.readouterr()
        data = json.loads(captured.out)
        assert "path" in data
        assert "regions" in data
        assert "registers" in data
        assert "size_bytes" in data

    def test_json_path_matches_output(self, capsys: pytest.CaptureFixture) -> None:
        from eab.cli.snapshot_cmd import cmd_snapshot

        mock_result = self._make_mock_result()
        with patch("eab.snapshot.capture_snapshot", return_value=mock_result):
            cmd_snapshot(
                device="NRF5340_XXAA_APP",
                elf="/build/fw.elf",
                output="/tmp/snap.core",
                json_mode=True,
            )

        data = json.loads(capsys.readouterr().out)
        assert data["path"] == "/tmp/snap.core"

    def test_json_regions_is_list(self, capsys: pytest.CaptureFixture) -> None:
        from eab.cli.snapshot_cmd import cmd_snapshot

        mock_result = self._make_mock_result()
        with patch("eab.snapshot.capture_snapshot", return_value=mock_result):
            cmd_snapshot(
                device="NRF5340_XXAA_APP",
                elf="/build/fw.elf",
                output="/tmp/snap.core",
                json_mode=True,
            )

        data = json.loads(capsys.readouterr().out)
        assert isinstance(data["regions"], list)
        assert len(data["regions"]) == 1
        assert data["regions"][0]["start"] == 0x20000000
        assert data["regions"][0]["size"] == 0x8000

    def test_json_registers_is_dict(self, capsys: pytest.CaptureFixture) -> None:
        from eab.cli.snapshot_cmd import cmd_snapshot

        mock_result = self._make_mock_result()
        with patch("eab.snapshot.capture_snapshot", return_value=mock_result):
            cmd_snapshot(
                device="NRF5340_XXAA_APP",
                elf="/build/fw.elf",
                output="/tmp/snap.core",
                json_mode=True,
            )

        data = json.loads(capsys.readouterr().out)
        assert isinstance(data["registers"], dict)
        assert data["registers"]["r0"] == 1
        assert data["registers"]["pc"] == 2

    def test_json_size_bytes_matches_total_size(self, capsys: pytest.CaptureFixture) -> None:
        from eab.cli.snapshot_cmd import cmd_snapshot

        mock_result = self._make_mock_result()
        with patch("eab.snapshot.capture_snapshot", return_value=mock_result):
            cmd_snapshot(
                device="NRF5340_XXAA_APP",
                elf="/build/fw.elf",
                output="/tmp/snap.core",
                json_mode=True,
            )

        data = json.loads(capsys.readouterr().out)
        assert data["size_bytes"] == 65536


# ---------------------------------------------------------------------------
# HIL step trigger conditions
# ---------------------------------------------------------------------------


class TestSnapshotStepTriggerConditions:
    """Verify snapshot HIL step calls capture_snapshot only under right triggers."""

    def _make_snap_result(self) -> MagicMock:
        return MagicMock(
            output_path="results/state.core",
            total_size=1024,
            regions=[MagicMock(), MagicMock()],
        )

    def _manual_step(self):
        from eab.cli.regression.models import StepSpec

        return StepSpec(
            "snapshot",
            {
                "output": "results/state.core",
                "elf": "build/zephyr/zephyr.elf",
                "trigger": "manual",
            },
        )

    def _on_fault_step(self):
        from eab.cli.regression.models import StepSpec

        return StepSpec(
            "snapshot",
            {
                "output": "results/state.core",
                "elf": "build/zephyr/zephyr.elf",
                "trigger": "on_fault",
            },
        )

    def _on_anomaly_step(self):
        from eab.cli.regression.models import StepSpec

        return StepSpec(
            "snapshot",
            {
                "output": "results/state.core",
                "elf": "build/zephyr/zephyr.elf",
                "trigger": "on_anomaly",
                "baseline": "baselines/nominal.json",
            },
        )

    def test_manual_trigger_always_calls_capture_snapshot(self) -> None:
        from eab.cli.regression.steps import _run_snapshot

        snap_result = self._make_snap_result()
        with patch("eab.cli.regression.steps.capture_snapshot", return_value=snap_result) as mock_capture:
            result = _run_snapshot(self._manual_step(), device="nrf5340", chip=None, timeout=60)
        mock_capture.assert_called_once()
        assert result.passed
        assert result.output["captured"] is True

    def test_on_fault_no_fault_skips_capture(self) -> None:
        from eab.cli.regression.steps import _run_snapshot

        with (
            patch("eab.cli.regression.steps._run_eabctl", return_value=(0, {"fault_detected": False})),
            patch("eab.cli.regression.steps.capture_snapshot") as mock_capture,
        ):
            result = _run_snapshot(self._on_fault_step(), device="nrf5340", chip=None, timeout=60)
        mock_capture.assert_not_called()
        assert result.passed
        assert result.output["captured"] is False

    def test_on_fault_with_fault_calls_capture(self) -> None:
        from eab.cli.regression.steps import _run_snapshot

        snap_result = self._make_snap_result()
        with (
            patch("eab.cli.regression.steps._run_eabctl", return_value=(0, {"fault_detected": True})),
            patch("eab.cli.regression.steps.capture_snapshot", return_value=snap_result) as mock_capture,
        ):
            result = _run_snapshot(self._on_fault_step(), device="nrf5340", chip=None, timeout=60)
        mock_capture.assert_called_once()
        assert result.passed
        assert result.output["captured"] is True

    def test_on_anomaly_zero_count_skips_capture(self) -> None:
        from eab.cli.regression.steps import _run_snapshot

        with (
            patch("eab.cli.regression.steps._run_eabctl", return_value=(0, {"anomaly_count": 0})),
            patch("eab.cli.regression.steps.capture_snapshot") as mock_capture,
        ):
            result = _run_snapshot(self._on_anomaly_step(), device="nrf5340", chip=None, timeout=60)
        mock_capture.assert_not_called()
        assert result.passed
        assert result.output["captured"] is False

    def test_on_anomaly_nonzero_count_calls_capture(self) -> None:
        from eab.cli.regression.steps import _run_snapshot

        snap_result = self._make_snap_result()
        with (
            patch("eab.cli.regression.steps._run_eabctl", return_value=(0, {"anomaly_count": 1})),
            patch("eab.cli.regression.steps.capture_snapshot", return_value=snap_result) as mock_capture,
        ):
            result = _run_snapshot(self._on_anomaly_step(), device="nrf5340", chip=None, timeout=60)
        mock_capture.assert_called_once()
        assert result.passed
        assert result.output["captured"] is True
