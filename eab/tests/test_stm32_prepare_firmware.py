"""Unit tests for STM32Profile.prepare_firmware() ELF-to-binary conversion."""
from __future__ import annotations

import subprocess
import tempfile
from pathlib import Path
from unittest.mock import MagicMock, patch

import pytest

from eab.chips.stm32 import STM32Profile


class TestPrepareFirmware:
    """Test ELF detection, passthrough, and objcopy error handling."""

    @pytest.fixture
    def profile(self) -> STM32Profile:
        return STM32Profile(variant="stm32l4")

    # -- Non-ELF passthrough ------------------------------------------------

    def test_non_elf_file_passes_through(self, profile: STM32Profile, tmp_path: Path):
        """A plain binary (non-ELF) should be returned unchanged."""
        fw = tmp_path / "firmware.bin"
        fw.write_bytes(b"\x00\x01\x02\x03" * 10)

        result_path, converted = profile.prepare_firmware(str(fw))
        assert result_path == str(fw)
        assert converted is False

    def test_short_file_passes_through(self, profile: STM32Profile, tmp_path: Path):
        """Files shorter than 4 bytes cannot be ELF — passthrough."""
        fw = tmp_path / "tiny.bin"
        fw.write_bytes(b"\x7f")

        result_path, converted = profile.prepare_firmware(str(fw))
        assert result_path == str(fw)
        assert converted is False

    # -- ELF detection and conversion ---------------------------------------

    def test_elf_file_detected_and_converted(self, profile: STM32Profile, tmp_path: Path):
        """An ELF file should trigger objcopy conversion."""
        fw = tmp_path / "firmware.elf"
        fw.write_bytes(b"\x7fELF" + b"\x00" * 100)

        mock_result = MagicMock()
        mock_result.returncode = 0
        mock_result.stderr = ""

        with patch("eab.chips.stm32.subprocess.run", return_value=mock_result) as mock_run:
            result_path, converted = profile.prepare_firmware(str(fw))

        assert converted is True
        assert result_path != str(fw)
        assert result_path.endswith(".bin")

        # Verify objcopy was called with correct args
        mock_run.assert_called_once()
        call_args = mock_run.call_args
        cmd_list = call_args[0][0]
        assert cmd_list[0] == "arm-none-eabi-objcopy"
        assert "-O" in cmd_list
        assert "binary" in cmd_list
        assert str(fw) in cmd_list

    # -- objcopy not found --------------------------------------------------

    def test_objcopy_not_found_raises_file_not_found(self, profile: STM32Profile, tmp_path: Path):
        """Missing objcopy should raise FileNotFoundError."""
        fw = tmp_path / "firmware.elf"
        fw.write_bytes(b"\x7fELF" + b"\x00" * 100)

        with patch("eab.chips.stm32.subprocess.run", side_effect=FileNotFoundError):
            with pytest.raises(FileNotFoundError, match="arm-none-eabi-objcopy not found"):
                profile.prepare_firmware(str(fw))

    # -- objcopy failure (non-zero exit) ------------------------------------

    def test_objcopy_failure_raises_runtime_error(self, profile: STM32Profile, tmp_path: Path):
        """Non-zero objcopy exit should raise RuntimeError."""
        fw = tmp_path / "firmware.elf"
        fw.write_bytes(b"\x7fELF" + b"\x00" * 100)

        mock_result = MagicMock()
        mock_result.returncode = 1
        mock_result.stderr = "objcopy: bad format"

        with patch("eab.chips.stm32.subprocess.run", return_value=mock_result):
            with pytest.raises(RuntimeError, match="Failed to convert ELF to binary"):
                profile.prepare_firmware(str(fw))

    # -- objcopy timeout ----------------------------------------------------

    def test_objcopy_timeout_raises_runtime_error(self, profile: STM32Profile, tmp_path: Path):
        """Objcopy timeout should raise RuntimeError."""
        fw = tmp_path / "firmware.elf"
        fw.write_bytes(b"\x7fELF" + b"\x00" * 100)

        with patch("eab.chips.stm32.subprocess.run", side_effect=subprocess.TimeoutExpired(cmd="objcopy", timeout=30)):
            with pytest.raises(RuntimeError, match="timed out"):
                profile.prepare_firmware(str(fw))

    # -- Missing firmware file ----------------------------------------------

    def test_missing_firmware_raises_file_not_found(self, profile: STM32Profile):
        """Non-existent firmware path should raise FileNotFoundError."""
        with pytest.raises(FileNotFoundError, match="Firmware file not found"):
            profile.prepare_firmware("/nonexistent/path/firmware.elf")
