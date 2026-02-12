"""Tests for DWT profiler module.

Tests DWT register manipulation, hardware breakpoint-based profiling,
ELF symbol parsing, and error handling with mocked pylink.
"""

from __future__ import annotations

from unittest.mock import MagicMock, Mock, patch

import pytest

from eab.dwt_profiler import (
    DEMCR_ADDR,
    DEMCR_TRCENA,
    DWT_CTRL_ADDR,
    DWT_CTRL_CYCCNTENA,
    DWT_CYCCNT_ADDR,
    ProfileResult,
    enable_dwt,
    get_dwt_status,
    profile_function,
    profile_region,
    read_cycle_count,
    reset_cycle_count,
    _find_function_end,
    _parse_symbol_address,
    _wait_for_halt,
)


# =============================================================================
# PyLink Import Tests
# =============================================================================

class TestPyLinkImport:
    """Test that module provides helpful error when pylink is missing."""

    @patch("eab.dwt_profiler.pylink", None)
    def test_enable_dwt_raises_import_error_when_pylink_missing(self):
        """enable_dwt() should raise helpful ImportError if pylink not installed."""
        mock_jlink = MagicMock()

        with pytest.raises(ImportError) as exc_info:
            enable_dwt(mock_jlink)

        assert "pylink module not found" in str(exc_info.value).lower()
        assert "pip install pylink-square" in str(exc_info.value)

    @patch("eab.dwt_profiler.pylink", None)
    def test_read_cycle_count_raises_import_error_when_pylink_missing(self):
        """read_cycle_count() should raise helpful ImportError if pylink not installed."""
        mock_jlink = MagicMock()

        with pytest.raises(ImportError) as exc_info:
            read_cycle_count(mock_jlink)

        assert "pylink module not found" in str(exc_info.value).lower()


# =============================================================================
# DWT Register Manipulation Tests
# =============================================================================

class TestEnableDWT:
    """Test enable_dwt() register operations."""

    @patch("eab.dwt_profiler.pylink", MagicMock())
    def test_enable_both_demcr_and_dwt_ctrl(self):
        """enable_dwt() should set TRCENA in DEMCR and CYCCNTENA in DWT_CTRL."""
        mock_jlink = MagicMock()

        # Initial reads: both disabled
        mock_jlink.memory_read32.side_effect = [
            [0x00000000],  # DEMCR (TRCENA=0)
            [0x00000000],  # DWT_CTRL (CYCCNTENA=0)
            [DEMCR_TRCENA],  # DEMCR verify (TRCENA=1)
            [DWT_CTRL_CYCCNTENA],  # DWT_CTRL verify (CYCCNTENA=1)
        ]

        result = enable_dwt(mock_jlink)

        # Should write both registers
        assert mock_jlink.memory_write32.call_count == 2
        
        # Verify DEMCR write
        call_args = mock_jlink.memory_write32.call_args_list[0]
        assert call_args[0][0] == DEMCR_ADDR
        assert call_args[0][1][0] & DEMCR_TRCENA

        # Verify DWT_CTRL write
        call_args = mock_jlink.memory_write32.call_args_list[1]
        assert call_args[0][0] == DWT_CTRL_ADDR
        assert call_args[0][1][0] & DWT_CTRL_CYCCNTENA

        assert result == True

    @patch("eab.dwt_profiler.pylink", MagicMock())
    def test_enable_when_already_enabled(self):
        """enable_dwt() should skip writes if already enabled."""
        mock_jlink = MagicMock()

        # Initial reads: both already enabled
        mock_jlink.memory_read32.side_effect = [
            [DEMCR_TRCENA],  # DEMCR (TRCENA=1)
            [DWT_CTRL_CYCCNTENA],  # DWT_CTRL (CYCCNTENA=1)
            [DEMCR_TRCENA],  # DEMCR verify
            [DWT_CTRL_CYCCNTENA],  # DWT_CTRL verify
        ]

        result = enable_dwt(mock_jlink)

        # Should not write (already enabled)
        assert mock_jlink.memory_write32.call_count == 0
        assert result == True

    @patch("eab.dwt_profiler.pylink", MagicMock())
    def test_enable_fails_if_verification_fails(self):
        """enable_dwt() should return False if bits don't stick."""
        mock_jlink = MagicMock()

        # Initial reads: disabled, then verification shows still disabled
        mock_jlink.memory_read32.side_effect = [
            [0x00000000],  # DEMCR (TRCENA=0)
            [0x00000000],  # DWT_CTRL (CYCCNTENA=0)
            [0x00000000],  # DEMCR verify (still 0 — failed)
            [0x00000000],  # DWT_CTRL verify
        ]

        result = enable_dwt(mock_jlink)

        assert result == False

    @patch("eab.dwt_profiler.pylink", MagicMock())
    def test_enable_raises_on_memory_error(self):
        """enable_dwt() should raise on memory access failure."""
        mock_jlink = MagicMock()
        mock_jlink.memory_read32.side_effect = Exception("Memory read failed")

        with pytest.raises(Exception) as exc_info:
            enable_dwt(mock_jlink)

        assert "Memory read failed" in str(exc_info.value)


