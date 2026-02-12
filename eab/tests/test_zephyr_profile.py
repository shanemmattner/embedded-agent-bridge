"""Tests for Zephyr RTOS chip profile."""

from __future__ import annotations

import tempfile
from pathlib import Path

import pytest

from eab.chips import get_chip_profile, detect_chip_family
from eab.chips.base import ChipFamily
from eab.chips.zephyr import ZephyrProfile


def test_zephyr_profile_construction_nrf5340():
    """Test ZephyrProfile construction with nRF5340 variant."""
    profile = ZephyrProfile(variant="nrf5340", board="nrf5340dk/nrf5340/cpuapp")
    assert profile.variant == "nrf5340"
    assert profile.board == "nrf5340dk/nrf5340/cpuapp"
    assert profile.runner is None


def test_zephyr_profile_family_nrf():
    """Test family returns NRF52 for nRF variants."""
    profile_nrf52 = ZephyrProfile(variant="nrf52840")
    assert profile_nrf52.family == ChipFamily.NRF52
    
    profile_nrf53 = ZephyrProfile(variant="nrf5340")
    assert profile_nrf53.family == ChipFamily.NRF52


def test_zephyr_profile_family_stm32():
    """Test family returns STM32 for STM32 variants."""
    profile = ZephyrProfile(variant="stm32f4")
    assert profile.family == ChipFamily.STM32


def test_zephyr_profile_family_esp32():
    """Test family returns ESP32 for ESP32 variants."""
    profile = ZephyrProfile(variant="esp32")
    assert profile.family == ChipFamily.ESP32


def test_zephyr_profile_family_rp2040():
    """Test family returns RP2040 for RP2040 variants."""
    profile = ZephyrProfile(variant="rp2040")
    assert profile.family == ChipFamily.RP2040


def test_zephyr_profile_family_default():
    """Test family defaults to NRF52 when no variant."""
    profile = ZephyrProfile()
    assert profile.family == ChipFamily.NRF52


def test_zephyr_flash_tool():
    """Test flash_tool returns 'west'."""
    profile = ZephyrProfile(variant="nrf5340")
    assert profile.flash_tool == "west"


def test_zephyr_name_property():
    """Test name property works correctly."""
    # With board
    profile1 = ZephyrProfile(variant="nrf5340", board="nrf5340dk/nrf5340/cpuapp")
    assert profile1.name == "Zephyr (nrf5340dk/nrf5340/cpuapp)"
    
    # With variant only
    profile2 = ZephyrProfile(variant="nrf52840")
    assert profile2.name == "Zephyr (NRF52840)"
    
    # Neither
    profile3 = ZephyrProfile()
    assert profile3.name == "Zephyr"


def test_zephyr_boot_patterns():
    """Test boot_patterns contains Zephyr-specific patterns."""
    profile = ZephyrProfile(variant="nrf5340")
    assert "*** Booting Zephyr" in profile.boot_patterns
    assert "Zephyr version" in profile.boot_patterns
    assert "BUILD: " in profile.boot_patterns


def test_zephyr_crash_patterns():
    """Test crash_patterns contains Zephyr and Cortex-M fault patterns."""
    profile = ZephyrProfile(variant="nrf5340")
    assert "FATAL ERROR" in profile.crash_patterns
    assert "HardFault_Handler" in profile.crash_patterns
    assert "k_panic" in profile.crash_patterns
    assert ">>> ZEPHYR FATAL ERROR" in profile.crash_patterns
    assert "Thread aborted" in profile.crash_patterns


def test_zephyr_get_flash_command():
    """Test get_flash_command returns correct FlashCommand."""
    profile = ZephyrProfile(variant="nrf5340", board="nrf5340dk/nrf5340/cpuapp", runner="jlink")
    
    cmd = profile.get_flash_command(
        firmware_path="/path/to/build",
        port="/dev/ttyUSB0",
        board="nrf5340dk/nrf5340/cpuapp",
        runner="jlink"
    )
    
    assert cmd.tool == "west"
    assert "flash" in cmd.args
    assert "--no-rebuild" in cmd.args
    assert "--build-dir" in cmd.args
    # Path gets resolved, so check that some path is present
    build_dir_index = cmd.args.index("--build-dir")
    assert build_dir_index >= 0
    assert len(cmd.args) > build_dir_index + 1
    assert "--runner" in cmd.args
    assert "jlink" in cmd.args
    assert cmd.timeout == 120.0


