"""
Unit tests for STM32 commands in eabctl.

These tests verify command generation, chip profile behavior, and error handling
WITHOUT requiring actual hardware. Hardware integration tests are separate.
"""
from __future__ import annotations

import json
import subprocess
import tempfile
from pathlib import Path
from unittest.mock import MagicMock, patch

import pytest

from eab.chips import STM32Profile, get_chip_profile
from eab.chips.base import ChipFamily
from eab.gdb_bridge import _default_gdb_for_chip


class TestSTM32Profile:
    """Test STM32Profile chip definition."""

    @pytest.fixture
    def profile(self) -> STM32Profile:
        return STM32Profile(variant="stm32l4")

    def test_family_is_stm32(self, profile: STM32Profile):
        assert profile.family == ChipFamily.STM32

    def test_name_includes_variant(self, profile: STM32Profile):
        assert "STM32" in profile.name
        assert "L4" in profile.name.upper()

    def test_boot_patterns_defined(self, profile: STM32Profile):
        patterns = profile.boot_patterns
        assert "HAL_Init" in patterns
        assert "SystemInit" in patterns
        assert "Reset_Handler" in patterns

    def test_crash_patterns_include_cortex_m_faults(self, profile: STM32Profile):
        patterns = profile.crash_patterns
        assert "HardFault_Handler" in patterns
        assert "MemManage_Handler" in patterns
        assert "BusFault_Handler" in patterns
        assert "UsageFault_Handler" in patterns

    def test_watchdog_patterns(self, profile: STM32Profile):
        patterns = profile.watchdog_patterns
        assert "IWDG" in patterns
        assert "WWDG" in patterns

    def test_bootloader_patterns(self, profile: STM32Profile):
        patterns = profile.bootloader_patterns
        assert "DFU mode" in patterns
        assert "System memory boot" in patterns


class TestSTM32FlashCommands:
    """Test flash command generation for STM32."""

    @pytest.fixture
    def profile(self) -> STM32Profile:
        return STM32Profile(variant="stm32l4")

    def test_flash_command_st_flash(self, profile: STM32Profile):
        cmd = profile.get_flash_command(
            firmware_path="/path/to/firmware.bin",
            port="",  # ST-Link doesn't use port
            address="0x08000000",
            tool="st-flash",
        )
        assert cmd.tool == "st-flash"
        assert "--reset" in cmd.args
        assert "write" in cmd.args
        assert "/path/to/firmware.bin" in cmd.args
        assert "0x08000000" in cmd.args
        assert cmd.timeout == 120.0

    def test_flash_command_stm32programmer(self, profile: STM32Profile):
        cmd = profile.get_flash_command(
            firmware_path="/path/to/firmware.bin",
            port="",
            address="0x08004000",
            tool="stm32programmer",
        )
        # Tool should be STM32_Programmer_CLI (may be full path)
        assert "STM32_Programmer_CLI" in cmd.tool
        assert "-c" in cmd.args
        assert "port=SWD" in cmd.args
        assert "-w" in cmd.args
        assert "/path/to/firmware.bin" in cmd.args
        assert "0x08004000" in cmd.args
        assert "-v" in cmd.args  # Verify
        assert "-rst" in cmd.args  # Reset after

    def test_flash_default_address_is_0x08000000(self, profile: STM32Profile):
        cmd = profile.get_flash_command(
            firmware_path="test.bin",
            port="",
        )
        assert "0x08000000" in cmd.args

    def test_flash_connect_under_reset_uses_cubeprog(self, profile: STM32Profile):
        """Test connect-under-reset automatically uses STM32CubeProgrammer.

        st-flash has a known bug (github.com/stlink-org/stlink/issues/1260)
        where it falsely reports "NRST is not connected". We prefer
        STM32CubeProgrammer for connect-under-reset operations.
        """
        cmd = profile.get_flash_command(
            firmware_path="/path/to/firmware.bin",
            port="",
            address="0x08000000",
            connect_under_reset=True,
        )
        # Should use STM32CubeProgrammer, not st-flash (may be full path)
        assert "STM32_Programmer_CLI" in cmd.tool
        assert "mode=UR" in cmd.args[1]
        assert "reset=HWrst" in cmd.args[1]

    def test_flash_stm32programmer_explicit(self, profile: STM32Profile):
        """Test explicit STM32CubeProgrammer selection."""
        cmd = profile.get_flash_command(
            firmware_path="/path/to/firmware.bin",
            port="",
            address="0x08000000",
            tool="stm32programmer",
        )
        # Tool should be STM32_Programmer_CLI (may be full path)
        assert "STM32_Programmer_CLI" in cmd.tool
        assert "port=SWD" in cmd.args[1]


