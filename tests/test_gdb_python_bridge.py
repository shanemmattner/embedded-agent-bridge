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


# =============================================================================
# Script Generator Tests
# =============================================================================


class TestScriptGenerators:
    """Tests for all GDB Python script generators."""

    def test_all_generators_produce_valid_python(self):
        """All script generators should produce syntactically valid Python."""
        from eab.gdb_bridge import (
            generate_struct_inspector,
            generate_thread_inspector,
            generate_watchpoint_logger,
            generate_memory_dump_script,
        )
        import ast

        scripts = [
            generate_struct_inspector("/path/to/app.elf", "struct kernel", "_kernel"),
            generate_thread_inspector(rtos='zephyr'),
            generate_watchpoint_logger("g_counter", max_hits=50),
            generate_memory_dump_script(0x20000000, 1024, "/tmp/dump.bin"),
        ]

        for script in scripts:
            try:
                ast.parse(script)
            except SyntaxError as e:
                pytest.fail(f"Generated script has syntax error: {e}\n{script}")

    def test_all_generators_use_result_file_pattern(self):
        """All generators should follow the result_file convenience variable pattern."""
        from eab.gdb_bridge import (
            generate_struct_inspector,
            generate_thread_inspector,
            generate_watchpoint_logger,
            generate_memory_dump_script,
        )

        scripts = [
            generate_struct_inspector("/path/to/app.elf", "struct kernel", "_kernel"),
            generate_thread_inspector(rtos='zephyr'),
            generate_watchpoint_logger("g_counter"),
            generate_memory_dump_script(0x20000000, 1024, "/tmp/dump.bin"),
        ]

        for script in scripts:
            assert 'result_file = gdb.convenience_variable("result_file")' in script
            assert 'with open(result_file, "w")' in script
            assert 'json.dump' in script

    def test_all_generators_import_required_modules(self):
        """All generators should import gdb and json."""
        from eab.gdb_bridge import (
            generate_struct_inspector,
            generate_thread_inspector,
            generate_watchpoint_logger,
            generate_memory_dump_script,
        )

        scripts = [
            generate_struct_inspector("/path/to/app.elf", "struct kernel", "_kernel"),
            generate_thread_inspector(rtos='zephyr'),
            generate_watchpoint_logger("g_counter"),
            generate_memory_dump_script(0x20000000, 1024, "/tmp/dump.bin"),
        ]

        for script in scripts:
            assert "import gdb" in script
            assert "import json" in script


class TestStructInspector:
    """Tests for generate_struct_inspector() with variable substitution and error handling."""

    def test_variable_names_substituted_correctly(self):
        """Variable and struct names should be properly substituted in template."""
        from eab.gdb_bridge import generate_struct_inspector

        struct_name = "struct task_info"
        var_name = "current_task"
        
        script = generate_struct_inspector("/app.elf", struct_name, var_name)
        
        # Check variable name appears in parse_and_eval
        assert f'"{var_name}"' in script or f"'{var_name}'" in script
        # Check struct name appears in result
        assert struct_name in script

    def test_includes_gdb_error_handling(self):
        """Script should handle gdb.error exceptions."""
        from eab.gdb_bridge import generate_struct_inspector

        script = generate_struct_inspector("/app.elf", "struct s", "var")
        
        assert "except gdb.error" in script
        # Check for status assignment to error (Python code, not JSON literal)
        assert 'result["status"] = "error"' in script or "result['status'] = 'error'" in script

    def test_handles_pointer_dereferencing(self):
        """Script should dereference pointers."""
        from eab.gdb_bridge import generate_struct_inspector

        script = generate_struct_inspector("/app.elf", "struct s", "var")
        
        assert "TYPE_CODE_PTR" in script
        assert "dereference" in script

    def test_iterates_struct_fields(self):
        """Script should iterate through struct fields."""
        from eab.gdb_bridge import generate_struct_inspector

        script = generate_struct_inspector("/app.elf", "struct s", "var")
        
        assert "fields()" in script
        assert "field_name" in script
        assert "TYPE_CODE_STRUCT" in script

    def test_different_vars_produce_different_scripts(self):
        """Different variable names should produce different scripts."""
        from eab.gdb_bridge import generate_struct_inspector

        script1 = generate_struct_inspector("/app.elf", "struct s", "var1")
        script2 = generate_struct_inspector("/app.elf", "struct s", "var2")
        
        assert script1 != script2
        assert "var1" in script1
        assert "var2" in script2

    def test_json_output_structure(self):
        """Script should generate proper JSON structure."""
        from eab.gdb_bridge import generate_struct_inspector

        script = generate_struct_inspector("/app.elf", "struct kernel", "_kernel")
        
        # Check for expected JSON fields
        assert '"status"' in script or "'status'" in script
        assert '"fields"' in script or "'fields'" in script
        assert '"var_name"' in script or "'var_name'" in script
        assert '"struct_name"' in script or "'struct_name'" in script


