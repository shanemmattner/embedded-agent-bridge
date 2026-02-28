Now I have enough information. Let me verify the exact structure of `_print` and how it integrates:
I have all the information needed. Here is the plan:

---

## Files to Modify

### `tests/test_cli_status_cmds.py`

Add a new class `TestCmdStatusJsonBody` at the end of the file, after the existing `TestCmdStatusExitCodes` class. The new class introduces test methods that capture stdout via `capsys` and verify the JSON payload structure for both healthy (exit 0) and unhealthy (exit 1) scenarios.

---

## Approach

### `tests/test_cli_status_cmds.py`

A new class `TestCmdStatusJsonBody` should be appended after the last line of `TestCmdStatusExitCodes`. Each test method in the new class will call `cmd_status` with `json_mode=True`, then call `capsys.readouterr()` on its `.out` attribute, parse the captured string with `json.loads`, and assert on the structure.

**For the healthy (exit 0) case:** write `status.json` via `_write_status(tmp_path, "connected", "healthy")`, monkeypatch `check_singleton` to return `_make_existing(is_alive=True)`, call `cmd_status`, capture stdout, parse JSON, then assert all of: `schema_version == 1`, `"daemon"` key is present and not `{"running": False}`, `"status"` key equals the written status dict, and that the return code is 0.

**For the unhealthy (exit 1, not running) case:** monkeypatch `check_singleton` to return `None` (no daemon), call `cmd_status` with `json_mode=True`, capture stdout, parse JSON, then assert `daemon == {"running": False}`, `"status"` key is `None`, and the return code is 1.

**For the unhealthy (exit 1, disconnected) case:** write `status.json` with `"disconnected"/"error"`, monkeypatch `check_singleton` to return `_make_existing(is_alive=True)`, call `cmd_status` with `json_mode=True`, capture stdout, parse JSON, then assert `"status"` key contains `connection.status == "disconnected"` and the return code is 1.

The `capsys` fixture is a built-in pytest fixture — no imports needed; add it as a parameter to the method signature, following the exact pattern seen in `tests/unit/test_dwt_explain.py` at `test_json_mode_prints_valid_json` and `tests/unit/test_thread_inspector.py` at `test_json_output_is_valid_array`.

The `_write_status` helper and `_make_existing` helper already exist at module level in `test_cli_status_cmds.py` and must be reused as-is.

---

## Patterns to Follow

- **`tests/unit/test_dwt_explain.py` → `TestCmdDwtExplainJsonMode.test_json_mode_prints_valid_json`**: captures stdout with `capsys`, calls `capsys.readouterr()`, passes `.out` to `json.loads`, then asserts on keys in the parsed dict. Mirror this exactly.
- **`tests/unit/test_thread_inspector.py` → `TestCliSnapshotJsonOutput.test_json_output_is_valid_array`**: same `capsys.readouterr().out` pattern, demonstrates the `capsys` fixture as a method parameter alongside `_mock`.
- **`tests/test_cli_status_cmds.py` → `TestCmdStatusExitCodes.test_json_mode_returns_0_when_running_and_healthy`**: the monkeypatching of `eab.cli.serial.status_cmds.check_singleton` and the invocation of `cmd_status(base_dir=str(tmp_path), json_mode=True)` must be followed identically in the new class.
- **`tests/test_cli_status_cmds.py` → `_write_status`** and **`_make_existing`**: reuse the existing module-level helper functions rather than duplicating status dict construction.

---

## Watch Out For

- `cmd_status` in `status_cmds.py` calls `check_singleton()` with **no arguments** (line 35), so the lambda patch `lambda **kwargs: ...` works (the call passes zero arguments), but ensure the new tests follow the exact same patch target string `"eab.cli.serial.status_cmds.check_singleton"`.
- When `check_singleton` returns `None`, the payload's `"daemon"` field is set to `{"running": False}` (not `None`). Assert against this literal dict, not `None`.
- When `status.json` is absent, `status` in the payload is `None` — `json.dumps` will serialize this as `null`, so `json.loads` will give Python `None`. Assert `parsed["status"] is None`.
- The JSON output is produced by `_print` via `json.dumps(obj, indent=2, sort_keys=True)`. Keys in the output will be in alphabetical order. This doesn't affect key-presence assertions but is worth knowing if asserting exact string fragments.
- Do **not** modify `test_cli_status_cmd.py` — it is a separate, parallel test file and is not the right place for additions per project convention (the `test_cli_status_cmds.py` file is the more complete and better-documented one).

---

## Uncertainty

**UNCERTAIN**: It is not immediately clear whether the task expects the new tests to live in `test_cli_status_cmds.py` (the more complete file) or whether a brand new third file should be created. Given the task says "find the existing test file" and both files exist, `test_cli_status_cmds.py` is the better match because its module docstring already explicitly mentions the `status --json` behavior the task is focused on.