class TestReadCycleCount:
    """Test read_cycle_count() functionality."""

    @patch("eab.dwt_profiler.pylink", MagicMock())
    def test_read_returns_32bit_value(self):
        """read_cycle_count() should return DWT_CYCCNT value."""
        mock_jlink = MagicMock()
        mock_jlink.memory_read32.return_value = [0x12345678]

        cycles = read_cycle_count(mock_jlink)

        mock_jlink.memory_read32.assert_called_once_with(DWT_CYCCNT_ADDR, 1)
        assert cycles == 0x12345678

    @patch("eab.dwt_profiler.pylink", MagicMock())
    def test_read_raises_on_memory_error(self):
        """read_cycle_count() should raise on memory read failure."""
        mock_jlink = MagicMock()
        mock_jlink.memory_read32.side_effect = Exception("Read failed")

        with pytest.raises(Exception) as exc_info:
            read_cycle_count(mock_jlink)

        assert "Read failed" in str(exc_info.value)


class TestResetCycleCount:
    """Test reset_cycle_count() functionality."""

    @patch("eab.dwt_profiler.pylink", MagicMock())
    def test_reset_writes_zero(self):
        """reset_cycle_count() should write 0 to DWT_CYCCNT."""
        mock_jlink = MagicMock()

        reset_cycle_count(mock_jlink)

        mock_jlink.memory_write32.assert_called_once_with(DWT_CYCCNT_ADDR, [0])

    @patch("eab.dwt_profiler.pylink", MagicMock())
    def test_reset_raises_on_memory_error(self):
        """reset_cycle_count() should raise on memory write failure."""
        mock_jlink = MagicMock()
        mock_jlink.memory_write32.side_effect = Exception("Write failed")

        with pytest.raises(Exception) as exc_info:
            reset_cycle_count(mock_jlink)

        assert "Write failed" in str(exc_info.value)


class TestGetDWTStatus:
    """Test get_dwt_status() diagnostics."""

    @patch("eab.dwt_profiler.pylink", MagicMock())
    def test_get_status_returns_all_registers(self):
        """get_dwt_status() should return dict with DEMCR, DWT_CTRL, DWT_CYCCNT."""
        mock_jlink = MagicMock()
        mock_jlink.memory_read32.side_effect = [
            [0xABCD0000],  # DEMCR
            [0x00001234],  # DWT_CTRL
            [0x56789ABC],  # DWT_CYCCNT
        ]

        status = get_dwt_status(mock_jlink)

        assert status == {
            "DEMCR": 0xABCD0000,
            "DWT_CTRL": 0x00001234,
            "DWT_CYCCNT": 0x56789ABC,
        }

    @patch("eab.dwt_profiler.pylink", MagicMock())
    def test_get_status_raises_on_memory_error(self):
        """get_dwt_status() should raise on memory read failure."""
        mock_jlink = MagicMock()
        mock_jlink.memory_read32.side_effect = Exception("Read failed")

        with pytest.raises(Exception) as exc_info:
            get_dwt_status(mock_jlink)

        assert "Read failed" in str(exc_info.value)


# =============================================================================
# ELF Symbol Parsing Tests
# =============================================================================

