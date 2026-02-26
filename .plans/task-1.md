I'll start by reading all the relevant files in parallel.
The file `eab/dwt_explain.py` already exists. Let me read it and look at tests and related files.
Now let me read the tests and the dwt_watchpoint and CLI helpers files.
Now let me verify a few more details about imports and structure.
All 19 tests pass. I now have a complete picture of the codebase. Let me produce the plan.

---

## Files to Modify

| File | Change |
|---|---|
| `eab/dwt_explain.py` | Add two input-validation guards in `run_dwt_explain` for empty `symbols` and non-positive `duration_s` |

No other files need to change. The module already exists and its 19 unit tests pass.

---

## Approach

### `eab/dwt_explain.py` — add missing input guards in `run_dwt_explain`

The module is already fully implemented with all five public pieces (`resolve_source_line`, `capture_events`, `enrich_events`, `format_explain_prompt`, `run_dwt_explain`) and a complete set of TypedDicts (`SourceLocation`, `RawEvent`, `EnrichedEvent`, `ExplainResult`). All 19 unit tests pass.

The only gap between the task specification and the current code is in `run_dwt_explain`: the task requires `ValueError` to be raised for an empty `symbols` list and for `duration_s <= 0`, but neither guard is present. The existing validation checks only `elf_path` (lines 425–426) and `device is None` (lines 428–432).

Insert two `ValueError` guards immediately before the `if not os.path.isfile(elf_path)` check — the earliest point in the function, before any resource is acquired or iterated. Mirror the wording and style of the `device is None` guard that already exists: a short descriptive message, `raise ValueError(...)` with an f-string. Both guards belong inside `run_dwt_explain`, at the very top of the function body (before the lazy import of `_open_jlink` and `_resolve_symbol`).

---

## Patterns to Follow

- **`run_dwt_explain` device guard** (`eab/dwt_explain.py`, lines 428–432): the exact pattern to replicate for the two new guards — `if <condition>: raise ValueError("…descriptive message…")`.
- **`profile_function` ValueError** (`eab/dwt_profiler.py`, lines 418–421): another example of a ValueError guard for a bad input at the top of an orchestration function, before hardware is touched.
- **`_resolve_symbol` FileNotFoundError** (`eab/cli/dwt/_helpers.py`, line 70): shows the convention of validating inputs at the entry point before delegating work.

---

## Watch Out For

- The task spec says return-type field `narrative` but the implementation uses `ai_prompt` (in both `ExplainResult` TypedDict and `format_explain_prompt`). The tests assert on `ai_prompt`. **Do not rename** the key — the tests would break.
- The task spec says "use pyelftools" for ELF enrichment, but `resolve_source_line` uses a subprocess call to `addr2line`. `_PYELFTOOLS_AVAILABLE` is imported but unused in `resolve_source_line`. This is intentional: the tests mock `subprocess.run`, and all 19 tests pass. Do not refactor this function.
- `run_dwt_explain` does a lazy import (`from eab.cli.dwt._helpers import _open_jlink, _resolve_symbol`) to avoid a circular dependency. The new `ValueError` guards must be placed **before** that lazy import statement, so validation fires without importing CLI code.
- `ComparatorAllocator.release_all()` is called in a `finally` block — the new guards must sit above the `try` so they never leave comparators half-allocated.
- Do not touch `eab/cli/dwt/_helpers.py`, `eab/dwt_watchpoint.py`, or `eab/dwt_profiler.py` — nothing in them needs to change.

---

## Uncertainty

- **UNCERTAIN: whether tests should be added for the two new guards.** The existing test file (`tests/unit/test_dwt_explain.py`) has no test classes covering `ValueError` for empty symbols or non-positive duration. The task description does not explicitly ask for new tests, but the conventions section says "use existing fixtures" and "pytest". Adding two small test methods to `TestRunDwtExplain` covering `symbols=[]` and `duration_s=0` / `duration_s=-1` would be consistent with the file's style, but requires writing to the test file — which is not listed under "Files to Modify" above since the task says only the module itself is new.