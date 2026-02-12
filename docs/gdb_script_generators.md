# GDB Python Script Generators

The `eab.gdb_bridge` module provides functions to generate GDB Python scripts for common debugging tasks. These generators follow a consistent pattern:

- Use GDB's Python API to interact with the target
- Write results to a JSON file via the `$result_file` convenience variable
- Include comprehensive error handling
- Auto-quit after execution (where appropriate)

## Quick Start

```python
from eab.gdb_bridge import (
    generate_struct_inspector,
    generate_thread_inspector,
    generate_watchpoint_logger,
    generate_memory_dump_script,
    run_gdb_python
)
from pathlib import Path

# Generate a script
script = generate_struct_inspector(
    elf_path="/path/to/zephyr.elf",
    struct_name="struct k_thread",
    var_name="_kernel"
)

# Save it to a file
script_path = Path("/tmp/inspect_kernel.py")
script_path.write_text(script)

# Execute it via GDB
result = run_gdb_python(
    chip='nrf5340',
    script_path=str(script_path),
    target='localhost:2331',
    elf='/path/to/zephyr.elf'
)

# Access the results
if result.success and result.json_result:
    print("Status:", result.json_result['status'])
    print("Fields:", result.json_result['fields'])
```

## Available Generators

### 1. `generate_struct_inspector(elf_path, struct_name, var_name)`

Generates a script that inspects a struct variable and outputs its fields as JSON.

**Parameters:**
- `elf_path` (str): Path to ELF file with debug symbols
- `struct_name` (str): Name of the struct type (e.g., "struct kernel")
- `var_name` (str): Name of the global variable to inspect (e.g., "_kernel")

**Returns:** String containing the GDB Python script

**JSON Output Structure:**
```json
{
  "status": "ok",
  "struct_name": "struct kernel",
  "var_name": "_kernel",
  "fields": {
    "field1": 42,
    "field2": 0x20000100,
    "field3": "value"
  }
}
```

**Example:**
```python
script = generate_struct_inspector(
    "/path/to/app.elf",
    "struct task_struct",
    "current_task"
)
```

### 2. `generate_thread_inspector(rtos='zephyr')`

Generates a script that walks the RTOS thread list and extracts thread state.

**Parameters:**
- `rtos` (str, optional): RTOS type (default: 'zephyr', only supported value)

**Returns:** String containing the GDB Python script

**JSON Output Structure:**
```json
{
  "status": "ok",
  "rtos": "zephyr",
  "threads": [
    {
      "address": 536870912,
      "node_ptr": "0x20000000"
    }
  ],
  "thread_count": 1
}
```

**Example:**
```python
script = generate_thread_inspector(rtos='zephyr')
```

**Notes:**
- Currently only supports Zephyr RTOS
- Includes safety limit (max 100 threads) to prevent infinite loops
- Walks `_kernel.threads` linked list

### 3. `generate_watchpoint_logger(var_name, max_hits=100)`

Generates a script that sets a watchpoint and logs each hit with backtrace.

**Parameters:**
- `var_name` (str): Name of the variable to watch
- `max_hits` (int, optional): Maximum hits to log before stopping (default: 100)

**Returns:** String containing the GDB Python script

**JSON Output Structure:**
```json
{
  "status": "ok",
  "var_name": "g_counter",
  "max_hits": 100,
  "hits": [
    {
      "hit_number": 1,
      "value": 42,
      "backtrace": [
        {
          "frame": 0,
          "name": "increment_counter",
          "pc": "0x080001234"
        }
      ]
    }
  ],
  "hit_count": 1
}
```

**Example:**
```python
script = generate_watchpoint_logger("g_counter", max_hits=50)
```

**Notes:**
- Uses `gdb.Command` class pattern
- Automatically quits after logging hits
- Limits backtrace depth to 20 frames per hit
- Handles process exit gracefully

### 4. `generate_memory_dump_script(start_addr, size, output_path)`

Generates a script that dumps a memory region to a binary file.

**Parameters:**
- `start_addr` (int): Starting memory address (as integer)
- `size` (int): Number of bytes to dump
- `output_path` (str): Path where the memory dump should be written

**Returns:** String containing the GDB Python script

**JSON Output Structure:**
```json
{
  "status": "ok",
  "start_addr": "0x20000000",
  "size": 4096,
  "output_path": "/tmp/memdump.bin",
  "bytes_written": 4096
}
```

**Example:**
```python
script = generate_memory_dump_script(
    start_addr=0x20000000,
    size=4096,
    output_path="/tmp/ram_dump.bin"
)
```

**Notes:**
- Writes raw binary data to the output file
- Reports number of bytes written in JSON result
- Handles both GDB errors and IO errors

