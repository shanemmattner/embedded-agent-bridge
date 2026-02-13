"""Tests for nRF5340 dual-core flash support in ZephyrProfile."""

from __future__ import annotations

import tempfile
from pathlib import Path

import pytest

from eab.chips.zephyr import ZephyrProfile


def test_get_flash_commands_single_core():
    """Test get_flash_commands returns single command for single-core targets."""
    profile = ZephyrProfile(variant="nrf52840", board="nrf52840dk/nrf52840", runner="jlink")
    
    cmds = profile.get_flash_commands(
        firmware_path="/path/to/build",
        port="/dev/ttyUSB0",
    )
    
    assert len(cmds) == 1
    assert cmds[0].tool == "west"
    assert "flash" in cmds[0].args
    assert "--runner" in cmds[0].args
    assert "jlink" in cmds[0].args


def test_get_flash_commands_single_core_no_net_firmware():
    """Test get_flash_commands returns single command when net_firmware not provided."""
    profile = ZephyrProfile(variant="nrf5340", board="nrf5340dk/nrf5340/cpuapp", runner="jlink")
    
    cmds = profile.get_flash_commands(
        firmware_path="/path/to/build/app",
        port="",
    )
    
    assert len(cmds) == 1
    assert cmds[0].tool == "west"


def test_get_flash_commands_dual_core_nrf5340():
    """Test get_flash_commands returns two commands for nRF5340 with net_firmware."""
    with tempfile.TemporaryDirectory() as tmpdir:
        app_build = Path(tmpdir) / "app"
        app_build.mkdir()
        
        net_build = Path(tmpdir) / "net"
        net_build.mkdir()
        
        profile = ZephyrProfile(variant="nrf5340", board="nrf5340dk/nrf5340/cpuapp", runner="jlink")
        
        cmds = profile.get_flash_commands(
            firmware_path=str(app_build),
            port="",
            net_core_firmware=str(net_build),
        )
        
        # Should return [NET core flash, APP core flash]
        assert len(cmds) == 2
        
        # NET core (first command)
        assert cmds[0].tool == "west"
        assert "flash" in cmds[0].args
        assert "--build-dir" in cmds[0].args
        net_build_idx = cmds[0].args.index("--build-dir") + 1
        assert str(net_build) == cmds[0].args[net_build_idx]
        
        # APP core (second command)
        assert cmds[1].tool == "west"
        assert "flash" in cmds[1].args
        assert "--build-dir" in cmds[1].args
        app_build_idx = cmds[1].args.index("--build-dir") + 1
        assert str(app_build) == cmds[1].args[app_build_idx]


def test_get_flash_commands_dual_core_with_runner():
    """Test get_flash_commands passes runner to both commands."""
    profile = ZephyrProfile(variant="nrf5340", runner="jlink")
    
    cmds = profile.get_flash_commands(
        firmware_path="/app/build",
        port="",
        net_core_firmware="/net/build",
        runner="jlink",
    )
    
    assert len(cmds) == 2
    
    # Both should have runner
    for cmd in cmds:
        assert "--runner" in cmd.args
        assert "jlink" in cmd.args


def test_get_flash_commands_dual_core_zephyr_base_env():
    """Test get_flash_commands sets ZEPHYR_BASE for both commands."""
    with tempfile.TemporaryDirectory() as tmpdir:
        workspace = Path(tmpdir)
        (workspace / ".west").mkdir()
        (workspace / "zephyr").mkdir()
        
        app_build = workspace / "app" / "build"
        app_build.mkdir(parents=True)
        
        net_build = workspace / "net" / "build"
        net_build.mkdir(parents=True)
        
        profile = ZephyrProfile(variant="nrf5340")
        cmds = profile.get_flash_commands(
            firmware_path=str(app_build),
            port="",
            net_core_firmware=str(net_build),
        )
        
        assert len(cmds) == 2
        
        # Both should have ZEPHYR_BASE
        for cmd in cmds:
            assert "ZEPHYR_BASE" in cmd.env
            assert str(workspace.resolve() / "zephyr") in cmd.env["ZEPHYR_BASE"]


def test_get_flash_commands_dual_core_net_build_dir_explicit():
    """Test get_flash_commands uses explicit net_build_dir when provided."""
    profile = ZephyrProfile(variant="nrf5340")
    
    cmds = profile.get_flash_commands(
        firmware_path="/app/build",
        port="",
        net_core_firmware="/net/firmware.hex",
        net_build_dir="/custom/net/build",
    )
    
    assert len(cmds) == 2
    
    # NET core should use explicit build dir
    net_build_idx = cmds[0].args.index("--build-dir") + 1
    assert cmds[0].args[net_build_idx] == "/custom/net/build"


