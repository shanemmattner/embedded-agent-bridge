I'll read the relevant files concurrently to understand the patterns before writing the plan.
Now let me look at existing tests and other relevant files:
Now let me check the tests directory for existing patterns relevant to thread inspector:
I now have all the context needed. Here is the implementation plan.

---

## Files to Modify

### New file: `eab/thread_inspector.py`
Create from scratch. Contains `ThreadInfo` dataclass, `_generate_thread_script()` private helper, and `inspect_threads()` public function.

### New file: `eab/tests/test_thread_inspector.py`
Create from scratch. Unit tests for `ThreadInfo` construction/serialization, the script generator, and `inspect_threads()` with mocked GDB bridge.

---

## Approach

### `eab/thread_inspector.py`

**Module layout** — mirror the structural pattern of `eab/elf_inspect.py`: module-level docstring, `from __future__ import annotations`, grouped imports (stdlib → external → internal), `logger = logging.getLogger(__name__)`, then sections delimited by `# ===` comment banners: constants, dataclass, script generator, public API.

**`ThreadInfo` dataclass** — decorate with `@dataclass(frozen=True)` following `ProfileResult` in `dwt_profiler.py` and `ElfSymbol` in `elf_inspect.py`. Fields: `name: str`, `state: str`, `priority: int`, `stack_base: int`, `stack_size: int`, `stack_used: int`, `stack_free: int`. Add a `to_dict()` method that returns a plain `dict[str, Any]` mapping each field name to its value (no special serialization needed; all fields are JSON-native types).

**Zephyr state constants** — define a module-level dict mapping Zephyr's `thread_state` integer bit patterns to the four required labels (`RUNNING`, `READY`, `PENDING`, `SUSPENDED`). Zephyr uses bitmask flags; the mapping function checks bits in priority order: running bit first, then pending, then suspended, falling back to `READY` when no special bits are set. Place this dict and a `_map_thread_state(raw: int) -> str` helper immediately before the script generator, following the pattern of private helpers like `_infer_section()` in `elf_inspect.py`.

**`_generate_thread_script() -> str`** — private function returning a complete GDB Python script string. The script follows the exact `$result_file` pattern used in every generator in `gdb_bridge.py` (i.e. `generate_struct_inspector`, `generate_thread_inspector`, `generate_memory_dump_script`): reads result path via `gdb.convenience_variable("result_file")`, wraps all GDB access in `try/except gdb.error`, and closes by writing `json.dump(result, f)` to the result file. The script body uses `gdb.parse_and_eval("_kernel")` to get the kernel struct, accesses the `threads` dlist head, then walks `next` pointers. For each node it casts to `struct k_thread` using `gdb.lookup_type` and an address-based cast (mirroring the approach in `generate_thread_inspector()` in `gdb_bridge.py`). It reads `t["name"]` (interpreted as a C string via `str()`), `int(t["base"]["thread_state"])`, `int(t["base"]["prio"])`, `int(t["stack_info"]["start"])`, `int(t["stack_info"]["size"])`, and `int(t["stack_info"]["delta"])`, then appends a dict per thread to `result["threads"]`. Includes a safety limit of 100 iterations. The outer GDB error is caught as `gdb.error`, not bare `Exception` (matching existing patterns).

**`inspect_threads(device: str, elf_path: str) -> list[ThreadInfo]`** — public function with Google-style docstring. Steps: (1) call `_generate_thread_script()` to get the script string; (2) write it to a `NamedTemporaryFile` with `.py` suffix (use `with` block to ensure cleanup, following the resource handling in `run_gdb_python` in `gdb_bridge.py`); (3) call `run_gdb_python(chip="", script_path=tmp.name, target=device, elf=elf_path)` — `chip=""` falls back to `shutil.which("gdb")` inside the bridge; (4) check `result.json_result` — if `None` or `result.json_result.get("status") == "error"`, raise `RuntimeError` with the embedded error message; (5) iterate `result.json_result["threads"]` and for each dict construct a `ThreadInfo`, calling `_map_thread_state()` on the raw `thread_state` int and computing `stack_free = stack_size - stack_used` (where `stack_used` is `delta`). Return the list.

Imports needed: `json`, `logging`, `tempfile` from stdlib; `dataclass` from `dataclasses`; `Path` from `pathlib`; `Any` from `typing`; `run_gdb_python` from `eab.gdb_bridge`.

