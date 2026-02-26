I'll start by reading the key files mentioned in the task.
Now let me check for snapshot.py's location, the models file, and existing tests.
Now let me look at the trace_steps for additional patterns, and check whether snapshot.py needs to be created.
`eab/snapshot.py` doesn't exist — it must be created. Let me check `eab/capture.py` and `eab/auto_fault_analyzer.py` for related patterns.
Let me check for any existing snapshot-related test files and the tests structure:
Now I have everything I need. Here is the implementation plan.

---

## Files to Modify

### `eab/snapshot.py` — **Create new file**
Add the `capture_snapshot()` function that performs the actual snapshot capture via subprocess.

### `eab/cli/regression/steps.py` — **Extend existing file**
Add `_run_snapshot()` handler function and register `"snapshot"` in `_STEP_DISPATCH`.

### `tests/unit/test_snapshot_step.py` — **Create new test file**
Unit tests covering all three trigger modes and the dispatch registration.

---

## Approach

### `eab/snapshot.py`

Create this module at `eab/snapshot.py`. It needs one public function, `capture_snapshot(output: str, elf: str) -> dict[str, Any]`, which uses `subprocess.run` to call `eabctl snapshot --output <output> --elf <elf> --json`, following exactly the same subprocess invocation pattern used in `_run_eabctl` in `steps.py`. Parse stdout as JSON and return it; handle `subprocess.TimeoutExpired` and `FileNotFoundError` the same way `_run_eabctl` does — returning an error dict rather than raising. Use `from __future__ import annotations`, standard stdlib imports, and group imports as: stdlib, then nothing else (no internal circular imports needed). Add a Google-style docstring covering Args and Returns.

### `eab/cli/regression/steps.py`

Add a new `_run_snapshot` function following the structure of `_run_fault_check` and `_run_anomaly_watch`. Place it immediately before the `_STEP_DISPATCH` dict (after `_run_anomaly_watch`). The function signature matches all other step handlers: `(step: StepSpec, *, device: Optional[str], chip: Optional[str], timeout: int, **_kw: Any) -> StepResult`.

At the top, validate that `output` and `elf` are present in `step.params`; if either is missing, return an error `StepResult` with `passed=False`, mirroring the early-exit pattern in `_run_debug_monitor` and `_run_sram_boot`.

Then implement the three trigger branches:

- **`manual`** (default when `trigger` is absent or unrecognised): set `should_capture = True` unconditionally.
- **`on_fault`**: call `_run_eabctl(["fault-analyze", "--elf", elf] + optional device/chip args, timeout=timeout)`, inspect the output for `output.get("fault_detected", False) or output.get("faulted", False)` — the same field names used in `_run_fault_check` — and set `should_capture` accordingly.
- **`on_anomaly`**: call `_run_eabctl(["anomaly", "compare", "--baseline", baseline, "--duration", str(duration), "--sigma", str(max_sigma)] + optional log_source args, timeout=...)`, inspect `output.get("anomaly_count", 0) >= 1`, mirroring `_run_anomaly_watch`. Require `baseline` in params; return an error `StepResult` if absent (consistent with the `_run_anomaly_watch` guard).

If `should_capture` is True, import and call `from eab.snapshot import capture_snapshot` (place the import at the top of the file alongside the other imports, after the `from eab.cli.regression.models` line). Call `capture_snapshot(output=output, elf=elf)` and use its return dict as `output` in the `StepResult`. If `capture_snapshot` raises `Exception`, catch it and return a failed `StepResult` with the error message.

The step always passes when no trigger condition is met (the step is informational). The step passes when `should_capture` is True and the capture succeeds; fails if capture raises.

Add `"snapshot": _run_snapshot` to `_STEP_DISPATCH`.

### `tests/unit/test_snapshot_step.py`

