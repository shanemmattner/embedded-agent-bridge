Now I have enough context. Let me check the pyproject.toml to understand the package structure.
Now I have enough context. Let me compile the plan.

---

## Files to Modify

### New File: `eab/dwt_explain.py`
Create this module with the five public functions that the tests will call: `resolve_source_line`, `capture_events`, `enrich_events`, `format_explain_prompt`, and `run_dwt_explain`.

### New File: `tests/unit/test_dwt_explain.py`
Create seven test classes/functions covering all acceptance-criteria scenarios.

---

## Approach

### `eab/dwt_explain.py`

Place the module at `eab/dwt_explain.py`, next to `eab/dwt_profiler.py`. Follow the optional-import pattern from `eab/cli/dwt/_helpers.py` for `pyelftools` and from `eab/dwt_profiler.py` for `pylink`. Group imports as: stdlib → external → internal, with blank lines between groups.

Define these five public functions in order:

1. **`resolve_source_line(elf_path: str, address: int) -> dict[str, Any]`** — Opens the ELF with `ELFFile` (imported at module level in a try/except block, same pattern as `_helpers.py` lines 21–25), calls `elf.get_dwarf_info()`, iterates CUs, retrieves the line program for each CU, and scans entries to find the entry whose state address matches. Returns a dict with at minimum `source_file`, `line_number`, and `function_name` keys. When no match is found, returns a dict with empty/zero values.

2. **`capture_events(event_source: Any, duration_s: float) -> list[dict[str, Any]]`** — Accepts any iterable that yields event dicts. Drains it, collecting events that arrive before `time.time() + duration_s`. Returns the collected list. This is the only time-dependent function; using a `deadline = time.time() + duration_s` guard is appropriate (mirrors the `_wait_for_halt` polling loop in `dwt_profiler.py`).

3. **`enrich_events(events: list[dict[str, Any]], elf_path: str) -> list[dict[str, Any]]`** — Iterates `events`; for each event that has an `address` field, calls `resolve_source_line` and merges the result into a copy of the event dict. Returns the enriched list.

4. **`format_explain_prompt(enriched_events: list[dict[str, Any]]) -> dict[str, Any]`** — Builds a human-readable AI prompt string from the enriched events. Returns a dict with keys `events`, `source_context`, `ai_prompt`, and `suggested_watchpoints`. When `enriched_events` is empty, `ai_prompt` must still be a non-empty string that contains the phrase "no activity observed" (or equivalent). `suggested_watchpoints` is a list; `source_context` is a string.

5. **`run_dwt_explain(symbols: list[str], elf_path: str, device: str, duration_s: float) -> dict[str, Any]`** — Orchestrator. First, validates all symbols by attempting ELF lookup via `_resolve_symbol` imported from `eab.cli.dwt._helpers`; raises `ValueError` for any symbol not found. Next, arms DWT hardware by calling `enable_dwt` (imported from `eab.dwt_profiler`) on a `pylink.JLink` instance. Then calls `capture_events` with a JSONL event source, calls `enrich_events`, calls `format_explain_prompt`, and returns the resulting dict.

For the JSONL event source, `run_dwt_explain` should use a helper generator (private, e.g. `_jsonl_event_stream`) that reads from a file or `subprocess.Popen` pipe. This generator is what tests will patch.

### `tests/unit/test_dwt_explain.py`

Model the file structure on `tests/unit/test_ble_central.py` (class-based, fixtures at module level) and the patching style of `eab/tests/test_elf_inspect.py` (using `@patch` decorators and `MagicMock`).

Place all imports at the top: `from __future__ import annotations`, stdlib (`unittest.mock.patch`, `unittest.mock.MagicMock`), external (`pytest`), then internal (`from eab.dwt_explain import ...`).

Define module-level fixtures where reusable:
- A `sample_events` fixture returning a hardcoded list of two or three event dicts with `address`, `ts`, `label`, `value` keys — matching what `DwtWatchpointDaemon._emit_event` writes (see `dwt_watchpoint.py` line 384).
- An `enriched_events` fixture building on `sample_events` by adding `source_file`, `line_number`, `function_name`.

**Seven test classes/functions:**

1. **`TestResolveSourceLine`** — Patches `eab.dwt_explain.ELFFile` with a `MagicMock`. Configures the mock's DWARF path: `mock_elf_file.get_dwarf_info.return_value` → mock DWARF info whose `iter_CUs()` yields one mock CU, whose line program yields a mock entry with a known address and state (file=`"main.c"`, line=`42`). Calls `resolve_source_line("/fake/app.elf", <address>)` and asserts the returned dict has `source_file == "main.c"` and `line_number == 42`.

