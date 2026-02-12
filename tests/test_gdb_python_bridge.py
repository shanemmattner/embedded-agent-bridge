"""Tests for GDB Python script execution in gdb_bridge.

Tests run_gdb_python() function with mocked subprocess to verify:
- Successful execution with JSON result parsing
- Timeout handling
- Invalid script path handling
- JSON parsing edge cases
"""

from __future__ import annotations

import json
import subprocess
from pathlib import Path
from unittest.mock import MagicMock, Mock, patch

import pytest

from eab.gdb_bridge import run_gdb_python, GDBResult


class TestRunGdbPython:
    """Tests for run_gdb_python() function."""

    @patch("eab.gdb_bridge.subprocess.run")
    @patch("eab.gdb_bridge._default_gdb_for_chip")
    def test_successful_execution_with_json(self, mock_default_gdb, mock_run, tmp_path):
        """run_gdb_python() should execute script and parse JSON results."""
        # Setup
        script = tmp_path / "test_script.py"
        script.write_text("# test script")
        
        mock_default_gdb.return_value = "/usr/bin/arm-none-eabi-gdb"
        
        # Mock successful execution
        mock_proc = MagicMock()
        mock_proc.returncode = 0
        mock_proc.stdout = "GDB output"
        mock_proc.stderr = ""
        mock_run.return_value = mock_proc
        
        # Mock JSON result file creation
        result_data = {"status": "ok", "registers": {"r0": 42, "r1": 100}}
        
        def side_effect(argv, **kwargs):
            # Find the result file path from argv
            for i, arg in enumerate(argv):
                if arg.startswith("set $result_file"):
                    # Extract path from: set $result_file = "/tmp/xyz.json"
                    result_file = arg.split('"')[1]
                    # Write JSON to the temp file
                    with open(result_file, "w") as f:
                        json.dump(result_data, f)
                    break
            return mock_proc
        
        mock_run.side_effect = side_effect
        
        # Execute
        result = run_gdb_python(
            chip="nrf5340",
            script_path=str(script),
            target="localhost:2331",
            elf="/path/to/app.elf",
            timeout_s=30.0,
        )
        
        # Verify
        assert result.success is True
        assert result.returncode == 0
        assert result.stdout == "GDB output"
        assert result.stderr == ""
        assert result.gdb_path == "/usr/bin/arm-none-eabi-gdb"
        assert result.json_result == result_data
        
        # Verify subprocess.run was called with correct arguments
        mock_run.assert_called_once()
        call_args = mock_run.call_args
        argv = call_args[0][0]
        
        assert "/usr/bin/arm-none-eabi-gdb" in argv
        assert "-q" in argv
        assert "-batch" in argv
        assert "/path/to/app.elf" in argv
        assert "-ex" in argv
        assert "target remote localhost:2331" in argv
        assert "-x" in argv
        assert str(script) in argv
        assert "detach" in argv
        assert "quit" in argv
        
        # Verify convenience variable is set
        result_file_cmd = [arg for arg in argv if arg.startswith("set $result_file")]
        assert len(result_file_cmd) == 1
        assert ".json" in result_file_cmd[0]

    @patch("eab.gdb_bridge.subprocess.run")
    @patch("eab.gdb_bridge._default_gdb_for_chip")
    def test_execution_without_elf(self, mock_default_gdb, mock_run, tmp_path):
        """run_gdb_python() should work without ELF file."""
        script = tmp_path / "script.py"
        script.write_text("# script")
        
        mock_default_gdb.return_value = "gdb-multiarch"
        
        mock_proc = MagicMock()
        mock_proc.returncode = 0
        mock_proc.stdout = "output"
        mock_proc.stderr = ""
        mock_run.return_value = mock_proc
        
        result = run_gdb_python(
            chip="stm32f4",
            script_path=str(script),
        )
        
        assert result.success is True
        
        # Verify no ELF in argv
        call_args = mock_run.call_args
        argv = call_args[0][0]
        # Should not have any .elf files
        elf_args = [arg for arg in argv if ".elf" in arg.lower()]
        assert len(elf_args) == 0

    @patch("eab.gdb_bridge.subprocess.run")
    def test_explicit_gdb_path(self, mock_run, tmp_path):
        """run_gdb_python() should use explicit gdb_path when provided."""
        script = tmp_path / "script.py"
        script.write_text("# script")
        
        mock_proc = MagicMock()
        mock_proc.returncode = 0
        mock_proc.stdout = ""
        mock_proc.stderr = ""
        mock_run.return_value = mock_proc
        
        result = run_gdb_python(
            chip="esp32s3",
            script_path=str(script),
            gdb_path="/custom/path/to/gdb",
        )
        
        assert result.gdb_path == "/custom/path/to/gdb"
        
        call_args = mock_run.call_args
        argv = call_args[0][0]
        assert argv[0] == "/custom/path/to/gdb"

    @patch("eab.gdb_bridge.subprocess.run")
    @patch("eab.gdb_bridge._default_gdb_for_chip")
    def test_timeout_handling(self, mock_default_gdb, mock_run, tmp_path):
        """run_gdb_python() should propagate timeout exceptions."""
        script = tmp_path / "script.py"
        script.write_text("# script")
        
        mock_default_gdb.return_value = "gdb"
        mock_run.side_effect = subprocess.TimeoutExpired("gdb", 10.0)
        
        with pytest.raises(subprocess.TimeoutExpired):
            run_gdb_python(
                chip="nrf5340",
                script_path=str(script),
                timeout_s=10.0,
            )

    def test_invalid_script_path(self):
        """run_gdb_python() should raise FileNotFoundError for missing script."""
        with pytest.raises(FileNotFoundError) as exc_info:
            run_gdb_python(
                chip="nrf5340",
                script_path="/nonexistent/script.py",
            )
        
        assert "not found" in str(exc_info.value).lower()
        assert "/nonexistent/script.py" in str(exc_info.value)

    @patch("eab.gdb_bridge.subprocess.run")
    @patch("eab.gdb_bridge._default_gdb_for_chip")
    def test_empty_json_result(self, mock_default_gdb, mock_run, tmp_path):
        """run_gdb_python() should handle empty result file gracefully."""
        script = tmp_path / "script.py"
        script.write_text("# script")
        
        mock_default_gdb.return_value = "gdb"
        
        mock_proc = MagicMock()
        mock_proc.returncode = 0
        mock_proc.stdout = "output"
        mock_proc.stderr = ""
        mock_run.return_value = mock_proc
        
        # Don't create result file - simulate script that doesn't write anything
        result = run_gdb_python(
            chip="nrf5340",
            script_path=str(script),
        )
        
        assert result.success is True
        assert result.json_result is None

    @patch("eab.gdb_bridge.subprocess.run")
    @patch("eab.gdb_bridge._default_gdb_for_chip")
    def test_invalid_json_result(self, mock_default_gdb, mock_run, tmp_path):
        """run_gdb_python() should handle malformed JSON gracefully."""
        script = tmp_path / "script.py"
        script.write_text("# script")
        
        mock_default_gdb.return_value = "gdb"
        
        mock_proc = MagicMock()
        mock_proc.returncode = 0
        mock_proc.stdout = "output"
        mock_proc.stderr = ""
        mock_run.return_value = mock_proc
        
        # Mock writing invalid JSON
        def side_effect(argv, **kwargs):
            for i, arg in enumerate(argv):
                if arg.startswith("set $result_file"):
                    result_file = arg.split('"')[1]
                    with open(result_file, "w") as f:
                        f.write("not valid json {")
                    break
            return mock_proc
        
        mock_run.side_effect = side_effect
        
        result = run_gdb_python(
            chip="nrf5340",
            script_path=str(script),
        )
        
        assert result.success is True
        assert result.json_result is None  # Should gracefully handle invalid JSON

    @patch("eab.gdb_bridge.subprocess.run")
    @patch("eab.gdb_bridge._default_gdb_for_chip")
    def test_nonzero_return_code(self, mock_default_gdb, mock_run, tmp_path):
        """run_gdb_python() should capture non-zero return codes."""
        script = tmp_path / "script.py"
        script.write_text("# script")
        
        mock_default_gdb.return_value = "gdb"
        
        mock_proc = MagicMock()
        mock_proc.returncode = 1
        mock_proc.stdout = "error output"
        mock_proc.stderr = "GDB error"
        mock_run.return_value = mock_proc
        
        result = run_gdb_python(
            chip="nrf5340",
            script_path=str(script),
        )
        
        assert result.success is False
        assert result.returncode == 1
        assert result.stdout == "error output"
        assert result.stderr == "GDB error"

    @patch("eab.gdb_bridge.subprocess.run")
    @patch("eab.gdb_bridge._default_gdb_for_chip")
    def test_chip_specific_gdb_selection(self, mock_default_gdb, mock_run, tmp_path):
        """run_gdb_python() should use chip-specific GDB selection."""
        script = tmp_path / "script.py"
        script.write_text("# script")
        
        mock_default_gdb.return_value = "xtensa-esp32s3-elf-gdb"
        
        mock_proc = MagicMock()
        mock_proc.returncode = 0
        mock_proc.stdout = ""
        mock_proc.stderr = ""
        mock_run.return_value = mock_proc
        
        result = run_gdb_python(
            chip="esp32s3",
            script_path=str(script),
        )
        
        # Verify chip was passed to _default_gdb_for_chip
        mock_default_gdb.assert_called_once_with("esp32s3")
        assert result.gdb_path == "xtensa-esp32s3-elf-gdb"

    @patch("eab.gdb_bridge.subprocess.run")
    @patch("eab.gdb_bridge._default_gdb_for_chip")
    def test_complex_json_result(self, mock_default_gdb, mock_run, tmp_path):
        """run_gdb_python() should handle complex nested JSON structures."""
        script = tmp_path / "script.py"
        script.write_text("# script")
        
        mock_default_gdb.return_value = "gdb"
        
        mock_proc = MagicMock()
        mock_proc.returncode = 0
        mock_proc.stdout = "output"
        mock_proc.stderr = ""
        mock_run.return_value = mock_proc
        
        complex_data = {
            "status": "ok",
            "registers": {
                "r0": 42,
                "r1": 100,
                "sp": 0x20001000,
            },
            "memory": [
                {"address": 0x20000000, "value": 0xDEADBEEF},
                {"address": 0x20000004, "value": 0xCAFEBABE},
            ],
            "nested": {
                "level1": {
                    "level2": {
                        "data": [1, 2, 3, 4, 5]
                    }
                }
            }
        }
        
        def side_effect(argv, **kwargs):
            for i, arg in enumerate(argv):
                if arg.startswith("set $result_file"):
                    result_file = arg.split('"')[1]
                    with open(result_file, "w") as f:
                        json.dump(complex_data, f)
                    break
            return mock_proc
        
        mock_run.side_effect = side_effect
        
        result = run_gdb_python(
            chip="nrf5340",
            script_path=str(script),
        )
        
        assert result.json_result == complex_data
        assert result.json_result["nested"]["level1"]["level2"]["data"] == [1, 2, 3, 4, 5]

    @patch("eab.gdb_bridge.subprocess.run")
    @patch("eab.gdb_bridge._default_gdb_for_chip")
    def test_custom_target(self, mock_default_gdb, mock_run, tmp_path):
        """run_gdb_python() should support custom target addresses."""
        script = tmp_path / "script.py"
        script.write_text("# script")
        
        mock_default_gdb.return_value = "gdb"
        
        mock_proc = MagicMock()
        mock_proc.returncode = 0
        mock_proc.stdout = ""
        mock_proc.stderr = ""
        mock_run.return_value = mock_proc
        
        result = run_gdb_python(
            chip="nrf5340",
            script_path=str(script),
            target="192.168.1.100:3333",
        )
        
        call_args = mock_run.call_args
        argv = call_args[0][0]
        
        # Verify target remote command
        assert "target remote 192.168.1.100:3333" in argv

    @patch("eab.gdb_bridge.subprocess.run")
    @patch("eab.gdb_bridge._default_gdb_for_chip")
    def test_timeout_parameter_passed(self, mock_default_gdb, mock_run, tmp_path):
        """run_gdb_python() should pass timeout to subprocess.run."""
        script = tmp_path / "script.py"
        script.write_text("# script")
        
        mock_default_gdb.return_value = "gdb"
        
        mock_proc = MagicMock()
        mock_proc.returncode = 0
        mock_proc.stdout = ""
        mock_proc.stderr = ""
        mock_run.return_value = mock_proc
        
        result = run_gdb_python(
            chip="nrf5340",
            script_path=str(script),
            timeout_s=42.5,
        )
        
        call_args = mock_run.call_args
        assert call_args[1]["timeout"] == 42.5