class TestParseSymbolAddress:
    """Test ELF symbol parsing with arm-none-eabi-nm."""

    @patch("eab.dwt_profiler._which_or_sdk")
    @patch("eab.dwt_profiler.subprocess.run")
    def test_parse_finds_function_address(self, mock_run, mock_which):
        """_parse_symbol_address() should parse nm output for function address."""
        mock_which.return_value = "/usr/bin/arm-none-eabi-nm"

        # Mock nm output
        mock_result = MagicMock()
        mock_result.stdout = (
            "00000000 T _start\n"
            "00001234 T my_function\n"
            "00005678 T another_function\n"
        )
        mock_run.return_value = mock_result

        addr = _parse_symbol_address("/path/to/app.elf", "my_function")

        assert addr == 0x1234
        mock_run.assert_called_once()
        assert mock_run.call_args[0][0] == [
            "/usr/bin/arm-none-eabi-nm",
            "-C",
            "/path/to/app.elf",
        ]

    @patch("eab.dwt_profiler._which_or_sdk")
    @patch("eab.dwt_profiler.subprocess.run")
    def test_parse_handles_weak_symbols(self, mock_run, mock_which):
        """_parse_symbol_address() should accept weak symbols (W)."""
        mock_which.return_value = "/usr/bin/arm-none-eabi-nm"

        mock_result = MagicMock()
        mock_result.stdout = "00002000 W weak_function\n"
        mock_run.return_value = mock_result

        addr = _parse_symbol_address("/path/to/app.elf", "weak_function")

        assert addr == 0x2000

    @patch("eab.dwt_profiler._which_or_sdk")
    @patch("eab.dwt_profiler.subprocess.run")
    def test_parse_returns_none_if_not_found(self, mock_run, mock_which):
        """_parse_symbol_address() should return None if symbol not found."""
        mock_which.return_value = "/usr/bin/arm-none-eabi-nm"

        mock_result = MagicMock()
        mock_result.stdout = "00001234 T other_function\n"
        mock_run.return_value = mock_result

        addr = _parse_symbol_address("/path/to/app.elf", "missing_function")

        assert addr is None

    @patch("eab.dwt_profiler._which_or_sdk")
    def test_parse_raises_if_nm_not_found(self, mock_which_or_sdk):
        """_parse_symbol_address() should raise FileNotFoundError if nm not on PATH."""
        mock_which_or_sdk.return_value = None

        with pytest.raises(FileNotFoundError) as exc_info:
            _parse_symbol_address("/path/to/app.elf", "my_function")

        assert "not found" in str(exc_info.value).lower()

    @patch("eab.dwt_profiler._which_or_sdk")
    @patch("eab.dwt_profiler.subprocess.run")
    def test_parse_raises_on_subprocess_error(self, mock_run, mock_which):
        """_parse_symbol_address() should raise on subprocess failure."""
        mock_which.return_value = "/usr/bin/arm-none-eabi-nm"
        mock_run.side_effect = Exception("nm failed")

        with pytest.raises(Exception) as exc_info:
            _parse_symbol_address("/path/to/app.elf", "my_function")

        assert "nm failed" in str(exc_info.value)


