"""Tests for ESP-IDF project detection and flashing."""

from __future__ import annotations

import json
import os
import sys
from pathlib import Path
from unittest.mock import Mock, patch

import pytest

# Add parent directory to path for imports (consistent with existing tests).
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__)))))

from eab.chips.esp32 import ESP32Profile
from eab.cli.flash import cmd_flash


def test_detect_esp_idf_project_with_valid_built_project(tmp_path: Path):
    """Test detection of a valid, built ESP-IDF project."""
    project_dir = tmp_path / "my_esp_project"
    project_dir.mkdir()
    
    # Create sdkconfig with chip target
    sdkconfig = project_dir / "sdkconfig"
    sdkconfig.write_text("CONFIG_IDF_TARGET=\"esp32c6\"\n")
    
    # Create build directory with flash_args
    build_dir = project_dir / "build"
    build_dir.mkdir()
    flash_args = build_dir / "flash_args"
    flash_args.write_text("0x0 bootloader.bin\n0x8000 partition-table.bin\n0x10000 app.bin\n")
    
    # Call detect function
    result = ESP32Profile.detect_esp_idf_project(str(project_dir))
    
    # Verify detection results
    assert result is not None
    assert result["chip"] == "esp32c6"
    assert result["has_flash_args"] is True
    assert result["build_dir"] is not None


def test_detect_esp_idf_project_with_unbuilt_project(tmp_path: Path):
    """Test detection of ESP-IDF project that hasn't been built."""
    project_dir = tmp_path / "unbuilt_project"
    project_dir.mkdir()
    
    # Create sdkconfig but no build directory
    sdkconfig = project_dir / "sdkconfig"
    sdkconfig.write_text("CONFIG_IDF_TARGET=\"esp32s3\"\n")
    
    # Call detect function
    result = ESP32Profile.detect_esp_idf_project(str(project_dir))
    
    # Verify detection results
    assert result is not None
    assert result["chip"] == "esp32s3"
    assert result["has_flash_args"] is False
    assert result["build_dir"] is None


def test_detect_esp_idf_project_with_non_esp_directory(tmp_path: Path):
    """Test detection of directory that is not an ESP-IDF project."""
    random_dir = tmp_path / "random_directory"
    random_dir.mkdir()
    
    # Create some random files but not ESP-IDF markers
    (random_dir / "README.md").write_text("Random project\n")
    (random_dir / "main.c").write_text("int main() {}\n")
    
    # Call detect function
    result = ESP32Profile.detect_esp_idf_project(str(random_dir))
    
    # Verify detection results
    assert result is None


def test_detect_esp_idf_project_with_different_chip_types(tmp_path: Path):
    """Test detection with various ESP32 chip types."""
    chip_types = ["esp32", "esp32s2", "esp32s3", "esp32c3", "esp32c6", "esp32h2"]
    
    for chip_type in chip_types:
        project_dir = tmp_path / f"project_{chip_type}"
        project_dir.mkdir()
        
        # Create sdkconfig with specific chip target
        sdkconfig = project_dir / "sdkconfig"
        sdkconfig.write_text(f"CONFIG_IDF_TARGET=\"{chip_type}\"\n")
        
        # Create build artifacts
        build_dir = project_dir / "build"
        build_dir.mkdir()
        flash_args = build_dir / "flash_args"
        flash_args.write_text("0x10000 app.bin\n")
        
        # Call detect function
        result = ESP32Profile.detect_esp_idf_project(str(project_dir))
        
        # Verify correct chip was detected
        assert result is not None
        assert result["chip"] == chip_type
        assert result["has_flash_args"] is True


