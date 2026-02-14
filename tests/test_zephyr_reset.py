"""Tests for Zephyr reset command functionality.

Tests reset command generation for different Zephyr targets including
nRF5340, nRF52840, MCXN947, and J-Link fallback behavior.
"""

from __future__ import annotations

import os
import tempfile
from unittest.mock import patch, MagicMock

import pytest

from eab.chips.zephyr import ZephyrProfile
from eab.chips.base import FlashCommand
from eab.cli.flash import cmd_reset


# =============================================================================
# ZephyrProfile.get_reset_command() Tests
# =============================================================================

class TestZephyrResetCommand:
    """Test ZephyrProfile.get_reset_command() method."""

    def test_nrf5340_reset_uses_nrfjprog(self):
        """Should use nrfjprog --reset for nRF5340."""
        profile = ZephyrProfile(variant="nrf5340")
        cmd = profile.get_reset_command()
        
        assert cmd.tool == "nrfjprog"
        assert cmd.args == ["--reset"]
        assert cmd.timeout == 30.0

    def test_nrf52840_reset_uses_nrfjprog(self):
        """Should use nrfjprog --reset for nRF52840."""
        profile = ZephyrProfile(variant="nrf52840")
        cmd = profile.get_reset_command()
        
        assert cmd.tool == "nrfjprog"
        assert cmd.args == ["--reset"]
        assert cmd.timeout == 30.0

    def test_nrf52833_reset_uses_nrfjprog(self):
        """Should use nrfjprog --reset for nRF52833."""
        profile = ZephyrProfile(variant="nrf52833")
        cmd = profile.get_reset_command()
        
        assert cmd.tool == "nrfjprog"
        assert cmd.args == ["--reset"]
        assert cmd.timeout == 30.0

    def test_mcxn947_reset_uses_openocd(self):
        """Should use OpenOCD reset for MCXN947."""
        profile = ZephyrProfile(variant="mcxn947")
        cmd = profile.get_reset_command()
        
        assert cmd.tool == "openocd"
        assert "-f" in cmd.args
        assert "interface/cmsis-dap.cfg" in cmd.args
        assert "reset run" in " ".join(cmd.args)
        assert "shutdown" in " ".join(cmd.args)
        assert cmd.timeout == 30.0

    def test_mcxn947_reset_with_linkserver_runner(self):
        """Should use OpenOCD even when runner is linkserver (default for MCXN947)."""
        profile = ZephyrProfile(variant="mcxn947", runner="linkserver")
        cmd = profile.get_reset_command()
        
        # Should ignore linkserver and use OpenOCD
        assert cmd.tool == "openocd"
        assert "reset run" in " ".join(cmd.args)

    def test_mcxn947_reset_ignores_runner_parameter(self):
        """Should always use OpenOCD for MCXN947 regardless of runner."""
        profile = ZephyrProfile(variant="mcxn947", runner="jlink")
        
        # Should not raise - just uses OpenOCD
        cmd = profile.get_reset_command(runner="jlink")
        assert cmd.tool == "openocd"
        assert "reset run" in " ".join(cmd.args)

    def test_jlink_fallback_with_device_creates_script(self):
        """Should create J-Link script for generic targets with device string."""
        profile = ZephyrProfile(variant="rp2040")
        cmd = profile.get_reset_command(device="RP2040")
        
        assert cmd.tool == "JLinkExe"
        assert "-CommandFile" in cmd.args
        
        # Verify script file was created
        script_idx = cmd.args.index("-CommandFile")
        script_path = cmd.args[script_idx + 1]
        assert os.path.exists(script_path)
        
        # Verify script contents
        with open(script_path, "r") as f:
            content = f.read()
            assert "device RP2040" in content
            assert "si SWD" in content
            assert "speed 4000" in content
            assert "r\n" in content  # reset command
            assert "g\n" in content  # go command
            assert "exit" in content
        
        # Cleanup
        os.unlink(script_path)

    def test_jlink_fallback_without_device_raises(self):
        """Should raise NotImplementedError when device string missing for generic targets."""
        profile = ZephyrProfile(variant="rp2040")
        
        with pytest.raises(NotImplementedError) as excinfo:
            profile.get_reset_command()
        
        assert "--device" in str(excinfo.value)
        assert "rp2040" in str(excinfo.value).lower()

    def test_jlink_script_temp_file_prefix(self):
        """Should create temp file with jlink_reset_ prefix."""
        profile = ZephyrProfile(variant="custom_board")
        cmd = profile.get_reset_command(device="CUSTOM_MCU")
        
        script_idx = cmd.args.index("-CommandFile")
        script_path = cmd.args[script_idx + 1]
        
        assert "jlink_reset_" in os.path.basename(script_path)
        assert script_path.endswith(".jlink")
        
        # Cleanup
        os.unlink(script_path)


