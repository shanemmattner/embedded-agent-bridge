"""Tests for eab.elf_inspect module.

Tests symbol parsing, MAP file parsing, and GDB script generation
with mocked subprocess output (no real toolchain needed).
"""

from __future__ import annotations

import ast
from unittest.mock import patch, MagicMock

import pytest

from eab.elf_inspect import (
    ElfSymbol,
    MapSymbol,
    parse_symbols,
    parse_map_file,
    generate_batch_variable_reader,
    generate_variable_lister,
    _infer_section,
    _extract_symbol_name,
)


# =============================================================================
# Data class tests
# =============================================================================


class TestElfSymbol:
    def test_construction(self):
        sym = ElfSymbol(name="g_counter", address=0x20000100, size=4, sym_type="D", section=".data")
        assert sym.name == "g_counter"
        assert sym.address == 0x20000100
        assert sym.size == 4
        assert sym.sym_type == "D"
        assert sym.section == ".data"

    def test_frozen(self):
        sym = ElfSymbol(name="g_counter", address=0x20000100, size=4, sym_type="D", section=".data")
        with pytest.raises(AttributeError):
            sym.name = "other"


class TestMapSymbol:
    def test_construction(self):
        sym = MapSymbol(name="g_sensor", address=0x20001000, size=32, region="RAM", section=".bss")
        assert sym.name == "g_sensor"
        assert sym.address == 0x20001000
        assert sym.size == 32
        assert sym.region == "RAM"
        assert sym.section == ".bss"


# =============================================================================
# Helper tests
# =============================================================================


class TestInferSection:
    def test_data_types(self):
        assert _infer_section("D") == ".data"
        assert _infer_section("d") == ".data"

    def test_bss_types(self):
        assert _infer_section("B") == ".bss"
        assert _infer_section("b") == ".bss"

    def test_rodata_types(self):
        assert _infer_section("R") == ".rodata"
        assert _infer_section("r") == ".rodata"

    def test_small_data_types(self):
        assert _infer_section("G") == ".sdata"
        assert _infer_section("g") == ".sdata"

    def test_unknown_type(self):
        assert _infer_section("T") == ".unknown"
        assert _infer_section("X") == ".unknown"


class TestExtractSymbolName:
    def test_bss_variable(self):
        assert _extract_symbol_name(".bss.g_sensor_data") == "g_sensor_data"

    def test_data_variable(self):
        assert _extract_symbol_name(".data.g_counter") == "g_counter"

    def test_rodata_variable(self):
        assert _extract_symbol_name(".rodata.VERSION") == "VERSION"

    def test_nested_section(self):
        assert _extract_symbol_name(".dram0.bss.g_state") == "g_state"

    def test_short_section(self):
        assert _extract_symbol_name(".bss") is None

    def test_single_word(self):
        assert _extract_symbol_name("something") is None


# =============================================================================
# parse_symbols tests
# =============================================================================


