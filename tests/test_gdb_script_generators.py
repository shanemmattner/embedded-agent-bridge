"""Tests for GDB Python script generators in gdb_bridge.

Tests verify that generated scripts:
- Have correct Python syntax
- Use correct variable names
- Follow the template pattern with gdb.Command class where appropriate
- Output proper JSON structure
- Handle errors gracefully
"""

from __future__ import annotations

import ast

import pytest

from eab.gdb_bridge import (
    generate_struct_inspector,
    generate_thread_inspector,
    generate_watchpoint_logger,
    generate_memory_dump_script,
)


class TestGenerateStructInspector:
    """Tests for generate_struct_inspector()."""

    def test_generates_valid_python_syntax(self):
        """generate_struct_inspector() should generate syntactically valid Python."""
        script = generate_struct_inspector(
            "/path/to/app.elf",
            "struct kernel",
            "_kernel"
        )
        
        # Should be valid Python syntax
        try:
            ast.parse(script)
        except SyntaxError as e:
            pytest.fail(f"Generated script has syntax error: {e}")

    def test_includes_struct_and_var_names(self):
        """generate_struct_inspector() should include struct and variable names in script."""
        struct_name = "struct task_struct"
        var_name = "current_task"
        
        script = generate_struct_inspector(
            "/path/to/app.elf",
            struct_name,
            var_name
        )
        
        # Check that variable and struct names appear in the script
        assert var_name in script
        assert struct_name in script or "struct_name" in script

    def test_uses_result_file_pattern(self):
        """generate_struct_inspector() should follow result_file pattern."""
        script = generate_struct_inspector(
            "/path/to/app.elf",
            "struct kernel",
            "_kernel"
        )
        
        # Should read result_file from convenience variable
        assert 'gdb.convenience_variable("result_file")' in script
        # Should write JSON to result_file
        assert 'with open(result_file, "w")' in script
        assert 'json.dump' in script

    def test_imports_required_modules(self):
        """generate_struct_inspector() should import gdb and json."""
        script = generate_struct_inspector(
            "/path/to/app.elf",
            "struct kernel",
            "_kernel"
        )
        
        assert "import gdb" in script
        assert "import json" in script

    def test_includes_error_handling(self):
        """generate_struct_inspector() should include error handling."""
        script = generate_struct_inspector(
            "/path/to/app.elf",
            "struct kernel",
            "_kernel"
        )
        
        # Should have try/except blocks
        assert "try:" in script
        assert "except" in script
        # Should handle gdb.error
        assert "gdb.error" in script

    def test_uses_parse_and_eval(self):
        """generate_struct_inspector() should use gdb.parse_and_eval."""
        var_name = "my_variable"
        script = generate_struct_inspector(
            "/path/to/app.elf",
            "struct my_struct",
            var_name
        )
        
        # Should use parse_and_eval with the variable name
        assert "gdb.parse_and_eval" in script
        assert f'"{var_name}"' in script or f"'{var_name}'" in script

    def test_generates_different_scripts_for_different_vars(self):
        """generate_struct_inspector() should generate different scripts for different variables."""
        script1 = generate_struct_inspector(
            "/path/to/app.elf",
            "struct kernel",
            "_kernel"
        )
        script2 = generate_struct_inspector(
            "/path/to/app.elf",
            "struct task",
            "current_task"
        )
        
        # Scripts should be different
        assert script1 != script2
        # Each should contain its own variable name
        assert "_kernel" in script1
        assert "current_task" in script2