def test_zephyr_get_flash_command_esp32_port():
    """Test get_flash_command adds ESP32 port argument."""
    profile = ZephyrProfile(variant="esp32")
    
    cmd = profile.get_flash_command(
        firmware_path="/path/to/build",
        port="/dev/ttyUSB0"
    )
    
    assert cmd.tool == "west"
    assert "--" in cmd.args
    assert "--esp-device" in cmd.args
    assert "/dev/ttyUSB0" in cmd.args


def test_zephyr_get_flash_command_build_dir_detection():
    """Test get_flash_command with build dir detection from zephyr.elf path."""
    with tempfile.TemporaryDirectory() as tmpdir:
        build_path = Path(tmpdir)
        zephyr_dir = build_path / "zephyr"
        zephyr_dir.mkdir()
        
        # Create CMakeCache.txt to mark as build directory
        (build_path / "CMakeCache.txt").write_text("BOARD:STRING=nrf5340dk/nrf5340/cpuapp\n")
        
        # Create zephyr.elf
        elf_path = zephyr_dir / "zephyr.elf"
        elf_path.write_text("fake elf")
        
        profile = ZephyrProfile(variant="nrf5340")
        cmd = profile.get_flash_command(
            firmware_path=str(elf_path),
            port=""
        )
        
        assert cmd.tool == "west"
        assert "--build-dir" in cmd.args
        # The build dir should be the parent of zephyr/ directory
        build_dir_index = cmd.args.index("--build-dir") + 1
        assert cmd.args[build_dir_index] == str(build_path)


def test_zephyr_detect_board_from_build():
    """Test detect_board_from_build reads CMakeCache.txt correctly."""
    with tempfile.TemporaryDirectory() as tmpdir:
        build_path = Path(tmpdir)
        cmake_cache = build_path / "CMakeCache.txt"
        
        # Write a mock CMakeCache.txt
        cmake_cache.write_text(
            "# CMake Cache\n"
            "BOARD:STRING=nrf5340dk/nrf5340/cpuapp\n"
            "OTHER_VAR:STRING=value\n"
        )
        
        profile = ZephyrProfile()
        board = profile.detect_board_from_build(build_path)
        
        assert board == "nrf5340dk/nrf5340/cpuapp"


def test_zephyr_detect_board_from_build_missing():
    """Test detect_board_from_build returns None when CMakeCache.txt missing."""
    with tempfile.TemporaryDirectory() as tmpdir:
        profile = ZephyrProfile()
        board = profile.detect_board_from_build(tmpdir)
        assert board is None


def test_get_chip_profile_zephyr_nrf5340():
    """Test get_chip_profile("zephyr_nrf5340") returns ZephyrProfile instance."""
    profile = get_chip_profile("zephyr_nrf5340")
    assert isinstance(profile, ZephyrProfile)
    assert profile.variant == "nrf5340"
    assert profile.board == "nrf5340dk/nrf5340/cpuapp"
    assert profile.runner == "jlink"


def test_get_chip_profile_zephyr_nrf52840():
    """Test get_chip_profile("zephyr_nrf52840") returns ZephyrProfile instance."""
    profile = get_chip_profile("zephyr_nrf52840")
    assert isinstance(profile, ZephyrProfile)
    assert profile.variant == "nrf52840"
    assert profile.board == "nrf52840dk/nrf52840"
    assert profile.runner == "jlink"


def test_get_chip_profile_zephyr_rp2040():
    """Test get_chip_profile("zephyr_rp2040") returns ZephyrProfile instance."""
    profile = get_chip_profile("zephyr_rp2040")
    assert isinstance(profile, ZephyrProfile)
    assert profile.variant == "rp2040"
    assert profile.board == "rpi_pico"
    assert profile.runner is None


def test_get_chip_profile_zephyr():
    """Test get_chip_profile("zephyr") returns ZephyrProfile instance."""
    profile = get_chip_profile("zephyr")
    assert isinstance(profile, ZephyrProfile)
    assert profile.variant is None


def test_detect_chip_family_booting_zephyr():
    """Test detect_chip_family detects '*** Booting Zephyr' as NRF52."""
    family = detect_chip_family("*** Booting Zephyr OS build v3.5.0 ***")
    assert family == ChipFamily.NRF52


def test_detect_chip_family_zephyr_version():
    """Test detect_chip_family detects 'Zephyr version' as NRF52."""
    family = detect_chip_family("Zephyr version 3.5.0")
    assert family == ChipFamily.NRF52


def test_detect_chip_family_zephyr_fatal_error():
    """Test detect_chip_family detects 'ZEPHYR FATAL ERROR' as NRF52."""
    family = detect_chip_family(">>> ZEPHYR FATAL ERROR 4 <<<")
    assert family == ChipFamily.NRF52