def test_cmd_flash_with_esp_idf_project_auto_detects_chip(tmp_path: Path, capsys):
    """Test that cmd_flash auto-detects chip from ESP-IDF project."""
    project_dir = tmp_path / "my_project"
    project_dir.mkdir()
    
    # Create sdkconfig
    sdkconfig = project_dir / "sdkconfig"
    sdkconfig.write_text("CONFIG_IDF_TARGET=\"esp32c6\"\n")
    
    # Create build directory
    build_dir = project_dir / "build"
    build_dir.mkdir()
    flash_args = build_dir / "flash_args"
    flash_args.write_text("0x0 bootloader.bin\n0x8000 partition-table.bin\n0x10000 app.bin\n")
    
    # Create dummy binary files
    (build_dir / "bootloader.bin").write_bytes(b"\x00" * 100)
    (build_dir / "partition-table.bin").write_bytes(b"\x00" * 100)
    (build_dir / "app.bin").write_bytes(b"\x00" * 100)
    
    # Mock subprocess.run to capture esptool command
    mock_result = Mock()
    mock_result.returncode = 0
    mock_result.stdout = "Flash successful"
    mock_result.stderr = ""
    
    with patch("eab.cli.flash._execute.subprocess.run", return_value=mock_result) as mock_run:
        result = cmd_flash(
            firmware=str(project_dir),
            chip=None,  # No chip specified, should auto-detect
            address=None,
            port="/dev/ttyUSB0",
            tool=None,
            baud=921600,
            connect_under_reset=False,
            board=None,
            runner=None,
            json_mode=True,
        )
    
    # Verify success
    assert result == 0
    
    # Verify subprocess.run was called
    assert mock_run.called
    call_args = mock_run.call_args[0][0]
    
    # Verify esptool command includes correct chip and all partitions
    assert call_args[0] == "esptool"
    assert "--chip" in call_args
    chip_idx = call_args.index("--chip")
    assert call_args[chip_idx + 1] == "esp32c6"
    
    # Verify all three binaries are in the command
    assert str(build_dir / "bootloader.bin") in call_args
    assert str(build_dir / "partition-table.bin") in call_args
    assert str(build_dir / "app.bin") in call_args
    
    # Verify JSON output
    captured = capsys.readouterr()
    output = json.loads(captured.out)
    assert output["success"] is True
    assert output["chip"] == "esp32c6"


def test_cmd_flash_with_esp_idf_project_explicit_chip_override(tmp_path: Path, capsys):
    """Test that explicit --chip flag overrides auto-detection."""
    project_dir = tmp_path / "my_project"
    project_dir.mkdir()
    
    # Create sdkconfig with esp32c6
    sdkconfig = project_dir / "sdkconfig"
    sdkconfig.write_text("CONFIG_IDF_TARGET=\"esp32c6\"\n")
    
    # Create build directory
    build_dir = project_dir / "build"
    build_dir.mkdir()
    flash_args = build_dir / "flash_args"
    flash_args.write_text("0x10000 app.bin\n")
    
    # Create dummy binary file
    (build_dir / "app.bin").write_bytes(b"\x00" * 100)
    
    # Mock subprocess.run
    mock_result = Mock()
    mock_result.returncode = 0
    mock_result.stdout = "Flash successful"
    mock_result.stderr = ""
    
    with patch("eab.cli.flash._execute.subprocess.run", return_value=mock_result) as mock_run:
        result = cmd_flash(
            firmware=str(project_dir),
            chip="esp32s3",  # Explicit override
            address=None,
            port="/dev/ttyUSB0",
            tool=None,
            baud=921600,
            connect_under_reset=False,
            board=None,
            runner=None,
            json_mode=True,
        )
    
    # Verify success
    assert result == 0
    
    # Verify subprocess.run was called with overridden chip
    assert mock_run.called
    call_args = mock_run.call_args[0][0]
    
    # Verify esptool uses the explicit chip, not auto-detected
    assert "--chip" in call_args
    chip_idx = call_args.index("--chip")
    assert call_args[chip_idx + 1] == "esp32s3"
    
    # Verify JSON output
    captured = capsys.readouterr()
    output = json.loads(captured.out)
    assert output["success"] is True
    assert output["chip"] == "esp32s3"