# =============================================================================
# cmd_reset() Integration Tests
# =============================================================================

class TestCmdResetIntegration:
    """Test cmd_reset() CLI command with Zephyr targets."""

    def test_reset_nrf5340_success(self):
        """Should successfully reset nRF5340 using nrfjprog."""
        mock_result = MagicMock()
        mock_result.returncode = 0
        mock_result.stdout = "Resetting device\nDevice reset successful"
        mock_result.stderr = ""
        
        with patch("eab.cli.flash.reset_cmd.subprocess.run", return_value=mock_result) as mock_run:
            with patch("eab.cli.flash.reset_cmd._print") as mock_print:
                result = cmd_reset(
                    chip="nrf5340",
                    method="hard",
                    connect_under_reset=False,
                    device=None,
                    json_mode=True,
                )
        
        assert result == 0
        mock_run.assert_called_once()
        call_args = mock_run.call_args
        assert call_args[0][0] == ["nrfjprog", "--reset"]
        
        # Verify JSON output
        assert mock_print.called
        output = mock_print.call_args[0][0]
        assert output["success"] is True
        assert output["chip"] == "nrf5340"
        assert output["command"] == ["nrfjprog", "--reset"]

    def test_reset_nrf52840_success(self):
        """Should successfully reset nRF52840 using nrfjprog."""
        mock_result = MagicMock()
        mock_result.returncode = 0
        mock_result.stdout = "Reset complete"
        mock_result.stderr = ""
        
        with patch("eab.cli.flash.reset_cmd.subprocess.run", return_value=mock_result) as mock_run:
            with patch("eab.cli.helpers._print"):
                result = cmd_reset(
                    chip="nrf52840",
                    method="hard",
                    connect_under_reset=False,
                    device=None,
                    json_mode=False,
                )
        
        assert result == 0
        mock_run.assert_called_once()
        call_args = mock_run.call_args[0][0]
        assert call_args == ["nrfjprog", "--reset"]

    def test_reset_mcxn947_success(self):
        """Should successfully reset MCXN947 using OpenOCD."""
        mock_result = MagicMock()
        mock_result.returncode = 0
        mock_result.stdout = "Open On-Chip Debugger 0.12.0\ntarget halted\nshutdown command invoked"
        mock_result.stderr = ""
        
        with patch("eab.cli.flash.reset_cmd.subprocess.run", return_value=mock_result) as mock_run:
            with patch("eab.cli.flash.reset_cmd._print") as mock_print:
                result = cmd_reset(
                    chip="mcxn947",
                    method="hard",
                    connect_under_reset=False,
                    device=None,
                    json_mode=True,
                )
        
        assert result == 0
        mock_run.assert_called_once()
        call_args = mock_run.call_args[0][0]
        assert call_args[0] == "openocd"
        assert "reset run" in " ".join(call_args)
        
        # Verify JSON output
        output = mock_print.call_args[0][0]
        assert output["success"] is True
        assert output["chip"] == "mcxn947"

    def test_reset_with_jlink_device_string(self):
        """Should use J-Link fallback when device string provided."""
        mock_result = MagicMock()
        mock_result.returncode = 0
        mock_result.stdout = "J-Link Commander\nReset OK\nExit"
        mock_result.stderr = ""
        
        with patch("eab.cli.flash.reset_cmd.subprocess.run", return_value=mock_result) as mock_run:
            with patch("eab.cli.flash.reset_cmd._print") as mock_print:
                result = cmd_reset(
                    chip="rp2040",
                    method="hard",
                    connect_under_reset=False,
                    device="RP2040",
                    json_mode=True,
                )
        
        assert result == 0
        mock_run.assert_called_once()
        call_args = mock_run.call_args[0][0]
        assert call_args[0] == "JLinkExe"
        assert "-CommandFile" in call_args
        
        # Verify temp script was created and cleaned up
        script_path = call_args[call_args.index("-CommandFile") + 1]
        # File should be deleted after command execution
        assert not os.path.exists(script_path)
        
        output = mock_print.call_args[0][0]
        assert output["success"] is True

    def test_reset_nrfjprog_not_found(self):
        """Should return error when nrfjprog not found."""
        with patch("eab.cli.flash.reset_cmd.subprocess.run", side_effect=FileNotFoundError("nrfjprog not found")):
            with patch("eab.cli.flash.reset_cmd._print") as mock_print:
                result = cmd_reset(
                    chip="nrf5340",
                    method="hard",
                    connect_under_reset=False,
                    device=None,
                    json_mode=True,
                )
        
        assert result == 1
        output = mock_print.call_args[0][0]
        assert output["success"] is False
        assert "not found" in output["stderr"].lower()

    def test_reset_timeout(self):
        """Should handle timeout gracefully."""
        import subprocess
        
        with patch("eab.cli.flash.reset_cmd.subprocess.run", side_effect=subprocess.TimeoutExpired("nrfjprog", 30)):
            with patch("eab.cli.flash.reset_cmd._print") as mock_print:
                result = cmd_reset(
                    chip="nrf5340",
                    method="hard",
                    connect_under_reset=False,
                    device=None,
                    json_mode=True,
                )
        
        assert result == 1
        output = mock_print.call_args[0][0]
        assert output["success"] is False
        assert "timeout" in output["stderr"].lower()

    def test_reset_invalid_chip(self):
        """Should return error code 2 for invalid chip."""
        with patch("eab.cli.flash.reset_cmd._print") as mock_print:
            result = cmd_reset(
                chip="invalid_chip_xyz",
                method="hard",
                connect_under_reset=False,
                device=None,
                json_mode=True,
            )
        
        assert result == 2
        output = mock_print.call_args[0][0]
        assert "error" in output
        assert "unsupported" in output["error"].lower() or "invalid" in output["error"].lower()

    def test_reset_stm32_still_works(self):
        """Should not break existing STM32 reset functionality."""
        mock_result = MagicMock()
        mock_result.returncode = 0
        mock_result.stdout = "st-flash reset\nReset complete"
        mock_result.stderr = ""
        
        with patch("eab.cli.flash.reset_cmd.subprocess.run", return_value=mock_result) as mock_run:
            with patch("eab.cli.helpers._print"):
                result = cmd_reset(
                    chip="stm32l4",
                    method="hard",
                    connect_under_reset=False,
                    device=None,
                    json_mode=False,
                )
        
        assert result == 0
        mock_run.assert_called_once()
        call_args = mock_run.call_args[0][0]
        assert call_args == ["st-flash", "reset"]


