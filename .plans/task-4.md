Now I have enough context. Let me verify the `eab/cli` structure briefly and the `CaptureResult` dataclass pattern.
I now have everything needed to write the plan.

---

## Files to Modify

### 1. `eab/snapshot.py` *(create new file)*
Create this file with `SnapshotResult` (frozen dataclass) and `capture_snapshot()`.

### 2. `eab/mcp_server.py` *(modify existing file)*
- Append a new entry to `TOOL_DEFINITIONS`.
- Add a new `if name == "capture_snapshot":` branch in `_handle_tool`.

### 3. `tests/test_mcp_server.py` *(modify existing file)*
- Add a test method for `capture_snapshot` to `TestHandleTool`.
- Update `test_tool_definitions_non_empty` count (currently asserts `>= 8`; new count is 9) — or leave it since `>= 8` still holds.
- Add `"capture_snapshot"` to `test_expected_tools_present`.

---

## Approach

### `eab/snapshot.py`
Create a new module following the exact pattern of `eab/capture.py`:  
- Define a `SnapshotResult` frozen dataclass (using `@dataclass(frozen=True)` from `dataclasses`) with four fields: `path: str`, `regions: list[dict[str, Any]]`, `registers: dict[str, int]`, `size_bytes: int`.  
- Define `capture_snapshot(*, device: str, elf_path: str, output_path: str) -> SnapshotResult` as a public function with a Google-style docstring (Args/Returns/Raises sections). The function should validate that `elf_path` exists (raise `ValueError` if not) and that `device` is non-empty (raise `ValueError` if not), then perform the snapshot operation and return a populated `SnapshotResult`. Use `with` for any file resources, `os.makedirs` for the output directory (matching `capture.py` line 85).

### `eab/mcp_server.py` — `TOOL_DEFINITIONS`
Append a new dict entry to `TOOL_DEFINITIONS` (after the `eab_regression` entry, before the closing `]`). The entry should use `_schema()` with three required string properties — `device`, `elf_path`, `output_path` — and pass `required=["device", "elf_path", "output_path"]` to `_schema()`. Mirror the shape of the `eab_fault_analyze` or `eab_reset` entries (explicit `"type": "string"` per property, a plain English `description`).

### `eab/mcp_server.py` — `_handle_tool`
Add a new `if name == "capture_snapshot":` block immediately before the final `return json.dumps({"error": f"Unknown tool: {name}"})` line, following the `eab_regression` pattern for lazy importing a non-`cli` module. Specifically:
1. Use `from eab.snapshot import capture_snapshot as _capture_snapshot` inside the `if` block (lazy import, matching the `from eab.cli.regression import cmd_regression` style on line 397).
2. Call `_capture_snapshot(device=arguments["device"], elf_path=arguments["elf_path"], output_path=arguments["output_path"])` — all three are required, so use direct `[]` access not `.get()`.
3. Convert the returned `SnapshotResult` to a dict via `dataclasses.asdict()` — import `dataclasses` at the top of the `if` block or use `result.__dict__` (but prefer `dataclasses.asdict` since `CaptureResult` in `capture.py` is also a frozen dataclass and that is the idiomatic approach).
4. Return `json.dumps(result_dict)`.  
Do **not** use `_capture_cmd()` here — that wrapper is for cmd_* functions that write to stdout and return int exit codes. `capture_snapshot()` returns a typed result object.

### `tests/test_mcp_server.py`
Add `test_capture_snapshot` inside `TestHandleTool`. The test should:
1. Construct a mock `SnapshotResult`-like object (a `MagicMock` or a `SimpleNamespace` that, when passed to `dataclasses.asdict`, yields the four expected fields).
2. Patch `eab.snapshot.capture_snapshot` with a mock returning that object.
3. Call `self._run(mcp_module._handle_tool("capture_snapshot", {"device": "NRF5340_XXAA_APP", "elf_path": "/fw/app.elf", "output_path": "/tmp/snap.bin"}))`.
4. Deserialize the JSON and assert the expected keys (`path`, `regions`, `registers`, `size_bytes`) are present.
5. Assert the mock was called with the correct keyword arguments.

Also add `"capture_snapshot"` to the `expected` set in `test_expected_tools_present`.

---

## Patterns to Follow

- `eab/capture.py` — `CaptureResult` frozen dataclass: the exact shape for `SnapshotResult` (frozen, field-per-field, no default values for required fields).
- `eab/mcp_server.py` — `TOOL_DEFINITIONS` entry for `eab_reset` (lines 171–196): how to write a schema with all-required parameters and no optional params.
- `eab/mcp_server.py` — `_handle_tool` branch for `eab_regression` (lines 396–405): lazy-importing from a non-`cli` module inside the `if` block, then calling the function directly.
- `tests/test_mcp_server.py` — `test_eab_regression` (lines 257–267): how to patch a non-`eab.cli` module, call `_handle_tool`, and assert kwargs.
- `eab/mcp_server.py` — `_schema()` helper (lines 72–77): all tool schemas are built through this helper — use it for the new tool definition.

---

## Watch Out For

- **`_capture_cmd()` is not appropriate here.** It captures stdout from a `cmd_*` function returning `int`. `capture_snapshot()` returns a `SnapshotResult` object; the handler must serialize it directly with `json.dumps(dataclasses.asdict(result))`.
- **`dataclasses` is not currently imported** in `mcp_server.py`. Either add it to the top-level imports or import it locally inside the `if` block (local import matches the lazy-import convention already used in that function).
- **All three parameters (`device`, `elf_path`, `output_path`) are required** — use `arguments["key"]` (not `.get()`) in the handler, mirroring how `arguments["pattern"]` and `arguments["text"]` are accessed for `eab_wait` and `eab_send`.
- **Test count assertion**: `test_tool_definitions_non_empty` asserts `>= 8`; adding one tool makes 9, which still satisfies the condition. Do not change this test unless the task explicitly requires it.
- **`eab/snapshot.py` does not exist** — it must be created. The `capture_snapshot` function's actual implementation (what it does with the probe/device) is implied by the task but its internal logic is not specified. Implement the interface (signature, docstring, dataclass, parameter validation, `ValueError` for bad device/missing ELF) faithfully; the body that actually reads registers/regions can use stub/placeholder logic since no probe-interaction contract is specified.

---

## Uncertainty

**CANNOT_ACCESS: `eab/snapshot.py`** — This file does not exist in the repository. The task describes its interface (`capture_snapshot()` returning `SnapshotResult` with `path, regions, registers, size_bytes`) but provides no implementation. The implementer must author it from scratch. The internal logic for reading memory regions and registers from a debug probe is **UNCERTAIN: not specified** — the plan assumes a minimal viable implementation that validates inputs and returns a `SnapshotResult`; the actual probe interaction is left to the implementer's judgment.