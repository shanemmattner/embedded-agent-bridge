I'll systematically read the target files and their dependencies before writing the plan.
Now let me check what's missing from the existing test file (it ends at line 399) and read the CLI/MCP files.
Now let me read one existing unit test for patterns, and the full MCP server to understand `_handle_tool`:
Now I have enough context to write the complete plan.

---

## Files to Modify

### `tests/unit/test_dwt_explain.py`
Append three new test classes after the existing `TestRunDwtExplainUnknownSymbol` class (line 399):
- `TestRunDwtExplainInvalidDuration` — two tests for `duration_s=0` and `duration_s=-1`
- `TestCmdDwtExplainJsonMode` — two tests exercising the CLI handler's `--json` output
- `TestMcpDwtStreamExplain` — two tests calling the MCP `_handle_tool` dispatcher

### `eab/dwt_explain.py`
Add a duration guard at the top of `run_dwt_explain`, after the existing `device is None` check, before the symbol resolution loop. This is required for `TestRunDwtExplainInvalidDuration` to pass — `run_dwt_explain` currently has no validation for non-positive `duration_s`.

---

## Approach

### `tests/unit/test_dwt_explain.py`

Add three imports at the top of the file alongside the existing ones: `import asyncio`, `from eab.cli.dwt.explain_cmd import cmd_dwt_explain`, and `from eab.mcp_server import _handle_tool`. These are needed by the new CLI and MCP test classes.

**`TestRunDwtExplainInvalidDuration`** (section 8, after `TestRunDwtExplainUnknownSymbol`): Mirror the patch stack from `TestRunDwtExplainUnknownSymbol` — patch `eab.dwt_explain.os.path.isfile` to return `True`. For `duration_s=0`, call `run_dwt_explain(["some_sym"], 0, "/fake/app.elf", "NRF5340_XXAA_APP")` inside `pytest.raises(ValueError)`. Repeat for `-1`. No need to patch `_resolve_symbol` because duration validation must fire before symbol resolution.

**`TestCmdDwtExplainJsonMode`** (section 9): Construct a fake `ExplainResult`-shaped dict (the same shape as `sample_enriched_events`-based results: `events`, `source_context`, `ai_prompt`, `suggested_watchpoints`). Patch `eab.cli.dwt.explain_cmd.run_dwt_explain` to return it. Call `cmd_dwt_explain(device="NRF5340_XXAA_APP", symbols="conn_interval", elf="/fake/app.elf", duration=1, json_mode=True)` using `capsys` to capture stdout. Assert `json.loads(captured.out)` succeeds and that the result has all four required keys. Add a second test asserting the non-JSON mode prints `ai_prompt` only (no braces).

**`TestMcpDwtStreamExplain`** (section 10): Patch `eab.mcp_server.run_dwt_explain` to return a fake `ExplainResult` dict. Call `asyncio.run(_handle_tool("dwt_stream_explain", {"symbols": ["conn_interval"], "duration_s": 1, "elf_path": "/fake/app.elf"}))` inside a regular (non-async) test method (consistent with no existing async tests). Assert the return value is a valid JSON string. Assert the parsed dict has keys `events`, `source_context`, `ai_prompt`, `suggested_watchpoints`. Add a second test that exercises the `"unknown_tool"` path to verify it returns `{"error": ...}`.

### `eab/dwt_explain.py`

Inside `run_dwt_explain`, immediately after the `if device is None: raise ValueError(...)` block (around line 432), add a guard that raises `ValueError` when `duration_s <= 0`. The error message should be descriptive (e.g. "duration_s must be a positive number, got {duration_s!r}"). This follows the same pattern as the existing `device is None` check just above it.

---

## Patterns to Follow

- **`TestRunDwtExplainUnknownSymbol`** in `tests/unit/test_dwt_explain.py` — exact decorator stack and fixture structure to mirror for `TestRunDwtExplainInvalidDuration`; patch `os.path.isfile` and `_resolve_symbol` in the same order.
- **`TestRunDwtExplain.test_returns_complete_result`** in `tests/unit/test_dwt_explain.py` — demonstrates the full patch chain for `run_dwt_explain`; new tests should use the same patch target strings.
- **`cmd_dwt_explain`** in `eab/cli/dwt/explain_cmd.py` — the CLI function to import and call in `TestCmdDwtExplainJsonMode`; patch target is `eab.cli.dwt.explain_cmd.run_dwt_explain`.
- **`_handle_tool`** in `eab/mcp_server.py` (lines 350–443) — the async dispatcher to call with `asyncio.run()`; patch target is `eab.mcp_server.run_dwt_explain` (imported at module level, line 25).
- **Duration guard pattern** in `run_dwt_explain` — follow the `if device is None: raise ValueError(...)` guard (line 428–431) as the structural template for the new `duration_s <= 0` guard.

---

## Watch Out For

- **`_handle_tool` calls `_import_cli()` unconditionally** before the `name == "dwt_stream_explain"` branch. This triggers a full `import eab.cli`, which re-exports many modules. All existing tests pass despite this, so the import is safe, but the test should not try to patch or suppress it — just let it happen.
- **`cmd_dwt_explain` passes wrong kwarg names to `run_dwt_explain`** (`elf=` and `duration=` instead of `elf_path=` and `duration_s=`). This is a latent bug in `explain_cmd.py`. The CLI tests must mock `run_dwt_explain` so the wrong kwargs are absorbed silently by `MagicMock`; do not assert on what args the mock was called with, as that would expose the kwarg mismatch.
- **Duration guard must come before `_resolve_symbol` calls** in `run_dwt_explain` — the existing tests `TestRunDwtExplainUnknownSymbol` do NOT patch `_open_jlink` or `ComparatorAllocator`, only `_resolve_symbol` and `os.path.isfile`. The new duration guard must fire before symbol resolution so the invalid-duration tests do not need a deep mock stack.
- **asyncio mode is STRICT** (`asyncio: mode=Mode.STRICT` in pyproject.toml). Using `asyncio.run(...)` inside a plain `def test_...` method is valid and avoids needing `@pytest.mark.asyncio`; this matches existing test style (no async tests exist).
- **`format_explain_prompt([])` returns `suggested_watchpoints=[]`** (verified in `test_format_explain_prompt_empty_returns_non_empty_prompt`). The fake `ExplainResult` used in CLI and MCP tests should include a non-empty `suggested_watchpoints` list so assertions against it are unambiguous.

---

## Uncertainty

**UNCERTAIN**: The task requires `run_dwt_explain` to raise `ValueError` for `duration_s=0` and `duration_s=-1`, but the current implementation has no such validation — it would call `capture_events(..., duration_s=0.0)` which calls `time.sleep(0)` successfully. For test 5 to pass, a validation guard must be added to `run_dwt_explain`. The task description only mentions the test file; modifying `eab/dwt_explain.py` is implied but not explicitly stated.