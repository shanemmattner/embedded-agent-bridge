I'll start by reading the target files and understanding the existing patterns.
Let me look at the existing test patterns and similar implementations:
Now let me look at the existing test in `tests/unit/test_runner_multi_device.py` and one more test file for patterns:
Now let me look at the CLI structure and how existing commands are registered:
Let me also quickly look at the regression steps dispatch and ble_steps to understand the HIL step pattern:
Now let me look at one more test and the ble_central test to confirm testing conventions:
I have enough context. Let me now write the plan.

---

## Files to Modify

### New files to create (all required for the acceptance tests to pass):

1. **`eab/thread_inspector.py`** — New module: `ThreadInfo` dataclass + `inspect_threads()` function
2. **`eab/cli/debug/thread_snapshot_cmds.py`** — New module: `cmd_threads_snapshot()` and `cmd_threads_watch()` CLI command functions
3. **`eab/cli/regression/thread_steps.py`** — New module: `_run_stack_headroom_assert()` step function + `THREAD_STEP_DISPATCH`
4. **`tests/unit/test_thread_inspector.py`** — New test file (the deliverable)

### Existing files to modify:

5. **`eab/cli/regression/steps.py`** — Import and register `THREAD_STEP_DISPATCH` into `_STEP_DISPATCH` (mirroring the `BLE_STEP_DISPATCH` pattern at the bottom of the file)

---

## Approach

### `eab/thread_inspector.py`

This module is the core. Define `ThreadInfo` as a `@dataclass(frozen=True)` with fields `name: str`, `state: str`, `priority: int`, `stack_size: int`, `stack_used: int`. Add `stack_free` as a `@property` returning `stack_size - stack_used` — or alternatively as a field computed in `__post_init__` if the dataclass is not frozen. (A `@property` requires a regular class or a dataclass with `__post_init__` field initializer — use `field(init=False)` with `__post_init__`). Add a `to_dict()` method that returns a plain dict with all five fields including `stack_free`.

The `inspect_threads()` function accepts `chip`, `target`, `elf`, and `gdb_path` keyword arguments. Internally it generates a thread inspector GDB script via `generate_thread_inspector()` from `eab.gdb_bridge`, writes it to a `tempfile.NamedTemporaryFile`, calls `run_gdb_python(...)` (imported from `eab.gdb_bridge`), reads `result.json_result["threads"]`, and constructs `ThreadInfo` objects from each dict. It propagates any exceptions raised by `run_gdb_python` without catching them (per the task requirement for test case 8). Mirror the import style of `eab/cli/debug/inspection_cmds.py`, which uses `from eab.gdb_bridge import run_gdb_python, generate_thread_inspector`.

### `eab/cli/debug/thread_snapshot_cmds.py`

`cmd_threads_snapshot()` accepts `chip`, `target`, `elf`, `gdb_path`, and `json_mode`. It calls `inspect_threads(...)` directly (imported from `eab.thread_inspector`) and prints the result as a JSON array to stdout (via `_print` from `eab.cli.helpers` or directly via `json.dumps`). No debug probe lifecycle management is needed — `inspect_threads` handles the GDB bridge call internally.

`cmd_threads_watch()` accepts the same arguments plus `interval_s: float`. It loops, calling `inspect_threads()` on each iteration, printing each result as a single JSON line with a `"timestamp"` key added (using `datetime.datetime.utcnow().isoformat()`), then sleeping. The loop exits on `KeyboardInterrupt`. This allows tests to mock `inspect_threads` to raise `KeyboardInterrupt` on the second call to terminate the loop after one iteration.

### `eab/cli/regression/thread_steps.py`

`_run_stack_headroom_assert()` follows the exact pattern of `_run_trace_validate` in `eab/cli/regression/trace_steps.py` — no subprocess call, pure logic. It reads `min_free_bytes` from `step.params`, calls `inspect_threads(...)` using connection parameters from step params (`chip`, `target`, etc.), then checks every `ThreadInfo.stack_free >= min_free_bytes`. On failure, sets `error` to a message that includes the offending thread's `name`. Define `THREAD_STEP_DISPATCH = {"stack_headroom_assert": _run_stack_headroom_assert}`. The `inspect_threads` import in this module is what tests will patch with `patch("eab.cli.regression.thread_steps.inspect_threads")`.

### `eab/cli/regression/steps.py`

At the bottom, after the `BLE_STEP_DISPATCH` import/update block, add a parallel import of `THREAD_STEP_DISPATCH` from `eab.cli.regression.thread_steps` and call `_STEP_DISPATCH.update(THREAD_STEP_DISPATCH)`.

### `tests/unit/test_thread_inspector.py`

