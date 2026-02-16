"""Tests for backtrace decoding with addr2line.

Tests multiple backtrace formats (ESP-IDF, Zephyr, GDB) and addr2line integration.
"""

from __future__ import annotations

from unittest.mock import patch, MagicMock
import subprocess

import pytest

from eab.backtrace import (
    BacktraceDecoder,
    BacktraceEntry,
    BacktraceResult,
    _parse_esp_backtrace,
    _parse_zephyr_backtrace,
    _parse_gdb_backtrace,
    _get_addr2line_for_arch,
)


# =============================================================================
# ESP-IDF Backtrace Parser Tests
# =============================================================================

class TestESPBacktraceParser:
    def test_parse_single_address_pair(self):
        text = "Backtrace:0x400d1234:0x3ffb5678"
        entries = _parse_esp_backtrace(text)
        
        assert len(entries) == 1
        assert entries[0].address == 0x400d1234
        assert entries[0].pc_address == 0x3ffb5678
        assert entries[0].raw_line == "0x400d1234:0x3ffb5678"
    
    def test_parse_multiple_address_pairs(self):
        text = "Backtrace:0x400d1234:0x3ffb5678 0x400d5678:0x3ffb9abc 0x400d9999:0x3ffba000"
        entries = _parse_esp_backtrace(text)
        
        assert len(entries) == 3
        assert entries[0].address == 0x400d1234
        assert entries[0].pc_address == 0x3ffb5678
        assert entries[1].address == 0x400d5678
        assert entries[1].pc_address == 0x3ffb9abc
        assert entries[2].address == 0x400d9999
        assert entries[2].pc_address == 0x3ffba000
    
    def test_parse_no_backtrace(self):
        text = "Some random log output without backtrace"
        entries = _parse_esp_backtrace(text)
        assert len(entries) == 0
    
    def test_parse_case_insensitive(self):
        text = "backtrace:0x400d1234:0x3ffb5678"  # lowercase
        entries = _parse_esp_backtrace(text)
        assert len(entries) == 1
        assert entries[0].address == 0x400d1234


# =============================================================================
# Zephyr Backtrace Parser Tests
# =============================================================================

class TestZephyrBacktraceParser:
    def test_parse_pc_register(self):
        text = "E: Faulting instruction address (r15/pc): 0x0800abcd"
        entries = _parse_zephyr_backtrace(text)
        
        assert len(entries) == 1
        assert entries[0].address == 0x0800abcd
        assert "r15/pc" in entries[0].raw_line
    
    def test_parse_pc_with_other_registers(self):
        text = """
        E: r0/a1:  0x00000000
        E: r1/a2:  0x20000100
        E: r15/pc: 0x08001234
        E: r14/lr: 0x0800abcd
        """
        entries = _parse_zephyr_backtrace(text)
        
        # Should extract PC and other plausible code addresses
        assert len(entries) >= 1
        # PC should be first
        assert entries[0].address == 0x08001234
    
    def test_parse_error_prefix(self):
        text = "ERROR: Faulting instruction address (r15/pc): 0x0000cafe"
        entries = _parse_zephyr_backtrace(text)
        
        assert len(entries) == 1
        assert entries[0].address == 0x0000cafe
    
    def test_parse_filters_low_addresses(self):
        text = """
        E: r0/a1:  0x00000000
        E: r1/a2:  0x00000001
        E: r15/pc: 0x08001234
        """
        entries = _parse_zephyr_backtrace(text)
        
        # Should filter out 0x0 and 0x1 (likely data, not code)
        # Only PC should remain
        assert any(e.address == 0x08001234 for e in entries)
        assert not any(e.address == 0x0 for e in entries)
        assert not any(e.address == 0x1 for e in entries)
    
    def test_parse_no_backtrace(self):
        text = "Normal log output without errors"
        entries = _parse_zephyr_backtrace(text)
        assert len(entries) == 0


# =============================================================================
# GDB Backtrace Parser Tests
# =============================================================================

