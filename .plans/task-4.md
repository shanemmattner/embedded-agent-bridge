Now I have a complete picture. Let me verify the current state precisely — the tool definition and handler already exist in `mcp_server.py`, and the test already exists. However, there is a mismatch with the task spec: `output_path` is currently marked as `required` in `TOOL_DEFINITIONS` and accessed via `arguments["output_path"]` in `_handle_tool`, but the task requires it to be optional with default `'snapshot.core'`.
All existing tests pass. Now I have a complete picture of the gap: the `capture_snapshot` tool structure and handler are already present, but `output_path` is incorrectly marked as `required` in the schema and accessed without a default in `_handle_tool`. The task spec says it must be optional with default `'snapshot.core'`.

---

## Files to Modify

### `eab/mcp_server.py`
Two places need to change: the `capture_snapshot` entry in `TOOL_DEFINITIONS` and the `capture_snapshot` branch in `_handle_tool`.

### `tests/test_mcp_server.py`
The existing `test_capture_snapshot` test only covers the path where `output_path` is explicitly provided. A second test case is needed to verify the default value of `'snapshot.core'` is used when `output_path` is omitted.

---

## Approach

### `eab/mcp_server.py`

**In `TOOL_DEFINITIONS`**, the `capture_snapshot` entry (lines 278–302) currently has `required=["device", "elf_path", "output_path"]`. Change it to `required=["device", "elf_path"]` only, and add `"default": "snapshot.core"` to the `output_path` property dict. This makes the property schema self-documenting about the default. Mirror the pattern used by `eab_tail`'s `lines` property and `eab_fault_analyze`'s `device` property, both of which include a `"default"` key in their property dict and are not listed as required.

**In `_handle_tool`**, the `capture_snapshot` branch (lines 432–444) currently uses `arguments["output_path"]`, which would raise a `KeyError` if the caller omits the parameter. Change this to `arguments.get("output_path", "snapshot.core")`, mirroring the pattern used throughout `_handle_tool` for every other optional parameter (e.g., `arguments.get("lines", 50)`, `arguments.get("method", "hard")`).

### `tests/test_mcp_server.py`

Add a new test method `test_capture_snapshot_default_output_path` inside `TestHandleTool`, directly after the existing `test_capture_snapshot`. It should call `_handle_tool("capture_snapshot", {"device": "...", "elf_path": "..."})` — omitting `output_path` — and assert that the mock was called with `output_path="snapshot.core"`. Follow the exact same pattern as `test_eab_tail_default_lines` (lines 197–202), which patches the function, calls `_handle_tool` without the optional arg, then inspects `mock_fn.call_args` to verify the default was applied.

---

## Patterns to Follow

- **`eab_tail`'s `lines` property in `TOOL_DEFINITIONS`** (`eab/mcp_server.py`, lines 97–103): optional integer parameter with `"default"` key in property dict, absent from `required`.
- **`eab_fault_analyze`'s `device` property in `TOOL_DEFINITIONS`** (`eab/mcp_server.py`, lines 207–211): optional string parameter with `"default"` in the property dict.
- **`arguments.get("lines", 50)` in `_handle_tool` for `eab_tail`** (`eab/mcp_server.py`, line 365): the idiom for applying a default to an optional argument from the arguments dict.
- **`test_eab_tail_default_lines`** (`tests/test_mcp_server.py`, lines 197–202): the pattern for a test that verifies the default value of an optional parameter is passed through correctly.

---

## Watch Out For

- The `capture_snapshot` entry in `TOOL_DEFINITIONS` currently has `output_path` in both the `"properties"` dict and the `required` list. Both need to change: remove `"output_path"` from `required`, and add `"default": "snapshot.core"` to its property dict. Missing either half leaves the schema inconsistent with the implementation.
- The `_handle_tool` branch for `capture_snapshot` imports `capture_snapshot` from `eab.snapshot` under the local alias `_capture_snapshot` to avoid shadowing the outer function name — this alias must be preserved; do not simplify it away.
- Do not change the `required` fields for `device` and `elf_path` — they remain required.
- The `call_tool` decorator in `run_mcp_server` already catches bare `Exception` and converts it to an error JSON response (lines 483–485). The `_handle_tool` function itself does not catch errors; that outer layer is the intended error boundary. Do not add a try/except inside the `capture_snapshot` branch of `_handle_tool`.
- The existing `test_capture_snapshot` test passes `output_path` explicitly and asserts the mock is called with that exact path. Do not alter that test; add a separate test for the default case.

---

## Uncertainty

No uncertainties — all referenced functions and line numbers were verified by direct file reads.