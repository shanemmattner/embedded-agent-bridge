Now let me check the models file and existing tests.
Let me check the runner to understand how steps are parsed from YAML.
The implementation is already complete and all 18 tests pass. The task has already been fully implemented. Here is what was found:

---

### Status: Already Implemented

After reading all relevant files, the snapshot HIL regression step is **fully implemented** in the codebase. No changes are needed.

---

### Files to Modify

**None.** The feature is already present.

---

### What Exists (Verified by Reading)

**`eab/cli/regression/steps.py`** (lines 657–803):

- `_run_snapshot` function (lines 657–773) implements the full handler following the exact same pattern as `_run_fault_check`, `_run_anomaly_watch`, and other step handlers in the file.
- It parses `output`, `elf`, and `trigger` from `step.params`.
- Default trigger is `"manual"` — always captures.
- `"on_fault"` calls `_run_eabctl(["fault-analyze", ...])` and checks `fault_detected` / `faulted` keys in the output.
- `"on_anomaly"` calls `_run_eabctl(["anomaly", "compare", ...])` and checks `anomaly_count >= 1`.
- When triggered, calls `capture_snapshot(device=..., elf_path=..., output_path=..., chip=...)` from `eab/snapshot.py`.
- Returns a `StepResult` with `output={"captured": True/False, "trigger": ..., ...}`.
- `"snapshot"` is registered in `_STEP_DISPATCH` (line 802).
- `capture_snapshot` is already imported at the top of the file (line 14).

**`tests/unit/test_snapshot_step.py`** (18 tests, all passing):

- `TestSnapshotDispatch` — verifies `"snapshot"` is in `_STEP_DISPATCH` and points to `_run_snapshot`.
- `TestSnapshotValidation` — verifies missing `output`, `elf`, and `baseline` (for `on_anomaly`) return `passed=False` with appropriate error strings.
- `TestSnapshotManualTrigger` — verifies always-capture behavior, default trigger, forwarding of `output_path`/`elf_path` to `capture_snapshot`, exception handling, and unknown trigger fallthrough.
- `TestSnapshotOnFaultTrigger` — verifies capture when `fault_detected=True` or `faulted=True`, and skip when no fault.
- `TestSnapshotOnAnomalyTrigger` — verifies capture when `anomaly_count >= 1`, skip when `0`, and correct baseline forwarding to `_run_eabctl`.

---

### Patterns Followed (Already Present)

- `_run_fault_check` in `eab/cli/regression/steps.py` — pattern for checking fault state via `_run_eabctl`.
- `_run_anomaly_watch` in `eab/cli/regression/steps.py` — pattern for anomaly check via `_run_eabctl`.
- `_run_sleep` in `eab/cli/regression/steps.py` — minimal step pattern (timing + StepResult).
- `_STEP_DISPATCH` dict at the bottom of `steps.py` — where all steps are registered.

---

### Watch Out For

- The implementation catches bare `Exception` around `capture_snapshot()` (line 767) — this is intentional to surface hardware errors as `StepResult.error` strings rather than crashing the regression runner.
- `chip` defaults to `"nrf5340"` in the `capture_snapshot` call (line 753) when `chip` is `None` — this is a hardcoded default matching the `capture_snapshot` signature's own default.
- The `on_fault` branch passes `--elf` to `fault-analyze` (line 700), unlike `_run_fault_check` which treats `elf` as optional — this is intentional since the snapshot step always requires `elf`.
- Do not touch `eab/snapshot.py` — it is consumed as-is via the existing import.