class TestThreadInspector:
    """Tests for generate_thread_inspector() with RTOS detection and error handling."""

    def test_only_zephyr_supported(self):
        """Should raise ValueError for unsupported RTOS."""
        from eab.gdb_bridge import generate_thread_inspector

        # Should work for zephyr
        script = generate_thread_inspector(rtos='zephyr')
        assert script is not None
        
        # Should fail for others
        with pytest.raises(ValueError) as exc_info:
            generate_thread_inspector(rtos='freertos')
        assert "unsupported" in str(exc_info.value).lower()

    def test_case_insensitive_rtos_check(self):
        """RTOS check should be case-insensitive."""
        from eab.gdb_bridge import generate_thread_inspector

        # Should work with different cases
        script1 = generate_thread_inspector(rtos='zephyr')
        script2 = generate_thread_inspector(rtos='ZEPHYR')
        script3 = generate_thread_inspector(rtos='Zephyr')
        
        # All should succeed
        assert script1 is not None
        assert script2 is not None
        assert script3 is not None

    def test_accesses_kernel_threads_list(self):
        """Script should access _kernel.threads linked list."""
        from eab.gdb_bridge import generate_thread_inspector

        script = generate_thread_inspector(rtos='zephyr')
        
        assert "_kernel" in script
        assert "threads" in script
        assert "next" in script  # Linked list traversal

    def test_includes_safety_limit(self):
        """Script should have safety limit to prevent infinite loops."""
        from eab.gdb_bridge import generate_thread_inspector

        script = generate_thread_inspector(rtos='zephyr')
        
        # Should have max_threads variable
        assert "max_threads" in script
        # Should check against it
        assert "< max_threads" in script or "<max_threads" in script

    def test_handles_list_traversal_errors(self):
        """Script should handle errors during list traversal."""
        from eab.gdb_bridge import generate_thread_inspector

        script = generate_thread_inspector(rtos='zephyr')
        
        assert "except" in script
        assert "gdb.error" in script
        # Should continue or break on error, not crash
        assert "break" in script or "continue" in script

    def test_json_output_structure(self):
        """Script should generate proper JSON structure for thread list."""
        from eab.gdb_bridge import generate_thread_inspector

        script = generate_thread_inspector(rtos='zephyr')
        
        assert '"status"' in script or "'status'" in script
        assert '"rtos"' in script or "'rtos'" in script
        assert '"threads"' in script or "'threads'" in script
        assert '"thread_count"' in script or "'thread_count'" in script


class TestWatchpointLogger:
    """Tests for generate_watchpoint_logger() with variable substitution."""

    def test_variable_name_substituted(self):
        """Variable name should be substituted in watchpoint and parse_and_eval."""
        from eab.gdb_bridge import generate_watchpoint_logger

        var_name = "g_watchme"
        script = generate_watchpoint_logger(var_name, max_hits=10)
        
        # Should appear in multiple places
        assert var_name in script
        # Should be in Breakpoint call
        assert f'"{var_name}"' in script or f"'{var_name}'" in script

    def test_max_hits_substituted(self):
        """max_hits parameter should be substituted in script."""
        from eab.gdb_bridge import generate_watchpoint_logger

        max_hits = 42
        script = generate_watchpoint_logger("var", max_hits=max_hits)
        
        assert str(max_hits) in script

    def test_uses_gdb_command_class(self):
        """Script should use gdb.Command pattern."""
        from eab.gdb_bridge import generate_watchpoint_logger

        script = generate_watchpoint_logger("var")
        
        assert "class" in script
        assert "gdb.Command" in script
        assert "def invoke" in script

    def test_captures_backtrace_on_hit(self):
        """Script should capture backtrace for each watchpoint hit."""
        from eab.gdb_bridge import generate_watchpoint_logger

        script = generate_watchpoint_logger("var")
        
        assert "backtrace" in script
        assert "newest_frame" in script
        assert "older" in script

    def test_continues_execution(self):
        """Script should continue execution to catch hits."""
        from eab.gdb_bridge import generate_watchpoint_logger

        script = generate_watchpoint_logger("var")
        
        assert "continue" in script

    def test_auto_quits_after_logging(self):
        """Script should automatically quit after logging hits."""
        from eab.gdb_bridge import generate_watchpoint_logger

        script = generate_watchpoint_logger("var")
        
        assert "quit" in script

    def test_default_max_hits(self):
        """Default max_hits should be 100."""
        from eab.gdb_bridge import generate_watchpoint_logger

        script = generate_watchpoint_logger("var")
        
        assert "100" in script

    def test_json_output_structure(self):
        """Script should generate proper JSON structure for hits."""
        from eab.gdb_bridge import generate_watchpoint_logger

        script = generate_watchpoint_logger("var", max_hits=10)
        
        assert '"status"' in script or "'status'" in script
        assert '"var_name"' in script or "'var_name'" in script
        assert '"max_hits"' in script or "'max_hits'" in script
        assert '"hits"' in script or "'hits'" in script


