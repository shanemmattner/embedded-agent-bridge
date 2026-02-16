"""Tests for TI C2000 chip profile, XDS110 debug probe, and MAP parser."""

from __future__ import annotations

import subprocess
import tempfile
from pathlib import Path
from unittest.mock import MagicMock, patch

import pytest

from eab.chips import get_chip_profile, detect_chip_family
from eab.chips.base import ChipFamily, FlashCommand
from eab.chips.c2000 import C2000Profile, _find_dslite, _find_ccxml
from eab.c2000_map_parser import parse_ti_map_file, find_symbol, C2000Symbol
from eab.debug_probes import get_debug_probe
from eab.debug_probes.xds110 import XDS110Probe


# =========================================================================
# C2000Profile
# =========================================================================


class TestC2000Profile:
    def test_family(self):
        p = C2000Profile()
        assert p.family == ChipFamily.C2000

    def test_name_default(self):
        p = C2000Profile()
        assert "TMS320F280039C" in p.name

    def test_name_variant(self):
        p = C2000Profile(variant="f28379d")
        assert "TMS320F28379D" in p.name

    def test_flash_tool(self):
        p = C2000Profile()
        assert p.flash_tool == "dslite"

    def test_get_flash_command(self):
        p = C2000Profile(ccxml="/path/to/target.ccxml")
        cmd = p.get_flash_command("/path/to/firmware.out", port="/dev/ttyUSB0")
        assert cmd.tool.endswith("DSLite") or cmd.tool.endswith("dslite") or cmd.tool == "dslite"
        assert "flash" in cmd.args
        assert "-f" in cmd.args
        assert "/path/to/firmware.out" in cmd.args
        assert any("--config=" in a for a in cmd.args)

    def test_get_flash_command_no_ccxml(self):
        p = C2000Profile()
        cmd = p.get_flash_command("/path/to/firmware.out", port="")
        assert "-f" in cmd.args
        # No --config= when ccxml is None
        has_config = any("--config=" in a for a in cmd.args)
        assert not has_config or p.ccxml is not None

    def test_get_erase_command(self):
        p = C2000Profile(ccxml="/path/to/target.ccxml")
        cmd = p.get_erase_command(port="")
        assert "Erase" in cmd.args

    def test_get_chip_info_command(self):
        p = C2000Profile()
        cmd = p.get_chip_info_command(port="")
        assert "identifyProbe" in cmd.args

    def test_get_reset_command(self):
        p = C2000Profile(ccxml="/path/to/target.ccxml")
        cmd = p.get_reset_command()
        assert "load" in cmd.args
        assert "--reset" in cmd.args

    def test_openocd_not_supported(self):
        p = C2000Profile()
        with pytest.raises(NotImplementedError, match="C28x"):
            p.get_openocd_config()

    def test_boot_patterns(self):
        p = C2000Profile()
        assert len(p.boot_patterns) > 0

    def test_crash_patterns(self):
        p = C2000Profile()
        assert any("NMI" in pat for pat in p.crash_patterns)

    def test_is_line_crash(self):
        p = C2000Profile()
        assert p.is_line_crash("NMI triggered")
        assert not p.is_line_crash("Normal operation")

    def test_is_line_boot(self):
        p = C2000Profile()
        assert p.is_line_boot("C2000 Boot started")
        assert not p.is_line_boot("Running normally")


# =========================================================================
# Chip Profile Registry
# =========================================================================


class TestChipProfileRegistry:
    def test_get_c2000_profile(self):
        p = get_chip_profile("c2000")
        assert isinstance(p, C2000Profile)
        assert p.family == ChipFamily.C2000

    def test_get_c2000_variant(self):
        p = get_chip_profile("c2000_f280039c")
        assert isinstance(p, C2000Profile)

    def test_detect_c2000_from_serial(self):
        assert detect_chip_family("XDS110 connected") == ChipFamily.C2000
        assert detect_chip_family("TMS320F280039C boot") == ChipFamily.C2000
        assert detect_chip_family("SCI Boot detected") == ChipFamily.C2000

    def test_no_false_positive(self):
        assert detect_chip_family("Hello world") is None


# =========================================================================
# XDS110 Debug Probe
# =========================================================================


class TestXDS110Probe:
    def test_name(self):
        with tempfile.TemporaryDirectory() as d:
            p = XDS110Probe(base_dir=d)
            assert p.name == "XDS110"

    def test_gdb_port_zero(self):
        with tempfile.TemporaryDirectory() as d:
            p = XDS110Probe(base_dir=d)
            assert p.gdb_port == 0

    @patch("subprocess.run")
    def test_start_gdb_server_xds110_found(self, mock_run):
        mock_run.return_value = MagicMock(
            returncode=0,
            stdout="DSLite version 20.4.0.3973",
            stderr="",
        )
        with tempfile.TemporaryDirectory() as d:
            p = XDS110Probe(base_dir=d)
            status = p.start_gdb_server()
            assert status.running is True

    @patch("subprocess.run")
    def test_start_gdb_server_not_found(self, mock_run):
        mock_run.return_value = MagicMock(
            returncode=1,
            stdout="",
            stderr="Failed: An invalid processor ID has been found.",
        )
        with tempfile.TemporaryDirectory() as d:
            p = XDS110Probe(base_dir=d)
            status = p.start_gdb_server()
            assert status.running is False

    @patch("subprocess.run", side_effect=FileNotFoundError("DSLite"))
    def test_start_gdb_server_dslite_missing(self, mock_run):
        with tempfile.TemporaryDirectory() as d:
            p = XDS110Probe(base_dir=d)
            status = p.start_gdb_server()
            assert status.running is False
            assert "DSLite not found" in status.last_error

    @patch("subprocess.run")
    def test_memory_read(self, mock_run):
        def _fake_dslite_memory(*args, **kwargs):
            """Simulate DSLite writing binary data to the --output file."""
            cmd = args[0]
            for arg in cmd:
                if arg.startswith("--output="):
                    out_path = arg.split("=", 1)[1]
                    Path(out_path).write_bytes(b"\x01\x02\x03\x04")
            return MagicMock(returncode=0, stdout="", stderr="")

        mock_run.side_effect = _fake_dslite_memory
        with tempfile.TemporaryDirectory() as d:
            p = XDS110Probe(base_dir=d)
            data = p.memory_read(0x0000C002, 4)
            assert data == b"\x01\x02\x03\x04"

    @patch("subprocess.run")
    def test_reset_target(self, mock_run):
        mock_run.return_value = MagicMock(returncode=0)
        with tempfile.TemporaryDirectory() as d:
            p = XDS110Probe(base_dir=d)
            assert p.reset_target() is True

    def test_probe_registry(self):
        with tempfile.TemporaryDirectory() as d:
            p = get_debug_probe("xds110", base_dir=d)
            assert isinstance(p, XDS110Probe)