2. **`TestCaptureEvents`** — No patching needed. Constructs a list of sample event dicts, passes them as the `event_source` argument (a plain list is iterable), uses a `duration_s` large enough that all events are captured (e.g., `10.0`). Asserts the returned list equals the input list.

3. **`TestEnrichEvents`** — Patches `eab.dwt_explain.resolve_source_line` via `patch` to return `{"source_file": "sensor.c", "line_number": 17, "function_name": "sensor_read"}`. Calls `enrich_events(sample_events, "/fake/app.elf")`. Asserts each enriched event has those three keys with the expected values.

4. **`TestFormatExplainPrompt`** — No patching. Calls `format_explain_prompt(enriched_events)`. Asserts the returned dict has keys `events`, `source_context`, `ai_prompt`, `suggested_watchpoints`. Asserts `ai_prompt` is a non-empty string.

5. **`TestRunDwtExplain`** — Uses `patch` on four targets: `eab.dwt_explain._resolve_symbol` (returns `(0x20001234, 4)`), `eab.dwt_explain.enable_dwt` (no-op MagicMock), `eab.dwt_explain._jsonl_event_stream` (yields the sample event dicts), and `eab.dwt_explain.resolve_source_line` (returns enriched fields). Also patches `eab.dwt_explain._pylink` or the JLink constructor to return a MagicMock. Calls `run_dwt_explain(["conn_interval"], "/fake/app.elf", "NRF5340_XXAA_APP", 1.0)`. Asserts the returned dict has keys `events`, `ai_prompt`, `source_context`, `suggested_watchpoints` and that `events` is non-empty.

6. **`TestRunDwtExplainNoEvents`** — Same patch setup as Test 5, but `_jsonl_event_stream` yields no events (empty iterator). Asserts `result["events"] == []` and `result["ai_prompt"]` contains "no activity" (or the exact phrase used in `format_explain_prompt` when events is empty).

7. **`TestRunDwtExplainUnknownSymbol`** — Patches `eab.dwt_explain._resolve_symbol` to raise `SymbolNotFoundError` (imported from `eab.dwt_watchpoint`). Calls `run_dwt_explain(["no_such_var"], ...)`. Uses `pytest.raises(ValueError)` to assert the error is raised and re-raised as `ValueError`.

---

## Patterns to Follow

- **`eab/cli/dwt/_helpers.py`, `_resolve_via_pyelftools`** — Pattern for opening ELF with `ELFFile` inside a `with open(elf_path, "rb") as f:` block and iterating sections/symbols.
- **`eab/tests/test_elf_inspect.py`, `TestParseSymbols.test_parses_data_symbols_with_sizes`** — Pattern for using `@patch("eab.elf_inspect.subprocess.run")` and `@patch("eab.elf_inspect._resolve_nm")` decorators together; how mock return values are set up with `.return_value`.
- **`tests/unit/test_ble_central.py`, `TestScan.test_success_returns_address`** — Pattern for class-based tests that use fixtures and make assertions on return values vs. mock call arguments.
- **`eab/dwt_profiler.py`, `_wait_for_halt`** — Pattern for deadline-based time-window loop using `time.time()`.
- **`eab/dwt_profiler.py`, module top** — Pattern for the optional `pylink` import wrapped in `try/except ImportError` with `pylink = None` fallback.

---

## Watch Out For

- **`eab/dwt_explain.py` does not exist yet** — the implementer must create it before the tests can import from it. The test file alone will fail with `ModuleNotFoundError` until the module exists.
- **pyelftools DWARF line program mock depth** — The mock chain for `ELFFile` → `get_dwarf_info()` → `iter_CUs()` → line program → entries is several levels deep. Use `MagicMock()` objects (not `spec=`) for DWARF internals since their API shapes vary. Set up the chain explicitly with `.return_value` and `.side_effect` rather than relying on auto-spec.
- **`SymbolNotFoundError` vs `ValueError`** — `_resolve_symbol` (from `_helpers.py`) raises `SymbolNotFoundError` (defined in `eab/dwt_watchpoint.py`). `run_dwt_explain` must catch it and re-raise as `ValueError` so test 7 uses `pytest.raises(ValueError)`.
- **`_jsonl_event_stream` must be a patchable name** — Define it as a module-level private generator function in `eab/dwt_explain.py` (not a lambda or inline). Tests patch it as `eab.dwt_explain._jsonl_event_stream`.
- **`time.time()` in `capture_events`** — The deadline-based guard can race in tests if `duration_s` is very small. Use `duration_s=10.0` in tests to avoid flakiness; test 6 achieves "no events" by mocking the source, not by using `duration_s=0`.