class TestSTM32EraseCommands:
    """Test erase command generation for STM32."""

    @pytest.fixture
    def profile(self) -> STM32Profile:
        return STM32Profile(variant="stm32l4")

    def test_erase_command_st_flash(self, profile: STM32Profile):
        cmd = profile.get_erase_command(port="", tool="st-flash")
        assert cmd.tool == "st-flash"
        assert "erase" in cmd.args
        assert cmd.timeout == 60.0

    def test_erase_command_stm32programmer(self, profile: STM32Profile):
        cmd = profile.get_erase_command(port="", tool="stm32programmer")
        # Tool should be STM32_Programmer_CLI (may be full path)
        assert "STM32_Programmer_CLI" in cmd.tool
        assert "-c" in cmd.args
        assert "port=SWD" in cmd.args
        assert "-e" in cmd.args
        assert "all" in cmd.args

    def test_erase_connect_under_reset_uses_cubeprog(self, profile: STM32Profile):
        """Test connect-under-reset automatically uses STM32CubeProgrammer.

        st-flash has a known bug (github.com/stlink-org/stlink/issues/1260)
        where it falsely reports "NRST is not connected". We prefer
        STM32CubeProgrammer for connect-under-reset operations.
        """
        cmd = profile.get_erase_command(port="", connect_under_reset=True)
        # Should use STM32CubeProgrammer, not st-flash (may be full path)
        assert "STM32_Programmer_CLI" in cmd.tool
        assert "mode=UR" in cmd.args[1]
        assert "reset=HWrst" in cmd.args[1]

    def test_erase_stm32programmer_explicit(self, profile: STM32Profile):
        """Test explicit STM32CubeProgrammer selection."""
        cmd = profile.get_erase_command(port="", tool="stm32programmer")
        # Tool should be STM32_Programmer_CLI (may be full path)
        assert "STM32_Programmer_CLI" in cmd.tool
        assert "-e" in cmd.args
        assert "all" in cmd.args


class TestSTM32ChipInfo:
    """Test chip info command generation for STM32."""

    @pytest.fixture
    def profile(self) -> STM32Profile:
        return STM32Profile(variant="stm32l4")

    def test_chip_info_command(self, profile: STM32Profile):
        cmd = profile.get_chip_info_command(port="")
        assert cmd.tool == "st-info"
        assert "--probe" in cmd.args
        assert cmd.timeout == 30.0


class TestSTM32OpenOCDConfig:
    """Test OpenOCD configuration generation for STM32."""

    @pytest.fixture
    def profile(self) -> STM32Profile:
        return STM32Profile(variant="stm32l4")

    def test_openocd_config_stlink(self, profile: STM32Profile):
        config = profile.get_openocd_config(adapter="stlink")
        assert config.interface_cfg == "interface/stlink.cfg"
        assert config.transport == "hla_swd"
        assert "stm32l4x.cfg" in config.target_cfg
        assert "reset_config srst_only" in config.extra_commands

    def test_openocd_config_jlink(self, profile: STM32Profile):
        config = profile.get_openocd_config(adapter="jlink")
        assert config.interface_cfg == "interface/jlink.cfg"

    @pytest.mark.parametrize("variant,expected_target", [
        ("stm32f1", "stm32f1x.cfg"),
        ("stm32f3", "stm32f3x.cfg"),
        ("stm32f4", "stm32f4x.cfg"),
        ("stm32l4", "stm32l4x.cfg"),
        ("stm32h7", "stm32h7x.cfg"),
        ("stm32g0", "stm32g0x.cfg"),
        ("stm32g4", "stm32g4x.cfg"),
    ])
    def test_openocd_target_mapping(self, variant: str, expected_target: str):
        profile = STM32Profile(variant=variant)
        config = profile.get_openocd_config()
        assert expected_target in config.target_cfg