## Complete Workflow Example

```python
from eab.gdb_bridge import (
    generate_watchpoint_logger,
    run_gdb_python
)
from pathlib import Path
import json

# Step 1: Generate the script
script = generate_watchpoint_logger("g_debug_counter", max_hits=10)

# Step 2: Save to temporary file
script_path = Path("/tmp/watch_debug.py")
script_path.write_text(script)

# Step 3: Execute via GDB (assumes target is already running and GDB server is available)
try:
    result = run_gdb_python(
        chip='nrf5340',
        script_path=str(script_path),
        target='localhost:2331',
        elf='/path/to/zephyr.elf',
        timeout_s=120.0  # Allow time for watchpoint hits
    )
    
    # Step 4: Process results
    if result.success:
        if result.json_result:
            data = result.json_result
            print(f"Status: {data['status']}")
            print(f"Captured {data['hit_count']} hits")
            
            for hit in data['hits']:
                print(f"\nHit #{hit['hit_number']}: value={hit['value']}")
                print("Backtrace:")
                for frame in hit['backtrace'][:5]:  # Show top 5 frames
                    print(f"  {frame['frame']}: {frame['name']} @ {frame['pc']}")
        else:
            print("Script executed but produced no JSON output")
            print("GDB stdout:", result.stdout)
    else:
        print(f"Script failed with return code {result.returncode}")
        print("stderr:", result.stderr)
        
except Exception as e:
    print(f"Error: {e}")
    
finally:
    # Cleanup
    script_path.unlink(missing_ok=True)
```

## Error Handling

All generated scripts include comprehensive error handling:

```python
{
  "status": "error",
  "error": "No symbol '_kernel' in current context"
}
```

Common error scenarios:
- Variable not found (GDB symbol lookup fails)
- Type mismatch (variable is not the expected type)
- Memory access errors (invalid address)
- IO errors (cannot write output file)
- Timeout (execution exceeds timeout_s)

## Best Practices

1. **Always use temporary files for generated scripts:**
   ```python
   from tempfile import NamedTemporaryFile
   with NamedTemporaryFile(mode='w', suffix='.py', delete=False) as f:
       f.write(script)
       script_path = f.name
   ```

2. **Set appropriate timeouts:**
   - Struct inspection: 10-30 seconds
   - Thread inspection: 10-30 seconds
   - Watchpoint logging: 60-300 seconds (depends on hit frequency)
   - Memory dumps: 10-60 seconds (depends on size)

3. **Check result.success before accessing result.json_result:**
   ```python
   if result.success and result.json_result:
       # Safe to access JSON data
       data = result.json_result
   ```

4. **Always clean up temporary files:**
   ```python
   try:
       result = run_gdb_python(...)
   finally:
       Path(script_path).unlink(missing_ok=True)
   ```

5. **For watchpoints, ensure the variable is actually modified:**
   - The target must be running (not halted)
   - The variable must be in scope and accessible
   - Set a reasonable max_hits to avoid long waits

## Integration with EAB Workflow

These generators integrate seamlessly with EAB's debug probe abstractions:

```python
from eab.debug_probes.jlink import JLinkProbe
from eab.gdb_bridge import generate_struct_inspector, run_gdb_python
from pathlib import Path

# Start GDB server via probe
probe = JLinkProbe()
gdb_status = probe.start_gdb_server(device="NRF5340_XXAA_APP", port=2331)

if gdb_status.running:
    try:
        # Generate and execute inspection script
        script = generate_struct_inspector(
            "/path/to/zephyr.elf",
            "struct k_thread",
            "_kernel"
        )
        script_path = Path("/tmp/inspect.py")
        script_path.write_text(script)
        
        result = run_gdb_python(
            chip='nrf5340',
            script_path=str(script_path),
            target=f'localhost:{probe.gdb_port}',
            elf='/path/to/zephyr.elf'
        )
        
        # Process results...
        
    finally:
        probe.stop_gdb_server()
        script_path.unlink(missing_ok=True)
```

## Limitations

- `generate_struct_inspector`: Does not currently parse DWARF info from ELF files directly; relies on GDB's type introspection
- `generate_thread_inspector`: Only supports Zephyr RTOS (FreeRTOS, Azure RTOS not yet implemented)
- `generate_watchpoint_logger`: Requires target to be running; cannot log watchpoint hits on halted targets
- All generators assume ARM/RISC-V architecture GDB features

## Future Enhancements

Planned improvements:
- [ ] Parse DWARF info directly for struct layouts
- [ ] Support for FreeRTOS thread inspection
- [ ] Conditional breakpoint logger (like watchpoints but for breakpoints)
- [ ] Register dump script generator
- [ ] Call stack analyzer with local variable inspection