class TestGenerateThreadInspector:
    """Tests for generate_thread_inspector()."""

    def test_generates_valid_python_syntax(self):
        """generate_thread_inspector() should generate syntactically valid Python."""
        script = generate_thread_inspector(rtos='zephyr')
        
        try:
            ast.parse(script)
        except SyntaxError as e:
            pytest.fail(f"Generated script has syntax error: {e}")

    def test_only_supports_zephyr(self):
        """generate_thread_inspector() should only support 'zephyr' RTOS."""
        # Should work with 'zephyr'
        script = generate_thread_inspector(rtos='zephyr')
        assert script is not None
        
        # Should raise ValueError for unsupported RTOS
        with pytest.raises(ValueError) as exc_info:
            generate_thread_inspector(rtos='freertos')
        
        assert "unsupported" in str(exc_info.value).lower()
        assert "freertos" in str(exc_info.value).lower()

    def test_uses_result_file_pattern(self):
        """generate_thread_inspector() should follow result_file pattern."""
        script = generate_thread_inspector(rtos='zephyr')
        
        assert 'gdb.convenience_variable("result_file")' in script
        assert 'with open(result_file, "w")' in script
        assert 'json.dump' in script

    def test_imports_required_modules(self):
        """generate_thread_inspector() should import gdb and json."""
        script = generate_thread_inspector(rtos='zephyr')
        
        assert "import gdb" in script
        assert "import json" in script

    def test_accesses_kernel_threads(self):
        """generate_thread_inspector() should access _kernel.threads."""
        script = generate_thread_inspector(rtos='zephyr')
        
        # Should try to access _kernel variable
        assert "_kernel" in script
        # Should access threads field
        assert "threads" in script

    def test_includes_safety_limit(self):
        """generate_thread_inspector() should include safety limit to prevent infinite loops."""
        script = generate_thread_inspector(rtos='zephyr')
        
        # Should have a max threads limit
        assert "max_threads" in script or "100" in script

    def test_includes_error_handling(self):
        """generate_thread_inspector() should include error handling."""
        script = generate_thread_inspector(rtos='zephyr')
        
        assert "try:" in script
        assert "except" in script
        assert "gdb.error" in script

    def test_outputs_thread_list(self):
        """generate_thread_inspector() should output a list of threads."""
        script = generate_thread_inspector(rtos='zephyr')
        
        # Should have threads array in result
        assert '"threads"' in script or "'threads'" in script

    def test_handles_linked_list_traversal(self):
        """generate_thread_inspector() should traverse linked list."""
        script = generate_thread_inspector(rtos='zephyr')
        
        # Should have linked list traversal logic
        assert "next" in script
        # Should have loop/while construct
        assert "while" in script


class TestGenerateWatchpointLogger:
    """Tests for generate_watchpoint_logger()."""

    def test_generates_valid_python_syntax(self):
        """generate_watchpoint_logger() should generate syntactically valid Python."""
        script = generate_watchpoint_logger("g_counter", max_hits=50)
        
        try:
            ast.parse(script)
        except SyntaxError as e:
            pytest.fail(f"Generated script has syntax error: {e}")

    def test_includes_variable_name(self):
        """generate_watchpoint_logger() should include the watched variable name."""
        var_name = "g_watchme"
        script = generate_watchpoint_logger(var_name, max_hits=10)
        
        assert var_name in script

    def test_includes_max_hits_parameter(self):
        """generate_watchpoint_logger() should include max_hits parameter."""
        max_hits = 42
        script = generate_watchpoint_logger("g_counter", max_hits=max_hits)
        
        # Should contain the max_hits value
        assert str(max_hits) in script

    def test_uses_gdb_command_class(self):
        """generate_watchpoint_logger() should use gdb.Command class pattern."""
        script = generate_watchpoint_logger("g_counter")
        
        # Should define a class inheriting from gdb.Command
        assert "class" in script
        assert "gdb.Command" in script

    def test_uses_result_file_pattern(self):
        """generate_watchpoint_logger() should follow result_file pattern."""
        script = generate_watchpoint_logger("g_counter")
        
        assert 'gdb.convenience_variable("result_file")' in script
        assert 'with open(result_file, "w")' in script
        assert 'json.dump' in script

    def test_imports_required_modules(self):
        """generate_watchpoint_logger() should import gdb and json."""
        script = generate_watchpoint_logger("g_counter")
        
        assert "import gdb" in script
        assert "import json" in script

    def test_sets_watchpoint(self):
        """generate_watchpoint_logger() should set a watchpoint."""
        var_name = "my_var"
        script = generate_watchpoint_logger(var_name)
        
        # Should create a watchpoint
        assert "gdb.Breakpoint" in script or "BP_WATCHPOINT" in script
        assert var_name in script

    def test_captures_backtrace(self):
        """generate_watchpoint_logger() should capture backtraces on hits."""
        script = generate_watchpoint_logger("g_counter")
        
        # Should capture backtrace
        assert "backtrace" in script
        # Should use frame walking
        assert "frame" in script.lower()
        assert "newest_frame" in script or "older" in script

    def test_includes_error_handling(self):
        """generate_watchpoint_logger() should include error handling."""
        script = generate_watchpoint_logger("g_counter")
        
        assert "try:" in script
        assert "except" in script
        assert "gdb.error" in script

    def test_outputs_hits_list(self):
        """generate_watchpoint_logger() should output a list of hits."""
        script = generate_watchpoint_logger("g_counter")
        
        # Should have hits array in result
        assert '"hits"' in script or "'hits'" in script

    def test_continues_execution(self):
        """generate_watchpoint_logger() should continue execution to catch watchpoint hits."""
        script = generate_watchpoint_logger("g_counter")
        
        # Should use continue command
        assert "continue" in script

    def test_auto_quits(self):
        """generate_watchpoint_logger() should auto-quit after logging."""
        script = generate_watchpoint_logger("g_counter")
        
        # Should execute quit command
        assert "quit" in script

    def test_generates_different_scripts_for_different_vars(self):
        """generate_watchpoint_logger() should generate different scripts for different variables."""
        script1 = generate_watchpoint_logger("var1", max_hits=10)
        script2 = generate_watchpoint_logger("var2", max_hits=20)
        
        assert script1 != script2
        assert "var1" in script1
        assert "var2" in script2
        assert "10" in script1
        assert "20" in script2

    def test_default_max_hits(self):
        """generate_watchpoint_logger() should default to 100 max_hits."""
        script = generate_watchpoint_logger("g_counter")
        
        # Should contain default value of 100
        assert "100" in script