class TestSTM32ResetSequences:
    """Test reset sequence definitions for STM32."""

    @pytest.fixture
    def profile(self) -> STM32Profile:
        return STM32Profile(variant="stm32l4")

    def test_hard_reset_sequence(self, profile: STM32Profile):
        sequences = profile.reset_sequences
        assert "hard_reset" in sequences
        hard_reset = sequences["hard_reset"]
        assert len(hard_reset) >= 2

    def test_soft_reset_sequence(self, profile: STM32Profile):
        sequences = profile.reset_sequences
        assert "soft_reset" in sequences

    def test_bootloader_sequence(self, profile: STM32Profile):
        sequences = profile.reset_sequences
        assert "bootloader" in sequences


class TestGDBBridgeARM:
    """Test ARM GDB detection for STM32."""

    def test_stm32_returns_arm_gdb_path(self):
        with patch("shutil.which") as mock_which:
            mock_which.side_effect = lambda name: f"/usr/bin/{name}" if name == "arm-none-eabi-gdb" else None
            result = _default_gdb_for_chip("stm32l4")
            assert result == "/usr/bin/arm-none-eabi-gdb"
            mock_which.assert_any_call("arm-none-eabi-gdb")

    def test_stm32_falls_back_to_gdb_multiarch(self):
        with patch("shutil.which") as mock_which:
            def which_side_effect(name):
                if name == "gdb-multiarch":
                    return "/usr/bin/gdb-multiarch"
                return None
            mock_which.side_effect = which_side_effect
            result = _default_gdb_for_chip("stm32f4")
            assert result == "/usr/bin/gdb-multiarch"

    def test_stm32_falls_back_to_system_gdb(self):
        with patch("shutil.which") as mock_which:
            def which_side_effect(name):
                if name == "gdb":
                    return "/usr/bin/gdb"
                return None
            mock_which.side_effect = which_side_effect
            result = _default_gdb_for_chip("stm32h7")
            assert result == "/usr/bin/gdb"


class TestChipProfileRegistry:
    """Test chip profile registry and lookup."""

    def test_get_stm32l4_profile(self):
        profile = get_chip_profile("stm32l4")
        assert isinstance(profile, STM32Profile)
        assert profile.family == ChipFamily.STM32

    def test_get_stm32f4_profile(self):
        profile = get_chip_profile("stm32f4")
        assert isinstance(profile, STM32Profile)

    def test_invalid_chip_raises(self):
        with pytest.raises(ValueError) as exc_info:
            get_chip_profile("invalid_chip")
        assert "Unsupported chip" in str(exc_info.value)

    def test_case_insensitive_lookup(self):
        profile1 = get_chip_profile("STM32L4")
        profile2 = get_chip_profile("stm32l4")
        assert type(profile1) == type(profile2)


class TestSTM32ErrorPatterns:
    """Test STM32 error pattern detection."""

    @pytest.fixture
    def profile(self) -> STM32Profile:
        return STM32Profile(variant="stm32l4")

    def test_error_patterns_defined(self, profile: STM32Profile):
        patterns = profile.error_patterns
        assert "ERROR" in patterns
        assert "HARDFAULT" in patterns
        assert "MEMFAULT" in patterns
        assert "BUSFAULT" in patterns
        assert "WATCHDOG" in patterns

    def test_hal_error_pattern(self, profile: STM32Profile):
        patterns = profile.error_patterns
        assert "HAL_ERROR" in patterns