class TestMemoryDumpScript:
    """Tests for generate_memory_dump_script() with address/size substitution."""

    def test_address_formatted_as_hex(self):
        """Address should be formatted as hex in script."""
        from eab.gdb_bridge import generate_memory_dump_script

        addr = 0x20001000
        script = generate_memory_dump_script(addr, 1024, "/tmp/dump.bin")
        
        # Should contain hex formatted address
        assert "0x20001000" in script

    def test_size_substituted(self):
        """Size parameter should be substituted."""
        from eab.gdb_bridge import generate_memory_dump_script

        size = 2048
        script = generate_memory_dump_script(0x20000000, size, "/tmp/dump.bin")
        
        assert str(size) in script

    def test_output_path_substituted(self):
        """Output path should be substituted."""
        from eab.gdb_bridge import generate_memory_dump_script

        output = "/tmp/my_memdump.bin"
        script = generate_memory_dump_script(0x20000000, 1024, output)
        
        assert output in script

    def test_uses_inferior_read_memory(self):
        """Script should use inferior.read_memory()."""
        from eab.gdb_bridge import generate_memory_dump_script

        script = generate_memory_dump_script(0x20000000, 1024, "/tmp/dump.bin")
        
        assert "inferior" in script
        assert "read_memory" in script

    def test_writes_binary_file(self):
        """Script should write binary file."""
        from eab.gdb_bridge import generate_memory_dump_script

        script = generate_memory_dump_script(0x20000000, 1024, "/tmp/dump.bin")
        
        assert '"wb"' in script or "'wb'" in script

    def test_handles_io_errors(self):
        """Script should handle IOError exceptions."""
        from eab.gdb_bridge import generate_memory_dump_script

        script = generate_memory_dump_script(0x20000000, 1024, "/tmp/dump.bin")
        
        assert "IOError" in script
        assert "except" in script

    def test_reports_bytes_written(self):
        """Script should report bytes written in result."""
        from eab.gdb_bridge import generate_memory_dump_script

        script = generate_memory_dump_script(0x20000000, 1024, "/tmp/dump.bin")
        
        assert "bytes_written" in script

    def test_json_output_structure(self):
        """Script should generate proper JSON structure."""
        from eab.gdb_bridge import generate_memory_dump_script

        script = generate_memory_dump_script(0x20000000, 1024, "/tmp/dump.bin")
        
        assert '"status"' in script or "'status'" in script
        assert '"start_addr"' in script or "'start_addr'" in script
        assert '"size"' in script or "'size'" in script
        assert '"output_path"' in script or "'output_path'" in script


# =============================================================================
# GDB Server Lifecycle Tests (from CLI commands)
# =============================================================================


