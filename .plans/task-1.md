Now I have everything I need. Let me write the plan.

---

## Files to Modify

### `eab/cli/serial/status_cmds.py`
Replace the final return statement in `cmd_status` with logic that inspects `status.json` health and connection fields rather than checking only whether the daemon process is alive.

### `tests/test_cli_status_cmd.py` *(new file)*
Add a test module covering the exit-code semantics of `cmd_status` in both `json_mode=True` and `json_mode=False`, using monkeypatching and `tmp_path` fixtures.

---

## Approach

### `eab/cli/serial/status_cmds.py`

The bug is on the last line of `cmd_status`. The original line is:

```
return 0 if (existing and existing.is_alive) else 1
```

This bases the exit code solely on whether the daemon PID is alive. It returns 1 whenever `check_singleton()` finds no live process—even if `status.json` clearly shows the daemon is healthy and connected. Conversely, it returns 0 whenever a process is alive, even if the connection is broken.

Immediately after the `if json_mode` / `else` block (lines 64–78 in the current file), introduce a boolean `healthy` that is `True` only when all four conditions hold: `status` is not `None`, `status` contains no `"error"` key, `status["connection"]["status"] == "connected"`, and `status["health"]["status"]` is one of `{"healthy", "idle"}`. Replace the original one-liner return with `return 0 if healthy else 1`. The docstring return annotation should be updated to reflect that 0 means healthy/connected and 1 means not running or unhealthy.

No other logic in the function changes. The `payload` construction, the `json_mode` branch, and the plain-text branch all remain identical.

### `tests/test_cli_status_cmd.py`

Create this file in the `tests/` directory (alongside the existing `tests/test_cli_status_cmds.py`). The file must:

- Import `cmd_status` from `eab.cli.serial.status_cmds` inside each test method (lazy import, matching the pattern used in `tests/test_cli_status_cmds.py`).
- Monkeypatch `eab.cli.serial.status_cmds.check_singleton` using `lambda **kwargs: mock` to return a controlled `ExistingDaemon` or `None`.
- Write fixture `status.json` into `tmp_path` using `(tmp_path / "status.json").write_text(json.dumps(...))` when simulating a running daemon.
- Cover: `json_mode=True` → exit 0 when connected+healthy; `json_mode=True` → exit 0 when connected+idle; `json_mode=True` → exit 1 when disconnected; `json_mode=True` → exit 1 when no `status.json`; `json_mode=True` → exit 1 when `status.json` is invalid JSON; `json_mode=False` → exit 0 when healthy; `json_mode=False` → exit 1 when not running; cross-mode consistency assertions.

Follow the structure of `tests/test_cli_status_cmds.py` exactly: helper functions `_make_existing` and `_make_status`/`_write_status`, a single `class TestCmdStatusExitCode`, and individual test methods named `test_returns_0_when_*` / `test_returns_1_when_*`.

---

## Patterns to Follow

- **`cmd_tail` in `eab/cli/serial/status_cmds.py`** — the unconditional `return 0` pattern shows how other subcommands signal success; `cmd_status` needs a conditional return instead.
- **`cmd_status` plain-text branch (lines 67–78)** — the existing `if existing and existing.is_alive` guard used only for printing; the `healthy` variable should be computed separately after the print block, not mixed into it.
- **`TestCmdStatusExitCodes` class in `tests/test_cli_status_cmds.py`** — test class structure, `_run` helper method, `monkeypatch.setattr` targeting `"eab.cli.serial.status_cmds.check_singleton"`, and `tmp_path` / `tmp_path_factory` fixture usage.
- **`_make_existing` helper in `tests/test_cli_status_cmds.py`** — minimal `ExistingDaemon` construction with keyword-only args; the same helper should appear in the new test file.
- **`ExistingDaemon` dataclass in `eab/singleton.py`** — fields `pid`, `is_alive`, `port`, `base_dir`, `started`; used directly in test fixtures.

---

## Watch Out For

- The `healthy` boolean must **not** include a check on `existing.is_alive`. If the daemon process has died but `status.json` still reports connected+healthy (stale file), the function correctly returns 0 under the new logic. The acceptance criteria says exit code is driven by `status.json`, not PID liveness. Mixing in `existing.is_alive` would cause a regression for the `test_json_mode_returns_1_when_daemon_stale_pid` test, which passes `is_alive=False` but no `status.json` (so `status is None` makes `healthy` False anyway).
- `check_singleton()` in `singleton.py` accepts an optional `device_name` keyword argument; tests monkeypatch it as `lambda **kwargs: mock`. The production call `check_singleton()` (no args) is correct and must not be changed.
- The `"error"` key check (`"error" not in status`) guards against the `json.JSONDecodeError` branch that sets `status = {"error": "invalid_json", ...}`. This must remain part of the `healthy` condition.
- `status.get("health", {}).get("status") in {"healthy", "idle"}` — both values must be accepted; tests cover both `"healthy"` and `"idle"`.
- Do **not** move the `healthy` computation above the `if json_mode` / `else` block; the block must complete before the return so output is always emitted regardless of exit code.

---

## Uncertainty

**UNCERTAIN: why the original code caused exit code 1 specifically when healthy.** The original `return 0 if (existing and existing.is_alive) else 1` returns 1 only when `check_singleton()` yields `None` or a stale PID. The most likely real-world trigger is that `check_singleton()` is called without a `device_name`, so it looks in the default (empty-named) device directory and finds no PID file even though a daemon is running under a different device name. The fix (using `status.json` for the healthy determination) sidesteps this entirely. However, the exact runtime scenario was not confirmed from the files read.