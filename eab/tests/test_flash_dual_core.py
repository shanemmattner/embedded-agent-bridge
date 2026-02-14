"""Tests for dual-core flash command integration in cmd_flash."""

from __future__ import annotations

import json
import tempfile
from pathlib import Path
from unittest.mock import MagicMock, patch


from eab.cli.flash_cmds import cmd_flash


def test_cmd_flash_single_core_no_net_firmware():
    """Test cmd_flash with single-core chip works without net_firmware."""
    with tempfile.TemporaryDirectory() as tmpdir:
        build_dir = Path(tmpdir) / "build"
        build_dir.mkdir()
        firmware = build_dir / "firmware.bin"
        firmware.write_bytes(b"fake firmware")
        
        with patch("eab.cli.flash_cmds.subprocess.run") as mock_run:
            mock_run.return_value = MagicMock(returncode=0, stdout="Success", stderr="")
            
            result = cmd_flash(
                firmware=str(firmware),
                chip="nrf52840",
                address=None,
                port=None,
                tool=None,
                baud=921600,
                connect_under_reset=False,
                board="nrf52840dk/nrf52840",
                runner="jlink",
                device=None,
                reset_after=True,
                net_firmware=None,
                json_mode=True,
            )
            
            assert result == 0
            assert mock_run.call_count == 1


def test_cmd_flash_dual_core_with_net_firmware(capsys):
    """Test cmd_flash executes both NET and APP core flashes for nRF5340."""
    with tempfile.TemporaryDirectory() as tmpdir:
        app_build = Path(tmpdir) / "app"
        app_build.mkdir()
        app_firmware = app_build / "firmware.bin"
        app_firmware.write_bytes(b"app firmware")
        
        net_build = Path(tmpdir) / "net"
        net_build.mkdir()
        net_firmware = net_build / "firmware.bin"
        net_firmware.write_bytes(b"net firmware")
        
        with patch("eab.cli.flash_cmds.subprocess.run") as mock_run:
            mock_run.return_value = MagicMock(returncode=0, stdout="Success", stderr="")
            
            result = cmd_flash(
                firmware=str(app_build),
                chip="nrf5340",
                address=None,
                port="",
                tool=None,
                baud=921600,
                connect_under_reset=False,
                board="nrf5340dk/nrf5340/cpuapp",
                runner="jlink",
                device=None,
                reset_after=True,
                net_firmware=str(net_build),
                json_mode=True,
            )
            
            assert result == 0
            # Should call subprocess.run at least twice (once for NET, once for APP)
            # May have extra calls for APPROTECT check
            assert mock_run.call_count >= 2
            
            # Check output contains method information
            captured = capsys.readouterr()
            output = json.loads(captured.out)
            assert output["success"] is True
            assert "west_flash" in output["method"]
            assert output.get("net_firmware") == str(net_build)


def test_cmd_flash_dual_core_net_fails_fast(capsys):
    """Test cmd_flash stops at NET core failure and doesn't flash APP core."""
    with tempfile.TemporaryDirectory() as tmpdir:
        app_build = Path(tmpdir) / "app"
        app_build.mkdir()
        
        net_build = Path(tmpdir) / "net"
        net_build.mkdir()
        
        with patch("eab.cli.flash_cmds.subprocess.run") as mock_run:
            # NET core fails
            mock_run.return_value = MagicMock(returncode=1, stdout="", stderr="NET flash failed")
            
            result = cmd_flash(
                firmware=str(app_build),
                chip="nrf5340",
                address=None,
                port="",
                tool=None,
                baud=921600,
                connect_under_reset=False,
                board="nrf5340dk/nrf5340/cpuapp",
                runner="jlink",
                device=None,
                reset_after=True,
                net_firmware=str(net_build),
                json_mode=True,
            )
            
            assert result == 1
            # Should have limited calls (APPROTECT check + NET flash, no APP flash)
            # The key is that we should have fewer calls than if both cores ran
            captured = capsys.readouterr()
            output = json.loads(captured.out)
            assert output["success"] is False
            assert "NET flash failed" in output["stderr"]
            # Verify only 1 attempt (NET core only)
            assert output["attempts"] == 1