def test_cmd_flash_with_unbuilt_project_returns_error(tmp_path: Path, capsys):
    """Test that cmd_flash returns helpful error for unbuilt ESP-IDF project."""
    project_dir = tmp_path / "unbuilt_project"
    project_dir.mkdir()
    
    # Create sdkconfig but no build directory
    sdkconfig = project_dir / "sdkconfig"
    sdkconfig.write_text("CONFIG_IDF_TARGET=\"esp32c6\"\n")
    
    # Call cmd_flash
    result = cmd_flash(
        firmware=str(project_dir),
        chip=None,
        address=None,
        port="/dev/ttyUSB0",
        tool=None,
        baud=921600,
        connect_under_reset=False,
        board=None,
        runner=None,
        json_mode=True,
    )
    
    # Verify error code
    assert result == 1
    
    # Verify JSON output contains helpful error message
    captured = capsys.readouterr()
    output = json.loads(captured.out)
    assert "error" in output
    assert "idf.py build" in output["error"]


def test_cmd_flash_with_non_esp_directory_returns_error(tmp_path: Path, capsys):
    """Test that cmd_flash returns error for non-ESP-IDF directory."""
    random_dir = tmp_path / "random_dir"
    random_dir.mkdir()
    
    # Create random files but not ESP-IDF markers
    (random_dir / "README.md").write_text("Random project\n")
    
    # Call cmd_flash
    result = cmd_flash(
        firmware=str(random_dir),
        chip=None,
        address=None,
        port="/dev/ttyUSB0",
        tool=None,
        baud=921600,
        connect_under_reset=False,
        board=None,
        runner=None,
        json_mode=True,
    )
    
    # Verify error code
    assert result == 1
    
    # Verify JSON output contains error about not being ESP-IDF project
    captured = capsys.readouterr()
    output = json.loads(captured.out)
    assert "error" in output
    assert "not an ESP-IDF project" in output["error"]
    assert "sdkconfig" in output["error"]


def test_cmd_flash_with_binary_file_no_chip_returns_error(tmp_path: Path, capsys):
    """Test that cmd_flash requires --chip when flashing a binary file."""
    firmware_bin = tmp_path / "firmware.bin"
    firmware_bin.write_bytes(b"\x00" * 100)
    
    # Call cmd_flash without --chip
    result = cmd_flash(
        firmware=str(firmware_bin),
        chip=None,  # No chip specified
        address="0x10000",
        port="/dev/ttyUSB0",
        tool=None,
        baud=921600,
        connect_under_reset=False,
        board=None,
        runner=None,
        json_mode=True,
    )
    
    # Verify error code
    assert result == 1
    
    # Verify JSON output contains error about --chip being required
    captured = capsys.readouterr()
    output = json.loads(captured.out)
    assert "error" in output
    assert "--chip is required" in output["error"]


def test_cmd_flash_with_binary_file_and_chip_still_works(tmp_path: Path, capsys):
    """Test backward compatibility: flashing binary file with --chip still works."""
    firmware_bin = tmp_path / "firmware.bin"
    firmware_bin.write_bytes(b"\x00" * 100)
    
    # Mock subprocess.run
    mock_result = Mock()
    mock_result.returncode = 0
    mock_result.stdout = "Flash successful"
    mock_result.stderr = ""
    
    with patch("eab.cli.flash._execute.subprocess.run", return_value=mock_result) as mock_run:
        result = cmd_flash(
            firmware=str(firmware_bin),
            chip="esp32c6",  # Explicit chip
            address="0x10000",
            port="/dev/ttyUSB0",
            tool=None,
            baud=921600,
            connect_under_reset=False,
            board=None,
            runner=None,
            json_mode=True,
        )
    
    # Verify success
    assert result == 0
    
    # Verify subprocess.run was called
    assert mock_run.called
    call_args = mock_run.call_args[0][0]
    
    # Verify esptool command includes chip and firmware path
    assert call_args[0] == "esptool"
    assert "--chip" in call_args
    chip_idx = call_args.index("--chip")
    assert call_args[chip_idx + 1] == "esp32c6"
    assert str(firmware_bin) in call_args
    
    # Verify JSON output
    captured = capsys.readouterr()
    output = json.loads(captured.out)
    assert output["success"] is True
    assert output["chip"] == "esp32c6"