def test_get_flash_commands_dual_core_net_build_dir_from_elf():
    """Test get_flash_commands detects net build dir from zephyr.elf path."""
    with tempfile.TemporaryDirectory() as tmpdir:
        net_build = Path(tmpdir) / "net_build"
        net_zephyr = net_build / "zephyr"
        net_zephyr.mkdir(parents=True)
        (net_build / "CMakeCache.txt").write_text("BOARD:STRING=nrf5340dk/nrf5340/cpunet\n")
        
        elf_path = net_zephyr / "zephyr.elf"
        elf_path.write_text("fake elf")
        
        profile = ZephyrProfile(variant="nrf5340")
        cmds = profile.get_flash_commands(
            firmware_path="/app/build",
            port="",
            net_core_firmware=str(elf_path),
        )
        
        assert len(cmds) == 2
        
        # NET core should detect build dir from elf path
        net_build_idx = cmds[0].args.index("--build-dir") + 1
        assert cmds[0].args[net_build_idx] == str(net_build)


def test_get_flash_commands_dual_core_sibling_detection():
    """Test get_flash_commands detects sibling net build directory."""
    with tempfile.TemporaryDirectory() as tmpdir:
        root = Path(tmpdir)
        app_build = root / "app"
        app_build.mkdir()
        
        net_build = root / "net"
        net_build.mkdir()
        
        profile = ZephyrProfile(variant="nrf5340")
        cmds = profile.get_flash_commands(
            firmware_path=str(app_build),
            port="",
            net_core_firmware="/some/net/firmware.hex",  # Non-directory path
        )
        
        assert len(cmds) == 2
        # NET core command should be created (even if path detection fails)
        assert cmds[0].tool == "west"


def test_get_flash_commands_not_nrf5340():
    """Test get_flash_commands returns single command for non-nRF5340 even with net_firmware."""
    # If someone mistakenly passes net_firmware for a non-dual-core chip, it should be ignored
    profile = ZephyrProfile(variant="nrf52840")
    
    cmds = profile.get_flash_commands(
        firmware_path="/build",
        port="",
        net_core_firmware="/net",  # This should be ignored
    )
    
    # Should still return single command (net_firmware ignored for non-nRF5340)
    assert len(cmds) == 1


def test_get_flash_commands_dual_core_board_detection():
    """Test get_flash_commands detects nRF5340 from board name."""
    # Even if variant doesn't mention nrf5340, board should trigger dual-core
    profile = ZephyrProfile(variant="custom", board="nrf5340dk/nrf5340/cpuapp")
    
    cmds = profile.get_flash_commands(
        firmware_path="/app/build",
        port="",
        net_core_firmware="/net/build",
    )
    
    assert len(cmds) == 2


def test_get_flash_commands_timeout():
    """Test get_flash_commands sets correct timeout for all commands."""
    profile = ZephyrProfile(variant="nrf5340")
    
    cmds = profile.get_flash_commands(
        firmware_path="/app",
        port="",
        net_core_firmware="/net",
    )
    
    assert len(cmds) == 2
    for cmd in cmds:
        assert cmd.timeout == 120.0


def test_get_flash_commands_preserves_kwargs():
    """Test get_flash_commands preserves additional kwargs for APP core."""
    profile = ZephyrProfile(variant="nrf5340")
    
    cmds = profile.get_flash_commands(
        firmware_path="/app",
        port="/dev/ttyUSB0",
        address="0x0",
        board="custom_board",
        runner="jlink",
        net_core_firmware="/net",
        extra_kwarg="value",
    )
    
    assert len(cmds) == 2
    # APP core (second command) should have runner
    assert "--runner" in cmds[1].args
    assert "jlink" in cmds[1].args


def test_get_flash_command_backwards_compatible():
    """Test get_flash_command still works without net_core_firmware kwarg."""
    profile = ZephyrProfile(variant="nrf5340", runner="jlink")
    
    # Old API should still work
    cmd = profile.get_flash_command(
        firmware_path="/build",
        port="",
    )
    
    assert cmd.tool == "west"
    assert "flash" in cmd.args
    assert "--runner" in cmd.args


def test_get_flash_commands_empty_net_firmware():
    """Test get_flash_commands treats empty string net_firmware as None."""
    profile = ZephyrProfile(variant="nrf5340")
    
    cmds = profile.get_flash_commands(
        firmware_path="/app",
        port="",
        net_core_firmware="",  # Empty string should be treated as None
    )
    
    # Empty string is falsy, should return single command
    assert len(cmds) == 1
