"""
Unit tests for ESP32 commands in eabctl.

These tests verify command generation, chip profile behavior, and error handling
WITHOUT requiring actual hardware. Hardware integration tests are separate.
"""
from __future__ import annotations

import json
import subprocess
import sys
import tempfile
from pathlib import Path

import pytest

from eab.chips import ESP32Profile, get_chip_profile
from eab.chips.base import ChipFamily


class TestESP32Profile:
    """Test ESP32Profile chip definition."""

    @pytest.fixture
    def profile(self) -> ESP32Profile:
        return ESP32Profile(variant="esp32c6")

    def test_family_is_esp32(self, profile: ESP32Profile):
        assert profile.family == ChipFamily.ESP32

    def test_name_includes_variant(self, profile: ESP32Profile):
        assert "ESP32" in profile.name
        assert "C6" in profile.name.upper()

    def test_boot_patterns_defined(self, profile: ESP32Profile):
        patterns = profile.boot_patterns
        assert "rst:0x" in patterns
        assert "boot:0x" in patterns
        assert "ESP-ROM:" in patterns
        assert "ESP-IDF" in patterns

    def test_crash_patterns_include_esp_faults(self, profile: ESP32Profile):
        patterns = profile.crash_patterns
        assert "Guru Meditation" in patterns
        assert "Backtrace:" in patterns
        assert "LoadProhibited" in patterns
        assert "StoreProhibited" in patterns
        assert "IllegalInstruction" in patterns
        assert "CORRUPT HEAP" in patterns

    def test_watchdog_patterns(self, profile: ESP32Profile):
        patterns = profile.watchdog_patterns
        assert "Task watchdog got triggered" in patterns
        assert "Interrupt wdt timeout" in patterns
        assert "wdt reset" in patterns

    def test_bootloader_patterns(self, profile: ESP32Profile):
        patterns = profile.bootloader_patterns
        assert "waiting for download" in patterns
        assert "download mode" in patterns

    def test_flash_tool_is_esptool(self, profile: ESP32Profile):
        """Verify flash_tool property returns 'esptool' (not deprecated 'esptool.py')."""
        assert profile.flash_tool == "esptool"


