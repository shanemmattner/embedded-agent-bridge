Now I have everything I need. Let me also check the tests directory for any existing tests of the MCP server:
### Files to Modify

**`eab/mcp_server.py`** — Three locations need changes: (1) the internal imports section, (2) the `TOOL_DEFINITIONS` list, and (3) the `_handle_tool` dispatch function.

**`tests/test_mcp_server.py`** — `TestHandleTool` needs a new test method for `dwt_stream_explain`, and `test_expected_tools_present` should include `"dwt_stream_explain"` in the expected set.

---

### Approach

**`eab/mcp_server.py`**

There are exactly three insertion points. First, add `from eab.dwt_explain import run_dwt_explain` in the internal imports section — after `from typing import Any` and before `log = logging.getLogger(__name__)`. This follows the convention of grouping stdlib imports, then external/optional imports, then internal `eab.*` imports with a blank line between groups.

Second, append a new dict entry to `TOOL_DEFINITIONS` after the `"eab_regression"` entry (currently the 8th). The entry follows the identical structure: a `"name"` key, a `"description"` string, and an `"inputSchema"` produced by `_schema()`. The `symbols` property uses `"type": "array"` with `"items": {"type": "string"}`. All three parameters — `symbols`, `duration_s`, `elf_path` — go in the `required` list passed to `_schema()`.

Third, add a new `if name == "dwt_stream_explain":` branch at the bottom of `_handle_tool`, immediately before the final `return json.dumps({"error": f"Unknown tool: {name}"})` fallback. The branch calls `run_dwt_explain(symbols=..., duration_s=..., elf_path=...)` extracting each argument directly from `arguments` (no `.get()` defaults — all three are required). The return is `json.dumps(result)`. ValueError error handling is provided for free by the outer `except Exception as exc` in `call_tool` (lines 480–482), which matches the exact same error pattern all other tools rely on — no per-branch try/except is needed.

**`tests/test_mcp_server.py`**

In `TestHandleTool`, add one new test method following the exact pattern of `test_eab_regression`: patch `eab.dwt_explain.run_dwt_explain` (or `eab.mcp_server.run_dwt_explain` since it is imported at module level), call `_handle_tool("dwt_stream_explain", {"symbols": ["conn_interval"], "duration_s": 5, "elf_path": "/fw.elf"})`, and assert that `run_dwt_explain` was called with the correct keyword arguments and that the return value parses as valid JSON. Also add a second test that patches `run_dwt_explain` to raise `ValueError("ELF file not found")` and confirms the outer `call_tool` wrapping returns a JSON payload with an `"error"` key.

In `test_expected_tools_present`, add `"dwt_stream_explain"` to the `expected` set so the count assertion stays accurate.

---

### Patterns to Follow

- **`eab/mcp_server.py` → `"eab_regression"` entry in `TOOL_DEFINITIONS`** — The closest structural analog: no `_BASE_DIR_PROP` or `_JSON_MODE_PROP` helpers, all properties are custom, and there is a non-empty `required` list.
- **`eab/mcp_server.py` → `if name == "eab_regression":` branch in `_handle_tool`** — Shows the pattern for calling a function imported at module level rather than via `cli`, returning `json.dumps(result)` directly.
- **`eab/mcp_server.py` → `_schema()` helper** — Call signature: first arg is a `dict` of property dicts, optional `required=` kwarg is a `list[str]`.
- **`tests/test_mcp_server.py` → `TestHandleTool.test_eab_regression`** — Shows how to patch a function that is lazily imported inside the handler (`with patch("eab.cli.regression.cmd_regression", ...)`). For `run_dwt_explain`, the patch target is `"eab.mcp_server.run_dwt_explain"` because it is imported by name at the top of `mcp_server.py`.
- **`tests/test_mcp_server.py` → `TestHandleTool.test_exception_in_cmd_returns_error_json`** — Shows the expected test pattern for error path: `side_effect=RuntimeError(...)` and assertion on raised exception.

---

### Watch Out For

- `run_dwt_explain` accepts a fourth parameter `device: Optional[str] = None` that the MCP tool does not expose. The handler must not pass `device=` at all (omit it entirely), so the function will raise `ValueError("A J-Link device string must be provided…")` when called without hardware context — this is expected and caught by the outer `except Exception`.
- The patch target for `run_dwt_explain` in tests must be `"eab.mcp_server.run_dwt_explain"` (where the name lives after import), not `"eab.dwt_explain.run_dwt_explain"` — patching the source module has no effect since `mcp_server` has already bound the name locally.
- `test_tool_definitions_non_empty` asserts `>= 8`, not `== 8`, so adding the 9th tool will not break it.
- The `TOOL_DEFINITIONS` list is consumed by `list_tools()` at registration time; order matters only for presentation — insert the new entry last to avoid renumbering unrelated indices.
- Do not add `_JSON_MODE_PROP` or `_BASE_DIR_PROP` to the `dwt_stream_explain` schema — `run_dwt_explain` accepts neither, and the schema should match the callable exactly.

---

### Uncertainty

No significant uncertainties. All three insertion points are unambiguous, the function signature of `run_dwt_explain` was verified in `eab/dwt_explain.py`, and the test patterns were verified in `tests/test_mcp_server.py`.