class TestGDBServerLifecycle:
    """Tests for GDB server lifecycle management in CLI integration."""

    @patch("eab.gdb_bridge.subprocess.run")
    @patch("eab.gdb_bridge._default_gdb_for_chip")
    def test_script_execution_with_target(self, mock_default_gdb, mock_run, tmp_path):
        """run_gdb_python() should connect to specified target."""
        script = tmp_path / "test.py"
        script.write_text("# test")
        
        mock_default_gdb.return_value = "gdb"
        
        mock_proc = MagicMock()
        mock_proc.returncode = 0
        mock_proc.stdout = ""
        mock_proc.stderr = ""
        mock_run.return_value = mock_proc
        
        # Test with custom target
        result = run_gdb_python(
            chip="nrf5340",
            script_path=str(script),
            target="192.168.1.100:3333",
        )
        
        assert result.success is True
        
        call_args = mock_run.call_args
        argv = call_args[0][0]
        
        # Verify target remote command
        assert "target remote 192.168.1.100:3333" in argv

    @patch("eab.gdb_bridge.subprocess.run")
    @patch("eab.gdb_bridge._default_gdb_for_chip")
    def test_default_target_localhost(self, mock_default_gdb, mock_run, tmp_path):
        """run_gdb_python() should default to localhost:3333."""
        script = tmp_path / "test.py"
        script.write_text("# test")
        
        mock_default_gdb.return_value = "gdb"
        
        mock_proc = MagicMock()
        mock_proc.returncode = 0
        mock_proc.stdout = ""
        mock_proc.stderr = ""
        mock_run.return_value = mock_proc
        
        # Don't specify target - should default
        result = run_gdb_python(
            chip="nrf5340",
            script_path=str(script),
        )
        
        call_args = mock_run.call_args
        argv = call_args[0][0]
        
        # Should use default
        assert "target remote localhost:3333" in argv

    @patch("eab.gdb_bridge.subprocess.run")
    @patch("eab.gdb_bridge._default_gdb_for_chip")
    def test_detach_and_quit_commands(self, mock_default_gdb, mock_run, tmp_path):
        """run_gdb_python() should always detach and quit."""
        script = tmp_path / "test.py"
        script.write_text("# test")
        
        mock_default_gdb.return_value = "gdb"
        
        mock_proc = MagicMock()
        mock_proc.returncode = 0
        mock_proc.stdout = ""
        mock_proc.stderr = ""
        mock_run.return_value = mock_proc
        
        result = run_gdb_python(
            chip="nrf5340",
            script_path=str(script),
        )
        
        call_args = mock_run.call_args
        argv = call_args[0][0]
        
        # Should have detach and quit
        assert "detach" in argv
        assert "quit" in argv

    @patch("eab.gdb_bridge.subprocess.run")
    @patch("eab.gdb_bridge._default_gdb_for_chip")
    def test_batch_mode_enabled(self, mock_default_gdb, mock_run, tmp_path):
        """run_gdb_python() should use batch mode."""
        script = tmp_path / "test.py"
        script.write_text("# test")
        
        mock_default_gdb.return_value = "gdb"
        
        mock_proc = MagicMock()
        mock_proc.returncode = 0
        mock_proc.stdout = ""
        mock_proc.stderr = ""
        mock_run.return_value = mock_proc
        
        result = run_gdb_python(
            chip="nrf5340",
            script_path=str(script),
        )
        
        call_args = mock_run.call_args
        argv = call_args[0][0]
        
        # Should use -batch and -q
        assert "-batch" in argv
        assert "-q" in argv


# =============================================================================
# Error Handling Tests
# =============================================================================