class TestGDBBacktraceParser:
    def test_parse_full_frame(self):
        text = "#0  0x08001234 in main () at src/main.c:42"
        entries = _parse_gdb_backtrace(text)
        
        assert len(entries) == 1
        assert entries[0].address == 0x08001234
        assert entries[0].function == "main"
        assert entries[0].file == "src/main.c"
        assert entries[0].line == 42
    
    def test_parse_multiple_frames(self):
        text = """
        #0  z_arm_hard_fault () at src/fault.c:42
        #1  0x08001234 in main () at src/main.c:100
        #2  0x08000100 in z_thread_entry () at kernel/thread.c:50
        """
        entries = _parse_gdb_backtrace(text)
        
        assert len(entries) == 3
        assert entries[0].function == "z_arm_hard_fault"
        assert entries[0].file == "src/fault.c"
        assert entries[0].line == 42
        
        assert entries[1].address == 0x08001234
        assert entries[1].function == "main"
        assert entries[1].file == "src/main.c"
        assert entries[1].line == 100
    
    def test_parse_frame_without_address(self):
        text = "#0  main () at src/main.c:42"
        entries = _parse_gdb_backtrace(text)
        
        assert len(entries) == 1
        assert entries[0].address == 0  # No address provided
        assert entries[0].function == "main"
        assert entries[0].file == "src/main.c"
    
    def test_parse_frame_without_source(self):
        text = "#0  0x08001234 in ?? ()"
        entries = _parse_gdb_backtrace(text)
        
        assert len(entries) == 1
        assert entries[0].address == 0x08001234
        assert entries[0].function == "??"
        assert entries[0].file is None
        assert entries[0].line is None
    
    def test_parse_no_backtrace(self):
        text = "Some GDB output without backtrace frames"
        entries = _parse_gdb_backtrace(text)
        assert len(entries) == 0


# =============================================================================
# Toolchain Discovery Tests
# =============================================================================

class TestToolchainDiscovery:
    @patch('eab.backtrace.which_or_sdk')
    def test_get_addr2line_esp32_xtensa(self, mock_which):
        mock_which.return_value = "/path/to/xtensa-esp32-elf-addr2line"
        
        result = _get_addr2line_for_arch('esp32')
        assert result == "/path/to/xtensa-esp32-elf-addr2line"
        mock_which.assert_called()
    
    @patch('eab.backtrace.which_or_sdk')
    def test_get_addr2line_esp32_riscv(self, mock_which):
        mock_which.return_value = "/path/to/riscv32-esp-elf-addr2line"
        
        result = _get_addr2line_for_arch('esp32c6')
        assert result == "/path/to/riscv32-esp-elf-addr2line"
    
    @patch('eab.backtrace.which_or_sdk')
    def test_get_addr2line_arm(self, mock_which):
        mock_which.return_value = "/path/to/arm-none-eabi-addr2line"
        
        result = _get_addr2line_for_arch('arm')
        assert result == "/path/to/arm-none-eabi-addr2line"
    
    @patch('eab.backtrace.which_or_sdk')
    def test_get_addr2line_nrf(self, mock_which):
        mock_which.return_value = "/path/to/arm-zephyr-eabi-addr2line"
        
        result = _get_addr2line_for_arch('nrf5340')
        assert result == "/path/to/arm-zephyr-eabi-addr2line"
    
    @patch('eab.backtrace.which_or_sdk')
    def test_get_addr2line_not_found(self, mock_which):
        mock_which.return_value = None
        
        result = _get_addr2line_for_arch('unknown-arch')
        assert result is None
    
    def test_get_addr2line_explicit_path(self, tmp_path):
        toolchain = tmp_path / "my-addr2line"
        toolchain.write_text("#!/bin/sh\n")
        
        result = _get_addr2line_for_arch('arm', toolchain_path=str(toolchain))
        assert result == str(toolchain)


# =============================================================================
# BacktraceDecoder Tests
# =============================================================================

