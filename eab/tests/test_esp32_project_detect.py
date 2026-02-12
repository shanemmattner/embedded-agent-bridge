"""Tests for ESP-IDF project detection in ESP32Profile."""

from __future__ import annotations

import tempfile
from pathlib import Path

import pytest

from eab.chips.esp32 import ESP32Profile


def test_detect_chip_from_sdkconfig_with_quotes():
    """Test detect_chip_from_sdkconfig parses CONFIG_IDF_TARGET with quotes."""
    with tempfile.TemporaryDirectory() as tmpdir:
        project_dir = Path(tmpdir)
        sdkconfig = project_dir / "sdkconfig"
        sdkconfig.write_text(
            "# ESP-IDF Configuration\n"
            'CONFIG_IDF_TARGET="esp32c6"\n'
            "CONFIG_ESPTOOLPY_FLASHSIZE_4MB=y\n"
        )

        chip = ESP32Profile.detect_chip_from_sdkconfig(project_dir)
        assert chip == "esp32c6"


def test_detect_chip_from_sdkconfig_without_quotes():
    """Test detect_chip_from_sdkconfig parses CONFIG_IDF_TARGET without quotes."""
    with tempfile.TemporaryDirectory() as tmpdir:
        project_dir = Path(tmpdir)
        sdkconfig = project_dir / "sdkconfig"
        sdkconfig.write_text(
            "# ESP-IDF Configuration\n"
            "CONFIG_IDF_TARGET=esp32s3\n"
            "CONFIG_ESPTOOLPY_FLASHSIZE_4MB=y\n"
        )

        chip = ESP32Profile.detect_chip_from_sdkconfig(project_dir)
        assert chip == "esp32s3"


def test_detect_chip_from_sdkconfig_defaults():
    """Test detect_chip_from_sdkconfig falls back to sdkconfig.defaults."""
    with tempfile.TemporaryDirectory() as tmpdir:
        project_dir = Path(tmpdir)
        sdkconfig_defaults = project_dir / "sdkconfig.defaults"
        sdkconfig_defaults.write_text(
            "# Minimal config for ESP32-C6\n"
            'CONFIG_IDF_TARGET="esp32c6"\n'
            "CONFIG_ESPTOOLPY_FLASHSIZE_4MB=y\n"
        )

        chip = ESP32Profile.detect_chip_from_sdkconfig(project_dir)
        assert chip == "esp32c6"


def test_detect_chip_from_sdkconfig_prefers_sdkconfig():
    """Test detect_chip_from_sdkconfig prefers sdkconfig over sdkconfig.defaults."""
    with tempfile.TemporaryDirectory() as tmpdir:
        project_dir = Path(tmpdir)
        
        # sdkconfig.defaults has esp32c6
        sdkconfig_defaults = project_dir / "sdkconfig.defaults"
        sdkconfig_defaults.write_text('CONFIG_IDF_TARGET="esp32c6"\n')
        
        # sdkconfig has esp32s3 (should win)
        sdkconfig = project_dir / "sdkconfig"
        sdkconfig.write_text('CONFIG_IDF_TARGET="esp32s3"\n')

        chip = ESP32Profile.detect_chip_from_sdkconfig(project_dir)
        assert chip == "esp32s3"


def test_detect_chip_from_sdkconfig_missing_files():
    """Test detect_chip_from_sdkconfig returns None when no config files exist."""
    with tempfile.TemporaryDirectory() as tmpdir:
        project_dir = Path(tmpdir)
        chip = ESP32Profile.detect_chip_from_sdkconfig(project_dir)
        assert chip is None


def test_detect_chip_from_sdkconfig_missing_target():
    """Test detect_chip_from_sdkconfig returns None when CONFIG_IDF_TARGET not in file."""
    with tempfile.TemporaryDirectory() as tmpdir:
        project_dir = Path(tmpdir)
        sdkconfig = project_dir / "sdkconfig"
        sdkconfig.write_text(
            "# ESP-IDF Configuration\n"
            "CONFIG_ESPTOOLPY_FLASHSIZE_4MB=y\n"
            "CONFIG_ESP_CONSOLE_USB_SERIAL_JTAG=y\n"
        )

        chip = ESP32Profile.detect_chip_from_sdkconfig(project_dir)
        assert chip is None


