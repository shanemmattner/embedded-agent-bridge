#!/usr/bin/env python3
"""Example GDB Python script for use with run_gdb_python().

This script demonstrates how to:
1. Access the result file path via GDB convenience variable
2. Read registers and memory
3. Write structured JSON results

Usage:
    from eab.gdb_bridge import run_gdb_python
    
    result = run_gdb_python(
        chip="nrf5340",
        script_path="examples/gdb_python_example.py",
        target="localhost:2331",
        elf="/path/to/app.elf",
    )
    
    if result.success and result.json_result:
        print("Registers:", result.json_result["registers"])
        print("Memory:", result.json_result["memory"])
"""

import gdb
import json

# Get the result file path from the GDB convenience variable
result_file = gdb.convenience_variable("result_file")

# Initialize result structure
result = {
    "status": "ok",
    "registers": {},
    "memory": {},
    "backtrace": [],
}

try:
    # Read some core registers
    for reg in ["r0", "r1", "r2", "r3", "sp", "lr", "pc"]:
        try:
            val = gdb.parse_and_eval(f"${reg}")
            result["registers"][reg] = int(val)
        except gdb.error:
            pass
    
    # Read a memory location (example: read 4 bytes from 0x20000000)
    try:
        mem_addr = 0x20000000
        inferior = gdb.selected_inferior()
        mem_bytes = inferior.read_memory(mem_addr, 4)
        result["memory"][hex(mem_addr)] = list(mem_bytes)
    except gdb.error as e:
        result["memory_error"] = str(e)
    
    # Get backtrace
    try:
        frame = gdb.newest_frame()
        while frame:
            result["backtrace"].append({
                "name": frame.name() or "??",
                "pc": int(frame.pc()) if frame.pc() else None,
            })
            frame = frame.older()
    except gdb.error:
        pass

except Exception as e:
    result["status"] = "error"
    result["error"] = str(e)

# Write the JSON result
with open(result_file, "w") as f:
    json.dump(result, f, indent=2)