class TestSTM32ParserMethods:
    """Test STM32 parsing utility methods."""

    @pytest.fixture
    def profile(self) -> STM32Profile:
        return STM32Profile(variant="stm32l4")

    def test_parse_reset_reason_string(self, profile: STM32Profile):
        result = profile.parse_reset_reason("Reset reason: IWDG")
        assert result == "IWDG"

    def test_parse_reset_reason_csr(self, profile: STM32Profile):
        result = profile.parse_reset_reason("RCC_CSR: 0x24000000")
        assert result == "CSR=0x24000000"

    def test_parse_reset_reason_none(self, profile: STM32Profile):
        result = profile.parse_reset_reason("Some unrelated output")
        assert result is None

    def test_parse_boot_mode_dfu(self, profile: STM32Profile):
        result = profile.parse_boot_mode("Entering DFU mode")
        assert result == "DFU"

    def test_parse_boot_mode_flash(self, profile: STM32Profile):
        result = profile.parse_boot_mode("main() called")
        assert result == "Flash"


class TestEabctlSTM32Commands:
    """Test eabctl CLI commands for STM32 (via subprocess)."""

    def test_eabctl_flash_help(self):
        """Verify flash subcommand exists and accepts --chip."""
        result = subprocess.run(
            ["./eabctl", "flash", "--help"],
            capture_output=True,
            text=True,
            cwd="/tmp/test-eab",
        )
        assert result.returncode == 0
        assert "--chip" in result.stdout
        assert "--address" in result.stdout

    def test_eabctl_erase_help(self):
        """Verify erase subcommand exists."""
        result = subprocess.run(
            ["./eabctl", "erase", "--help"],
            capture_output=True,
            text=True,
            cwd="/tmp/test-eab",
        )
        assert result.returncode == 0
        assert "--chip" in result.stdout

    def test_eabctl_chip_info_help(self):
        """Verify chip-info subcommand exists."""
        result = subprocess.run(
            ["./eabctl", "chip-info", "--help"],
            capture_output=True,
            text=True,
            cwd="/tmp/test-eab",
        )
        assert result.returncode == 0
        assert "--chip" in result.stdout

    def test_eabctl_reset_help(self):
        """Verify reset subcommand exists."""
        result = subprocess.run(
            ["./eabctl", "reset", "--help"],
            capture_output=True,
            text=True,
            cwd="/tmp/test-eab",
        )
        assert result.returncode == 0
        assert "--chip" in result.stdout

    def test_eabctl_flash_invalid_chip(self):
        """Verify flash fails gracefully with invalid chip."""
        with tempfile.NamedTemporaryFile(suffix=".bin", delete=False) as f:
            f.write(b"fake firmware")
            firmware_path = f.name

        try:
            result = subprocess.run(
                ["./eabctl", "flash", firmware_path, "--chip", "invalid_chip", "--json"],
                capture_output=True,
                text=True,
                cwd="/tmp/test-eab",
            )
            assert result.returncode != 0
            data = json.loads(result.stdout)
            # Invalid chip returns {"error": "..."} without success field
            assert "error" in data
            assert "Unsupported chip" in data["error"]
        finally:
            Path(firmware_path).unlink()

    def test_eabctl_flash_missing_file(self):
        """Verify flash fails gracefully with missing firmware file."""
        result = subprocess.run(
            ["./eabctl", "flash", "/nonexistent/firmware.bin", "--chip", "stm32l4", "--json"],
            capture_output=True,
            text=True,
            cwd="/tmp/test-eab",
        )
        assert result.returncode != 0
        data = json.loads(result.stdout)
        # st-flash runs but fails to open file - returns success: false with stderr
        assert data.get("success") is False or "error" in data
        # Check stderr contains the error message about missing file
        if "stderr" in data:
            assert "open(" in data["stderr"] or "-1" in data["stderr"]