class TestFindFunctionEnd:
    """Test function end address detection via objdump."""

    @patch("eab.dwt_profiler._which_or_sdk")
    @patch("eab.dwt_profiler.subprocess.run")
    def test_find_end_from_objdump(self, mock_run, mock_which):
        """_find_function_end() should parse objdump to find next function."""
        mock_which.return_value = "/usr/bin/arm-none-eabi-objdump"

        mock_result = MagicMock()
        mock_result.stdout = (
            "00001234 <my_function>:\n"
            "    1234:  push {r4, lr}\n"
            "    1236:  movs r0, #42\n"
            "    1238:  pop {r4, pc}\n"
            "0000123c <next_function>:\n"
            "    123c:  bx lr\n"
        )
        mock_run.return_value = mock_result

        end_addr = _find_function_end("/path/to/app.elf", "my_function", 0x1234)

        # Should return address of next_function (0x123c)
        assert end_addr == 0x123c

    @patch("eab.dwt_profiler._which_or_sdk")
    @patch("eab.dwt_profiler.subprocess.run")
    def test_find_end_when_last_function(self, mock_run, mock_which):
        """_find_function_end() should use last_addr + 4 if no next function."""
        mock_which.return_value = "/usr/bin/arm-none-eabi-objdump"

        mock_result = MagicMock()
        mock_result.stdout = (
            "00001234 <my_function>:\n"
            "    1234:  push {r4, lr}\n"
            "    1236:  movs r0, #42\n"
            "    1238:  pop {r4, pc}\n"
        )
        mock_run.return_value = mock_result

        end_addr = _find_function_end("/path/to/app.elf", "my_function", 0x1234)

        # Should return last instruction + 4
        assert end_addr == 0x123c  # 0x1238 + 4

    @patch("eab.dwt_profiler._which_or_sdk")
    def test_find_end_fallback_when_objdump_missing(self, mock_which):
        """_find_function_end() should use heuristic if objdump not found."""
        mock_which.return_value = None

        end_addr = _find_function_end("/path/to/app.elf", "my_function", 0x1234)

        # Fallback: start + 32 bytes
        assert end_addr == 0x1234 + 32

    @patch("eab.dwt_profiler._which_or_sdk")
    @patch("eab.dwt_profiler.subprocess.run")
    def test_find_end_fallback_on_subprocess_error(self, mock_run, mock_which):
        """_find_function_end() should use heuristic on objdump failure."""
        mock_which.return_value = "/usr/bin/arm-none-eabi-objdump"
        mock_run.side_effect = Exception("objdump failed")

        end_addr = _find_function_end("/path/to/app.elf", "my_function", 0x1234)

        assert end_addr == 0x1234 + 32


# =============================================================================
# Wait for Halt Tests
# =============================================================================

class TestWaitForHalt:
    """Test _wait_for_halt() polling logic."""

    def test_wait_returns_true_when_halted(self):
        """_wait_for_halt() should return True if target halts."""
        mock_jlink = MagicMock()
        mock_jlink.halted.return_value = True

        result = _wait_for_halt(mock_jlink, timeout_s=1.0)

        assert result == True
        mock_jlink.halted.assert_called()

    def test_wait_returns_false_on_timeout(self):
        """_wait_for_halt() should return False if timeout expires."""
        mock_jlink = MagicMock()
        mock_jlink.halted.return_value = False

        result = _wait_for_halt(mock_jlink, timeout_s=0.1)

        assert result == False

    def test_wait_polls_until_halted(self):
        """_wait_for_halt() should poll multiple times before returning True."""
        mock_jlink = MagicMock()
        # Return False twice, then True
        mock_jlink.halted.side_effect = [False, False, True]

        result = _wait_for_halt(mock_jlink, timeout_s=1.0)

        assert result == True
        assert mock_jlink.halted.call_count == 3


# =============================================================================
# Profile Region Tests
# =============================================================================

