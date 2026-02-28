Now I have enough information to write the plan.

---

## Files to Modify

### `tests/test_cli_status_cmds.py` (new file)

Create a new test file in the top-level `tests/` directory. The file does not exist yet and must be created from scratch.

---

## Approach

### `tests/test_cli_status_cmds.py`

Create a new test file with a class `TestCmdStatus` containing tests for `cmd_status` from `eab.cli.serial.status_cmds`. The function `cmd_status` reads `check_singleton()` (imported at the module level via `from eab.singleton import check_singleton`) and returns `0` if `existing and existing.is_alive` is true, else `1`. The full logic is in `eab/cli/serial/status_cmds.py`, lines 35–80.

The tests must patch `check_singleton` at the location where it is bound in the target module: `"eab.cli.serial.status_cmds.check_singleton"`. This is the same pattern used in `tests/test_cli_daemon_cmds.py` with `monkeypatch.setattr("eab.cli.daemon.lifecycle_cmds.check_singleton", ...)`.

For the healthy scenario: patch `check_singleton` to return an `ExistingDaemon` instance with `is_alive=True`; call `cmd_status(base_dir=str(tmp_path), json_mode=True)` and assert `result == 0`. Repeat the assertion with `json_mode=False`.

For the unhealthy/not-running scenarios: patch `check_singleton` to return `None` (daemon not running), call `cmd_status` and assert `result == 1`. A second unhealthy variant patches `check_singleton` to return an `ExistingDaemon` with `is_alive=False` (stale PID file), and also asserts `result == 1`.

The `tmp_path` pytest fixture is used as `base_dir` so that the `status.json` read inside `cmd_status` gracefully returns `None` (file not found), which is an already-handled code path in the function. No actual `status.json` file needs to be present for the exit-code tests.

Place each scenario in its own test method. Follow the class-based test structure used in `tests/test_cli_daemon_cmds.py` (`class TestClearSessionFiles`) and the `monkeypatch` + `tmp_path` usage pattern seen there and in `tests/test_cli_helpers.py`.

---

## Patterns to Follow

1. **`tests/test_cli_daemon_cmds.py` → `TestClearSessionFiles.test_cmd_start_clears_session_files`** — Shows how to use `monkeypatch.setattr` with the full dotted module path to patch `check_singleton`, and how to use `tmp_path` as the `base_dir`.

2. **`tests/test_cli_daemon_cmds.py` → `TestClearSessionFiles.test_cmd_start_early_return_does_not_clear_files`** — Shows patching `check_singleton` to return a mock object with `.pid` and `.is_alive` attributes when you want to simulate a running daemon.

3. **`tests/test_cli_entry_points.py` → `TestControlEntryPoint.test_control_status_json`** — Shows calling `cmd_status`-level functionality through `main(["status", "--json"])` and asserting `isinstance(result, int)`, a lighter integration pattern that can complement the unit tests.

4. **`eab/cli/serial/status_cmds.py` → `cmd_status`** — The exact return logic at line 80: `return 0 if (existing and existing.is_alive) else 1`. Tests should exercise all three branches: `existing is None`, `existing.is_alive is False`, and `existing.is_alive is True`.

5. **`eab/singleton.py` → `ExistingDaemon`** — Dataclass with required fields `pid`, `is_alive`, `port`, `base_dir`, `started`; optional fields `device_name`, `device_type`, `chip`. Tests must construct instances with at minimum the required fields to avoid `TypeError`.

---

## Watch Out For

- **Patch target must be `"eab.cli.serial.status_cmds.check_singleton"`**, not `"eab.singleton.check_singleton"`, because `cmd_status` uses a bound name from its own module's import (`from eab.singleton import check_singleton`).
- **`ExistingDaemon` is a dataclass** — it requires positional-or-keyword arguments for all non-defaulted fields (`pid`, `is_alive`, `port`, `base_dir`, `started`). Do not construct it with only `is_alive=True`; supply all required fields.
- **`cmd_status` reads `status.json` inside `tmp_path`** — using `tmp_path` as `base_dir` means `FileNotFoundError` is raised and caught, setting `status` to `None`. This is safe and already handled; do not create a `status.json` unless a specific test needs to validate JSON-output content rather than exit code.
- **The non-JSON `status` command** (plain-text mode) is tested by calling `cmd_status(..., json_mode=False)` — it prints to stdout, but the exit-code logic is identical to JSON mode (line 80 is outside any branch). No additional mocking of `print` is needed; use `capsys` only if verifying output, which is not required for exit-code tests.
- **Do not modify `eab/cli/serial/status_cmds.py`** — the exit-code behavior is already implemented correctly at line 80 and no source changes are needed.

---

## Uncertainty

- **UNCERTAIN: where the test file should live** — the task says "follow existing test patterns and fixtures in the test suite," and both `tests/` (top-level) and `eab/tests/` (inline) directories exist. The top-level `tests/` directory is the primary location for CLI tests (all `test_cli_*.py` files live there), making `tests/test_cli_status_cmds.py` the most consistent choice, but the task does not explicitly state this.