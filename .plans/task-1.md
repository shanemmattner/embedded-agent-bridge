Now I have all the information I need. Let me write the plan.

---

## Files to Modify

### 1. `eab/cli/serial/status_cmds.py`
Modify the `cmd_status` function — specifically the return statement at line 80 and the helper logic that determines healthy/connected status from the `status` dict.

### 2. `tests/test_cli_status_cmd.py` *(new file)*
Create a new test file covering the exit-code behaviour of `cmd_status` under JSON and non-JSON modes, with healthy, unhealthy, and missing-daemon scenarios.

---

## Approach

### `eab/cli/serial/status_cmds.py` — `cmd_status`

The bug is on line 80: `return 0 if (existing and existing.is_alive) else 1`. When `check_singleton()` is called with no `device_name` argument, `SingletonDaemon.__init__` receives `device_name=""` and constructs a PID-file path like `<devices_dir>/daemon.pid` — not `<devices_dir>/default/daemon.pid` where the actual daemon writes its PID. Because the file path is wrong, `get_existing()` returns `None`, `existing` is `None`, and the function always returns 1 regardless of whether the daemon is actually running and healthy.

The fix is to make the exit-code determination use the `status` dict (already read from `status.json`) rather than — or in addition to — the unreliable singleton check. Following the pattern used in `cmd_diagnose` (same file's sibling, `health_cmds.py`), derive a `healthy` boolean by testing:

- `status` is not `None` and does not have an `"error"` key
- `status.get("connection", {}).get("status") == "connected"`
- `status.get("health", {}).get("status") in {"healthy", "idle"}`

Replace the final `return` with `return 0 if healthy else 1`, where `healthy` is that boolean. The `if json_mode` / `else` printing block above the return does not need to change; both branches already fall through to the same return statement, so no separate `return 0` is needed for the JSON path.

The `existing` variable (singleton check) should remain in the function because it is used to build the `payload["daemon"]` field and drives the human-readable print block — just stop using it for the exit-code decision.

### `tests/test_cli_status_cmd.py`

Create a new test file following the exact pattern of `tests/test_cli_helpers.py` and `tests/test_cli_daemon_cmds.py`: top-level class per concern, `monkeypatch`/`patch` for filesystem and singleton, `tmp_path` for the `base_dir`, and `capsys` to check output.

Add a `TestCmdStatusExitCode` class with these test methods:

1. **`test_returns_0_when_connected_and_healthy`** — write a `status.json` with `connection.status = "connected"` and `health.status = "healthy"`, patch `check_singleton` to return a mock alive daemon, assert return value is 0 for both `json_mode=True` and `json_mode=False`.
2. **`test_returns_0_when_connected_and_idle`** — same but `health.status = "idle"`.
3. **`test_returns_1_when_connection_not_connected`** — write a `status.json` with `connection.status = "disconnected"`, assert return is 1.
4. **`test_returns_1_when_status_json_missing`** — do not create `status.json`, assert return is 1.
5. **`test_returns_1_when_health_starting`** — write `status.json` with `health.status = "starting"` and `connection.status = "starting"` (the placeholder written by `cmd_start`), assert return is 1.
6. **`test_json_mode_same_exit_code_as_text_mode`** — verify that `json_mode=True` and `json_mode=False` produce the same exit code for both healthy and unhealthy states (guards against a future regression where the JSON path diverges).

---

## Patterns to Follow

- **`cmd_diagnose` in `eab/cli/daemon/health_cmds.py`** — exact pattern for reading `connection.status` and `health.status` from the `status` dict and deriving a `healthy` boolean; use `status.get("connection", {}).get("status")` and `status.get("health", {}).get("status") in {"healthy", "idle"}`.
- **`TestClearSessionFiles` in `tests/test_cli_daemon_cmds.py`** — class-based test layout, `tmp_path` fixture, file-writing setup, assertion pattern to follow for the new test class.
- **`test_cmd_start_clears_session_files` in `tests/test_cli_daemon_cmds.py`** — shows how to monkeypatch `check_singleton` and `subprocess.Popen` for unit tests of CLI commands.
- **`TestNowIso`/`TestPrint` in `tests/test_cli_helpers.py`** — shows standard import style, `capsys` usage, and test file header conventions.

---

## Watch Out For

- **Do not change the `existing` variable usage** in the `payload["daemon"]` field or the human-readable print block — those are correct and unrelated to the exit-code bug.
- **`check_singleton()` call without `device_name`** in `cmd_status` (line 35) is intentional for payload reporting; do not add a `device_name` argument to fix the exit code — instead decouple the exit-code logic from the singleton result.
- **`status = {"error": "invalid_json", "path": ...}` path** (line 44) — the new `healthy` computation must treat this dict as unhealthy since it has an `"error"` key; a simple `"error" not in status` guard handles it.
- **`status` variable can be `None`** (line 42, `FileNotFoundError` path) — the healthy check must short-circuit on `None` before accessing nested keys.
- **Placeholder `status.json`** written by `cmd_start` sets both `connection.status` and `health.status` to `"starting"` — under the new logic this correctly returns exit code 1 (daemon started but not yet connected/healthy), which is the desired behaviour.

---

## Uncertainty

- **UNCERTAIN: whether `cmd_status` should also require `existing.is_alive` in addition to the `status.json` healthy check.** The task description says "exit code 0 is returned when the daemon status indicates it is healthy/connected" — phrasing that points to `status.json` alone — but a belt-and-suspenders guard (`existing.is_alive OR status_healthy`) would catch stale `status.json` files. The `cmd_diagnose` function only uses `status.json` for health checks (not the singleton), so following that pattern means `status.json` alone is sufficient. The implementer should use `status.json` alone for the exit-code condition, consistent with `cmd_diagnose`.