class TestBacktraceDecoder:
    def test_detect_format_esp_idf(self):
        decoder = BacktraceDecoder()
        text = "Backtrace:0x400d1234:0x3ffb5678"
        
        assert decoder.detect_format(text) == 'esp-idf'
    
    def test_detect_format_zephyr(self):
        decoder = BacktraceDecoder()
        text = "E: Faulting instruction address (r15/pc): 0x0800abcd"
        
        assert decoder.detect_format(text) == 'zephyr'
    
    def test_detect_format_gdb(self):
        decoder = BacktraceDecoder()
        text = "#0  0x08001234 in main () at src/main.c:42"
        
        assert decoder.detect_format(text) == 'gdb'
    
    def test_detect_format_unknown(self):
        decoder = BacktraceDecoder()
        text = "Random text with no backtrace"
        
        assert decoder.detect_format(text) == 'unknown'
    
    def test_parse_esp_backtrace(self):
        decoder = BacktraceDecoder()
        text = "Backtrace:0x400d1234:0x3ffb5678 0x400d5678:0x3ffb9abc"
        
        result = decoder.parse(text)
        
        assert result.format == 'esp-idf'
        assert len(result.entries) == 2
        assert result.entries[0].address == 0x400d1234
    
    def test_parse_zephyr_backtrace(self):
        decoder = BacktraceDecoder()
        text = "E: r15/pc: 0x08001234"
        
        result = decoder.parse(text)
        
        assert result.format == 'zephyr'
        assert len(result.entries) == 1
        assert result.entries[0].address == 0x08001234
    
    def test_parse_gdb_backtrace(self):
        decoder = BacktraceDecoder()
        text = "#0  0x08001234 in main () at src/main.c:42"
        
        result = decoder.parse(text)
        
        assert result.format == 'gdb'
        assert len(result.entries) == 1
        assert result.entries[0].address == 0x08001234
    
    @patch('eab.backtrace.subprocess.run')
    def test_resolve_addresses(self, mock_run, tmp_path):
        # Create fake ELF file
        elf_file = tmp_path / "app.elf"
        elf_file.write_text("fake ELF")
        
        # Mock addr2line output
        mock_result = MagicMock()
        mock_result.returncode = 0
        mock_result.stdout = "main\nsrc/main.c:42\n"
        mock_run.return_value = mock_result
        
        decoder = BacktraceDecoder(elf_path=str(elf_file), arch='arm')
        entries = [BacktraceEntry(address=0x08001234)]
        
        decoder.resolve_addresses(entries)
        
        assert entries[0].function == "main"
        assert entries[0].file == "src/main.c"
        assert entries[0].line == 42
        
        # Verify addr2line was called correctly
        mock_run.assert_called_once()
        call_args = mock_run.call_args[0][0]
        assert '-e' in call_args
        assert str(elf_file) in call_args
        assert '0x8001234' in call_args
    
    @patch('eab.backtrace.subprocess.run')
    def test_resolve_multiple_addresses(self, mock_run, tmp_path):
        elf_file = tmp_path / "app.elf"
        elf_file.write_text("fake ELF")
        
        mock_result = MagicMock()
        mock_result.returncode = 0
        mock_result.stdout = "main\nsrc/main.c:42\nfoo\nsrc/foo.c:10\n"
        mock_run.return_value = mock_result
        
        decoder = BacktraceDecoder(elf_path=str(elf_file), arch='arm')
        entries = [
            BacktraceEntry(address=0x08001234),
            BacktraceEntry(address=0x08005678),
        ]
        
        decoder.resolve_addresses(entries)
        
        assert entries[0].function == "main"
        assert entries[0].file == "src/main.c"
        assert entries[0].line == 42
        
        assert entries[1].function == "foo"
        assert entries[1].file == "src/foo.c"
        assert entries[1].line == 10
    
    @patch('eab.backtrace.subprocess.run')
    def test_resolve_unknown_address(self, mock_run, tmp_path):
        elf_file = tmp_path / "app.elf"
        elf_file.write_text("fake ELF")
        
        mock_result = MagicMock()
        mock_result.returncode = 0
        mock_result.stdout = "??\n??:0\n"
        mock_run.return_value = mock_result
        
        decoder = BacktraceDecoder(elf_path=str(elf_file), arch='arm')
        entries = [BacktraceEntry(address=0x08001234)]
        
        decoder.resolve_addresses(entries)
        
        # Unknown symbols should not be set
        assert entries[0].function is None
        assert entries[0].file is None
        assert entries[0].line is None
    
    def test_resolve_addresses_no_elf(self, tmp_path):
        decoder = BacktraceDecoder(elf_path="/nonexistent/app.elf", arch='arm')
        entries = [BacktraceEntry(address=0x08001234)]
        
        # Should not crash, just skip resolution
        decoder.resolve_addresses(entries)
        
        assert entries[0].function is None
        assert entries[0].file is None
    
    def test_resolve_addresses_no_addr2line(self, tmp_path):
        elf_file = tmp_path / "app.elf"
        elf_file.write_text("fake ELF")
        
        decoder = BacktraceDecoder(elf_path=str(elf_file), arch='arm')
        decoder._addr2line = None  # Simulate missing addr2line
        entries = [BacktraceEntry(address=0x08001234)]
        
        decoder.resolve_addresses(entries)
        
        assert entries[0].function is None
        assert entries[0].file is None
    
    @patch('eab.backtrace.subprocess.run')
    def test_decode_full_pipeline(self, mock_run, tmp_path):
        elf_file = tmp_path / "app.elf"
        elf_file.write_text("fake ELF")
        
        mock_result = MagicMock()
        mock_result.returncode = 0
        mock_result.stdout = "main\nsrc/main.c:42\n"
        mock_run.return_value = mock_result
        
        decoder = BacktraceDecoder(elf_path=str(elf_file), arch='arm')
        text = "Backtrace:0x400d1234:0x3ffb5678"
        
        result = decoder.decode(text)
        
        assert result.format == 'esp-idf'
        assert len(result.entries) == 1
        assert result.entries[0].address == 0x400d1234
        assert result.entries[0].function == "main"
        assert result.entries[0].file == "src/main.c"
        assert result.entries[0].line == 42
    
    def test_format_result_with_source(self):
        decoder = BacktraceDecoder()
        result = BacktraceResult(
            format='esp-idf',
            entries=[
                BacktraceEntry(
                    address=0x400d1234,
                    function='main',
                    file='src/main.c',
                    line=42,
                ),
            ],
        )
        
        output = decoder.format_result(result)
        
        assert "BACKTRACE DECODE (ESP-IDF)" in output
        assert "0x400d1234" in output
        assert "src/main.c:42" in output
        assert "main" in output
    
    def test_format_result_without_source(self):
        decoder = BacktraceDecoder()
        result = BacktraceResult(
            format='zephyr',
            entries=[
                BacktraceEntry(address=0x08001234),
            ],
        )
        
        output = decoder.format_result(result)
        
        assert "BACKTRACE DECODE (ZEPHYR)" in output
        assert "0x08001234" in output
        assert "??" in output
    
    def test_format_result_with_raw(self):
        decoder = BacktraceDecoder()
        result = BacktraceResult(
            format='gdb',
            entries=[
                BacktraceEntry(
                    address=0x08001234,
                    function='main',
                    raw_line='#0  0x08001234 in main () at src/main.c:42',
                ),
            ],
        )
        
        output = decoder.format_result(result, show_raw=True)
        
        assert "raw: #0  0x08001234 in main () at src/main.c:42" in output
    
    def test_format_result_empty(self):
        decoder = BacktraceDecoder()
        result = BacktraceResult(format='unknown', entries=[])
        
        output = decoder.format_result(result)
        
        assert "(no backtrace entries found)" in output
    
    def test_format_result_error(self):
        decoder = BacktraceDecoder()
        result = BacktraceResult(
            format='esp-idf',
            entries=[],
            error="addr2line failed",
        )
        
        output = decoder.format_result(result)
        
        assert "ERROR: addr2line failed" in output