class TestParseSymbols:
    NM_OUTPUT_WITH_SIZES = """\
20000100 00000004 D g_counter
20000104 00000020 B g_sensor_data
20000200 00000002 d s_local_var
20000300 00000004 R g_version
08001000 00000040 T main
08001040 00000020 t _helper
20000400 00000001 b s_flag
20000500 00000008 G g_small
"""

    NM_OUTPUT_NO_SIZES = """\
20000100 D g_counter
20000104 B g_sensor_data
08001000 T main
"""

    @patch("eab.elf_inspect.subprocess.run")
    @patch("eab.elf_inspect._resolve_nm")
    def test_parses_data_symbols_with_sizes(self, mock_resolve, mock_run):
        mock_resolve.return_value = "arm-none-eabi-nm"
        mock_proc = MagicMock()
        mock_proc.stdout = self.NM_OUTPUT_WITH_SIZES
        mock_run.return_value = mock_proc

        symbols = parse_symbols("/path/to/app.elf")

        # Should only include data symbols, not text (T/t)
        names = [s.name for s in symbols]
        assert "g_counter" in names
        assert "g_sensor_data" in names
        assert "s_local_var" in names
        assert "g_version" in names
        assert "s_flag" in names
        assert "g_small" in names
        assert "main" not in names
        assert "_helper" not in names

    @patch("eab.elf_inspect.subprocess.run")
    @patch("eab.elf_inspect._resolve_nm")
    def test_symbol_sizes_parsed(self, mock_resolve, mock_run):
        mock_resolve.return_value = "arm-none-eabi-nm"
        mock_proc = MagicMock()
        mock_proc.stdout = self.NM_OUTPUT_WITH_SIZES
        mock_run.return_value = mock_proc

        symbols = parse_symbols("/path/to/app.elf")
        by_name = {s.name: s for s in symbols}

        assert by_name["g_counter"].size == 4
        assert by_name["g_sensor_data"].size == 0x20
        assert by_name["g_version"].size == 4

    @patch("eab.elf_inspect.subprocess.run")
    @patch("eab.elf_inspect._resolve_nm")
    def test_symbols_without_sizes(self, mock_resolve, mock_run):
        mock_resolve.return_value = "arm-none-eabi-nm"
        mock_proc = MagicMock()
        mock_proc.stdout = self.NM_OUTPUT_NO_SIZES
        mock_run.return_value = mock_proc

        symbols = parse_symbols("/path/to/app.elf")
        by_name = {s.name: s for s in symbols}

        assert "g_counter" in by_name
        assert by_name["g_counter"].size == 0  # Unknown size
        assert by_name["g_counter"].sym_type == "D"

    @patch("eab.elf_inspect.subprocess.run")
    @patch("eab.elf_inspect._resolve_nm")
    def test_sorted_by_address(self, mock_resolve, mock_run):
        mock_resolve.return_value = "arm-none-eabi-nm"
        mock_proc = MagicMock()
        mock_proc.stdout = self.NM_OUTPUT_WITH_SIZES
        mock_run.return_value = mock_proc

        symbols = parse_symbols("/path/to/app.elf")
        addresses = [s.address for s in symbols]
        assert addresses == sorted(addresses)

    @patch("eab.elf_inspect.subprocess.run")
    @patch("eab.elf_inspect._resolve_nm")
    def test_section_inference(self, mock_resolve, mock_run):
        mock_resolve.return_value = "arm-none-eabi-nm"
        mock_proc = MagicMock()
        mock_proc.stdout = self.NM_OUTPUT_WITH_SIZES
        mock_run.return_value = mock_proc

        symbols = parse_symbols("/path/to/app.elf")
        by_name = {s.name: s for s in symbols}

        assert by_name["g_counter"].section == ".data"
        assert by_name["g_sensor_data"].section == ".bss"
        assert by_name["g_version"].section == ".rodata"

    @patch("eab.elf_inspect._resolve_nm")
    def test_nm_not_found(self, mock_resolve):
        mock_resolve.side_effect = FileNotFoundError("nm not found")
        with pytest.raises(FileNotFoundError):
            parse_symbols("/path/to/app.elf")

    @patch("eab.elf_inspect.subprocess.run")
    @patch("eab.elf_inspect._resolve_nm")
    def test_empty_output(self, mock_resolve, mock_run):
        mock_resolve.return_value = "arm-none-eabi-nm"
        mock_proc = MagicMock()
        mock_proc.stdout = ""
        mock_run.return_value = mock_proc

        symbols = parse_symbols("/path/to/app.elf")
        assert symbols == []

    @patch("eab.elf_inspect.subprocess.run")
    @patch("eab.elf_inspect._resolve_nm")
    def test_nm_flags(self, mock_resolve, mock_run):
        """Verify nm is called with -S -C --defined-only flags."""
        mock_resolve.return_value = "/usr/bin/arm-none-eabi-nm"
        mock_proc = MagicMock()
        mock_proc.stdout = ""
        mock_run.return_value = mock_proc

        parse_symbols("/path/to/app.elf")

        call_args = mock_run.call_args
        argv = call_args[0][0]
        assert "-S" in argv
        assert "-C" in argv
        assert "--defined-only" in argv


# =============================================================================
# parse_map_file tests
# =============================================================================