Follow `tests/unit/test_ble_steps.py` structure. Import `_run_snapshot` from `eab.cli.regression.steps` and `StepSpec`, `StepResult` from `eab.cli.regression.models`. Use `unittest.mock.patch` to mock `eab.snapshot.capture_snapshot` and `eab.cli.regression.steps._run_eabctl`.

Write test classes:

- **`TestSnapshotDispatch`** — assert `"snapshot"` is in `_STEP_DISPATCH` (mirrors `TestBleStepDispatch.test_all_ble_step_types_registered`).
- **`TestSnapshotManualTrigger`** — verify `capture_snapshot` is always called when `trigger` is `"manual"` or absent; verify `StepResult.passed` is True; verify `output` and `elf` are forwarded.
- **`TestSnapshotOnFaultTrigger`** — mock `_run_eabctl` returning `{"fault_detected": True}` → assert capture is called; returning `{"fault_detected": False}` → assert capture is NOT called and step still passes.
- **`TestSnapshotOnAnomalyTrigger`** — mock `_run_eabctl` returning `{"anomaly_count": 2}` → assert capture called; returning `{"anomaly_count": 0}` → assert capture not called. Also test missing `baseline` returns a failed step.
- **`TestSnapshotValidation`** — test missing `output` param → `passed=False`; missing `elf` param → `passed=False`.

---

## Patterns to Follow

| Pattern | File | What it shows |
|---|---|---|
| `_run_fault_check` | `eab/cli/regression/steps.py` | Early-return guard on missing params, `_run_eabctl` call, checking `fault_detected`/`faulted` keys |
| `_run_anomaly_watch` | `eab/cli/regression/steps.py` | `anomaly_count` field inspection, `baseline` required guard, eabctl anomaly compare invocation |
| `_run_debug_monitor` | `eab/cli/regression/steps.py` | Missing required param early-exit with `passed=False` error |
| `_run_eabctl` | `eab/cli/regression/steps.py` | Subprocess pattern, JSON parse, TimeoutExpired/FileNotFoundError handling — replicate in `capture_snapshot` |
| `TestBleStepDispatch` / `TestBleScanStep` | `tests/unit/test_ble_steps.py` | Test class structure, `patch` usage, dispatch registration assertion |

---

## Watch Out For

- **`eab/snapshot.py` must not import from `eab.cli.regression`** — the dependency flows one way: the step (CLI layer) imports the library module, not the reverse.
- **`_run_eabctl` is defined in `steps.py`**, not in `trace_steps.py`. The `trace_steps.py` module imports it from `steps.py`. If `capture_snapshot` in `eab/snapshot.py` needs to invoke eabctl, it must use `subprocess.run` directly (same pattern), not import `_run_eabctl` (which would create a circular/layering dependency).
- **The `on_anomaly` trigger requires a `baseline` param** — unlike `manual`/`on_fault`. Fail early with a clear error if it's absent, consistent with how `_run_anomaly_watch` handles it.
- **`_STEP_DISPATCH` is mutated after definition** by the BLE late-import (`_STEP_DISPATCH.update(BLE_STEP_DISPATCH)`). The `"snapshot"` key must be added in the initial `_STEP_DISPATCH` literal (before the BLE update block), not after it.
- **Do not touch `eab/fault_analyzer.py`** — fault condition detection in the step uses `_run_eabctl(["fault-analyze", ...])` directly, not the `analyze_fault()` Python API (which requires a live probe object).

---

## Uncertainty

**UNCERTAIN:** The exact command name and arguments for `capture_snapshot`'s subprocess call — `eabctl snapshot` is inferred by analogy with other eabctl subcommands (`fault-analyze`, `anomaly compare`, `trace start`) but no `snapshot` subcommand is visible in the codebase. The implementer should use `eabctl snapshot --output <path> --elf <elf>` as the most natural name matching the file/step naming; if an alternative command already exists, adapt accordingly.

**CANNOT_ACCESS:** `eab/snapshot.py` — file does not exist yet; it must be created as part of this task.