def test_detect_esp_idf_project_with_sdkconfig_without_quotes(tmp_path: Path):
    """Test detection when sdkconfig has CONFIG_IDF_TARGET without quotes."""
    project_dir = tmp_path / "project"
    project_dir.mkdir()
    
    # Create sdkconfig without quotes around target value
    sdkconfig = project_dir / "sdkconfig"
    sdkconfig.write_text("CONFIG_IDF_TARGET=esp32c3\n")
    
    # Create build artifacts
    build_dir = project_dir / "build"
    build_dir.mkdir()
    flash_args = build_dir / "flash_args"
    flash_args.write_text("0x10000 app.bin\n")
    
    # Call detect function
    result = ESP32Profile.detect_esp_idf_project(str(project_dir))
    
    # Verify detection works even without quotes
    assert result is not None
    assert result["chip"] == "esp32c3"
    assert result["has_flash_args"] is True


def test_detect_esp_idf_project_with_build_only_no_sdkconfig(tmp_path: Path):
    """Test detection when build directory exists but no sdkconfig (edge case)."""
    project_dir = tmp_path / "project"
    project_dir.mkdir()
    
    # Create build directory without sdkconfig (should not be detected)
    build_dir = project_dir / "build"
    build_dir.mkdir()
    flash_args = build_dir / "flash_args"
    flash_args.write_text("0x10000 app.bin\n")
    
    # Call detect function
    result = ESP32Profile.detect_esp_idf_project(str(project_dir))
    
    # Verify it's NOT detected as ESP project (requires sdkconfig or CMakeLists.txt with chip info)
    assert result is None


def test_cmd_flash_with_esp_project_no_sdkconfig_requires_explicit_chip(tmp_path: Path, capsys):
    """Test that project without sdkconfig requires explicit --chip flag."""
    project_dir = tmp_path / "project"
    project_dir.mkdir()
    
    # Create build directory without sdkconfig
    build_dir = project_dir / "build"
    build_dir.mkdir()
    flash_args = build_dir / "flash_args"
    flash_args.write_text("0x10000 app.bin\n")
    (build_dir / "app.bin").write_bytes(b"\x00" * 100)
    
    # Call cmd_flash without --chip
    result = cmd_flash(
        firmware=str(project_dir),
        chip=None,
        address=None,
        port="/dev/ttyUSB0",
        tool=None,
        baud=921600,
        connect_under_reset=False,
        board=None,
        runner=None,
        json_mode=True,
    )
    
    # Verify error code
    assert result == 1
    
    # Verify error message about not being ESP-IDF project
    captured = capsys.readouterr()
    output = json.loads(captured.out)
    assert "error" in output
    assert "not an ESP-IDF project" in output["error"]


def test_cmd_flash_with_no_stub_flag(tmp_path: Path, capsys):
    """Test that --no-stub flag is passed to esptool when specified."""
    firmware_bin = tmp_path / "firmware.bin"
    firmware_bin.write_bytes(b"\x00" * 100)
    
    # Mock subprocess.run
    mock_result = Mock()
    mock_result.returncode = 0
    mock_result.stdout = "Flash successful"
    mock_result.stderr = ""
    
    with patch("eab.cli.flash._execute.subprocess.run", return_value=mock_result) as mock_run:
        result = cmd_flash(
            firmware=str(firmware_bin),
            chip="esp32c6",
            address="0x10000",
            port="/dev/ttyUSB0",
            tool=None,
            baud=921600,
            connect_under_reset=False,
            board=None,
            runner=None,
            no_stub=True,  # Enable --no-stub
            json_mode=True,
        )
    
    # Verify success
    assert result == 0
    
    # Verify subprocess.run was called
    assert mock_run.called
    call_args = mock_run.call_args[0][0]
    
    # Verify esptool command includes --no-stub flag
    assert call_args[0] == "esptool"
    assert "--no-stub" in call_args
    
    # Verify JSON output
    captured = capsys.readouterr()
    output = json.loads(captured.out)
    assert output["success"] is True
    assert output["chip"] == "esp32c6"