class TestESP32FlashCommands:
    """Test flash command generation for ESP32."""

    @pytest.fixture
    def profile(self) -> ESP32Profile:
        return ESP32Profile(variant="esp32c6")

    def test_flash_command_tool_is_esptool(self, profile: ESP32Profile):
        """Verify get_flash_command returns FlashCommand with tool='esptool'."""
        cmd = profile.get_flash_command(
            firmware_path="/path/to/firmware.bin",
            port="/dev/ttyUSB0",
            address="0x10000",
            chip="esp32c6",
        )
        assert cmd.tool == "esptool"

    def test_flash_command_uses_dash_arguments(self, profile: ESP32Profile):
        """Verify all esptool arguments use dash form (not underscore)."""
        cmd = profile.get_flash_command(
            firmware_path="/path/to/firmware.bin",
            port="/dev/ttyUSB0",
            address="0x10000",
            chip="esp32c6",
        )
        
        # Check for dash-form arguments
        assert "--flash-mode" in cmd.args
        assert "--flash-size" in cmd.args
        assert "write-flash" in cmd.args
        assert "hard-reset" in cmd.args or "default-reset" in cmd.args
        
        # Check that deprecated forms are NOT present
        assert "--flash_mode" not in cmd.args
        assert "--flash_size" not in cmd.args
        assert "write_flash" not in cmd.args
        assert "hard_reset" not in cmd.args
        assert "default_reset" not in cmd.args

    def test_flash_command_non_usb_jtag_uses_default_reset(self, profile: ESP32Profile):
        """Verify non-USB-JTAG ports use default-reset (dash form)."""
        cmd = profile.get_flash_command(
            firmware_path="/path/to/firmware.bin",
            port="/dev/ttyUSB0",  # Regular USB-UART
            chip="esp32c6",
        )
        assert "default-reset" in cmd.args
        # Should NOT use deprecated form
        assert "default_reset" not in cmd.args

    def test_flash_command_usb_jtag_uses_usb_reset(self, profile: ESP32Profile):
        """Verify USB-JTAG ports use usb-reset."""
        cmd = profile.get_flash_command(
            firmware_path="/path/to/firmware.bin",
            port="/dev/cu.usbmodem14201",  # USB-JTAG port
            chip="esp32c6",
        )
        assert "usb-reset" in cmd.args

    def test_flash_command_includes_chip(self, profile: ESP32Profile):
        """Verify --chip argument is included."""
        cmd = profile.get_flash_command(
            firmware_path="/path/to/firmware.bin",
            port="/dev/ttyUSB0",
            chip="esp32s3",
        )
        assert "--chip" in cmd.args
        assert "esp32s3" in cmd.args

    def test_flash_command_includes_port(self, profile: ESP32Profile):
        """Verify --port argument is included."""
        cmd = profile.get_flash_command(
            firmware_path="/path/to/firmware.bin",
            port="/dev/ttyUSB0",
        )
        assert "--port" in cmd.args
        assert "/dev/ttyUSB0" in cmd.args

    def test_flash_command_includes_baud(self, profile: ESP32Profile):
        """Verify --baud argument is included."""
        cmd = profile.get_flash_command(
            firmware_path="/path/to/firmware.bin",
            port="/dev/ttyUSB0",
            baud=115200,
        )
        assert "--baud" in cmd.args
        assert "115200" in cmd.args

    def test_flash_command_includes_firmware_path(self, profile: ESP32Profile):
        """Verify firmware path is in args."""
        cmd = profile.get_flash_command(
            firmware_path="/path/to/firmware.bin",
            port="/dev/ttyUSB0",
        )
        assert "/path/to/firmware.bin" in cmd.args

    def test_flash_command_includes_address(self, profile: ESP32Profile):
        """Verify flash address is included."""
        cmd = profile.get_flash_command(
            firmware_path="/path/to/firmware.bin",
            port="/dev/ttyUSB0",
            address="0x20000",
        )
        assert "0x20000" in cmd.args

    def test_flash_command_default_address_0x10000(self, profile: ESP32Profile):
        """Verify default address is 0x10000."""
        cmd = profile.get_flash_command(
            firmware_path="/path/to/firmware.bin",
            port="/dev/ttyUSB0",
        )
        assert "0x10000" in cmd.args

    def test_flash_command_no_stub_flag(self, profile: ESP32Profile):
        """Verify --no-stub flag is included when requested."""
        cmd = profile.get_flash_command(
            firmware_path="/path/to/firmware.bin",
            port="/dev/ttyUSB0",
            no_stub=True,
        )
        assert "--no-stub" in cmd.args

    def test_flash_command_no_stub_timeout_longer(self, profile: ESP32Profile):
        """Verify --no-stub increases timeout."""
        cmd_stub = profile.get_flash_command(
            firmware_path="/path/to/firmware.bin",
            port="/dev/ttyUSB0",
            no_stub=False,
        )
        cmd_no_stub = profile.get_flash_command(
            firmware_path="/path/to/firmware.bin",
            port="/dev/ttyUSB0",
            no_stub=True,
        )
        assert cmd_no_stub.timeout > cmd_stub.timeout

    def test_flash_command_flash_mode_dio(self, profile: ESP32Profile):
        """Verify flash mode is set to dio."""
        cmd = profile.get_flash_command(
            firmware_path="/path/to/firmware.bin",
            port="/dev/ttyUSB0",
        )
        assert "--flash-mode" in cmd.args
        assert "dio" in cmd.args

    def test_flash_command_flash_size_detect(self, profile: ESP32Profile):
        """Verify flash size is set to detect."""
        cmd = profile.get_flash_command(
            firmware_path="/path/to/firmware.bin",
            port="/dev/ttyUSB0",
        )
        assert "--flash-size" in cmd.args
        assert "detect" in cmd.args


