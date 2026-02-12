"""
Tests for device_control.py module.

Tests that esptool commands use non-deprecated argument forms:
- esptool (not esptool.py)
- write-flash (not write_flash)
- chip-id (not chip_id)
- erase-flash (not erase_flash)
"""

from unittest.mock import Mock, patch
import subprocess
from eab.device_control import DeviceController, RESET_SEQUENCES, strip_ansi


def test_strip_ansi():
    """Test ANSI escape code removal."""
    assert strip_ansi("hello") == "hello"
    assert strip_ansi("\x1b[31mred\x1b[0m") == "red"
    assert strip_ansi("\x1b[1;32mgreen\x1b[0m text") == "green text"
    assert strip_ansi("no\x1b[Aescapes\x1b[Bhere") == "noescapeshere"


def test_reset_sequences_unchanged():
    """Test that internal reset sequence names still use underscores."""
    # These are internal dict keys, NOT esptool CLI args
    assert "hard_reset" in RESET_SEQUENCES
    assert "soft_reset" in RESET_SEQUENCES
    assert "bootloader" in RESET_SEQUENCES
    
    # Verify they are NOT using hyphens
    assert "hard-reset" not in RESET_SEQUENCES
    assert "soft-reset" not in RESET_SEQUENCES


def test_flash_uses_non_deprecated_esptool_command():
    """Test that flash() uses 'esptool' and 'write-flash', not deprecated forms."""
    # Mock serial port
    mock_serial = Mock()
    mock_serial.is_open.return_value = False
    mock_serial._serial = Mock()
    
    controller = DeviceController(
        serial_port=mock_serial,
        port_name="/dev/ttyUSB0",
        baud=115200
    )
    
    with patch('subprocess.run') as mock_run:
        mock_run.return_value = Mock(returncode=0, stdout="", stderr="")
        
        result = controller.flash("/path/to/firmware.bin", "0x10000")
        
        # Verify subprocess.run was called with correct command
        assert mock_run.called
        cmd = mock_run.call_args[0][0]
        
        # Check that we're using non-deprecated forms
        assert "esptool" in cmd
        assert "esptool.py" not in cmd
        assert "write-flash" in cmd
        assert "write_flash" not in cmd
        
        # Verify full command structure
        assert cmd[0] == "esptool"
        assert "--port" in cmd
        assert "/dev/ttyUSB0" in cmd
        assert "--baud" in cmd
        assert "460800" in cmd
        assert "write-flash" in cmd
        assert "0x10000" in cmd
        assert "/path/to/firmware.bin" in cmd
        
        assert result == "OK: Flash complete"


def test_flash_file_not_found_error_message():
    """Test that FileNotFoundError uses updated error message."""
    mock_serial = Mock()
    mock_serial.is_open.return_value = False
    
    controller = DeviceController(
        serial_port=mock_serial,
        port_name="/dev/ttyUSB0"
    )
    
    with patch('subprocess.run', side_effect=FileNotFoundError("esptool not found")):
        result = controller.flash("/path/to/firmware.bin")
        
        # Check error message uses "esptool" not "esptool.py"
        assert "esptool not found" in result
        assert "esptool.py" not in result
        assert "pip install esptool" in result


def test_get_chip_info_uses_non_deprecated_command():
    """Test that get_chip_info() uses 'esptool' and 'chip-id', not deprecated forms."""
    mock_serial = Mock()
    mock_serial.is_open.return_value = False
    
    controller = DeviceController(
        serial_port=mock_serial,
        port_name="/dev/ttyUSB0"
    )
    
    with patch('subprocess.run') as mock_run:
        mock_run.return_value = Mock(
            returncode=0,
            stdout="Chip is ESP32-C6",
            stderr=""
        )
        
        result = controller.get_chip_info()
        
        # Verify subprocess.run was called with correct command
        assert mock_run.called
        cmd = mock_run.call_args[0][0]
        
        # Check that we're using non-deprecated forms
        assert "esptool" in cmd
        assert "esptool.py" not in cmd
        assert "chip-id" in cmd
        assert "chip_id" not in cmd
        
        # Verify full command structure
        assert cmd[0] == "esptool"
        assert "--port" in cmd
        assert "/dev/ttyUSB0" in cmd
        assert "chip-id" in cmd
        
        assert "OK:" in result
        assert "ESP32-C6" in result


