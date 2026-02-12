#!/usr/bin/env python3
"""Demonstration of GDB Python script generators.

This example shows how to use the generator functions in eab.gdb_bridge
to create GDB Python scripts for various debugging tasks.
"""

from pathlib import Path
from eab.gdb_bridge import (
    generate_struct_inspector,
    generate_thread_inspector,
    generate_watchpoint_logger,
    generate_memory_dump_script,
)


def main():
    """Generate example GDB Python scripts."""
    
    # Create output directory
    output_dir = Path("/tmp/gdb_scripts_demo")
    output_dir.mkdir(exist_ok=True)
    
    print(f"Generating example GDB Python scripts in {output_dir}/\n")
    
    # 1. Struct Inspector
    print("1. Generating struct inspector script...")
    struct_script = generate_struct_inspector(
        elf_path="/path/to/zephyr.elf",
        struct_name="struct k_thread",
        var_name="_kernel"
    )
    struct_path = output_dir / "inspect_kernel_struct.py"
    struct_path.write_text(struct_script)
    print(f"   Created: {struct_path}")
    print(f"   Purpose: Inspects the _kernel struct fields and outputs as JSON\n")
    
    # 2. Thread Inspector
    print("2. Generating thread inspector script...")
    thread_script = generate_thread_inspector(rtos='zephyr')
    thread_path = output_dir / "inspect_threads.py"
    thread_path.write_text(thread_script)
    print(f"   Created: {thread_path}")
    print(f"   Purpose: Walks _kernel.threads linked list and extracts thread state\n")
    
    # 3. Watchpoint Logger
    print("3. Generating watchpoint logger script...")
    watchpoint_script = generate_watchpoint_logger(
        var_name="g_counter",
        max_hits=50
    )
    watchpoint_path = output_dir / "watch_counter.py"
    watchpoint_path.write_text(watchpoint_script)
    print(f"   Created: {watchpoint_path}")
    print(f"   Purpose: Logs up to 50 hits on g_counter with backtrace\n")
    
    # 4. Memory Dump Script
    print("4. Generating memory dump script...")
    memdump_script = generate_memory_dump_script(
        start_addr=0x20000000,
        size=4096,
        output_path="/tmp/memory_dump.bin"
    )
    memdump_path = output_dir / "dump_memory.py"
    memdump_path.write_text(memdump_script)
    print(f"   Created: {memdump_path}")
    print(f"   Purpose: Dumps 4KB from 0x20000000 to /tmp/memory_dump.bin\n")
    
    print("All scripts generated successfully!")
    print("\nUsage example:")
    print("  from eab.gdb_bridge import run_gdb_python")
    print("  result = run_gdb_python(")
    print("      chip='nrf5340',")
    print(f"      script_path='{struct_path}',")
    print("      target='localhost:2331',")
    print("      elf='/path/to/zephyr.elf'")
    print("  )")
    print("  if result.success and result.json_result:")
    print("      print('Struct fields:', result.json_result['fields'])")


if __name__ == "__main__":
    main()