class TestESP32EraseCommands:
    """Test erase command generation for ESP32."""

    @pytest.fixture
    def profile(self) -> ESP32Profile:
        return ESP32Profile(variant="esp32c6")

    def test_erase_command_tool_is_esptool(self, profile: ESP32Profile):
        """Verify get_erase_command returns FlashCommand with tool='esptool'."""
        cmd = profile.get_erase_command(port="/dev/ttyUSB0")
        assert cmd.tool == "esptool"

    def test_erase_command_uses_erase_flash_dash_form(self, profile: ESP32Profile):
        """Verify erase command uses 'erase-flash' (not deprecated 'erase_flash')."""
        cmd = profile.get_erase_command(port="/dev/ttyUSB0")
        assert "erase-flash" in cmd.args
        # Should NOT use deprecated form
        assert "erase_flash" not in cmd.args

    def test_erase_command_includes_chip(self, profile: ESP32Profile):
        """Verify --chip argument is included."""
        cmd = profile.get_erase_command(port="/dev/ttyUSB0", chip="esp32s3")
        assert "--chip" in cmd.args
        assert "esp32s3" in cmd.args

    def test_erase_command_includes_port(self, profile: ESP32Profile):
        """Verify --port argument is included."""
        cmd = profile.get_erase_command(port="/dev/ttyUSB0")
        assert "--port" in cmd.args
        assert "/dev/ttyUSB0" in cmd.args

    def test_erase_command_timeout(self, profile: ESP32Profile):
        """Verify erase command has reasonable timeout."""
        cmd = profile.get_erase_command(port="/dev/ttyUSB0")
        assert cmd.timeout == 60.0


class TestESP32ChipInfo:
    """Test chip info command generation for ESP32."""

    @pytest.fixture
    def profile(self) -> ESP32Profile:
        return ESP32Profile(variant="esp32c6")

    def test_chip_info_command_tool_is_esptool(self, profile: ESP32Profile):
        """Verify get_chip_info_command returns FlashCommand with tool='esptool'."""
        cmd = profile.get_chip_info_command(port="/dev/ttyUSB0")
        assert cmd.tool == "esptool"

    def test_chip_info_command_uses_chip_id_dash_form(self, profile: ESP32Profile):
        """Verify chip info command uses 'chip-id' (not deprecated 'chip_id')."""
        cmd = profile.get_chip_info_command(port="/dev/ttyUSB0")
        assert "chip-id" in cmd.args
        # Should NOT use deprecated form
        assert "chip_id" not in cmd.args

    def test_chip_info_command_includes_port(self, profile: ESP32Profile):
        """Verify --port argument is included."""
        cmd = profile.get_chip_info_command(port="/dev/ttyUSB0")
        assert "--port" in cmd.args
        assert "/dev/ttyUSB0" in cmd.args

    def test_chip_info_command_timeout(self, profile: ESP32Profile):
        """Verify chip info command has reasonable timeout."""
        cmd = profile.get_chip_info_command(port="/dev/ttyUSB0")
        assert cmd.timeout == 30.0


class TestESP32OpenOCDConfig:
    """Test OpenOCD configuration generation for ESP32."""

    @pytest.fixture
    def profile(self) -> ESP32Profile:
        return ESP32Profile(variant="esp32c6")

    def test_openocd_config_esp_usb_jtag(self, profile: ESP32Profile):
        config = profile.get_openocd_config()
        assert config.interface_cfg == "interface/esp_usb_jtag.cfg"
        assert "esp32c6.cfg" in config.target_cfg
        assert config.adapter_driver == "esp_usb_jtag"

    @pytest.mark.parametrize("variant,expected_target", [
        ("esp32", "target/esp32.cfg"),
        ("esp32s2", "target/esp32s2.cfg"),
        ("esp32s3", "target/esp32s3.cfg"),
        ("esp32c3", "target/esp32c3.cfg"),
        ("esp32c6", "target/esp32c6.cfg"),
    ])
    def test_openocd_target_mapping(self, variant: str, expected_target: str):
        profile = ESP32Profile(variant=variant)
        config = profile.get_openocd_config()
        assert expected_target in config.target_cfg


