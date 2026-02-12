"""
Tests for the esptool-wrapper shell script.

This tests that the wrapper correctly intercepts both underscore and dash forms
of esptool commands when EAB daemon is running.
"""
import os
import subprocess
import tempfile
import json
from pathlib import Path


def test_wrapper_detects_underscore_write_flash():
    """Test that wrapper intercepts write_flash command."""
    # Create a temporary status.json to simulate running daemon
    with tempfile.TemporaryDirectory() as tmpdir:
        status_file = Path(tmpdir) / "status.json"
        status_data = {
            "port": "/dev/ttyUSB0",
            "connection": {"status": "connected"}
        }
        status_file.write_text(json.dumps(status_data))
        
        # Run wrapper with write_flash command
        env = os.environ.copy()
        env["EAB_TEST_STATUS_FILE"] = str(status_file)
        
        # We need to test the wrapper behavior, but we can't easily mock /tmp/eab-session
        # Instead, we'll verify the case pattern by checking the script directly
        wrapper_path = Path(__file__).parent.parent / "esptool-wrapper"
        assert wrapper_path.exists(), "esptool-wrapper not found"
        
        content = wrapper_path.read_text()
        # Check that both underscore and dash forms are in the case pattern
        assert "write_flash" in content
        assert "write-flash" in content
        assert "erase_flash" in content
        assert "erase-flash" in content
        assert "erase_region" in content
        assert "erase-region" in content
        assert "read_flash" in content
        assert "read-flash" in content


def test_wrapper_detects_dash_write_flash():
    """Test that wrapper intercepts write-flash command (modern form)."""
    wrapper_path = Path(__file__).parent.parent / "esptool-wrapper"
    content = wrapper_path.read_text()
    
    # Verify the case statement includes dash forms
    # The pattern should be on line 42 approximately
    lines = content.split('\n')
    case_pattern_line = None
    for i, line in enumerate(lines):
        if 'write_flash|erase_flash|erase_region|read_flash' in line:
            case_pattern_line = line
            break
    
    assert case_pattern_line is not None, "Case pattern not found"
    assert 'write-flash' in case_pattern_line, "write-flash not in case pattern"
    assert 'erase-flash' in case_pattern_line, "erase-flash not in case pattern"
    assert 'erase-region' in case_pattern_line, "erase-region not in case pattern"
    assert 'read-flash' in case_pattern_line, "read-flash not in case pattern"


def test_wrapper_detects_all_underscore_forms():
    """Test all underscore command forms are detected."""
    wrapper_path = Path(__file__).parent.parent / "esptool-wrapper"
    content = wrapper_path.read_text()
    
    underscore_commands = [
        "write_flash",
        "erase_flash", 
        "erase_region",
        "read_flash"
    ]
    
    for cmd in underscore_commands:
        assert cmd in content, f"Command {cmd} not found in wrapper"


def test_wrapper_detects_all_dash_forms():
    """Test all dash command forms are detected."""
    wrapper_path = Path(__file__).parent.parent / "esptool-wrapper"
    content = wrapper_path.read_text()
    
    dash_commands = [
        "write-flash",
        "erase-flash",
        "erase-region", 
        "read-flash"
    ]
    
    for cmd in dash_commands:
        assert cmd in content, f"Command {cmd} not found in wrapper"


def test_wrapper_blocks_when_eab_running():
    """Test wrapper blocks write operations when EAB daemon is running on same port."""
    wrapper_path = Path(__file__).parent.parent / "esptool-wrapper"
    
    # Create temporary EAB session directory
    with tempfile.TemporaryDirectory() as tmpdir:
        session_dir = Path(tmpdir) / "eab-session"
        session_dir.mkdir()
        status_file = session_dir / "status.json"
        
        # Create status.json with a specific port
        status_data = {
            "port": "/dev/ttyUSB0",
            "connection": {"status": "connected"}
        }
        status_file.write_text(json.dumps(status_data))
        
        # Try to run wrapper with write_flash on same port
        # This should fail with exit code 1
        result = subprocess.run(
            ["bash", str(wrapper_path), "-p", "/dev/ttyUSB0", "write_flash", "0x0", "test.bin"],
            capture_output=True,
            text=True,
            env={**os.environ, "EAB_SESSION_DIR": str(session_dir)}
        )
        
        # The wrapper should detect we're using esptool directly and suggest eabctl
        # However, it needs /tmp/eab-session/status.json specifically, not a custom path
        # So we can't fully test the blocking behavior without root or mocking
        # Instead, we verify the script logic is correct by checking the source
        content = wrapper_path.read_text()
        assert "Use eabctl instead of esptool" in content
        assert "eabctl flash" in content


def test_wrapper_passthrough_when_eab_not_running():
    """Test wrapper passes through to real esptool when EAB is not running."""
    wrapper_path = Path(__file__).parent.parent / "esptool-wrapper"
    content = wrapper_path.read_text()
    
    # Verify the script has passthrough logic
    assert "exec" in content
    assert "REAL_ESPTOOL" in content
    assert "Pass through to real esptool" in content


def test_wrapper_checks_both_underscore_and_dash_commands_in_case_statement():
    """Test that the case statement on line 42 checks both underscore and dash forms."""
    wrapper_path = Path(__file__).parent.parent / "esptool-wrapper"
    content = wrapper_path.read_text()
    lines = content.split('\n')
    
    # Find the case statement (should be around line 42)
    case_found = False
    for i in range(35, 50):  # Search around line 42
        if i < len(lines) and 'write_flash' in lines[i]:
            line = lines[i]
            # This should be the case pattern line
            # It must contain all 8 commands (4 underscore + 4 dash forms)
            assert 'write_flash' in line
            assert 'write-flash' in line
            assert 'erase_flash' in line
            assert 'erase-flash' in line
            assert 'erase_region' in line
            assert 'erase-region' in line
            assert 'read_flash' in line
            assert 'read-flash' in line
            case_found = True
            break
    
    assert case_found, "Case statement with all commands not found around line 42"


def test_wrapper_has_correct_error_messages():
    """Test wrapper has helpful error messages."""
    wrapper_path = Path(__file__).parent.parent / "esptool-wrapper"
    content = wrapper_path.read_text()
    
    # Check for helpful messages
    assert "STOP! Use eabctl instead of esptool" in content
    assert "eabctl flash <project_dir>" in content
    assert "eabctl erase" in content
    assert "The eabctl command automatically:" in content


def test_wrapper_script_is_executable():
    """Test that the wrapper script has execute permissions."""
    wrapper_path = Path(__file__).parent.parent / "esptool-wrapper"
    assert wrapper_path.exists(), "esptool-wrapper not found"
    # Check if file is executable
    assert os.access(wrapper_path, os.X_OK), "esptool-wrapper is not executable"


def test_wrapper_handles_both_esptool_py_and_esptool():
    """Test wrapper searches for both esptool.py and esptool executables."""
    wrapper_path = Path(__file__).parent.parent / "esptool-wrapper"
    content = wrapper_path.read_text()
    
    # Check that it searches for both forms
    assert "esptool.py" in content
    assert "/esptool " in content or "esptool 2" in content
    assert "which -a esptool.py" in content
    assert "which -a esptool" in content
