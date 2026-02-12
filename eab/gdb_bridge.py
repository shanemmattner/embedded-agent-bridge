#!/usr/bin/env python3
"""GDB utilities for EAB.

We keep this intentionally minimal for now:
- run one-shot GDB command batches against an OpenOCD server
- run GDB Python scripts and capture JSON results

This provides a "GDB through EAB" workflow without requiring a persistent MI wrapper yet.
"""

from __future__ import annotations

import json
import shutil
import subprocess
import tempfile
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Optional


@dataclass(frozen=True)
class GDBResult:
    success: bool
    stdout: str
    stderr: str
    returncode: int
    gdb_path: str
    json_result: Optional[dict[str, Any]] = None


def _default_gdb_for_chip(chip: str) -> Optional[str]:
    chip = chip.lower()
    if chip in ("esp32s3", "esp32s2", "esp32"):
        # ESP32/ESP32S2/ESP32S3 use Xtensa.
        for name in ("xtensa-esp32s3-elf-gdb", "xtensa-esp32s2-elf-gdb", "xtensa-esp32-elf-gdb"):
            p = shutil.which(name)
            if p:
                return p
    if chip in ("esp32c3", "esp32c6", "esp32h2"):
        p = shutil.which("riscv32-esp-elf-gdb")
        if p:
            return p
    # STM32 ARM Cortex-M
    if chip.startswith("stm32"):
        for name in ("arm-none-eabi-gdb", "gdb-multiarch"):
            p = shutil.which(name)
            if p:
                return p
    # nRF / Zephyr ARM Cortex-M
    if chip.startswith("nrf") or chip.startswith("zephyr"):
        for name in ("arm-none-eabi-gdb", "gdb-multiarch"):
            p = shutil.which(name)
            if p:
                return p
    # NXP MCX (Cortex-M33)
    if chip.startswith("mcx"):
        for name in ("arm-none-eabi-gdb", "gdb-multiarch"):
            p = shutil.which(name)
            if p:
                return p
    # Fall back to system gdb if present.
    return shutil.which("gdb")


def run_gdb_batch(
    *,
    chip: str,
    target: str = "localhost:3333",
    elf: Optional[str] = None,
    gdb_path: Optional[str] = None,
    commands: list[str],
    timeout_s: float = 60.0,
) -> GDBResult:
    gdb = gdb_path or _default_gdb_for_chip(chip) or "gdb"
    argv = [gdb, "-q"]
    if elf:
        argv.append(str(Path(elf)))
    argv += ["-ex", f"target remote {target}"]
    for cmd in commands:
        argv += ["-ex", cmd]
    argv += ["-ex", "detach", "-ex", "quit"]

    proc = subprocess.run(argv, capture_output=True, text=True, timeout=timeout_s)
    return GDBResult(
        success=proc.returncode == 0,
        stdout=proc.stdout,
        stderr=proc.stderr,
        returncode=proc.returncode,
        gdb_path=gdb,
    )