def test_detect_chip_from_sdkconfig_with_spaces():
    """Test detect_chip_from_sdkconfig handles extra whitespace."""
    with tempfile.TemporaryDirectory() as tmpdir:
        project_dir = Path(tmpdir)
        sdkconfig = project_dir / "sdkconfig"
        sdkconfig.write_text(
            "# ESP-IDF Configuration\n"
            '  CONFIG_IDF_TARGET  =  "esp32"  \n'
            "CONFIG_ESPTOOLPY_FLASHSIZE_4MB=y\n"
        )

        chip = ESP32Profile.detect_chip_from_sdkconfig(project_dir)
        assert chip == "esp32"


def test_detect_chip_from_sdkconfig_various_chips():
    """Test detect_chip_from_sdkconfig handles various ESP32 chip variants."""
    chips = ["esp32", "esp32s2", "esp32s3", "esp32c3", "esp32c6", "esp32h2"]
    
    for expected_chip in chips:
        with tempfile.TemporaryDirectory() as tmpdir:
            project_dir = Path(tmpdir)
            sdkconfig = project_dir / "sdkconfig"
            sdkconfig.write_text(f'CONFIG_IDF_TARGET="{expected_chip}"\n')

            chip = ESP32Profile.detect_chip_from_sdkconfig(project_dir)
            assert chip == expected_chip


def test_detect_esp_idf_project_with_sdkconfig_and_build():
    """Test detect_esp_idf_project detects valid project with sdkconfig and build dir."""
    with tempfile.TemporaryDirectory() as tmpdir:
        project_dir = Path(tmpdir)
        
        # Create sdkconfig
        sdkconfig = project_dir / "sdkconfig"
        sdkconfig.write_text('CONFIG_IDF_TARGET="esp32c6"\n')
        
        # Create CMakeLists.txt
        cmakelists = project_dir / "CMakeLists.txt"
        cmakelists.write_text(
            "cmake_minimum_required(VERSION 3.16)\n"
            "include($ENV{IDF_PATH}/tools/cmake/project.cmake)\n"
            "project(test-project)\n"
        )
        
        # Create build dir with flash_args
        build_dir = project_dir / "build"
        build_dir.mkdir()
        flash_args = build_dir / "flash_args"
        flash_args.write_text("0x0 bootloader.bin\n0x10000 app.bin\n")

        result = ESP32Profile.detect_esp_idf_project(str(project_dir))
        
        assert result is not None
        assert result["chip"] == "esp32c6"
        assert result["build_dir"] == str(build_dir)
        assert result["has_flash_args"] is True


def test_detect_esp_idf_project_with_sdkconfig_defaults():
    """Test detect_esp_idf_project works with sdkconfig.defaults only."""
    with tempfile.TemporaryDirectory() as tmpdir:
        project_dir = Path(tmpdir)
        
        # Create sdkconfig.defaults only
        sdkconfig_defaults = project_dir / "sdkconfig.defaults"
        sdkconfig_defaults.write_text('CONFIG_IDF_TARGET="esp32c6"\n')
        
        # Create CMakeLists.txt
        cmakelists = project_dir / "CMakeLists.txt"
        cmakelists.write_text("project(test-project)\n")

        result = ESP32Profile.detect_esp_idf_project(str(project_dir))
        
        assert result is not None
        assert result["chip"] == "esp32c6"
        assert result["build_dir"] is None
        assert result["has_flash_args"] is False


def test_detect_esp_idf_project_without_build_dir():
    """Test detect_esp_idf_project detects project without build directory."""
    with tempfile.TemporaryDirectory() as tmpdir:
        project_dir = Path(tmpdir)
        
        # Create sdkconfig
        sdkconfig = project_dir / "sdkconfig"
        sdkconfig.write_text('CONFIG_IDF_TARGET="esp32s3"\n')
        
        # Create CMakeLists.txt
        cmakelists = project_dir / "CMakeLists.txt"
        cmakelists.write_text("idf_component_register(SRCS main.c)\n")

        result = ESP32Profile.detect_esp_idf_project(str(project_dir))
        
        assert result is not None
        assert result["chip"] == "esp32s3"
        assert result["build_dir"] is None
        assert result["has_flash_args"] is False