def test_zephyr_erase_command_nrf():
    """Test erase command returns nrfjprog for nRF variants."""
    profile = ZephyrProfile(variant="nrf5340")
    cmd = profile.get_erase_command(port="")
    
    assert cmd.tool == "nrfjprog"
    assert "--recover" in cmd.args
    assert cmd.timeout == 60.0


def test_zephyr_erase_command_pyocd():
    """Test erase command returns pyocd when runner is pyocd."""
    profile = ZephyrProfile(variant="rp2040", runner="pyocd")
    cmd = profile.get_erase_command(port="", runner="pyocd")
    
    assert cmd.tool == "pyocd"
    assert "erase" in cmd.args
    assert cmd.timeout == 60.0


def test_zephyr_erase_command_not_implemented():
    """Test erase command raises NotImplementedError for unsupported variants."""
    profile = ZephyrProfile(variant="esp32")
    
    with pytest.raises(NotImplementedError) as exc_info:
        profile.get_erase_command(port="")
    
    assert "Erase not implemented" in str(exc_info.value)


def test_zephyr_openocd_config_nrf52():
    """Test OpenOCD config returns jlink interface for nRF52 variants."""
    profile = ZephyrProfile(variant="nrf52840")
    config = profile.get_openocd_config()
    
    assert config.interface_cfg == "interface/jlink.cfg"
    assert config.target_cfg == "target/nrf52.cfg"
    assert config.transport == "swd"


def test_zephyr_openocd_config_nrf53():
    """Test OpenOCD config returns jlink interface for nRF53 variants."""
    profile = ZephyrProfile(variant="nrf5340")
    config = profile.get_openocd_config()
    
    assert config.interface_cfg == "interface/jlink.cfg"
    assert "nrf52.cfg" in config.target_cfg
    assert config.transport == "swd"


def test_zephyr_openocd_config_rp2040():
    """Test OpenOCD config returns cmsis-dap interface for RP2040."""
    profile = ZephyrProfile(variant="rp2040")
    config = profile.get_openocd_config()
    
    assert config.interface_cfg == "interface/cmsis-dap.cfg"
    assert config.target_cfg == "target/rp2040.cfg"
    assert config.transport == "swd"


def test_zephyr_openocd_config_fallback():
    """Test OpenOCD config fallback for unknown variants."""
    profile = ZephyrProfile(variant="unknown")
    config = profile.get_openocd_config()
    
    assert config.interface_cfg == "interface/stlink.cfg"
    assert config.target_cfg == "target/stm32f4x.cfg"
    assert config.transport == "swd"


def test_zephyr_chip_info_nrf():
    """Test chip info command for nRF variants."""
    profile = ZephyrProfile(variant="nrf5340")
    cmd = profile.get_chip_info_command(port="")
    
    assert cmd.tool == "pyocd"
    assert "info" in cmd.args
    assert cmd.timeout == 30.0


def test_zephyr_chip_info_not_implemented():
    """Test chip info raises NotImplementedError for unsupported variants."""
    profile = ZephyrProfile(variant="esp32")
    
    with pytest.raises(NotImplementedError) as exc_info:
        profile.get_chip_info_command(port="")
    
    assert "Chip info not implemented" in str(exc_info.value)


def test_zephyr_reset_sequences():
    """Test reset sequences are defined."""
    profile = ZephyrProfile(variant="nrf5340")
    sequences = profile.reset_sequences

    assert "hard_reset" in sequences
    assert len(sequences["hard_reset"]) == 2


def test_zephyr_find_workspace_found():
    """Test _find_workspace returns workspace root when .west/ exists."""
    with tempfile.TemporaryDirectory() as tmpdir:
        workspace = Path(tmpdir)
        (workspace / ".west").mkdir()
        build_dir = workspace / "app" / "build"
        build_dir.mkdir(parents=True)

        result = ZephyrProfile._find_workspace(build_dir)
        assert result == workspace.resolve()


def test_zephyr_find_workspace_not_found():
    """Test _find_workspace returns None when no .west/ exists."""
    with tempfile.TemporaryDirectory() as tmpdir:
        result = ZephyrProfile._find_workspace(Path(tmpdir))
        assert result is None


def test_zephyr_find_workspace_safety_limit():
    """Test _find_workspace stops at filesystem root without infinite loop."""
    result = ZephyrProfile._find_workspace(Path("/tmp/nonexistent/deep/path"))
    assert result is None