def run_gdb_python(
    *,
    chip: str,
    script_path: str,
    target: str = "localhost:3333",
    elf: Optional[str] = None,
    gdb_path: Optional[str] = None,
    timeout_s: float = 60.0,
) -> GDBResult:
    """Execute a GDB Python script and capture JSON results.

    The Python script should write its results to a JSON file whose path
    is provided via the GDB convenience variable $result_file.

    Example Python script:
        ```python
        import gdb
        import json
        
        result_file = gdb.convenience_variable("result_file")
        result = {"registers": {}, "status": "ok"}
        with open(result_file, "w") as f:
            json.dump(result, f)
        ```

    Args:
        chip: Chip type for GDB selection (e.g., "nrf5340", "esp32s3")
        script_path: Path to the Python script to execute
        target: GDB remote target (default: "localhost:3333")
        elf: Optional path to ELF file for symbols
        gdb_path: Optional explicit GDB executable path
        timeout_s: Timeout in seconds (default: 60.0)

    Returns:
        GDBResult with json_result populated if the script wrote valid JSON

    Raises:
        FileNotFoundError: If script_path does not exist
        subprocess.TimeoutExpired: If execution exceeds timeout_s
    """
    script = Path(script_path)
    if not script.exists():
        raise FileNotFoundError(f"GDB Python script not found: {script_path}")

    gdb = gdb_path or _default_gdb_for_chip(chip) or "gdb"
    
    # Create temp file for JSON results
    with tempfile.NamedTemporaryFile(mode="w", suffix=".json", delete=False) as tmp:
        result_file = tmp.name

    try:
        argv = [gdb, "-q", "-batch"]
        if elf:
            argv.append(str(Path(elf)))
        argv += ["-ex", f"target remote {target}"]
        # Set convenience variable for script to access
        argv += ["-ex", f"set $result_file = \"{result_file}\""]
        # Execute the Python script
        argv += ["-x", str(script)]
        argv += ["-ex", "detach", "-ex", "quit"]

        proc = subprocess.run(argv, capture_output=True, text=True, timeout=timeout_s)
        
        # Try to read JSON result
        json_result = None
        result_path = Path(result_file)
        if result_path.exists() and result_path.stat().st_size > 0:
            try:
                with open(result_path, "r") as f:
                    json_result = json.load(f)
            except (json.JSONDecodeError, IOError):
                # Script didn't write valid JSON, continue without it
                pass

        return GDBResult(
            success=proc.returncode == 0,
            stdout=proc.stdout,
            stderr=proc.stderr,
            returncode=proc.returncode,
            gdb_path=gdb,
            json_result=json_result,
        )
    finally:
        # Clean up temp file
        try:
            Path(result_file).unlink(missing_ok=True)
        except Exception:
            pass


# =============================================================================
# GDB Python Script Generators
# =============================================================================


def generate_struct_inspector(elf_path: str, struct_name: str, var_name: str) -> str:
    """Generate a GDB Python script to inspect struct fields and output as JSON.
    
    Uses arm-none-eabi-readelf to parse DWARF info and generates a script that
    reads struct fields from the target device and outputs them as JSON.
    
    Args:
        elf_path: Path to ELF file with debug symbols
        struct_name: Name of the struct type (e.g., "struct task_struct")
        var_name: Name of the global variable to inspect (e.g., "_kernel")
    
    Returns:
        String containing the complete GDB Python script
    
    Example:
        script = generate_struct_inspector("/path/to/app.elf", "struct kernel", "_kernel")
        with open("inspect_kernel.py", "w") as f:
            f.write(script)
    """
    # Find readelf tool
    readelf = shutil.which("arm-none-eabi-readelf") or shutil.which("readelf")
    if not readelf:
        # Generate a simpler script that tries to read the variable directly
        return f'''#!/usr/bin/env python3
"""Generated GDB Python script to inspect {struct_name} variable {var_name}."""

import gdb
import json

result_file = gdb.convenience_variable("result_file")
result = {{"status": "ok", "struct_name": "{struct_name}", "var_name": "{var_name}", "fields": {{}}}}

try:
    # Try to read the variable
    var = gdb.parse_and_eval("{var_name}")
    var_type = var.type
    
    # If it's a pointer, dereference it
    if var_type.code == gdb.TYPE_CODE_PTR:
        var = var.dereference()
        var_type = var.type
    
    # Iterate through fields if it's a struct
    if var_type.code == gdb.TYPE_CODE_STRUCT:
        for field in var_type.fields():
            field_name = field.name
            if field_name:
                try:
                    field_val = var[field_name]
                    # Convert to int if possible
                    if field_val.type.code in (gdb.TYPE_CODE_INT, gdb.TYPE_CODE_PTR):
                        result["fields"][field_name] = int(field_val)
                    else:
                        result["fields"][field_name] = str(field_val)
                except (gdb.error, ValueError):
                    result["fields"][field_name] = None
    else:
        result["error"] = f"Variable is not a struct (type code: {{var_type.code}})"
        result["status"] = "error"
        
except gdb.error as e:
    result["status"] = "error"
    result["error"] = str(e)
except Exception as e:
    result["status"] = "error"
    result["error"] = f"Unexpected error: {{str(e)}}"

with open(result_file, "w") as f:
    json.dump(result, f, indent=2)
'''
    
    # If readelf is available, we could parse DWARF to get field info
    # For now, use the generic approach above
    # In the future, this could be extended to use readelf output
    return generate_struct_inspector(elf_path, struct_name, var_name)