def test_erase_flash_uses_non_deprecated_command():
    """Test that erase_flash() uses 'esptool' and 'erase-flash', not deprecated forms."""
    mock_serial = Mock()
    mock_serial.is_open.return_value = False
    
    controller = DeviceController(
        serial_port=mock_serial,
        port_name="/dev/ttyUSB0"
    )
    
    with patch('subprocess.run') as mock_run:
        mock_run.return_value = Mock(returncode=0, stdout="", stderr="")
        
        result = controller.erase_flash()
        
        # Verify subprocess.run was called with correct command
        assert mock_run.called
        cmd = mock_run.call_args[0][0]
        
        # Check that we're using non-deprecated forms
        assert "esptool" in cmd
        assert "esptool.py" not in cmd
        assert "erase-flash" in cmd
        assert "erase_flash" not in cmd
        
        # Verify full command structure
        assert cmd[0] == "esptool"
        assert "--port" in cmd
        assert "/dev/ttyUSB0" in cmd
        assert "erase-flash" in cmd
        
        assert result == "OK: Flash erased"


def test_reset_hard():
    """Test hard reset sequence."""
    mock_serial = Mock()
    mock_serial._serial = Mock()
    
    controller = DeviceController(
        serial_port=mock_serial,
        port_name="/dev/ttyUSB0"
    )
    
    result = controller.reset("hard_reset")
    
    # Verify DTR/RTS were set
    assert mock_serial._serial.setDTR.called
    assert mock_serial._serial.setRTS.called
    assert result == "OK: Device reset"


def test_reset_soft():
    """Test soft reset sequence."""
    mock_serial = Mock()
    mock_serial._serial = Mock()
    
    controller = DeviceController(
        serial_port=mock_serial,
        port_name="/dev/ttyUSB0"
    )
    
    result = controller.reset("soft_reset")
    
    # Verify RTS was toggled
    assert mock_serial._serial.setRTS.called
    assert result == "OK: Device reset"


def test_reset_bootloader():
    """Test bootloader entry sequence."""
    mock_serial = Mock()
    mock_serial._serial = Mock()
    
    controller = DeviceController(
        serial_port=mock_serial,
        port_name="/dev/ttyUSB0"
    )
    
    result = controller.enter_bootloader()
    
    # Verify DTR/RTS were set
    assert mock_serial._serial.setDTR.called
    assert mock_serial._serial.setRTS.called
    assert result == "OK: Device reset"


def test_handle_command_reset():
    """Test !RESET command handling."""
    mock_serial = Mock()
    mock_serial._serial = Mock()
    
    controller = DeviceController(
        serial_port=mock_serial,
        port_name="/dev/ttyUSB0"
    )
    
    result = controller.handle_command("!RESET")
    assert "OK: Device reset" in result
    
    result = controller.handle_command("!RESET:soft_reset")
    assert "OK: Device reset" in result


def test_handle_command_flash():
    """Test !FLASH command handling."""
    mock_serial = Mock()
    mock_serial.is_open.return_value = False
    
    controller = DeviceController(
        serial_port=mock_serial,
        port_name="/dev/ttyUSB0"
    )
    
    with patch('subprocess.run') as mock_run:
        mock_run.return_value = Mock(returncode=0, stdout="", stderr="")
        
        result = controller.handle_command("!FLASH:/path/to/fw.bin")
        assert "OK: Flash complete" in result


def test_handle_command_erase():
    """Test !ERASE command handling."""
    mock_serial = Mock()
    mock_serial.is_open.return_value = False
    
    controller = DeviceController(
        serial_port=mock_serial,
        port_name="/dev/ttyUSB0"
    )
    
    with patch('subprocess.run') as mock_run:
        mock_run.return_value = Mock(returncode=0, stdout="", stderr="")
        
        result = controller.handle_command("!ERASE")
        assert "OK: Flash erased" in result