# =============================================================================
# CLI Argument Parsing Tests
# =============================================================================

class TestResetArgumentParsing:
    """Test reset command argument parsing."""

    def test_reset_with_device_argument(self):
        """Should parse --device argument correctly."""
        from eab.cli import _build_parser
        
        parser = _build_parser()
        args = parser.parse_args([
            "reset",
            "--chip", "nrf5340",
            "--device", "NRF5340_XXAA_APP",
        ])
        
        assert args.cmd == "reset"
        assert args.chip == "nrf5340"
        assert args.device == "NRF5340_XXAA_APP"
        assert args.method == "hard"  # default

    def test_reset_without_device_argument(self):
        """Should work without --device argument (defaults to None)."""
        from eab.cli import _build_parser
        
        parser = _build_parser()
        args = parser.parse_args([
            "reset",
            "--chip", "nrf5340",
        ])
        
        assert args.cmd == "reset"
        assert args.chip == "nrf5340"
        assert args.device is None

    def test_reset_with_method(self):
        """Should parse --method argument correctly."""
        from eab.cli import _build_parser
        
        parser = _build_parser()
        args = parser.parse_args([
            "reset",
            "--chip", "mcxn947",
            "--method", "soft",
        ])
        
        assert args.method == "soft"

    def test_reset_with_connect_under_reset(self):
        """Should parse --connect-under-reset flag correctly."""
        from eab.cli import _build_parser
        
        parser = _build_parser()
        args = parser.parse_args([
            "reset",
            "--chip", "stm32l4",
            "--connect-under-reset",
        ])
        
        assert args.connect_under_reset is True


# =============================================================================
# CLI Integration Tests
# =============================================================================