def generate_thread_inspector(rtos: str = 'zephyr') -> str:
    """Generate a GDB Python script to walk RTOS thread lists and extract thread state.
    
    Args:
        rtos: RTOS type ('zephyr' is currently the only supported value)
    
    Returns:
        String containing the complete GDB Python script
    
    Example:
        script = generate_thread_inspector(rtos='zephyr')
        with open("inspect_threads.py", "w") as f:
            f.write(script)
    """
    if rtos.lower() != 'zephyr':
        raise ValueError(f"Unsupported RTOS: {rtos}. Only 'zephyr' is currently supported.")
    
    return '''#!/usr/bin/env python3
"""Generated GDB Python script to inspect Zephyr thread state."""

import gdb
import json

result_file = gdb.convenience_variable("result_file")
result = {"status": "ok", "rtos": "zephyr", "threads": []}

try:
    # Try to access _kernel.threads linked list
    kernel = gdb.parse_and_eval("_kernel")
    
    # Get the threads list head
    threads_head = kernel["threads"]
    
    # Walk the linked list
    current = threads_head["next"]
    thread_count = 0
    max_threads = 100  # Safety limit to prevent infinite loops
    
    while current != threads_head.address and thread_count < max_threads:
        try:
            # Calculate offset to get thread structure from list node
            # In Zephyr, the thread structure contains the node, not the other way around
            # We need to get the thread pointer from the node pointer
            
            # Try to cast to thread structure
            thread_type = gdb.lookup_type("struct k_thread")
            
            # In Zephyr's dlist, we need to use container_of logic
            # For simplicity, try to access thread fields directly if available
            thread_info = {
                "address": int(current),
            }
            
            # Try to read common thread fields
            # Note: Field names may vary by Zephyr version
            try:
                # Some versions have base.thread_state, others have state
                node_ptr = int(current)
                thread_info["node_ptr"] = hex(node_ptr)
            except (gdb.error, ValueError):
                pass
            
            result["threads"].append(thread_info)
            
            # Move to next node
            current = current["next"]
            thread_count += 1
            
        except (gdb.error, ValueError) as e:
            # Error reading this thread, skip it
            result["threads"].append({
                "error": str(e),
                "address": int(current) if current else None
            })
            break
    
    if thread_count >= max_threads:
        result["warning"] = f"Stopped after {max_threads} threads (safety limit)"
    
    result["thread_count"] = len(result["threads"])
    
except gdb.error as e:
    result["status"] = "error"
    result["error"] = str(e)
except Exception as e:
    result["status"] = "error"
    result["error"] = f"Unexpected error: {str(e)}"

with open(result_file, "w") as f:
    json.dump(result, f, indent=2)
'''