# =============================================================================
# Integration Tests
# =============================================================================

class TestBacktraceIntegration:
    """Test full end-to-end backtrace decode scenarios."""
    
    @patch('eab.backtrace.which_or_sdk')
    @patch('eab.backtrace.subprocess.run')
    def test_esp32_crash_decode(self, mock_run, mock_which, tmp_path):
        """Simulate ESP32 crash with backtrace and decode it."""
        elf_file = tmp_path / "app.elf"
        elf_file.write_text("fake ELF")
        
        # Mock addr2line discovery
        mock_which.return_value = "/usr/bin/xtensa-esp32-elf-addr2line"
        
        # Simulate addr2line output for ESP32 addresses
        mock_result = MagicMock()
        mock_result.returncode = 0
        mock_result.stdout = (
            "app_main\n"
            "/project/main/app_main.c:100\n"
            "main_task\n"
            "/esp-idf/components/freertos/port/port_common.c:141\n"
        )
        mock_run.return_value = mock_result
        
        crash_log = """
        Guru Meditation Error: Core  0 panic'ed (LoadProhibited). Exception was unhandled.
        Core  0 register dump:
        PC      : 0x400d1234  PS      : 0x00060030  A0      : 0x800d5678
        Backtrace:0x400d1234:0x3ffb5678 0x400d5678:0x3ffb9abc
        """
        
        decoder = BacktraceDecoder(elf_path=str(elf_file), arch='esp32')
        result = decoder.decode(crash_log)
        
        assert result.format == 'esp-idf'
        assert len(result.entries) == 2
        assert result.entries[0].function == "app_main"
        assert result.entries[0].file == "/project/main/app_main.c"
        assert result.entries[0].line == 100
    
    @patch('eab.backtrace.which_or_sdk')
    @patch('eab.backtrace.subprocess.run')
    def test_zephyr_hardfault_decode(self, mock_run, mock_which, tmp_path):
        """Simulate Zephyr hard fault and decode it."""
        elf_file = tmp_path / "zephyr.elf"
        elf_file.write_text("fake ELF")
        
        # Mock addr2line discovery
        mock_which.return_value = "/usr/bin/arm-none-eabi-addr2line"
        
        mock_result = MagicMock()
        mock_result.returncode = 0
        mock_result.stdout = (
            "z_arm_hard_fault\n"
            "/zephyr/arch/arm/core/fault.c:42\n"
            "main\n"
            "/project/src/main.c:100\n"
        )
        mock_run.return_value = mock_result
        
        fault_log = """
        *** Booting Zephyr OS build v3.5.0 ***
        E: ***** HARD FAULT *****
        E:   Fault escalation (see below)
        E: r0/a1:  0x00000000  r1/a2:  0x20000100
        E: r2/a3:  0x00000000  r3/a4:  0x00000000
        E: Faulting instruction address (r15/pc): 0x0800abcd
        E: >>> ZEPHYR FATAL ERROR 0: CPU exception on CPU 0
        """
        
        decoder = BacktraceDecoder(elf_path=str(elf_file), arch='nrf5340')
        result = decoder.decode(fault_log)
        
        assert result.format == 'zephyr'
        assert len(result.entries) >= 1
        # PC should be decoded
        pc_entry = next(e for e in result.entries if e.address == 0x0800abcd)
        assert pc_entry.function == "z_arm_hard_fault"
        assert pc_entry.file == "/zephyr/arch/arm/core/fault.c"


