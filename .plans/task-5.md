I'll start by reading all the relevant files in parallel to understand the codebase structure.
Now let me read the remaining relevant files:
Now let me read the regression steps file and one similar existing unit test for comparison:
Now let me check the GDBResult structure in gdb_bridge:
Now I have enough context. Let me verify the current test count and check the gdb_bridge import:
I have all the context I need. Here is the plan:

---

## Files to Modify

### `tests/unit/test_snapshot.py`

**What needs to change:** Add two new test classes at the end of the file — one covering the CLI `cmd_snapshot` JSON output (`test_snapshot_cli_json_output`) and one covering the HIL regression step trigger conditions (`test_snapshot_step_trigger_conditions`). The file already contains 29 passing tests (classes `TestElfParsing`, `TestRegisterReading`, `TestMemoryReading`, `TestCoreFileFormat`, `TestSnapshotResult`, `TestEdgeCases`) that cover task items 1–5. Items 6 and 7 are absent from this file and must be added.

---

## Approach

### Adding `TestSnapshotCliJsonOutput` (task item 6)

Add this class after the existing `TestEdgeCases` class at the bottom of `tests/unit/test_snapshot.py`. The test mocks `eab.snapshot.capture_snapshot` (which is what `cmd_snapshot` calls internally) using `unittest.mock.patch`. It constructs a real `SnapshotResult` object (the concrete class is already imported at the top via `from eab.snapshot import ... SnapshotResult`) and uses `pytest`'s `capsys` fixture to capture stdout. It then calls `cmd_snapshot` from `eab.cli.snapshot_cmd` directly with `json_mode=True` and asserts that the captured stdout parses as valid JSON containing the keys `path`, `regions`, `registers`, and `size_bytes`. Import `cmd_snapshot` inside the test method (as a local import matching the pattern in `tests/test_cli_snapshot.py::TestSnapshotCmd::test_success_json_output`).

The `MemoryRegion` class is already imported. A `SnapshotResult` with `regions=[MemoryRegion(start=0x20000000, size=0x8000)]`, `registers={"r0": 1, "pc": 2}`, and a non-zero `total_size` provides enough to assert all four required JSON keys. Mirror the mock target `"eab.snapshot.capture_snapshot"` used in `tests/test_cli_snapshot.py::TestSnapshotCmd`.

### Adding `TestSnapshotStepTriggerConditions` (task item 7)

Add this class immediately after `TestSnapshotCliJsonOutput`. It imports `_run_snapshot` and `StepSpec` from `eab.cli.regression.steps` and `eab.cli.regression.models` respectively. Three test methods cover the three trigger values:

- **manual**: patch `eab.cli.regression.steps.capture_snapshot` to return a `MagicMock` result, confirm `capture_snapshot` is called exactly once and `result.passed` is `True`. Mirror `tests/unit/test_snapshot_step.py::TestSnapshotManualTrigger::test_manual_always_captures`.
- **on_fault**: patch `eab.cli.regression.steps._run_eabctl` to return `(0, {"fault_detected": False})`, confirm `capture_snapshot` is **not** called and `result.output["captured"]` is `False`. Then a second test with `fault_detected=True` confirms it **is** called. Mirror `tests/unit/test_snapshot_step.py::TestSnapshotOnFaultTrigger`.
- **on_anomaly**: patch `_run_eabctl` to return `(0, {"anomaly_count": 0})`, confirm no capture; then with `anomaly_count=1`, confirm capture is called. Mirror `tests/unit/test_snapshot_step.py::TestSnapshotOnAnomalyTrigger`.

Use `unittest.mock.MagicMock` and `patch` for all external calls. The `StepSpec` and `_run_snapshot` are already tested in `test_snapshot_step.py`, so this class only needs the minimal set to satisfy "verify it only calls capture_snapshot under the right conditions." Use `tmp_path` only if a real output path is needed — for these trigger tests a string literal is sufficient since `capture_snapshot` is mocked.

Add `from unittest.mock import MagicMock` to the existing imports block (currently only `patch` is imported from `unittest.mock`).

---

## Patterns to Follow

1. **`tests/unit/test_snapshot_step.py::TestSnapshotManualTrigger`** — shows the exact `StepSpec` construction, `patch("eab.cli.regression.steps.capture_snapshot", ...)`, and assertions on `result.passed` and `result.output["captured"]`.

2. **`tests/unit/test_snapshot_step.py::TestSnapshotOnFaultTrigger`** — shows how to patch `_run_eabctl` and how to assert `mock_capture.assert_not_called()` vs `mock_capture.assert_called_once()`.

3. **`tests/test_cli_snapshot.py::TestSnapshotCmd::test_success_json_output`** — shows the exact mock target path (`"eab.snapshot.capture_snapshot"`), `capsys` usage, and `json.loads(captured.out)` assertion pattern for the CLI JSON output test.

4. **`tests/unit/test_snapshot.py::TestSnapshotResult::_capture`** — shows the helper method pattern used within a test class for shared setup, and how `SnapshotResult` / `MemoryRegion` are instantiated.

5. **`tests/unit/test_ble_steps.py::TestBleScanStep`** — shows the broader class/method naming convention and `patch` context manager usage for unit tests in `tests/unit/`.

---

## Watch Out For

- **Import location:** `cmd_snapshot` must be imported inside the test method body (e.g., `from eab.cli.snapshot_cmd import cmd_snapshot`) — the module does a lazy `from eab.snapshot import capture_snapshot` inside the function body, so the mock target must be `"eab.snapshot.capture_snapshot"`, not `"eab.cli.snapshot_cmd.capture_snapshot"`. Confirm by reading `snapshot_cmd.py` line 31: `from eab.snapshot import capture_snapshot`.

- **`on_anomaly` requires `baseline` param:** `_run_snapshot` returns `passed=False` early if `trigger == "on_anomaly"` and `baseline` is missing. The test class must include `"baseline": "baselines/nominal.json"` in the step params to reach the `_run_eabctl` call.

- **`MagicMock` not yet imported:** The current `tests/unit/test_snapshot.py` imports only `patch` from `unittest.mock`. `MagicMock` must be added to that import line to construct mock `capture_snapshot` return values for the step trigger tests.

- **`json` not yet imported:** `tests/unit/test_snapshot.py` does not currently import `json`. It must be added to the stdlib imports section for `TestSnapshotCliJsonOutput` to call `json.loads(captured.out)`.

- **Do not modify `test_snapshot_step.py` or `test_cli_snapshot.py`** — these files already exist and cover those same subjects; the new classes in `test_snapshot.py` are intentionally minimal and complementary, not replacements.

---

## Uncertainty

- **UNCERTAIN:** The exact mock return value shape expected by `capture_snapshot` in the step trigger tests. The `MagicMock` approach from `test_snapshot_step.py::_make_snapshot_result()` works for `_run_snapshot` because it only accesses `.output_path`, `.total_size`, and `.regions` attributes on the result — a plain `MagicMock()` with those attributes set (or auto-specced) is sufficient.