def test_detect_esp_idf_project_with_idf_component_register():
    """Test detect_esp_idf_project detects ESP-IDF via idf_component_register."""
    with tempfile.TemporaryDirectory() as tmpdir:
        project_dir = Path(tmpdir)
        
        # Create CMakeLists.txt with idf_component_register (no sdkconfig yet)
        cmakelists = project_dir / "CMakeLists.txt"
        cmakelists.write_text(
            "idf_component_register(SRCS main.c\n"
            "                       INCLUDE_DIRS .)\n"
        )
        
        # Create sdkconfig.defaults
        sdkconfig_defaults = project_dir / "sdkconfig.defaults"
        sdkconfig_defaults.write_text('CONFIG_IDF_TARGET="esp32"\n')

        result = ESP32Profile.detect_esp_idf_project(str(project_dir))
        
        assert result is not None
        assert result["chip"] == "esp32"


def test_detect_esp_idf_project_with_idf_path():
    """Test detect_esp_idf_project detects ESP-IDF via IDF_PATH reference."""
    with tempfile.TemporaryDirectory() as tmpdir:
        project_dir = Path(tmpdir)
        
        # Create CMakeLists.txt with IDF_PATH
        cmakelists = project_dir / "CMakeLists.txt"
        cmakelists.write_text(
            "cmake_minimum_required(VERSION 3.16)\n"
            "include($ENV{IDF_PATH}/tools/cmake/project.cmake)\n"
        )
        
        # Create sdkconfig
        sdkconfig = project_dir / "sdkconfig"
        sdkconfig.write_text('CONFIG_IDF_TARGET="esp32c3"\n')

        result = ESP32Profile.detect_esp_idf_project(str(project_dir))
        
        assert result is not None
        assert result["chip"] == "esp32c3"


def test_detect_esp_idf_project_non_esp_idf_directory():
    """Test detect_esp_idf_project returns None for non-ESP-IDF directory."""
    with tempfile.TemporaryDirectory() as tmpdir:
        project_dir = Path(tmpdir)
        
        # Create a generic CMakeLists.txt (no ESP-IDF markers)
        cmakelists = project_dir / "CMakeLists.txt"
        cmakelists.write_text(
            "cmake_minimum_required(VERSION 3.10)\n"
            "project(generic-project)\n"
            "add_executable(app main.c)\n"
        )

        result = ESP32Profile.detect_esp_idf_project(str(project_dir))
        
        assert result is None


def test_detect_esp_idf_project_empty_directory():
    """Test detect_esp_idf_project returns None for empty directory."""
    with tempfile.TemporaryDirectory() as tmpdir:
        project_dir = Path(tmpdir)
        result = ESP32Profile.detect_esp_idf_project(str(project_dir))
        assert result is None


def test_detect_esp_idf_project_not_a_directory():
    """Test detect_esp_idf_project returns None when path is not a directory."""
    with tempfile.TemporaryDirectory() as tmpdir:
        # Create a file instead of directory
        file_path = Path(tmpdir) / "not_a_dir.txt"
        file_path.write_text("test")
        
        result = ESP32Profile.detect_esp_idf_project(str(file_path))
        assert result is None


def test_detect_esp_idf_project_nonexistent_path():
    """Test detect_esp_idf_project returns None for nonexistent path."""
    result = ESP32Profile.detect_esp_idf_project("/nonexistent/path/to/project")
    assert result is None


def test_detect_esp_idf_project_build_without_flash_args():
    """Test detect_esp_idf_project detects build dir without flash_args."""
    with tempfile.TemporaryDirectory() as tmpdir:
        project_dir = Path(tmpdir)
        
        # Create sdkconfig
        sdkconfig = project_dir / "sdkconfig"
        sdkconfig.write_text('CONFIG_IDF_TARGET="esp32c6"\n')
        
        # Create CMakeLists.txt
        cmakelists = project_dir / "CMakeLists.txt"
        cmakelists.write_text("project(test)\n")
        
        # Create build dir but no flash_args
        build_dir = project_dir / "build"
        build_dir.mkdir()

        result = ESP32Profile.detect_esp_idf_project(str(project_dir))
        
        assert result is not None
        assert result["chip"] == "esp32c6"
        assert result["build_dir"] == str(build_dir)
        assert result["has_flash_args"] is False


def test_detect_esp_idf_project_minimal_with_sdkconfig_only():
    """Test detect_esp_idf_project with only sdkconfig file."""
    with tempfile.TemporaryDirectory() as tmpdir:
        project_dir = Path(tmpdir)
        
        # Create only sdkconfig (minimal ESP-IDF project marker)
        sdkconfig = project_dir / "sdkconfig"
        sdkconfig.write_text('CONFIG_IDF_TARGET="esp32"\n')

        result = ESP32Profile.detect_esp_idf_project(str(project_dir))
        
        assert result is not None
        assert result["chip"] == "esp32"
        assert result["build_dir"] is None
        assert result["has_flash_args"] is False