class TestErrorHandling:
    """Tests for error handling in various failure scenarios."""

    def test_invalid_struct_name_in_script(self):
        """generate_struct_inspector() should generate script that handles invalid symbols."""
        from eab.gdb_bridge import generate_struct_inspector

        # Generate script with any struct name - it should handle errors
        script = generate_struct_inspector("/app.elf", "struct nonexistent", "bad_var")
        
        # Script should have error handling
        assert "except gdb.error" in script
        # Should set error status (Python assignment, not JSON literal)
        assert 'result["status"] = "error"' in script or "result['status'] = 'error'" in script
        # Should store error message
        assert 'result["error"]' in script or "result['error']" in script

    def test_missing_elf_symbols(self):
        """run_gdb_python() should handle case where ELF has no symbols."""
        from eab.gdb_bridge import run_gdb_python
        
        # Without ELF file, script should still execute
        # This is a valid use case (e.g., examining registers only)
        # Test is in TestRunGdbPython.test_execution_without_elf

    def test_rtos_detection_failure(self):
        """generate_thread_inspector() should fail fast for unsupported RTOS."""
        from eab.gdb_bridge import generate_thread_inspector
        
        # Should raise ValueError immediately
        with pytest.raises(ValueError) as exc_info:
            generate_thread_inspector(rtos='unsupported_os')
        
        error_msg = str(exc_info.value).lower()
        assert "unsupported" in error_msg
        assert "zephyr" in error_msg  # Should mention what IS supported

    def test_invalid_watchpoint_variable(self):
        """Watchpoint logger script should handle gdb.error for invalid variables."""
        from eab.gdb_bridge import generate_watchpoint_logger
        
        script = generate_watchpoint_logger("nonexistent_var")
        
        # Script should catch errors during watchpoint creation
        assert "except gdb.error" in script
        # Should handle errors gracefully (Python assignment, not JSON literal)
        assert 'result["status"] = "error"' in script or "result['status'] = 'error'" in script

    def test_memory_read_error_handling(self):
        """Memory dump script should handle invalid memory addresses."""
        from eab.gdb_bridge import generate_memory_dump_script
        
        # Generate script with any address - should have error handling
        script = generate_memory_dump_script(0xFFFFFFFF, 1024, "/tmp/dump.bin")
        
        # Should catch gdb.error for invalid reads
        assert "except gdb.error" in script
        # Should set error status (Python assignment, not JSON literal)
        assert 'result["status"] = "error"' in script or "result['status'] = 'error'" in script

    @patch("eab.gdb_bridge.subprocess.run")
    @patch("eab.gdb_bridge._default_gdb_for_chip")
    def test_gdb_not_found_error(self, mock_default_gdb, mock_run, tmp_path):
        """run_gdb_python() should handle GDB not found in PATH."""
        script = tmp_path / "test.py"
        script.write_text("# test")
        
        # Mock GDB not found
        mock_default_gdb.return_value = None
        
        # Should still try with "gdb" fallback
        mock_proc = MagicMock()
        mock_proc.returncode = 127  # Command not found
        mock_proc.stdout = ""
        mock_proc.stderr = "gdb: command not found"
        mock_run.return_value = mock_proc
        
        result = run_gdb_python(
            chip="nrf5340",
            script_path=str(script),
        )
        
        # Should return failure
        assert result.success is False
        assert result.returncode == 127

    @patch("eab.gdb_bridge.subprocess.run")
    @patch("eab.gdb_bridge._default_gdb_for_chip")
    def test_gdb_connection_timeout(self, mock_default_gdb, mock_run, tmp_path):
        """run_gdb_python() should handle connection timeouts."""
        script = tmp_path / "test.py"
        script.write_text("# test")
        
        mock_default_gdb.return_value = "gdb"
        
        # Mock timeout
        mock_run.side_effect = subprocess.TimeoutExpired("gdb", 5.0)
        
        with pytest.raises(subprocess.TimeoutExpired):
            run_gdb_python(
                chip="nrf5340",
                script_path=str(script),
                timeout_s=5.0,
            )


# =============================================================================
# Pytest Fixtures for Common Test Data
# =============================================================================


@pytest.fixture
def sample_elf_path(tmp_path):
    """Provide a sample ELF path for testing."""
    elf = tmp_path / "sample_app.elf"
    elf.write_bytes(b"ELF\x01\x01\x01\x00")  # Minimal ELF header
    return str(elf)


@pytest.fixture
def device_names():
    """Provide common device names for testing."""
    return {
        "nrf5340": "NRF5340_XXAA_APP",
        "stm32f4": "STM32F407VG",
        "esp32s3": "esp32s3",
        "mcxn947": "MCXN947",
    }


@pytest.fixture
def mock_gdb_output():
    """Provide mock GDB output for testing."""
    return {
        "registers": (
            "r0             0x20000100       536871168\n"
            "r1             0x00000000       0\n"
            "sp             0x20008000       0x20008000\n"
            "pc             0x08001234       0x08001234\n"
        ),
        "fault_regs": (
            "0xe000ed28:\t0x00000200\n"  # CFSR
            "0xe000ed2c:\t0x40000000\n"  # HFSR
        ),
        "backtrace": (
            "#0  fault_handler () at fault.c:42\n"
            "#1  0x08001234 in main () at main.c:100\n"
        ),
    }


@pytest.fixture
def mock_debug_probe():
    """Provide a mock debug probe for testing."""
    probe = MagicMock()
    probe.gdb_port = 2331
    probe.start_gdb_server.return_value = MagicMock(
        running=True,
        pid=12345,
        port=2331,
        last_error=None,
    )
    return probe