# =========================================================================
# C2000 MAP File Parser
# =========================================================================


SAMPLE_TI_MAP = """\
******************************************************************************
              TMS320F280039C Linker PC v22.6.1
******************************************************************************
>> Linked Mon Jan  6 10:30:00 2025

OUTPUT FILE NAME:   <firmware.out>

GLOBAL SYMBOLS: SORTED ALPHABETICALLY BY Name

address    name
--------   ----
00000000   $O$C
0000c002   _motorVars_M1
0000c120   _motorVars_M2
0000d000   _adcResult
00008000   _main
ffffffff   binit

GLOBAL SYMBOLS: SORTED BY Symbol Address

address    name
--------   ----
00000000   $O$C
00008000   _main
0000c002   _motorVars_M1
0000c120   _motorVars_M2
0000d000   _adcResult
ffffffff   binit

MEMORY ALLOCATION

  name              address    length   section
  ----              -------    ------   -------
  _motorVars_M1     0000c002   00000120 RAMLS4
  _motorVars_M2     0000c120   00000120 RAMLS4
  _adcResult        0000d000   00000020 RAMGS0
"""


class TestC2000MapParser:
    def test_parse_ti_map_file(self):
        with tempfile.NamedTemporaryFile(mode="w", suffix=".map", delete=False) as f:
            f.write(SAMPLE_TI_MAP)
            f.flush()
            symbols = parse_ti_map_file(f.name)

        names = [s.name for s in symbols]
        assert "motorVars_M1" in names
        assert "motorVars_M2" in names
        assert "adcResult" in names
        assert "main" in names
        # Compiler internals should be filtered
        assert "$O$C" not in names

    def test_symbol_addresses(self):
        with tempfile.NamedTemporaryFile(mode="w", suffix=".map", delete=False) as f:
            f.write(SAMPLE_TI_MAP)
            f.flush()
            symbols = parse_ti_map_file(f.name)

        by_name = {s.name: s for s in symbols}
        assert by_name["motorVars_M1"].address == 0x0000C002
        assert by_name["main"].address == 0x00008000

    def test_symbol_sizes_from_memory_alloc(self):
        with tempfile.NamedTemporaryFile(mode="w", suffix=".map", delete=False) as f:
            f.write(SAMPLE_TI_MAP)
            f.flush()
            symbols = parse_ti_map_file(f.name)

        by_name = {s.name: s for s in symbols}
        assert by_name["motorVars_M1"].size == 0x120
        assert by_name["adcResult"].size == 0x20

    def test_find_symbol_exact(self):
        symbols = [
            C2000Symbol(name="motorVars_M1", address=0xC002, size=0x120),
            C2000Symbol(name="adcResult", address=0xD000, size=0x20),
        ]
        result = find_symbol(symbols, "motorVars_M1")
        assert result is not None
        assert result.address == 0xC002

    def test_find_symbol_dotted(self):
        symbols = [
            C2000Symbol(name="motorVars_M1", address=0xC002, size=0x120),
        ]
        result = find_symbol(symbols, "motorVars_M1.motorState")
        assert result is not None
        assert result.name == "motorVars_M1"

    def test_find_symbol_not_found(self):
        symbols = [
            C2000Symbol(name="motorVars_M1", address=0xC002, size=0x120),
        ]
        assert find_symbol(symbols, "nonexistent") is None

    def test_file_not_found(self):
        with pytest.raises(FileNotFoundError):
            parse_ti_map_file("/nonexistent/file.map")

    def test_sorted_by_address(self):
        with tempfile.NamedTemporaryFile(mode="w", suffix=".map", delete=False) as f:
            f.write(SAMPLE_TI_MAP)
            f.flush()
            symbols = parse_ti_map_file(f.name)

        addresses = [s.address for s in symbols]
        assert addresses == sorted(addresses)


# =========================================================================
# Regression Test YAML (Phase 6)
# =========================================================================


class TestC2000RegressionYAML:
    """Verify the regression test YAML is valid."""

    def test_yaml_exists(self):
        yaml_path = Path(__file__).parent / "hw" / "c2000_launchxl.yaml"
        assert yaml_path.exists(), f"Missing regression test: {yaml_path}"

    def test_yaml_parseable(self):
        yaml_path = Path(__file__).parent / "hw" / "c2000_launchxl.yaml"
        if not yaml_path.exists():
            pytest.skip("YAML not yet created")

        import yaml
        with open(yaml_path) as f:
            data = yaml.safe_load(f)
        assert data["name"] == "C2000 LaunchXL-F280039C"
        assert data["device"] == "c2000"