### `eab/tests/test_thread_inspector.py`

Mirror the structure of `eab/tests/test_elf_inspect.py`: `from __future__ import annotations`, grouped imports, test classes named `TestThreadInfo`, `TestGenerateThreadScript`, `TestInspectThreads`. Use `unittest.mock.patch` to mock `eab.thread_inspector.run_gdb_python` in `TestInspectThreads`, returning a `GDBResult`-like mock with a `json_result` dict containing a sample `threads` list. Verify that `inspect_threads` returns the correct number of `ThreadInfo` objects with expected field values. Test `to_dict()` returns a plain dict with all expected keys. Test that a `json_result` with `status == "error"` raises `RuntimeError`.

---

## Patterns to Follow

- **`eab/elf_inspect.py` — `ElfSymbol` dataclass** — frozen dataclass with plain fields; model `ThreadInfo` and its `to_dict()` on this structure.
- **`eab/gdb_bridge.py` — `generate_struct_inspector()`** — the exact `$result_file` / `gdb.convenience_variable` / `json.dump` script template to reproduce in `_generate_thread_script()`.
- **`eab/gdb_bridge.py` — `run_gdb_python()`** — API to call: `chip`, `script_path`, `target`, `elf` parameters; reads back `json_result` from temp file.
- **`eab/dwt_profiler.py` — `profile_function()`** — Google-style docstring with Args/Returns/Raises, logger usage, `ValueError` for missing data; model the error-handling structure in `inspect_threads()`.
- **`eab/tests/test_elf_inspect.py`** — test class layout, `@dataclass(frozen=True)` immutability test via `pytest.raises(AttributeError)`, mocking subprocess patterns.

---

## Watch Out For

- **`run_gdb_python` requires a file path, not a script string.** The generated script string must be written to a temp `.py` file before calling the bridge. Use `tempfile.NamedTemporaryFile(mode="w", suffix=".py", delete=False)` wrapped in a `try/finally` with `Path(tmp_path).unlink(missing_ok=True)` in the cleanup block — the same pattern `run_gdb_python` itself uses for the JSON result file.
- **`chip=""` falls through all conditionals in `_default_gdb_for_chip` to `shutil.which("gdb")`.** This is the correct silent fallback for a device-agnostic function signature; do not introduce a new `chip` parameter that contradicts the task's specified signature.
- **`generate_thread_inspector()` already exists in `gdb_bridge.py` but is a skeleton** — it does not extract the required fields. Do not modify or call that function; `_generate_thread_script()` in the new module is a complete, independent implementation.
- **Thread state is a bitmask.** Multiple bits can be set simultaneously. The mapping function must check bits in priority order (e.g. RUNNING bit overrides others) to return exactly one of the four labels. The precise bitmask values vary by Zephyr version; test with mocked raw integers that exercise each branch.
- **`stack_info.delta` in Zephyr represents the stack bytes used** (high-water mark from stack canary checking). `stack_free` must be computed on the host side as `stack_size - stack_used` after parsing, not inside the GDB script.

---

## Uncertainty

- **UNCERTAIN: exact Zephyr `thread_state` bit values.** The mapping of raw integer flags to `RUNNING`/`READY`/`PENDING`/`SUSPENDED` strings depends on the Zephyr version. Common values are `_THREAD_RUNNING` = `BIT(0)`, `_THREAD_QUEUED` = `BIT(1)`, `_THREAD_PENDING` = `BIT(2)`, `_THREAD_SUSPENDED` = `BIT(3)`, but these should be confirmed against the target Zephyr source tree at integration time. The implementation should document these assumptions in comments.
- **UNCERTAIN: `_kernel.threads` linked list traversal mechanics.** In Zephyr the `threads` field is a `sys_dlist_t` and threads are linked via `base.qnode_dlist`. The container-of cast to `struct k_thread *` using `gdb.lookup_type` works when DWARF symbols are present; the script must guard each field access with `gdb.error` catches since field names can vary across Zephyr versions.
- **UNCERTAIN: thread name field availability.** Some Zephyr builds strip thread names (when `CONFIG_THREAD_NAME` is not set). The GDB script should handle a `gdb.error` on `t["name"]` access gracefully and fall back to an empty string or a placeholder like `"<unnamed>"`.