def test_detect_esp_idf_project_no_chip_info():
    """Test detect_esp_idf_project returns None when no sdkconfig files exist."""
    with tempfile.TemporaryDirectory() as tmpdir:
        project_dir = Path(tmpdir)
        
        # Create CMakeLists.txt with ESP-IDF markers
        cmakelists = project_dir / "CMakeLists.txt"
        cmakelists.write_text("idf_component_register(SRCS main.c)\n")
        
        # No sdkconfig or sdkconfig.defaults

        result = ESP32Profile.detect_esp_idf_project(str(project_dir))
        
        # Should return None - requires at least sdkconfig.defaults for ESP-IDF detection
        assert result is None


def test_detect_esp_idf_project_real_example_structure():
    """Test detect_esp_idf_project with realistic ESP-IDF project structure."""
    with tempfile.TemporaryDirectory() as tmpdir:
        project_dir = Path(tmpdir)
        
        # Create typical ESP-IDF project structure
        (project_dir / "main").mkdir()
        (project_dir / "main" / "CMakeLists.txt").write_text(
            "idf_component_register(SRCS main.c)\n"
        )
        (project_dir / "main" / "main.c").write_text("void app_main() {}\n")
        
        # Root CMakeLists.txt
        (project_dir / "CMakeLists.txt").write_text(
            "cmake_minimum_required(VERSION 3.16)\n"
            "include($ENV{IDF_PATH}/tools/cmake/project.cmake)\n"
            "project(my-app)\n"
        )
        
        # sdkconfig.defaults
        (project_dir / "sdkconfig.defaults").write_text(
            "# Minimal config\n"
            'CONFIG_IDF_TARGET="esp32c6"\n'
            "CONFIG_ESPTOOLPY_FLASHSIZE_4MB=y\n"
        )
        
        # Build directory with flash_args
        build_dir = project_dir / "build"
        build_dir.mkdir()
        (build_dir / "flash_args").write_text(
            "--flash_mode dio --flash_freq 80m --flash_size 4MB\n"
            "0x0 bootloader.bin\n"
            "0x8000 partition-table.bin\n"
            "0x10000 my-app.bin\n"
        )

        result = ESP32Profile.detect_esp_idf_project(str(project_dir))
        
        assert result is not None
        assert result["chip"] == "esp32c6"
        assert result["build_dir"] == str(build_dir)
        assert result["has_flash_args"] is True


def test_detect_esp_idf_project_cmake_read_error():
    """Test detect_esp_idf_project handles CMakeLists.txt read errors gracefully."""
    with tempfile.TemporaryDirectory() as tmpdir:
        project_dir = Path(tmpdir)
        
        # Create sdkconfig
        sdkconfig = project_dir / "sdkconfig"
        sdkconfig.write_text('CONFIG_IDF_TARGET="esp32"\n')
        
        # Create CMakeLists.txt but make it unreadable
        cmakelists = project_dir / "CMakeLists.txt"
        cmakelists.write_text("project(test)\n")
        cmakelists.chmod(0o000)

        try:
            result = ESP32Profile.detect_esp_idf_project(str(project_dir))
            
            # Should still detect as ESP-IDF project due to sdkconfig
            assert result is not None
            assert result["chip"] == "esp32"
        finally:
            # Restore permissions for cleanup
            cmakelists.chmod(0o644)


def test_detect_chip_from_sdkconfig_unreadable_file():
    """Test detect_chip_from_sdkconfig handles unreadable files gracefully."""
    with tempfile.TemporaryDirectory() as tmpdir:
        project_dir = Path(tmpdir)
        
        # Create sdkconfig but make it unreadable
        sdkconfig = project_dir / "sdkconfig"
        sdkconfig.write_text('CONFIG_IDF_TARGET="esp32c6"\n')
        sdkconfig.chmod(0o000)

        try:
            chip = ESP32Profile.detect_chip_from_sdkconfig(project_dir)
            # Should return None when unable to read
            assert chip is None
        finally:
            # Restore permissions for cleanup
            sdkconfig.chmod(0o644)