class TestProfileRegion:
    """Test profile_region() hardware breakpoint profiling."""

    @patch("eab.dwt_profiler.pylink", MagicMock())
    @patch("eab.dwt_profiler.enable_dwt")
    @patch("eab.dwt_profiler.reset_cycle_count")
    @patch("eab.dwt_profiler.read_cycle_count")
    @patch("eab.dwt_profiler._wait_for_halt")
    def test_profile_region_success(
        self, mock_wait, mock_read_cycles, mock_reset, mock_enable
    ):
        """profile_region() should measure cycles between breakpoints."""
        mock_jlink = MagicMock()
        mock_enable.return_value = True
        mock_wait.return_value = True  # Both breakpoints hit
        mock_read_cycles.return_value = 100000  # 100k cycles
        mock_jlink.register_read.side_effect = [0x1234, 0x5678]  # PC values
        mock_jlink.breakpoint_set.side_effect = [1, 2]  # Breakpoint handles

        result = profile_region(
            mock_jlink,
            start_addr=0x1234,
            end_addr=0x5678,
            cpu_freq_hz=64_000_000,  # 64 MHz
            timeout_s=5.0,
        )

        # Verify breakpoints were set
        assert mock_jlink.breakpoint_set.call_count == 2
        assert mock_jlink.breakpoint_set.call_args_list[0][0][0] == 0x1234
        assert mock_jlink.breakpoint_set.call_args_list[1][0][0] == 0x5678

        # Verify cycle counter was reset at start
        mock_reset.assert_called_once()

        # Verify results
        assert result.address == 0x1234
        assert result.cycles == 100000
        assert result.cpu_freq_hz == 64_000_000
        # time_us = (100000 / 64_000_000) * 1_000_000 = 1562.5 µs
        assert abs(result.time_us - 1562.5) < 0.1

        # Verify cleanup
        mock_jlink.breakpoint_clear_all.assert_called()

    @patch("eab.dwt_profiler.pylink", MagicMock())
    @patch("eab.dwt_profiler.enable_dwt")
    def test_profile_region_raises_if_dwt_unavailable(self, mock_enable):
        """profile_region() should raise RuntimeError if DWT can't be enabled."""
        mock_jlink = MagicMock()
        mock_enable.return_value = False  # DWT not available

        with pytest.raises(RuntimeError) as exc_info:
            profile_region(
                mock_jlink,
                start_addr=0x1234,
                end_addr=0x5678,
                cpu_freq_hz=64_000_000,
            )

        assert "DWT not available" in str(exc_info.value)

    @patch("eab.dwt_profiler.pylink", MagicMock())
    @patch("eab.dwt_profiler.enable_dwt")
    @patch("eab.dwt_profiler._wait_for_halt")
    def test_profile_region_timeout_at_start(self, mock_wait, mock_enable):
        """profile_region() should raise TimeoutError if start breakpoint not hit."""
        mock_jlink = MagicMock()
        mock_enable.return_value = True
        mock_wait.return_value = False  # Timeout

        with pytest.raises(TimeoutError) as exc_info:
            profile_region(
                mock_jlink,
                start_addr=0x1234,
                end_addr=0x5678,
                cpu_freq_hz=64_000_000,
                timeout_s=1.0,
            )

        assert "start breakpoint" in str(exc_info.value).lower()
        assert "0x00001234" in str(exc_info.value)

    @patch("eab.dwt_profiler.pylink", MagicMock())
    @patch("eab.dwt_profiler.enable_dwt")
    @patch("eab.dwt_profiler.reset_cycle_count")
    @patch("eab.dwt_profiler._wait_for_halt")
    def test_profile_region_timeout_at_end(
        self, mock_wait, mock_reset, mock_enable
    ):
        """profile_region() should raise TimeoutError if end breakpoint not hit."""
        mock_jlink = MagicMock()
        mock_enable.return_value = True
        # First call (start) succeeds, second call (end) times out
        mock_wait.side_effect = [True, False]
        mock_jlink.register_read.return_value = 0x1234

        with pytest.raises(TimeoutError) as exc_info:
            profile_region(
                mock_jlink,
                start_addr=0x1234,
                end_addr=0x5678,
                cpu_freq_hz=64_000_000,
                timeout_s=1.0,
            )

        assert "end breakpoint" in str(exc_info.value).lower()
        assert "0x00005678" in str(exc_info.value)

    @patch("eab.dwt_profiler.pylink", MagicMock())
    @patch("eab.dwt_profiler.enable_dwt")
    @patch("eab.dwt_profiler.reset_cycle_count")
    @patch("eab.dwt_profiler.read_cycle_count")
    @patch("eab.dwt_profiler._wait_for_halt")
    def test_profile_region_cleans_up_breakpoints_on_error(
        self, mock_wait, mock_read, mock_reset, mock_enable
    ):
        """profile_region() should clear breakpoints even on error."""
        mock_jlink = MagicMock()
        mock_enable.return_value = True
        mock_wait.return_value = True
        mock_read.side_effect = Exception("Read failed")
        mock_jlink.register_read.side_effect = [0x1234, 0x5678]

        with pytest.raises(Exception):
            profile_region(
                mock_jlink,
                start_addr=0x1234,
                end_addr=0x5678,
                cpu_freq_hz=64_000_000,
            )

        # Should still clear breakpoints in finally block
        mock_jlink.breakpoint_clear_all.assert_called()


# =============================================================================
# Profile Function Tests
# =============================================================================