class TestParseMapFile:
    ESP_IDF_MAP = """\
Linker script and memory map

MEMORY Configuration

Name             Origin             Length             Attributes
IRAM             0x00000000403ce000 0x0000000000032000
DRAM             0x000000003fc88000 0x0000000000050000

.bss.g_sensor_data
                0x000000003fc89000       0x20 build/sensor.o
 .bss.g_error_count
                0x000000003fc89020       0x04 build/main.o
 .data.g_config
                0x000000003fc89024       0x10 build/config.o
"""

    ZEPHYR_MAP = """\
Linker script and memory map

.bss            0x0000000020000000      0x100
 .bss.k_heap_default
                0x0000000020000000       0x40 zephyr/kernel/libkernel.a(init.c.obj)
 .bss.z_main_thread
                0x0000000020000040       0x80 zephyr/kernel/libkernel.a(init.c.obj)
"""

    INLINE_MAP = """\
 .bss.g_inline_var  0x20002000  0x08  build/inline.o
 .data.g_inline_data  0x20003000  0x10  build/inline.o
"""

    def test_esp_idf_format(self, tmp_path):
        map_file = tmp_path / "app.map"
        map_file.write_text(self.ESP_IDF_MAP)

        symbols = parse_map_file(str(map_file))
        by_name = {s.name: s for s in symbols}

        assert "g_sensor_data" in by_name
        assert by_name["g_sensor_data"].size == 0x20
        assert by_name["g_sensor_data"].section == ".bss"

        assert "g_error_count" in by_name
        assert by_name["g_error_count"].size == 0x04

        assert "g_config" in by_name
        assert by_name["g_config"].section == ".data"

    def test_zephyr_format(self, tmp_path):
        map_file = tmp_path / "zephyr.map"
        map_file.write_text(self.ZEPHYR_MAP)

        symbols = parse_map_file(str(map_file))
        by_name = {s.name: s for s in symbols}

        assert "k_heap_default" in by_name
        assert by_name["k_heap_default"].size == 0x40
        assert by_name["k_heap_default"].section == ".bss"

        assert "z_main_thread" in by_name
        assert by_name["z_main_thread"].size == 0x80

    def test_inline_entries(self, tmp_path):
        map_file = tmp_path / "inline.map"
        map_file.write_text(self.INLINE_MAP)

        symbols = parse_map_file(str(map_file))
        by_name = {s.name: s for s in symbols}

        assert "g_inline_var" in by_name
        assert by_name["g_inline_var"].size == 0x08

        assert "g_inline_data" in by_name
        assert by_name["g_inline_data"].size == 0x10

    def test_sorted_by_address(self, tmp_path):
        map_file = tmp_path / "app.map"
        map_file.write_text(self.ESP_IDF_MAP)

        symbols = parse_map_file(str(map_file))
        addresses = [s.address for s in symbols]
        assert addresses == sorted(addresses)

    def test_empty_map_file(self, tmp_path):
        map_file = tmp_path / "empty.map"
        map_file.write_text("")

        symbols = parse_map_file(str(map_file))
        assert symbols == []

    def test_region_inference(self, tmp_path):
        map_file = tmp_path / "app.map"
        map_file.write_text(self.ESP_IDF_MAP)

        symbols = parse_map_file(str(map_file))
        by_name = {s.name: s for s in symbols}

        # BSS and data should be in RAM
        assert by_name["g_sensor_data"].region == "RAM"


# =============================================================================
# GDB script generator tests
# =============================================================================


class TestGenerateBatchVariableReader:
    def test_produces_valid_python(self):
        script = generate_batch_variable_reader(["g_counter", "g_state"])
        ast.parse(script)  # Should not raise SyntaxError

    def test_includes_variable_names(self):
        script = generate_batch_variable_reader(["g_counter", "g_state"])
        assert "g_counter" in script
        assert "g_state" in script

    def test_uses_result_file_pattern(self):
        script = generate_batch_variable_reader(["var1"])
        assert 'gdb.convenience_variable("result_file")' in script
        assert "json.dump" in script

    def test_imports_gdb_and_json(self):
        script = generate_batch_variable_reader(["var1"])
        assert "import gdb" in script
        assert "import json" in script

    def test_handles_multiple_types(self):
        script = generate_batch_variable_reader(["var1"])
        assert "TYPE_CODE_INT" in script
        assert "TYPE_CODE_FLT" in script
        assert "TYPE_CODE_STRUCT" in script
        assert "TYPE_CODE_ARRAY" in script
        assert "TYPE_CODE_ENUM" in script
        assert "TYPE_CODE_PTR" in script
        assert "TYPE_CODE_BOOL" in script

    def test_has_depth_limit(self):
        script = generate_batch_variable_reader(["var1"])
        assert "MAX_DEPTH" in script
        assert "max depth exceeded" in script

    def test_has_array_limit(self):
        script = generate_batch_variable_reader(["var1"])
        assert "MAX_ARRAY_ELEMENTS" in script

    def test_error_handling(self):
        script = generate_batch_variable_reader(["var1"])
        assert "except gdb.error" in script

    def test_empty_var_list(self):
        script = generate_batch_variable_reader([])
        ast.parse(script)  # Should still be valid Python

    def test_special_characters_in_names(self):
        """Variable names with special chars should be properly escaped in JSON."""
        script = generate_batch_variable_reader(["my_struct.field"])
        ast.parse(script)
        assert "my_struct.field" in script


class TestGenerateVariableLister:
    def test_produces_valid_python(self):
        script = generate_variable_lister()
        ast.parse(script)

    def test_with_filter_pattern(self):
        script = generate_variable_lister(filter_pattern="g_*")
        ast.parse(script)
        assert "g_*" in script

    def test_without_filter(self):
        script = generate_variable_lister()
        assert "null" in script  # JSON null for None filter

    def test_uses_info_variables(self):
        script = generate_variable_lister()
        assert "info variables" in script

    def test_uses_fnmatch(self):
        script = generate_variable_lister(filter_pattern="*sensor*")
        assert "fnmatch" in script

    def test_imports_required_modules(self):
        script = generate_variable_lister()
        assert "import gdb" in script
        assert "import json" in script
        assert "import fnmatch" in script

    def test_uses_result_file_pattern(self):
        script = generate_variable_lister()
        assert 'gdb.convenience_variable("result_file")' in script
        assert "json.dump" in script

    def test_error_handling(self):
        script = generate_variable_lister()
        assert "except gdb.error" in script