def test_cmd_flash_dual_core_app_fails(capsys):
    """Test cmd_flash reports failure when APP core fails but NET succeeds."""
    with tempfile.TemporaryDirectory() as tmpdir:
        app_build = Path(tmpdir) / "app"
        app_build.mkdir()
        
        net_build = Path(tmpdir) / "net"
        net_build.mkdir()
        
        with patch("eab.cli.flash_cmds.subprocess.run") as mock_run:
            # First call: APPROTECT check (returns success)
            # Second call: NET succeeds
            # Third call: APP fails
            mock_run.side_effect = [
                MagicMock(returncode=0, stdout="", stderr=""),  # APPROTECT check
                MagicMock(returncode=0, stdout="NET success", stderr=""),  # NET flash
                MagicMock(returncode=1, stdout="", stderr="APP flash failed"),  # APP flash
            ]
            
            result = cmd_flash(
                firmware=str(app_build),
                chip="nrf5340",
                address=None,
                port="",
                tool=None,
                baud=921600,
                connect_under_reset=False,
                board="nrf5340dk/nrf5340/cpuapp",
                runner="jlink",
                device=None,
                reset_after=True,
                net_firmware=str(net_build),
                json_mode=True,
            )
            
            assert result == 1
            
            captured = capsys.readouterr()
            output = json.loads(captured.out)
            assert output["success"] is False
            assert "APP flash failed" in output["stderr"]
            assert "NET success" in output["stdout"]
            # Verify 2 attempts (NET + APP)
            assert output["attempts"] == 2


def test_cmd_flash_dual_core_both_succeed(capsys):
    """Test cmd_flash reports success when both cores flash successfully."""
    with tempfile.TemporaryDirectory() as tmpdir:
        app_build = Path(tmpdir) / "app"
        app_build.mkdir()
        
        net_build = Path(tmpdir) / "net"
        net_build.mkdir()
        
        with patch("eab.cli.flash_cmds.subprocess.run") as mock_run:
            mock_run.return_value = MagicMock(returncode=0, stdout="Success", stderr="")
            
            result = cmd_flash(
                firmware=str(app_build),
                chip="nrf5340",
                address=None,
                port="",
                tool=None,
                baud=921600,
                connect_under_reset=False,
                board="nrf5340dk/nrf5340/cpuapp",
                runner="jlink",
                device=None,
                reset_after=True,
                net_firmware=str(net_build),
                json_mode=True,
            )
            
            assert result == 0
            # May have extra APPROTECT check call
            assert mock_run.call_count >= 2
            
            captured = capsys.readouterr()
            output = json.loads(captured.out)
            assert output["success"] is True
            assert output["attempts"] == 2


def test_cmd_flash_dual_core_method_field(capsys):
    """Test cmd_flash sets correct method field for dual-core flash."""
    with tempfile.TemporaryDirectory() as tmpdir:
        app_build = Path(tmpdir) / "app"
        app_build.mkdir()
        
        net_build = Path(tmpdir) / "net"
        net_build.mkdir()
        
        with patch("eab.cli.flash_cmds.subprocess.run") as mock_run:
            mock_run.return_value = MagicMock(returncode=0, stdout="Success", stderr="")
            
            cmd_flash(
                firmware=str(app_build),
                chip="nrf5340",
                address=None,
                port="",
                tool=None,
                baud=921600,
                connect_under_reset=False,
                runner="jlink",
                device=None,
                reset_after=True,
                net_firmware=str(net_build),
                json_mode=True,
            )
            
            captured = capsys.readouterr()
            output = json.loads(captured.out)
            
            # Method should be "west_flash+west_flash" or similar
            assert "west_flash" in output["method"]
            assert output["tool"] == "multi_core"


def test_cmd_flash_ignores_net_firmware_for_non_zephyr():
    """Test cmd_flash ignores net_firmware for non-Zephyr chips."""
    with tempfile.TemporaryDirectory() as tmpdir:
        firmware = Path(tmpdir) / "firmware.bin"
        firmware.write_bytes(b"firmware")
        
        with patch("eab.cli.flash_cmds.subprocess.run") as mock_run:
            mock_run.return_value = MagicMock(returncode=0, stdout="Success", stderr="")
            
            result = cmd_flash(
                firmware=str(firmware),
                chip="stm32l4",
                address="0x08000000",
                port=None,
                tool=None,
                baud=921600,
                connect_under_reset=False,
                device=None,
                reset_after=True,
                net_firmware="/some/net/firmware",  # Should be ignored
                json_mode=True,
            )
            
            assert result == 0
            # Should only call once (single-core flash)
            assert mock_run.call_count == 1
