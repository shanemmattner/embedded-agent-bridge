I'll read the relevant files to understand the patterns before writing the plan.
`thread_inspector.py` does not exist. Let me check for any references to it and look at similar existing patterns (like `fault_analyzer.py`) and the inspection_cmds for context.
Now I have enough context. Let me write the plan.

---

## Files to Modify

### 1. `eab/thread_inspector.py` *(new file — create)*
Add a `ThreadInfo` dataclass with a `to_dict()` method, and an `inspect_threads(device, elf_path)` function that returns `list[ThreadInfo]`.

### 2. `eab/mcp_server.py` *(modify)*
- Add a `get_thread_state` entry to `TOOL_DEFINITIONS`.
- Add a `get_thread_state` branch to `_handle_tool`.

---

## Approach

### `eab/thread_inspector.py` (new file)

Create this file in `eab/`. Define `ThreadInfo` as a frozen dataclass (following the `FaultReport` pattern in `eab/fault_decoders/base.py`) with fields that correspond directly to the keys the `generate_thread_inspector` GDB script places in each thread dict: `address: int`, `node_ptr: Optional[str]`, and `error: Optional[str]`. Add a `to_dict()` method that returns a plain `dict[str, Any]` by converting `dataclasses.asdict(self)`.

Implement `inspect_threads(device: str, elf_path: str) -> list[ThreadInfo]` below the class. This function mirrors the structure of `cmd_threads` in `eab/cli/debug/inspection_cmds.py`: build a `JLinkProbe`, call `probe.start_gdb_server(device=device)`, then write `generate_thread_inspector(rtos='zephyr')` to a `NamedTemporaryFile`, call `run_gdb_python(chip=..., script_path=..., elf=elf_path)`, clean up the temp file in a `finally` block, and stop the probe's GDB server in an outer `finally`. Derive `chip` from the device string using the same split-on-underscore approach shown in `_load_rtt_context` in `fault_analyzer.py` (e.g., `"NRF5340_XXAA_APP".split("_")[0].lower()` → `"nrf5340"`). Parse `res.json_result["threads"]` into `ThreadInfo` objects; if `json_result` is absent, raise `RuntimeError` with the GDB stderr. The imports needed are: `dataclasses`, `pathlib.Path`, `tempfile`, `typing`, `eab.gdb_bridge.run_gdb_python`, `eab.gdb_bridge.generate_thread_inspector`, and `eab.debug_probes.JLinkProbe`.

### `eab/mcp_server.py` (modify)

**In `TOOL_DEFINITIONS`:** Append a new dict entry after the `eab_regression` entry (the last entry in the list, ending at line 277). The entry should have `name = "get_thread_state"`, a clear description, and `inputSchema` built via `_schema({...}, required=["device", "elf_path"])`. The `device` property schema is already established as a precedent in `eab_reset` and `eab_fault_analyze` (J-Link device string). Add an `elf_path` string property with a description matching what similar `elf` params say in `eab_fault_analyze`.

**In `_handle_tool`:** Add a new `if name == "get_thread_state":` branch after the `eab_regression` branch (before the final `return json.dumps({"error": ...})` fallback). Use a lazy import (`from eab.thread_inspector import inspect_threads`) mirroring the `eab_regression` import pattern (line 397). Call `inspect_threads(arguments["device"], arguments["elf_path"])` and return `json.dumps({"threads": [t.to_dict() for t in threads]})`. The parameters are both `required`, so use `arguments["device"]` and `arguments["elf_path"]` (not `.get()`), consistent with how `arguments["pattern"]` and `arguments["text"]` are accessed in `eab_wait` and `eab_send`.

---

## Patterns to Follow

| Pattern | File | What it demonstrates |
|---|---|---|
| `FaultReport` dataclass + shape | `eab/fault_decoders/base.py` | `@dataclass` with optional fields, for `ThreadInfo` |
| `cmd_threads` | `eab/cli/debug/inspection_cmds.py` | Full probe start/stop + GDB script lifecycle, for `inspect_threads` |
| `eab_regression` handler | `eab/mcp_server.py` lines 397–405 | Lazy import inside `_handle_tool`, the model to follow |
| `eab_send` / `eab_wait` required-param access | `eab/mcp_server.py` lines 356–364 | `arguments["key"]` (no `.get()`) for required fields |
| `_schema({...}, required=[...])` | `eab/mcp_server.py` lines 72–77 | How to declare required input params in a tool definition |

---

## Watch Out For

- **`to_dict()` vs `dataclasses.asdict()`**: Use `dataclasses.asdict(self)` inside `to_dict()` as the simplest correct implementation; do not hand-roll key iteration.
- **`chip` derivation**: The `device` parameter (e.g., `"NRF5340_XXAA_APP"`) must be lowercased and split to get a chip string that `run_gdb_python` / `_default_gdb_for_chip` understand. Use the exact pattern from `_load_rtt_context` in `fault_analyzer.py` (`device.lower().split("_")[0]`).
- **Do not modify `test_mcp_server.py` `test_tool_definitions_non_empty`**: The threshold is `>= 8`; adding one more tool to 9 still passes. Similarly `test_expected_tools_present` checks a fixed subset — adding a new tool does not break it.
- **The existing tools use `_capture_cmd`**: `get_thread_state` must NOT use `_capture_cmd` because `inspect_threads` is not a `cmd_*` function that writes to stdout. The handler returns `json.dumps(...)` directly, as is already legal in `_handle_tool`.
- **temp file cleanup**: The `NamedTemporaryFile` for the GDB script must be cleaned up in a `finally` block (using `Path(...).unlink(missing_ok=True)`), exactly as `cmd_threads` does — not relying on the `delete=True` default, which conflicts with Windows and open-file semantics on some platforms.

---

## Uncertainty

**UNCERTAIN**: The `inspect_threads` function requires a running GDB server and a physical debug probe. The task description does not specify how to handle the case where `elf_path` is empty/missing or the probe is unavailable. The `cmd_threads` function in `inspection_cmds.py` returns exit code 1 and prints a message; `inspect_threads` should raise a `RuntimeError` instead (since it is not a CLI cmd_* function), consistent with the calling convention implied by the MCP handler's exception-catching logic in `call_tool` (line 444).