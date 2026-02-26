---

### Files to Modify

**`eab/mcp_server.py`** — add one entry to `TOOL_DEFINITIONS`, one dispatch branch in `_handle_tool`, and one top-level import.

---

### Approach

**`eab/mcp_server.py`**

**Import:** Add `from eab.dwt_explain import run_dwt_explain` after the stdlib imports block (lines 19–24) and before the optional `mcp` import block. This creates an internal imports section following the stdlib → external → internal grouping convention. Because `dwt_explain.py` does not yet exist at read time, the implementer must ensure the previous subtask's file is present before this import will succeed.

**TOOL_DEFINITIONS entry:** Append a ninth dict to `TOOL_DEFINITIONS` (after the `eab_regression` entry, before the closing `]` on line 278). The entry should have `name: "dwt_stream_explain"`, a `description`, and an `inputSchema` built via `_schema(...)` with three property keys: `symbols` (type `array`, items type `string`), `duration_s` (type `integer`), and `elf_path` (type `string`). All three should appear in the `required` list passed to `_schema`.

**_handle_tool dispatch branch:** Add an `if name == "dwt_stream_explain":` branch inside `_handle_tool` immediately after the `eab_regression` branch and before the final `return json.dumps({"error": ...})` fallthrough. Unlike the other eight branches — which all delegate to `_capture_cmd` because their underlying functions are cmd-style (print to stdout, return int) — this branch calls `run_dwt_explain` directly and returns `json.dumps` of its result. No individual try/except is added; errors propagate to the outer `call_tool` decorator's `except Exception` handler (line 444), which is the same pattern used by all existing branches.

---

### Patterns to Follow

- **`eab_regression` branch in `_handle_tool`** (`eab/mcp_server.py`, lines 396–405) — closest pattern for a tool that uses a non-`_import_cli()` import; note that `eab_regression` uses a *lazy* local import, whereas `dwt_stream_explain` is required to use a top-level import.
- **`eab_reset` entry in `TOOL_DEFINITIONS`** (`eab/mcp_server.py`, lines 196–196) — example of a tool with a `required` list passed to `_schema`, mirroring how all three `dwt_stream_explain` params must be marked required.
- **`eab_wait` entry** (`eab/mcp_server.py`, lines 106–137) — example of `_schema` with a non-empty `required` list and multiple typed properties including arrays/primitives.
- **`_schema` helper** (`eab/mcp_server.py`, lines 72–77) — all tool schemas must be constructed through this helper; do not write raw dicts.

---

### Watch Out For

- **`dwt_explain.py` does not yet exist** in the repository. Adding a top-level `from eab.dwt_explain import run_dwt_explain` means `eab/mcp_server.py` will fail to import if `dwt_explain.py` is absent. The implementer must confirm the previous subtask's output is in place before running tests.
- **`run_dwt_explain` return type is unknown** — the file to be imported doesn't exist yet. The handler should serialize its return value with `json.dumps`. If `run_dwt_explain` already returns a JSON string, wrapping it again would double-encode it. **UNCERTAIN: what `run_dwt_explain` returns (string vs dict) needs to be verified once `dwt_explain.py` exists.**
- **`symbols` JSON schema type** — MCP input schemas use JSON Schema types. A `list[str]` Python parameter corresponds to `{"type": "array", "items": {"type": "string"}}` in JSON Schema; do not use `"type": "list"`.
- **Do not modify the `call_tool` error handler** (lines 443–446) — it already catches all exceptions generically. The new branch inherits this behavior without any additional try/except.
- **Test file `test_mcp_server.py`** — `test_tool_definitions_non_empty` asserts `>= 8`; it will pass with 9. `test_expected_tools_present` checks a fixed set of 8 names — it will still pass since it uses `issubset`. No existing test will break; a new test for `dwt_stream_explain` dispatch should be added alongside the others in `TestHandleTool`.