class TestGenerateMemoryDumpScript:
    """Tests for generate_memory_dump_script()."""

    def test_generates_valid_python_syntax(self):
        """generate_memory_dump_script() should generate syntactically valid Python."""
        script = generate_memory_dump_script(0x20000000, 1024, "/tmp/dump.bin")
        
        try:
            ast.parse(script)
        except SyntaxError as e:
            pytest.fail(f"Generated script has syntax error: {e}")

    def test_includes_memory_address(self):
        """generate_memory_dump_script() should include the memory address."""
        start_addr = 0x20001000
        script = generate_memory_dump_script(start_addr, 512, "/tmp/dump.bin")
        
        # Should contain the address in hex format
        hex_addr = f"0x{start_addr:08x}"
        assert hex_addr in script

    def test_includes_size(self):
        """generate_memory_dump_script() should include the size parameter."""
        size = 2048
        script = generate_memory_dump_script(0x20000000, size, "/tmp/dump.bin")
        
        # Should contain the size value
        assert str(size) in script

    def test_includes_output_path(self):
        """generate_memory_dump_script() should include the output path."""
        output_path = "/tmp/my_memory_dump.bin"
        script = generate_memory_dump_script(0x20000000, 1024, output_path)
        
        assert output_path in script

    def test_uses_result_file_pattern(self):
        """generate_memory_dump_script() should follow result_file pattern."""
        script = generate_memory_dump_script(0x20000000, 1024, "/tmp/dump.bin")
        
        assert 'gdb.convenience_variable("result_file")' in script
        assert 'with open(result_file, "w")' in script
        assert 'json.dump' in script

    def test_imports_required_modules(self):
        """generate_memory_dump_script() should import gdb and json."""
        script = generate_memory_dump_script(0x20000000, 1024, "/tmp/dump.bin")
        
        assert "import gdb" in script
        assert "import json" in script

    def test_uses_read_memory(self):
        """generate_memory_dump_script() should use inferior.read_memory()."""
        script = generate_memory_dump_script(0x20000000, 1024, "/tmp/dump.bin")
        
        # Should use inferior to read memory
        assert "inferior" in script
        assert "read_memory" in script

    def test_writes_binary_file(self):
        """generate_memory_dump_script() should write memory to binary file."""
        output_path = "/tmp/memdump.bin"
        script = generate_memory_dump_script(0x20000000, 1024, output_path)
        
        # Should open file in binary write mode
        assert '"wb"' in script or "'wb'" in script
        # Should write to the output path
        assert output_path in script

    def test_includes_error_handling(self):
        """generate_memory_dump_script() should include error handling."""
        script = generate_memory_dump_script(0x20000000, 1024, "/tmp/dump.bin")
        
        assert "try:" in script
        assert "except" in script
        # Should handle both gdb errors and IO errors
        assert "gdb.error" in script
        assert "IOError" in script or "Exception" in script

    def test_reports_bytes_written(self):
        """generate_memory_dump_script() should report bytes written in JSON result."""
        script = generate_memory_dump_script(0x20000000, 1024, "/tmp/dump.bin")
        
        # Should include bytes_written in result
        assert "bytes_written" in script

    def test_generates_different_scripts_for_different_params(self):
        """generate_memory_dump_script() should generate different scripts for different parameters."""
        script1 = generate_memory_dump_script(0x20000000, 1024, "/tmp/dump1.bin")
        script2 = generate_memory_dump_script(0x30000000, 2048, "/tmp/dump2.bin")
        
        assert script1 != script2
        assert "0x20000000" in script1
        assert "0x30000000" in script2
        assert "1024" in script1
        assert "2048" in script2
        assert "dump1.bin" in script1
        assert "dump2.bin" in script2

    def test_handles_integer_addresses(self):
        """generate_memory_dump_script() should handle integer addresses."""
        # Test with plain integer
        script = generate_memory_dump_script(536870912, 1024, "/tmp/dump.bin")  # 0x20000000
        
        assert "0x20000000" in script