Organized into test classes, one per feature area. All tests use `unittest.mock.patch` and `MagicMock`. No fixtures other than `capsys` (which pytest provides automatically). Import `ThreadInfo` and `inspect_threads` from `eab.thread_inspector`. Import `cmd_threads_snapshot` and `cmd_threads_watch` from `eab.cli.debug.thread_snapshot_cmds`. Import `run_step` from `eab.cli.regression.steps` and `StepSpec` from `eab.cli.regression.models`. Import `GDBResult` from `eab.gdb_bridge` to construct mock return values.

---

## Patterns to Follow

1. **`eab/cli/regression/trace_steps.py` → `_run_trace_validate()`** — The pattern for a HIL step that does pure logic without a subprocess call: reads params, runs checks, returns `StepResult` with `passed`, `error`, and `output` fields. Mirror this exactly for `_run_stack_headroom_assert`.

2. **`eab/cli/regression/ble_steps.py` + `BLE_STEP_DISPATCH` update in `steps.py`** — The pattern for registering new step dispatch entries from a separate module. Mirror this late-import update pattern for `THREAD_STEP_DISPATCH`.

3. **`tests/unit/test_ble_steps.py`** — The overall test file structure: `from __future__ import annotations`, grouped imports (stdlib → external → internal), one class per feature area, plain `assert` statements, `patch()` as context manager.

4. **`tests/test_cli_debug_gdb_commands.py` → `TestCmdGdbScript.test_successful_execution_jlink()`** — Pattern for testing CLI command functions: `@patch` decorators, construct `GDBResult`, call the command function directly, use `capsys.readouterr()` to capture stdout, parse with `json.loads`.

5. **`eab/cli/debug/inspection_cmds.py` → `cmd_threads()`** — Existing function that calls `run_gdb_python` — mirror its import style (`from eab.gdb_bridge import run_gdb_python, generate_thread_inspector`) for `thread_inspector.py`, so the correct patch target in tests is `eab.thread_inspector.run_gdb_python`.

---

## Watch Out For

- **Patch target for GDB bridge**: Because `thread_inspector.py` will do `from eab.gdb_bridge import run_gdb_python`, the correct `patch()` target in tests is `eab.thread_inspector.run_gdb_python`, **not** `eab.gdb_bridge.run_gdb_python`. The task description says "patch the function in `eab/gdb_bridge.py`" but the mock-by-name rule requires patching where the name is *used*, not where it's *defined*. See the existing pattern in `test_cli_debug_gdb_commands.py` line 119: `@patch("eab.cli.debug.gdb_cmds.run_gdb_python")`.

- **Watch mode termination in tests**: `cmd_threads_watch()` is an infinite loop. The test must mock `inspect_threads` with `side_effect=[result_list, KeyboardInterrupt()]` so the second call breaks the loop. The command must catch `KeyboardInterrupt` silently (or let it propagate — test with `pytest.raises(KeyboardInterrupt)` if needed).

- **`stack_free` as a dataclass field**: If `ThreadInfo` is `frozen=True`, `stack_free` cannot be set in `__post_init__`. Use `@dataclass` without `frozen=True` and set `stack_free` in `__post_init__` with `field(init=False, default=0)`, or use `@property` with a regular (non-frozen) dataclass. Avoid `frozen=True` for simplicity since `stack_free` is derived. The test for `to_dict()` must verify `stack_free` appears in the returned dict.

- **`_run_stack_headroom_assert` needs `inspect_threads` parameters**: The step needs a way to call `inspect_threads()`. It must read `chip` and `target` (defaulting to `"localhost:3333"`) from `step.params`, not from a probe lifecycle. Keep it simple — the test mocks `inspect_threads` directly, so the step just needs `from eab.thread_inspector import inspect_threads` at the top of `thread_steps.py`.

- **Do not modify `eab/cli/debug/inspection_cmds.py` or the existing `cmd_threads`**: The new `threads snapshot` and `threads watch` commands are distinct from the low-level `cmd_threads` that wraps the full debug probe workflow. Keep them in a new file.

---

## Uncertainty

**UNCERTAIN**: Whether the `cmd_threads_snapshot` and `cmd_threads_watch` functions should be exposed through the argparse CLI (requiring changes to `parser.py` and `dispatch.py`) or tested purely as standalone Python functions. The acceptance test only runs the unit test file, so the tests can call the functions directly without going through `main()`. The plan assumes direct function calls in tests — no argparse changes are required for the acceptance criterion, but the implementer may optionally wire them up.

**UNCERTAIN**: The exact set of fields in `ThreadInfo` beyond `name`, `state`, `priority`, `stack_size`, `stack_used`. The task description implies these five (plus computed `stack_free`). If the GDB thread inspector script produces additional fields (e.g., `cpu_usage`, `entry_fn`), the dataclass can include them as `Optional` with defaults. The tests only verify the five named fields.