class TestResetCLIIntegration:
    """Test reset command via main CLI entry point."""

    def test_reset_via_main_cli_nrf5340(self):
        """Should invoke reset command for nRF5340 via main() entry point."""
        mock_result = MagicMock()
        mock_result.returncode = 0
        mock_result.stdout = "Reset OK"
        mock_result.stderr = ""
        
        with patch("eab.cli.flash.reset_cmd.subprocess.run", return_value=mock_result):
            with patch("eab.cli._print"):
                from eab.cli import main
                result = main([
                    "--json",
                    "reset",
                    "--chip", "nrf5340",
                ])
        
        assert result == 0

    def test_reset_via_main_cli_mcxn947(self):
        """Should invoke reset command for MCXN947 via main() entry point."""
        mock_result = MagicMock()
        mock_result.returncode = 0
        mock_result.stdout = "OpenOCD reset successful"
        mock_result.stderr = ""
        
        with patch("eab.cli.flash.reset_cmd.subprocess.run", return_value=mock_result):
            with patch("eab.cli._print"):
                from eab.cli import main
                result = main([
                    "reset",
                    "--chip", "mcxn947",
                ])
        
        assert result == 0

    def test_reset_via_main_cli_with_device(self):
        """Should pass --device argument through main() entry point."""
        mock_result = MagicMock()
        mock_result.returncode = 0
        mock_result.stdout = "J-Link reset OK"
        mock_result.stderr = ""
        
        with patch("eab.cli.flash.reset_cmd.subprocess.run", return_value=mock_result):
            with patch("eab.cli._print"):
                from eab.cli import main
                result = main([
                    "reset",
                    "--chip", "rp2040",
                    "--device", "RP2040",
                ])
        
        assert result == 0


# =============================================================================
# Edge Case Tests
# =============================================================================

class TestResetEdgeCases:
    """Test edge cases and error handling."""

    def test_reset_with_none_variant(self):
        """Should handle ZephyrProfile with None variant gracefully."""
        profile = ZephyrProfile(variant=None)
        
        # Should raise NotImplementedError since variant is None
        with pytest.raises(NotImplementedError):
            profile.get_reset_command()

    def test_reset_empty_device_string(self):
        """Should handle empty device string like None."""
        profile = ZephyrProfile(variant="custom")
        
        with pytest.raises(NotImplementedError):
            profile.get_reset_command(device="")

    def test_reset_command_preserves_timeout(self):
        """Should preserve timeout value from FlashCommand."""
        profile = ZephyrProfile(variant="nrf5340")
        cmd = profile.get_reset_command()
        
        assert cmd.timeout == 30.0

    def test_jlink_script_creation_failure(self):
        """Should handle temp file creation failure gracefully."""
        profile = ZephyrProfile(variant="custom")
        
        with patch("tempfile.mkstemp", side_effect=OSError("No space left")):
            with pytest.raises(RuntimeError) as excinfo:
                profile.get_reset_command(device="CUSTOM_DEVICE")
            
            assert "Failed to create J-Link script" in str(excinfo.value)

    def test_reset_cleans_up_temp_script_on_success(self):
        """Should clean up temp J-Link script after successful reset."""
        mock_result = MagicMock()
        mock_result.returncode = 0
        mock_result.stdout = "Reset OK"
        mock_result.stderr = ""
        
        script_path_holder = []
        
        def capture_script_path(*args, **kwargs):
            # Capture the script path from the command
            cmd_list = args[0]
            if "-CommandFile" in cmd_list:
                idx = cmd_list.index("-CommandFile")
                script_path_holder.append(cmd_list[idx + 1])
            return mock_result
        
        with patch("eab.cli.flash.reset_cmd.subprocess.run", side_effect=capture_script_path):
            with patch("eab.cli.helpers._print"):
                result = cmd_reset(
                    chip="rp2040",
                    method="hard",
                    connect_under_reset=False,
                    device="RP2040",
                    json_mode=True,
                )
        
        assert result == 0
        # Script should be cleaned up
        assert len(script_path_holder) == 1
        assert not os.path.exists(script_path_holder[0])

    def test_reset_cleans_up_temp_script_on_failure(self):
        """Should clean up temp J-Link script even after failure."""
        script_path_holder = []
        
        def capture_and_fail(*args, **kwargs):
            cmd_list = args[0]
            if "-CommandFile" in cmd_list:
                idx = cmd_list.index("-CommandFile")
                script_path_holder.append(cmd_list[idx + 1])
            raise FileNotFoundError("JLinkExe not found")
        
        with patch("eab.cli.flash.reset_cmd.subprocess.run", side_effect=capture_and_fail):
            with patch("eab.cli.helpers._print"):
                result = cmd_reset(
                    chip="rp2040",
                    method="hard",
                    connect_under_reset=False,
                    device="RP2040",
                    json_mode=True,
                )
        
        assert result == 1
        # Script should still be cleaned up
        assert len(script_path_holder) == 1
        assert not os.path.exists(script_path_holder[0])