# =============================================================================
# Malformed Input Tests
# =============================================================================

class TestMalformedInput:
    def test_empty_input(self):
        decoder = BacktraceDecoder()
        result = decoder.parse("")
        
        assert result.format == 'unknown'
        assert len(result.entries) == 0
    
    def test_garbage_input(self):
        decoder = BacktraceDecoder()
        result = decoder.parse("!@#$%^&*()_+{}|:<>?")
        
        assert result.format == 'unknown'
        assert len(result.entries) == 0
    
    def test_partial_esp_backtrace(self):
        decoder = BacktraceDecoder()
        text = "Backtrace:0x400d"  # Incomplete address (no valid pair)
        result = decoder.parse(text)
        
        # Incomplete address without valid pair should not be detected
        assert result.format == 'unknown'
        assert len(result.entries) == 0
    
    @patch('eab.backtrace.subprocess.run')
    def test_addr2line_failure(self, mock_run, tmp_path):
        elf_file = tmp_path / "app.elf"
        elf_file.write_text("fake ELF")
        
        # Simulate addr2line error
        mock_run.side_effect = subprocess.SubprocessError("addr2line crashed")
        
        decoder = BacktraceDecoder(elf_path=str(elf_file), arch='arm')
        entries = [BacktraceEntry(address=0x08001234)]
        
        # Should not crash
        decoder.resolve_addresses(entries)
        
        assert entries[0].function is None
    
    @patch('eab.backtrace.subprocess.run')
    def test_addr2line_timeout(self, mock_run, tmp_path):
        elf_file = tmp_path / "app.elf"
        elf_file.write_text("fake ELF")
        
        # Simulate timeout
        mock_run.side_effect = subprocess.TimeoutExpired("addr2line", 10.0)
        
        decoder = BacktraceDecoder(elf_path=str(elf_file), arch='arm')
        entries = [BacktraceEntry(address=0x08001234)]
        
        decoder.resolve_addresses(entries)
        
        assert entries[0].function is None