def test_zephyr_get_flash_command_explicit_build_dir():
    """Test get_flash_command uses explicit build_dir when provided."""
    profile = ZephyrProfile(variant="nrf5340")
    cmd = profile.get_flash_command(
        firmware_path="/some/firmware.bin",
        port="",
        build_dir="/explicit/build/path",
    )

    build_dir_index = cmd.args.index("--build-dir") + 1
    assert cmd.args[build_dir_index] == "/explicit/build/path"


def test_zephyr_get_flash_command_env_zephyr_base():
    """Test get_flash_command sets ZEPHYR_BASE env when workspace found."""
    with tempfile.TemporaryDirectory() as tmpdir:
        workspace = Path(tmpdir)
        (workspace / ".west").mkdir()
        (workspace / "zephyr").mkdir()
        build_dir = workspace / "app" / "build"
        build_dir.mkdir(parents=True)

        profile = ZephyrProfile(variant="nrf5340")
        cmd = profile.get_flash_command(
            firmware_path=str(build_dir),
            port="",
        )

        assert "ZEPHYR_BASE" in cmd.env
        assert cmd.env["ZEPHYR_BASE"] == str(workspace.resolve() / "zephyr")


def test_zephyr_get_flash_command_env_empty_without_workspace():
    """Test get_flash_command has empty env when no workspace found."""
    with tempfile.TemporaryDirectory() as tmpdir:
        profile = ZephyrProfile(variant="nrf5340")
        cmd = profile.get_flash_command(
            firmware_path=tmpdir,
            port="",
        )

        assert cmd.env == {}


def test_zephyr_board_defaults_class_var():
    """Test BOARD_DEFAULTS class variable contains expected entries."""
    assert "nrf5340" in ZephyrProfile.BOARD_DEFAULTS
    assert ZephyrProfile.BOARD_DEFAULTS["nrf5340"]["board"] == "nrf5340dk/nrf5340/cpuapp"
    assert ZephyrProfile.BOARD_DEFAULTS["nrf5340"]["runner"] == "jlink"
    assert ZephyrProfile.BOARD_DEFAULTS["rp2040"]["runner"] is None


def test_get_chip_profile_bare_nrf5340():
    """Test get_chip_profile("nrf5340") returns ZephyrProfile with correct settings."""
    profile = get_chip_profile("nrf5340")
    assert isinstance(profile, ZephyrProfile)
    assert profile.variant == "nrf5340"
    assert profile.board == "nrf5340dk/nrf5340/cpuapp"
    assert profile.runner == "jlink"


def test_get_chip_profile_bare_nrf52840():
    """Test get_chip_profile("nrf52840") returns ZephyrProfile with correct settings."""
    profile = get_chip_profile("nrf52840")
    assert isinstance(profile, ZephyrProfile)
    assert profile.variant == "nrf52840"
    assert profile.board == "nrf52840dk/nrf52840"
    assert profile.runner == "jlink"


def test_get_chip_profile_bare_nrf52833():
    """Test get_chip_profile("nrf52833") returns ZephyrProfile with correct settings."""
    profile = get_chip_profile("nrf52833")
    assert isinstance(profile, ZephyrProfile)
    assert profile.variant == "nrf52833"
    assert profile.board == "nrf52833dk/nrf52833"
    assert profile.runner == "jlink"


def test_get_chip_profile_bare_rp2040():
    """Test get_chip_profile("rp2040") returns ZephyrProfile with correct settings."""
    profile = get_chip_profile("rp2040")
    assert isinstance(profile, ZephyrProfile)
    assert profile.variant == "rp2040"
    assert profile.board == "rpi_pico"
    assert profile.runner is None


def test_get_chip_profile_bare_mcxn947():
    """Test get_chip_profile("mcxn947") returns ZephyrProfile with correct settings."""
    profile = get_chip_profile("mcxn947")
    assert isinstance(profile, ZephyrProfile)
    assert profile.variant == "mcxn947"
    assert profile.board == "frdm_mcxn947/mcxn947/cpu0"
    assert profile.runner == "linkserver"


def test_get_chip_profile_alias_matches_prefixed():
    """Test that bare chip name aliases match the zephyr_prefixed versions."""
    # Test nrf5340
    bare_profile = get_chip_profile("nrf5340")
    prefixed_profile = get_chip_profile("zephyr_nrf5340")
    assert bare_profile.variant == prefixed_profile.variant
    assert bare_profile.board == prefixed_profile.board
    assert bare_profile.runner == prefixed_profile.runner
    
    # Test nrf52840
    bare_profile = get_chip_profile("nrf52840")
    prefixed_profile = get_chip_profile("zephyr_nrf52840")
    assert bare_profile.variant == prefixed_profile.variant
    assert bare_profile.board == prefixed_profile.board
    assert bare_profile.runner == prefixed_profile.runner
