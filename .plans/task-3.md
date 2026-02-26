Now I have all the context needed. Here is the implementation plan.

---

## Files to Modify

### `eab/thread_inspector.py` — **New file**
Create this module. It must export `ThreadInfo` (a dataclass) and `inspect_threads(device, elf)`.

### `eab/cli/regression/steps.py` — **Extend existing file**
Add `_run_stack_headroom_assert` step handler function and register it in `_STEP_DISPATCH`.

### `tests/test_regression.py` — **Extend existing file**
Add tests for the new step inside the existing `TestStepExecution` class.

---

## Approach

### `eab/thread_inspector.py`

Create a new module at `eab/thread_inspector.py`. Define a `ThreadInfo` dataclass with at minimum a `name: str` field and a `stack_free: int` field (both matching the keys expected in the thread dicts returned by `eabctl threads --json`). Define `inspect_threads(device: str, elf: str) -> list[ThreadInfo]` which uses `subprocess.run` to call `eabctl threads --device <device> --elf <elf> --json` (following the exact same invocation style as `_run_eabctl` in `steps.py`), parses the JSON stdout, extracts the `"threads"` list from the result, and maps each dict entry to a `ThreadInfo`. If the subprocess call fails or returns a non-zero code, raise a `RuntimeError` with the error detail. Include a Google-style docstring on `inspect_threads` since it is a public function over 5 lines.

The `ThreadInfo` dataclass fields should use `.get()` with sensible defaults (`name` defaults to `""`, `stack_free` defaults to `0`) so that partial thread data from the GDB script does not crash the parse step.

### `eab/cli/regression/steps.py`

Add the import of `inspect_threads` and `ThreadInfo` from `eab.thread_inspector` near the top of the file, after the existing internal imports. Then add `_run_stack_headroom_assert` as a new private function, placed immediately before the `_STEP_DISPATCH` dict (between `_run_anomaly_watch` and the `from eab.cli.regression.trace_steps import ...` line). Follow the pattern of `_run_fault_check` and `_run_read_vars` exactly: capture `t0 = time.monotonic()` first, extract params from `step.params`, perform the logic, and return a `StepResult`. The step signature must match all other handlers: `(step: StepSpec, *, device: Optional[str], chip: Optional[str], timeout: int, **_kw: Any) -> StepResult`.

Inside the function:
- Extract `min_free_bytes = int(p.get("min_free_bytes", 0))` (required; if missing or zero that is the caller's problem, but no extra validation is needed beyond what the task specifies).
- Extract `step_device = p.get("device") or device` and `elf = p.get("elf", "")`, mirroring how `_run_fault_check` resolves its `device` param.
- Call `inspect_threads(step_device, elf)` inside a `try` block; on `RuntimeError` return a failed `StepResult` with the error string.
- Iterate through the returned list checking `t.stack_free < min_free_bytes`; collect offending threads.
- If any offenders, build an error string of the form `"thread '<name>' has stack_free=<n> < min_free_bytes=<m>"` for each, joined with `"; "`, and return a failing `StepResult`.
- Otherwise return a passing `StepResult`.

Finally, add `"stack_headroom_assert": _run_stack_headroom_assert` to `_STEP_DISPATCH`.

### `tests/test_regression.py`

Add three test methods inside `TestStepExecution`, patching `eab.cli.regression.steps.inspect_threads` (the imported name in `steps.py`):

1. `test_stack_headroom_assert_pass` — mock returns two `ThreadInfo` objects both above threshold; assert `result.passed is True`.
2. `test_stack_headroom_assert_fail` — mock returns threads where one is below threshold; assert `result.passed is False` and `result.error` contains the offending thread name and both the `stack_free` value and `min_free_bytes` value.
3. `test_stack_headroom_assert_inspect_error` — mock raises `RuntimeError("connection failed")`; assert `result.passed is False` and `result.error` contains the error message.

---

## Patterns to Follow

| Pattern | File | Purpose |
|---|---|---|
| `_run_fault_check` | `eab/cli/regression/steps.py` line 421 | Step handler signature, `p.get("device") or device` resolution, early-return failure |
| `_run_read_vars` | `eab/cli/regression/steps.py` line 367 | Collecting multiple validation errors, joining with `"; "` in `StepResult.error` |
| `_run_anomaly_watch` | `eab/cli/regression/steps.py` line 598 | Building a descriptive error string listing offending items, similar structure |
| `_run_eabctl` | `eab/cli/regression/steps.py` line 96 | Subprocess invocation style and JSON parsing to mirror in `inspect_threads` |
| `StepResult` / `StepSpec` | `eab/cli/regression/models.py` | Exact fields available on each dataclass |

---

## Watch Out For

- `_STEP_DISPATCH` is defined **after** all handler functions in `steps.py`. The new `_run_stack_headroom_assert` function must appear **before** the dispatch dict, and the import of `inspect_threads` must appear at the top of the file in the internal-imports group — not inline next to the dispatch dict (unlike the late `trace_steps` import, which is an explicit exception for circular-dependency avoidance).
- The `**_kw: Any` parameter is present on every step handler to absorb extra keyword arguments. Do not omit it on `_run_stack_headroom_assert`.
- `eab/thread_inspector.py` does not yet exist. It must be created as a new top-level module inside `eab/` (same level as `gdb_bridge.py`, `fault_analyzer.py`, etc.).
- In tests, patch `eab.cli.regression.steps.inspect_threads` (the name as it appears in the `steps` module after import), not `eab.thread_inspector.inspect_threads`, to correctly intercept the call.
- The `ThreadInfo` dataclass in `thread_inspector.py` must be importable from `eab.thread_inspector` since test code will need to construct instances directly when building mock return values.

---

## Uncertainty

**UNCERTAIN:** The exact field names that `eabctl threads --json` places in each thread dict (e.g. whether the key is `"name"` or something else) are not pinned by the existing GDB-script output, which currently only writes `address` and `node_ptr`. `ThreadInfo.name` and `ThreadInfo.stack_free` must be defined to match whatever keys `eabctl threads` outputs in the `threads` list. Since the GDB-generated script does not currently populate `name` or `stack_free`, the implementer should define `ThreadInfo` with `name: str = ""` and `stack_free: int = 0` as defaults and parse from the same-named keys in the dict — the tests will mock `inspect_threads` entirely, so the round-trip through `eabctl` is not exercised in unit tests.