class TestProfileFunction:
    """Test profile_function() ELF parsing + profiling."""

    @patch("eab.dwt_profiler.pylink", MagicMock())
    @patch("eab.dwt_profiler._parse_symbol_address")
    @patch("eab.dwt_profiler._find_function_end")
    @patch("eab.dwt_profiler.profile_region")
    def test_profile_function_success(
        self, mock_profile_region, mock_find_end, mock_parse_addr
    ):
        """profile_function() should parse ELF and delegate to profile_region()."""
        mock_jlink = MagicMock()
        mock_parse_addr.return_value = 0x1234
        mock_find_end.return_value = 0x1260

        # Mock profile_region result
        mock_profile_region.return_value = ProfileResult(
            function="region_0x00001234_to_0x00001260",
            address=0x1234,
            cycles=50000,
            time_us=781.25,
            cpu_freq_hz=64_000_000,
        )

        result = profile_function(
            mock_jlink,
            elf_path="/path/to/app.elf",
            function_name="my_function",
            cpu_freq_hz=64_000_000,
            timeout_s=5.0,
        )

        # Verify symbol parsing
        mock_parse_addr.assert_called_once_with("/path/to/app.elf", "my_function")
        mock_find_end.assert_called_once_with("/path/to/app.elf", "my_function", 0x1234)

        # Verify profile_region was called with correct addresses
        mock_profile_region.assert_called_once_with(
            mock_jlink,
            start_addr=0x1234,
            end_addr=0x1260,
            cpu_freq_hz=64_000_000,
            timeout_s=5.0,
        )

        # Verify result has updated function name
        assert result.function == "my_function"
        assert result.address == 0x1234
        assert result.cycles == 50000
        assert result.time_us == 781.25

    @patch("eab.dwt_profiler.pylink", MagicMock())
    @patch("eab.dwt_profiler._parse_symbol_address")
    def test_profile_function_raises_if_symbol_not_found(self, mock_parse_addr):
        """profile_function() should raise ValueError if function not in ELF."""
        mock_jlink = MagicMock()
        mock_parse_addr.return_value = None  # Symbol not found

        with pytest.raises(ValueError) as exc_info:
            profile_function(
                mock_jlink,
                elf_path="/path/to/app.elf",
                function_name="missing_function",
                cpu_freq_hz=64_000_000,
            )

        assert "not found in ELF" in str(exc_info.value)
        assert "missing_function" in str(exc_info.value)

    @patch("eab.dwt_profiler.pylink", MagicMock())
    @patch("eab.dwt_profiler._parse_symbol_address")
    @patch("eab.dwt_profiler._find_function_end")
    @patch("eab.dwt_profiler.profile_region")
    def test_profile_function_propagates_timeout_error(
        self, mock_profile_region, mock_find_end, mock_parse_addr
    ):
        """profile_function() should propagate TimeoutError from profile_region()."""
        mock_jlink = MagicMock()
        mock_parse_addr.return_value = 0x1234
        mock_find_end.return_value = 0x1260
        mock_profile_region.side_effect = TimeoutError("Timeout waiting for breakpoint")

        with pytest.raises(TimeoutError) as exc_info:
            profile_function(
                mock_jlink,
                elf_path="/path/to/app.elf",
                function_name="my_function",
                cpu_freq_hz=64_000_000,
            )

        assert "breakpoint" in str(exc_info.value).lower()


# =============================================================================
# ProfileResult Dataclass Tests
# =============================================================================

class TestProfileResult:
    """Test ProfileResult dataclass."""

    def test_profile_result_creation(self):
        """ProfileResult should store all fields correctly."""
        result = ProfileResult(
            function="test_function",
            address=0x1234,
            cycles=100000,
            time_us=1562.5,
            cpu_freq_hz=64_000_000,
        )

        assert result.function == "test_function"
        assert result.address == 0x1234
        assert result.cycles == 100000
        assert result.time_us == 1562.5
        assert result.cpu_freq_hz == 64_000_000

    def test_profile_result_is_frozen(self):
        """ProfileResult should be immutable (frozen dataclass)."""
        result = ProfileResult(
            function="test",
            address=0x1000,
            cycles=1000,
            time_us=10.0,
            cpu_freq_hz=100_000_000,
        )

        with pytest.raises(AttributeError):
            result.cycles = 2000  # type: ignore