def test_cmd_flash_no_stub_in_json_output(tmp_path: Path, capsys):
    """Test that JSON output includes no_stub field."""
    firmware_bin = tmp_path / "firmware.bin"
    firmware_bin.write_bytes(b"\x00" * 100)
    
    # Mock subprocess.run
    mock_result = Mock()
    mock_result.returncode = 0
    mock_result.stdout = "Flash successful"
    mock_result.stderr = ""
    
    with patch("eab.cli.flash._execute.subprocess.run", return_value=mock_result) as mock_run:
        # Test with no_stub=True
        result = cmd_flash(
            firmware=str(firmware_bin),
            chip="esp32c6",
            address="0x10000",
            port="/dev/ttyUSB0",
            tool=None,
            baud=921600,
            connect_under_reset=False,
            board=None,
            runner=None,
            no_stub=True,
            json_mode=True,
        )
    
    # Verify JSON output includes no_stub field
    captured = capsys.readouterr()
    output = json.loads(captured.out)
    assert "no_stub" in output
    assert output["no_stub"] is True
    
    # Test with no_stub=False (default)
    with patch("eab.cli.flash._execute.subprocess.run", return_value=mock_result) as mock_run:
        result = cmd_flash(
            firmware=str(firmware_bin),
            chip="esp32c6",
            address="0x10000",
            port="/dev/ttyUSB0",
            tool=None,
            baud=921600,
            connect_under_reset=False,
            board=None,
            runner=None,
            no_stub=False,
            json_mode=True,
        )
    
    # Verify JSON output includes no_stub field set to False
    captured = capsys.readouterr()
    output = json.loads(captured.out)
    assert "no_stub" in output
    assert output["no_stub"] is False


def test_cmd_flash_with_extra_esptool_args(tmp_path: Path, capsys):
    """Test that extra_esptool_args are passed to esptool when specified."""
    firmware_bin = tmp_path / "firmware.bin"
    firmware_bin.write_bytes(b"\x00" * 100)
    
    # Mock subprocess.run
    mock_result = Mock()
    mock_result.returncode = 0
    mock_result.stdout = "Flash successful"
    mock_result.stderr = ""
    
    extra_args = ["--no-compress", "--verify"]
    
    with patch("eab.cli.flash._execute.subprocess.run", return_value=mock_result) as mock_run:
        result = cmd_flash(
            firmware=str(firmware_bin),
            chip="esp32c6",
            address="0x10000",
            port="/dev/ttyUSB0",
            tool=None,
            baud=921600,
            connect_under_reset=False,
            board=None,
            runner=None,
            extra_esptool_args=extra_args,
            json_mode=True,
        )
    
    # Verify success
    assert result == 0
    
    # Verify subprocess.run was called
    assert mock_run.called
    call_args = mock_run.call_args[0][0]
    
    # Verify esptool command includes extra args
    assert call_args[0] == "esptool"
    assert "--no-compress" in call_args
    assert "--verify" in call_args
    
    # Verify JSON output
    captured = capsys.readouterr()
    output = json.loads(captured.out)
    assert output["success"] is True


def test_cmd_flash_with_no_stub_and_extra_args_together(tmp_path: Path, capsys):
    """Test that both no_stub and extra_esptool_args can be used together."""
    firmware_bin = tmp_path / "firmware.bin"
    firmware_bin.write_bytes(b"\x00" * 100)
    
    # Mock subprocess.run
    mock_result = Mock()
    mock_result.returncode = 0
    mock_result.stdout = "Flash successful"
    mock_result.stderr = ""
    
    extra_args = ["--verify"]
    
    with patch("eab.cli.flash._execute.subprocess.run", return_value=mock_result) as mock_run:
        result = cmd_flash(
            firmware=str(firmware_bin),
            chip="esp32c6",
            address="0x10000",
            port="/dev/ttyUSB0",
            tool=None,
            baud=921600,
            connect_under_reset=False,
            board=None,
            runner=None,
            no_stub=True,
            extra_esptool_args=extra_args,
            json_mode=True,
        )
    
    # Verify success
    assert result == 0
    
    # Verify subprocess.run was called
    assert mock_run.called
    call_args = mock_run.call_args[0][0]
    
    # Verify esptool command includes both --no-stub and extra args
    assert call_args[0] == "esptool"
    assert "--no-stub" in call_args
    assert "--verify" in call_args
    
    # Verify JSON output includes no_stub field
    captured = capsys.readouterr()
    output = json.loads(captured.out)
    assert output["success"] is True
    assert output["no_stub"] is True