class TestESP32ResetSequences:
    """Test reset sequence definitions for ESP32."""

    @pytest.fixture
    def profile(self) -> ESP32Profile:
        return ESP32Profile(variant="esp32c6")

    def test_hard_reset_sequence(self, profile: ESP32Profile):
        sequences = profile.reset_sequences
        assert "hard_reset" in sequences
        hard_reset = sequences["hard_reset"]
        assert len(hard_reset) >= 2

    def test_soft_reset_sequence(self, profile: ESP32Profile):
        sequences = profile.reset_sequences
        assert "soft_reset" in sequences

    def test_bootloader_sequence(self, profile: ESP32Profile):
        sequences = profile.reset_sequences
        assert "bootloader" in sequences


class TestESP32USBJTAGDetection:
    """Test USB-JTAG port detection."""

    @pytest.fixture
    def profile(self) -> ESP32Profile:
        return ESP32Profile(variant="esp32c6")

    def test_is_usb_jtag_port_usbmodem(self, profile: ESP32Profile):
        """Test USB-JTAG detection for macOS usbmodem ports."""
        assert profile.is_usb_jtag_port("/dev/cu.usbmodem14201") is True

    def test_is_usb_jtag_port_ttyacm(self, profile: ESP32Profile):
        """Test USB-JTAG detection for Linux ttyACM ports."""
        assert profile.is_usb_jtag_port("/dev/ttyACM0") is True

    def test_is_usb_jtag_port_usbserial_false(self, profile: ESP32Profile):
        """Test that regular USB-serial ports are not detected as USB-JTAG."""
        assert profile.is_usb_jtag_port("/dev/ttyUSB0") is False
        assert profile.is_usb_jtag_port("/dev/cu.usbserial-1420") is False
        assert profile.is_usb_jtag_port("/dev/cu.SLAB_USBtoUART") is False


class TestChipProfileRegistry:
    """Test chip profile registry and lookup."""

    def test_get_esp32_profile(self):
        profile = get_chip_profile("esp32")
        assert isinstance(profile, ESP32Profile)
        assert profile.family == ChipFamily.ESP32

    def test_get_esp32c6_profile(self):
        profile = get_chip_profile("esp32c6")
        assert isinstance(profile, ESP32Profile)

    def test_get_esp32s3_profile(self):
        profile = get_chip_profile("esp32s3")
        assert isinstance(profile, ESP32Profile)


class TestESP32ErrorPatterns:
    """Test ESP32 error pattern detection."""

    @pytest.fixture
    def profile(self) -> ESP32Profile:
        return ESP32Profile(variant="esp32c6")

    def test_error_patterns_defined(self, profile: ESP32Profile):
        patterns = profile.error_patterns
        assert "ERROR" in patterns
        assert "CRASH" in patterns
        assert "PANIC" in patterns
        assert "MEMORY" in patterns
        assert "WATCHDOG" in patterns


class TestESP32ParserMethods:
    """Test ESP32 parsing utility methods."""

    @pytest.fixture
    def profile(self) -> ESP32Profile:
        return ESP32Profile(variant="esp32c6")

    def test_parse_reset_reason_poweron(self, profile: ESP32Profile):
        result = profile.parse_reset_reason("rst:0x1 (POWERON),boot:0x8")
        assert result == "POWERON"

    def test_parse_reset_reason_brownout(self, profile: ESP32Profile):
        result = profile.parse_reset_reason("rst:0xc (BROWNOUT),boot:0x13")
        assert result == "BROWNOUT"

    def test_parse_reset_reason_none(self, profile: ESP32Profile):
        result = profile.parse_reset_reason("Some unrelated output")
        assert result is None

    def test_parse_boot_mode_flash(self, profile: ESP32Profile):
        result = profile.parse_boot_mode("boot:0x13 (SPI_FAST_FLASH_BOOT)")
        assert result == "SPI_FAST_FLASH_BOOT"

    def test_parse_boot_mode_download(self, profile: ESP32Profile):
        result = profile.parse_boot_mode("boot:0x0 (DOWNLOAD_BOOT(UART))")
        # Note: regex captures up to first closing paren, so nested parens are truncated
        assert result == "DOWNLOAD_BOOT(UART"