class TestScriptIntegration:
    """Integration tests to verify generated scripts work correctly."""

    def test_struct_inspector_produces_valid_json_structure(self):
        """Verify struct inspector generates script with correct JSON structure."""
        script = generate_struct_inspector(
            "/path/to/app.elf",
            "struct kernel",
            "_kernel"
        )
        
        # Extract the JSON structure being built (look for result dict)
        assert '"status":' in script or "'status':" in script
        assert '"fields":' in script or "'fields':" in script
        assert '"var_name":' in script or "'var_name':" in script
        assert '"struct_name":' in script or "'struct_name':" in script

    def test_thread_inspector_produces_valid_json_structure(self):
        """Verify thread inspector generates script with correct JSON structure."""
        script = generate_thread_inspector(rtos='zephyr')
        
        assert '"status":' in script or "'status':" in script
        assert '"rtos":' in script or "'rtos':" in script
        assert '"threads":' in script or "'threads':" in script

    def test_watchpoint_logger_produces_valid_json_structure(self):
        """Verify watchpoint logger generates script with correct JSON structure."""
        script = generate_watchpoint_logger("g_counter", max_hits=10)
        
        assert '"status":' in script or "'status':" in script
        assert '"var_name":' in script or "'var_name':" in script
        assert '"hits":' in script or "'hits':" in script
        assert '"max_hits":' in script or "'max_hits':" in script

    def test_memory_dump_script_produces_valid_json_structure(self):
        """Verify memory dump script generates correct JSON structure."""
        script = generate_memory_dump_script(0x20000000, 1024, "/tmp/dump.bin")
        
        assert '"status":' in script or "'status':" in script
        assert '"start_addr":' in script or "'start_addr':" in script
        assert '"size":' in script or "'size':" in script
        assert '"output_path":' in script or "'output_path':" in script

    def test_all_scripts_can_be_written_to_files(self, tmp_path):
        """Verify all generated scripts can be written to actual files."""
        scripts = [
            ("struct_inspector.py", generate_struct_inspector("/app.elf", "struct s", "var")),
            ("thread_inspector.py", generate_thread_inspector(rtos='zephyr')),
            ("watchpoint_logger.py", generate_watchpoint_logger("var", 10)),
            ("memory_dump.py", generate_memory_dump_script(0x20000000, 1024, "/tmp/dump.bin")),
        ]
        
        for filename, script_content in scripts:
            script_path = tmp_path / filename
            script_path.write_text(script_content)
            
            # Verify file was created and is readable
            assert script_path.exists()
            assert script_path.stat().st_size > 0
            
            # Verify it's valid Python
            try:
                ast.parse(script_content)
            except SyntaxError as e:
                pytest.fail(f"{filename} has syntax error: {e}")