# =============================================================================
# OpenOCD DWT Backend Tests
# =============================================================================

class TestOcdRead32:
    """Test _ocd_read32 OpenOCD telnet register read."""

    def test_parses_mdw_response(self):
        from eab.dwt_profiler import _ocd_read32
        bridge = MagicMock()
        bridge.cmd.return_value = "0xe0001004: 00000042"
        assert _ocd_read32(bridge, 0xE0001004) == 0x42

    def test_raises_on_unparseable_response(self):
        from eab.dwt_profiler import _ocd_read32
        bridge = MagicMock()
        bridge.cmd.return_value = "error: target not halted"
        with pytest.raises(RuntimeError, match="Failed to parse mdw"):
            _ocd_read32(bridge, 0xE0001004)


class TestOcdWrite32:
    """Test _ocd_write32 OpenOCD telnet register write."""

    def test_sends_mww_command(self):
        from eab.dwt_profiler import _ocd_write32
        bridge = MagicMock()
        _ocd_write32(bridge, 0xE0001004, 0)
        bridge.cmd.assert_called_once_with("mww 0xE0001004 0x00000000", telnet_port=4444)


class TestEnableDwtOpenocd:
    """Test enable_dwt_openocd via mocked bridge."""

    def test_enables_trcena_and_cyccntena(self):
        from eab.dwt_profiler import enable_dwt_openocd
        bridge = MagicMock()
        # First reads: DEMCR=0, DWT_CTRL=0 (disabled)
        # After writes, verification reads return enabled bits
        bridge.cmd.side_effect = [
            "0xe000edfc: 00000000",  # read DEMCR
            "",                       # write DEMCR
            "0xe0001000: 00000000",  # read DWT_CTRL
            "",                       # write DWT_CTRL
            "0xe000edfc: 01000000",  # verify DEMCR (TRCENA set)
            "0xe0001000: 00000001",  # verify DWT_CTRL (CYCCNTENA set)
        ]
        assert enable_dwt_openocd(bridge) is True

    def test_returns_false_on_verify_failure(self):
        from eab.dwt_profiler import enable_dwt_openocd
        bridge = MagicMock()
        bridge.cmd.side_effect = [
            "0xe000edfc: 00000000",  # read DEMCR
            "",                       # write DEMCR
            "0xe0001000: 00000000",  # read DWT_CTRL
            "",                       # write DWT_CTRL
            "0xe000edfc: 00000000",  # verify DEMCR (still 0 — failed)
            "0xe0001000: 00000000",  # verify DWT_CTRL (still 0)
        ]
        assert enable_dwt_openocd(bridge) is False


class TestReadCycleCountOpenocd:
    """Test read_cycle_count_openocd."""

    def test_reads_cyccnt(self):
        from eab.dwt_profiler import read_cycle_count_openocd
        bridge = MagicMock()
        bridge.cmd.return_value = "0xe0001004: 0000ffff"
        assert read_cycle_count_openocd(bridge) == 0xFFFF


class TestResetCycleCountOpenocd:
    """Test reset_cycle_count_openocd."""

    def test_writes_zero_to_cyccnt(self):
        from eab.dwt_profiler import reset_cycle_count_openocd
        bridge = MagicMock()
        reset_cycle_count_openocd(bridge)
        bridge.cmd.assert_called_once_with("mww 0xE0001004 0x00000000", telnet_port=4444)


class TestGetDwtStatusOpenocd:
    """Test get_dwt_status_openocd."""

    def test_returns_register_dict(self):
        from eab.dwt_profiler import get_dwt_status_openocd
        bridge = MagicMock()
        bridge.cmd.side_effect = [
            "0xe000edfc: 01000000",  # DEMCR
            "0xe0001000: 40000001",  # DWT_CTRL
            "0xe0001004: 00001234",  # DWT_CYCCNT
        ]
        status = get_dwt_status_openocd(bridge)
        assert status["DEMCR"] == 0x01000000
        assert status["DWT_CTRL"] == 0x40000001
        assert status["DWT_CYCCNT"] == 0x1234