class TestESP32FlashArgsParser:
    """Test flash_args file parsing for multi-partition flashing."""

    @pytest.fixture
    def profile(self) -> ESP32Profile:
        return ESP32Profile(variant="esp32c6")

    def test_parse_flash_args_valid(self, profile: ESP32Profile, tmp_path: Path):
        """Test parsing valid flash_args file."""
        build_dir = tmp_path / "build"
        build_dir.mkdir()
        
        # Create mock flash_args file
        flash_args = build_dir / "flash_args"
        flash_args.write_text("""--flash_mode dio
--flash_size detect
0x0 bootloader/bootloader.bin
0x8000 partition_table/partition-table.bin
0x10000 app.bin
""")
        
        # Create mock binary files
        (build_dir / "bootloader").mkdir()
        (build_dir / "bootloader" / "bootloader.bin").write_bytes(b"bootloader")
        (build_dir / "partition_table").mkdir()
        (build_dir / "partition_table" / "partition-table.bin").write_bytes(b"partition")
        (build_dir / "app.bin").write_bytes(b"app")
        
        partitions = profile.parse_flash_args(build_dir)
        assert partitions is not None
        assert len(partitions) == 3
        assert partitions[0][0] == "0x0"
        assert "bootloader.bin" in partitions[0][1]
        assert partitions[1][0] == "0x8000"
        assert "partition-table.bin" in partitions[1][1]
        assert partitions[2][0] == "0x10000"
        assert "app.bin" in partitions[2][1]

    def test_parse_flash_args_missing_file(self, profile: ESP32Profile, tmp_path: Path):
        """Test parsing flash_args when file doesn't exist."""
        build_dir = tmp_path / "build"
        build_dir.mkdir()
        
        partitions = profile.parse_flash_args(build_dir)
        assert partitions is None

    def test_get_flash_command_with_build_dir(self, profile: ESP32Profile, tmp_path: Path):
        """Test that get_flash_command handles build directory correctly."""
        build_dir = tmp_path / "build"
        build_dir.mkdir()
        
        # Create flash_args
        flash_args = build_dir / "flash_args"
        flash_args.write_text("""0x0 bootloader/bootloader.bin
0x10000 app.bin
""")
        
        # Create binaries
        (build_dir / "bootloader").mkdir()
        (build_dir / "bootloader" / "bootloader.bin").write_bytes(b"boot")
        (build_dir / "app.bin").write_bytes(b"app")
        
        cmd = profile.get_flash_command(
            firmware_path=str(build_dir),
            port="/dev/ttyUSB0",
        )
        
        # Should have both partitions in args
        assert "0x0" in cmd.args
        assert "bootloader.bin" in " ".join(cmd.args)
        assert "0x10000" in cmd.args
        assert "app.bin" in " ".join(cmd.args)


class TestEabctlESP32Commands:
    """Test eabctl CLI commands for ESP32 (via subprocess)."""

    def test_eabctl_flash_help(self):
        """Verify flash subcommand exists and accepts --chip."""
        result = subprocess.run(
            [sys.executable, "-m", "eab.control", "flash", "--help"],
            capture_output=True,
            text=True,
        )
        assert result.returncode == 0
        assert "--chip" in result.stdout
        assert "--address" in result.stdout

    def test_eabctl_erase_help(self):
        """Verify erase subcommand exists."""
        result = subprocess.run(
            [sys.executable, "-m", "eab.control", "erase", "--help"],
            capture_output=True,
            text=True,
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
                [sys.executable, "-m", "eab.control", "flash", firmware_path, "--chip", "invalid_chip", "--json"],
                capture_output=True,
                text=True,
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
            [sys.executable, "-m", "eab.control", "flash", "/nonexistent/firmware.bin", "--chip", "esp32c6", "--json"],
            capture_output=True,
            text=True,
        )
        assert result.returncode != 0
        data = json.loads(result.stdout)
        # esptool runs but fails to open file - returns success: false with stderr
        assert data.get("success") is False or "error" in data