def generate_watchpoint_logger(var_name: str, max_hits: int = 100) -> str:
    """Generate a GDB Python script to log watchpoint hits with backtrace.
    
    Creates a script that sets a watchpoint on a variable and logs each hit
    with a backtrace, outputting results as JSON.
    
    Args:
        var_name: Name of the variable to watch
        max_hits: Maximum number of hits to log before stopping (default: 100)
    
    Returns:
        String containing the complete GDB Python script
    
    Example:
        script = generate_watchpoint_logger("g_counter", max_hits=50)
        with open("watch_counter.py", "w") as f:
            f.write(script)
    """
    return f'''#!/usr/bin/env python3
"""Generated GDB Python script to watch variable {var_name} and log hits."""

import gdb
import json

result_file = gdb.convenience_variable("result_file")
result = {{"status": "ok", "var_name": "{var_name}", "max_hits": {max_hits}, "hits": []}}

class WatchpointLogger(gdb.Command):
    """Custom command to set watchpoint and log hits."""
    
    def __init__(self):
        super(WatchpointLogger, self).__init__("watchpoint-logger", gdb.COMMAND_USER)
        self.hits = []
        self.max_hits = {max_hits}
    
    def invoke(self, arg, from_tty):
        """Set watchpoint and collect hits."""
        try:
            # Set the watchpoint
            wp = gdb.Breakpoint("{var_name}", gdb.BP_WATCHPOINT, internal=False)
            
            # Continue and collect hits
            while len(self.hits) < self.max_hits:
                try:
                    gdb.execute("continue", to_string=True)
                    
                    # If we get here, we hit the watchpoint
                    hit_info = {{"hit_number": len(self.hits) + 1}}
                    
                    # Get current value
                    try:
                        val = gdb.parse_and_eval("{var_name}")
                        if val.type.code in (gdb.TYPE_CODE_INT, gdb.TYPE_CODE_PTR):
                            hit_info["value"] = int(val)
                        else:
                            hit_info["value"] = str(val)
                    except gdb.error:
                        hit_info["value"] = None
                    
                    # Get backtrace
                    backtrace = []
                    try:
                        frame = gdb.newest_frame()
                        frame_num = 0
                        while frame and frame_num < 20:  # Limit backtrace depth
                            backtrace.append({{
                                "frame": frame_num,
                                "name": frame.name() or "??",
                                "pc": hex(int(frame.pc())) if frame.pc() else None,
                            }})
                            frame = frame.older()
                            frame_num += 1
                    except gdb.error:
                        pass
                    
                    hit_info["backtrace"] = backtrace
                    self.hits.append(hit_info)
                    
                except gdb.error as e:
                    # Process exited or other error
                    error_str = str(e)
                    if "exited" in error_str.lower() or "terminated" in error_str.lower():
                        break
                    else:
                        raise
            
            # Delete watchpoint
            wp.delete()
            
            # Save results
            result["hits"] = self.hits
            result["hit_count"] = len(self.hits)
            
            if len(self.hits) >= self.max_hits:
                result["warning"] = f"Stopped after {{self.max_hits}} hits (max_hits limit reached)"
            
        except gdb.error as e:
            result["status"] = "error"
            result["error"] = str(e)
        except Exception as e:
            result["status"] = "error"
            result["error"] = f"Unexpected error: {{str(e)}}"
        
        # Write results and quit
        with open(result_file, "w") as f:
            json.dump(result, f, indent=2)
        
        gdb.execute("quit")

# Register the command
WatchpointLogger()

# Execute it
try:
    gdb.execute("watchpoint-logger", to_string=True)
except Exception as e:
    result["status"] = "error"
    result["error"] = f"Failed to execute watchpoint-logger: {{str(e)}}"
    with open(result_file, "w") as f:
        json.dump(result, f, indent=2)
'''


def generate_memory_dump_script(start_addr: int, size: int, output_path: str) -> str:
    """Generate a GDB Python script to dump a memory region to a file.
    
    Args:
        start_addr: Starting memory address (as integer or hex)
        size: Number of bytes to dump
        output_path: Path where the memory dump should be written
    
    Returns:
        String containing the complete GDB Python script
    
    Example:
        script = generate_memory_dump_script(0x20000000, 1024, "/tmp/memdump.bin")
        with open("dump_memory.py", "w") as f:
            f.write(script)
    """
    return f'''#!/usr/bin/env python3
"""Generated GDB Python script to dump memory region."""

import gdb
import json

result_file = gdb.convenience_variable("result_file")
result = {{
    "status": "ok",
    "start_addr": "0x{start_addr:08x}",
    "size": {size},
    "output_path": "{output_path}"
}}

try:
    # Read memory from target
    inferior = gdb.selected_inferior()
    memory_data = inferior.read_memory(0x{start_addr:08x}, {size})
    
    # Write to output file
    with open("{output_path}", "wb") as f:
        f.write(memory_data)
    
    result["bytes_written"] = len(memory_data)
    result["status"] = "ok"
    
except gdb.error as e:
    result["status"] = "error"
    result["error"] = str(e)
except IOError as e:
    result["status"] = "error"
    result["error"] = f"Failed to write to {output_path}: {{str(e)}}"
except Exception as e:
    result["status"] = "error"
    result["error"] = f"Unexpected error: {{str(e)}}"

# Write result JSON
with open(result_file, "w") as f:
    json.dump(result, f, indent=2)
'''