def test_handle_command_chip_info():
    """Test !CHIP_INFO command handling."""
    mock_serial = Mock()
    mock_serial.is_open.return_value = False
    
    controller = DeviceController(
        serial_port=mock_serial,
        port_name="/dev/ttyUSB0"
    )
    
    with patch('subprocess.run') as mock_run:
        mock_run.return_value = Mock(
            returncode=0,
            stdout="ESP32-C6",
            stderr=""
        )
        
        result = controller.handle_command("!CHIP_INFO")
        assert "OK:" in result


def test_is_special_command():
    """Test special command detection."""
    mock_serial = Mock()
    
    controller = DeviceController(
        serial_port=mock_serial,
        port_name="/dev/ttyUSB0"
    )
    
    assert controller.is_special_command("!RESET")
    assert controller.is_special_command("!FLASH:/path")
    assert not controller.is_special_command("normal command")
    assert not controller.is_special_command("")


def test_flash_callbacks():
    """Test that flash start/end callbacks are invoked."""
    mock_serial = Mock()
    mock_serial.is_open.return_value = False
    
    on_flash_start = Mock()
    on_flash_end = Mock()
    
    controller = DeviceController(
        serial_port=mock_serial,
        port_name="/dev/ttyUSB0",
        on_flash_start=on_flash_start,
        on_flash_end=on_flash_end
    )
    
    with patch('subprocess.run') as mock_run:
        mock_run.return_value = Mock(returncode=0, stdout="", stderr="")
        
        controller.flash("/path/to/fw.bin")
        
        assert on_flash_start.called
        assert on_flash_end.called
        # Check callback was called with success=True
        on_flash_end.assert_called_with(True)


def test_flash_failure_callback():
    """Test that flash end callback receives False on failure."""
    mock_serial = Mock()
    mock_serial.is_open.return_value = False
    
    on_flash_end = Mock()
    
    controller = DeviceController(
        serial_port=mock_serial,
        port_name="/dev/ttyUSB0",
        on_flash_end=on_flash_end
    )
    
    with patch('subprocess.run') as mock_run:
        mock_run.return_value = Mock(returncode=1, stdout="", stderr="Flash error")
        
        controller.flash("/path/to/fw.bin")
        
        # Check callback was called with success=False
        on_flash_end.assert_called_with(False)


def test_flash_timeout():
    """Test flash timeout handling."""
    mock_serial = Mock()
    mock_serial.is_open.return_value = False
    
    controller = DeviceController(
        serial_port=mock_serial,
        port_name="/dev/ttyUSB0"
    )
    
    with patch('subprocess.run', side_effect=subprocess.TimeoutExpired(cmd=[], timeout=120)):
        result = controller.flash("/path/to/fw.bin")
        
        assert "ERROR: Flash timeout" in result


def test_unknown_reset_sequence():
    """Test handling of unknown reset sequence name."""
    mock_serial = Mock()
    
    controller = DeviceController(
        serial_port=mock_serial,
        port_name="/dev/ttyUSB0"
    )
    
    result = controller.reset("unknown_sequence")
    assert "ERROR: Unknown reset sequence" in result


def test_unknown_special_command():
    """Test handling of unknown special command."""
    mock_serial = Mock()
    
    controller = DeviceController(
        serial_port=mock_serial,
        port_name="/dev/ttyUSB0"
    )
    
    result = controller.handle_command("!UNKNOWN")
    assert "ERROR: Unknown command" in result


def test_flash_missing_path():
    """Test !FLASH without path."""
    mock_serial = Mock()
    
    controller = DeviceController(
        serial_port=mock_serial,
        port_name="/dev/ttyUSB0"
    )
    
    result = controller.handle_command("!FLASH")
    assert "ERROR: !FLASH requires firmware path" in result