class TestFixturesUsage:
    """Tests demonstrating fixture usage."""

    def test_sample_elf_fixture(self, sample_elf_path):
        """sample_elf_path fixture should provide valid path."""
        from pathlib import Path
        assert Path(sample_elf_path).exists()
        assert sample_elf_path.endswith(".elf")

    def test_device_names_fixture(self, device_names):
        """device_names fixture should provide chip-to-device mappings."""
        assert "nrf5340" in device_names
        assert "NRF5340_XXAA_APP" in device_names["nrf5340"]

    def test_mock_gdb_output_fixture(self, mock_gdb_output):
        """mock_gdb_output fixture should provide sample GDB output."""
        assert "registers" in mock_gdb_output
        assert "r0" in mock_gdb_output["registers"]

    def test_mock_debug_probe_fixture(self, mock_debug_probe):
        """mock_debug_probe fixture should provide configured probe."""
        assert mock_debug_probe.gdb_port == 2331
        status = mock_debug_probe.start_gdb_server()
        assert status.running is True


# =============================================================================
# Integration Tests with Fixtures
# =============================================================================


class TestIntegrationWithFixtures:
    """Integration tests using common fixtures."""

    @patch("eab.gdb_bridge.subprocess.run")
    @patch("eab.gdb_bridge._default_gdb_for_chip")
    def test_struct_inspector_with_elf(
        self, mock_default_gdb, mock_run, sample_elf_path, tmp_path
    ):
        """Integration test: struct inspector with real ELF path."""
        from eab.gdb_bridge import generate_struct_inspector
        
        # Generate script
        script_content = generate_struct_inspector(
            sample_elf_path, "struct kernel", "_kernel"
        )
        
        script_path = tmp_path / "inspect.py"
        script_path.write_text(script_content)
        
        # Mock GDB execution
        mock_default_gdb.return_value = "gdb"
        mock_proc = MagicMock()
        mock_proc.returncode = 0
        mock_proc.stdout = ""
        mock_proc.stderr = ""
        
        def side_effect(argv, **kwargs):
            # Write mock result
            for arg in argv:
                if arg.startswith("set $result_file"):
                    result_file = arg.split('"')[1]
                    with open(result_file, "w") as f:
                        json.dump({
                            "status": "ok",
                            "var_name": "_kernel",
                            "fields": {"ready_q": 0x20001000}
                        }, f)
                    break
            return mock_proc
        
        mock_run.side_effect = side_effect
        
        # Execute
        result = run_gdb_python(
            chip="nrf5340",
            script_path=str(script_path),
            elf=sample_elf_path,
        )
        
        assert result.success is True
        assert result.json_result["status"] == "ok"
        assert result.json_result["var_name"] == "_kernel"

    @patch("eab.gdb_bridge.subprocess.run")
    @patch("eab.gdb_bridge._default_gdb_for_chip")
    def test_thread_inspector_integration(
        self, mock_default_gdb, mock_run, sample_elf_path, tmp_path
    ):
        """Integration test: thread inspector with mock threads."""
        from eab.gdb_bridge import generate_thread_inspector
        
        script_content = generate_thread_inspector(rtos='zephyr')
        script_path = tmp_path / "threads.py"
        script_path.write_text(script_content)
        
        mock_default_gdb.return_value = "gdb"
        mock_proc = MagicMock()
        mock_proc.returncode = 0
        mock_proc.stdout = ""
        mock_proc.stderr = ""
        
        def side_effect(argv, **kwargs):
            for arg in argv:
                if arg.startswith("set $result_file"):
                    result_file = arg.split('"')[1]
                    with open(result_file, "w") as f:
                        json.dump({
                            "status": "ok",
                            "rtos": "zephyr",
                            "thread_count": 2,
                            "threads": [
                                {"address": 0x20001000},
                                {"address": 0x20002000},
                            ]
                        }, f)
                    break
            return mock_proc
        
        mock_run.side_effect = side_effect
        
        result = run_gdb_python(
            chip="nrf5340",
            script_path=str(script_path),
            elf=sample_elf_path,
        )
        
        assert result.success is True
        assert result.json_result["rtos"] == "zephyr"
        assert result.json_result["thread_count"] == 2
