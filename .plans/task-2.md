Now I have enough context. Let me check what the `__all__` exports look like at the bottom of `__init__.py` and how lazy imports work in dispatch:
Now I have enough information to write the plan.

---

## Files to Modify

### 1. `eab/cli/snapshot_cmd.py` (new file)
Create the command handler module containing `cmd_snapshot()`.

### 2. `eab/cli/parser.py`
Add the `snapshot` subparser with its three required `--device`, `--elf`, `--output` arguments.

### 3. `eab/cli/dispatch.py`
Add the `if args.cmd == "snapshot":` dispatch block with a lazy import of `cmd_snapshot`.

### 4. `tests/test_cli_snapshot.py` (new file)
Add tests for the new command: parser registration, argument routing, JSON output, error handling.

---

## Approach

### `eab/cli/snapshot_cmd.py`

Create a new module following the same single-file command pattern used by `eab/cli/size_cmd.py` and `eab/cli/defmt_cmd.py`. The module contains one public function `cmd_snapshot(device, elf, output, json_mode)` that returns an `int` exit code.

At the top: `from __future__ import annotations`, stdlib imports, then `from eab.cli.helpers import _print`, then `from eab.snapshot import capture_snapshot`. Inside `cmd_snapshot`, call `capture_snapshot(device=device, elf=elf, output=output)` within a `try`/`except` block catching `ValueError`, `FileNotFoundError`, and `RuntimeError`. On success with `json_mode=True`, build the dict `{"path": result.path, "regions": result.regions, "registers": result.registers, "size_bytes": result.size_bytes}` and pass to `_print`. On success without `json_mode`, print human-readable lines (path, region count, size in bytes/KB). On failure, print the error message to `sys.stderr` (consistent with the task spec and `mcp_cmd.py`'s use of `file=sys.stderr`) and return `1`. The function signature and docstring should mirror `cmd_size` in `eab/cli/size_cmd.py`.

**UNCERTAIN:** The exact return type of `capture_snapshot()` from `eab/snapshot.py` is unknown since the file doesn't exist yet. The plan assumes it returns an object (dataclass or TypedDict instance) with `.path`, `.regions`, `.registers`, and `.size_bytes` attributes. If it returns a plain `dict`, access would use `result["path"]` etc. The implementer should check `eab/snapshot.py` once subtask 1 is complete and adjust attribute access accordingly.

### `eab/cli/parser.py`

After the existing `# --- defmt decode ---` block (around line 551), add a `# --- snapshot ---` comment block. Call `p_snapshot = sub.add_parser("snapshot", help="Capture a core snapshot from a running device")`. Then add three `required=True` arguments: `p_snapshot.add_argument("--device", required=True, ...)`, `p_snapshot.add_argument("--elf", required=True, ...)`, `p_snapshot.add_argument("--output", required=True, ...)`. The `--json` flag is **global** and does not need to be added to the subparser — it is already handled by the top-level parser via `_preprocess_argv` and is available as `args.json`. Mirror the argument style of `p_defmt_decode` (line 555–557) for `--elf` and use `p_fault` (line 166+) for `--device`.

### `eab/cli/dispatch.py`

After the `if args.cmd == "size":` block (around line 519–525), add an `if args.cmd == "snapshot":` block. Inside it, lazily import `from eab.cli.snapshot_cmd import cmd_snapshot` and call it with keyword arguments: `device=args.device`, `elf=args.elf`, `output=args.output`, `json_mode=args.json`. Return the result. This mirrors the pattern used by the `"size"` and `"usb-reset"` blocks exactly.

### `tests/test_cli_snapshot.py`

Create a new test file following the same structure as `tests/test_cli_entry_points.py`'s `TestProfileCommands` class. Write a class `TestSnapshotCommand` with tests for:
- Parser registration: using `from eab.cli import _build_parser`, verify `snapshot` is registered, missing required args cause `SystemExit`, and all three required args parse correctly into `args.device`, `args.elf`, and `args.output`.
- Dispatch/routing: using `from unittest.mock import patch` to patch `eab.cli.snapshot_cmd.cmd_snapshot`, call `from eab.control import main` with well-formed args and verify `cmd_snapshot` was called with the right keyword arguments.
- JSON flag: verify `json_mode=True` is passed when `--json` is given.
- Failure case: mock `cmd_snapshot` to return `1` and verify the main function returns `1`.

---

## Patterns to Follow

1. **`cmd_size` in `eab/cli/size_cmd.py`** — single-file command handler pattern: imports, one public `cmd_XXX` function, `try/except` specific exceptions, `_print` for output, returns `int`.

2. **`if args.cmd == "size":` block in `eab/cli/dispatch.py` (lines 519–525)** — lazy import pattern: `from eab.cli.size_cmd import cmd_size` inside the `if` block, pass keyword args, return the result.

3. **`p_size` parser block in `eab/cli/parser.py` (lines 546–549)** — simple `add_parser` + `add_argument` pattern for standalone (non-subcommand) commands.

4. **`p_fault` subparser arguments in `eab/cli/parser.py` (line 166+)** — how `--device`, `--elf` are defined for hardware-facing commands (use as reference for help text style).

5. **`TestProfileCommands.test_profile_commands_dispatcher_integration` in `tests/test_cli_entry_points.py` (lines 382–443)** — how to write a dispatch integration test using `monkeypatch.setattr` or `unittest.mock.patch` to mock the `eab.cli.cmd_XXX` attribute and verify call kwargs.

---

## Watch Out For

- **`--json` is a global flag** — it must NOT be added to `p_snapshot`'s argument list. It is extracted by `_preprocess_argv` and registered on the top-level parser. Accessing `args.json` in `dispatch.py` will work correctly without any extra parser definition.

- **`capture_snapshot` return type is unknown** — `eab/snapshot.py` does not exist yet (subtask 1). The `cmd_snapshot` implementation must be reviewed against the actual return type once the file is created. The plan assumes an object with `.path`, `.regions`, `.registers`, `.size_bytes`.

- **Lazy import, not `__init__.py` re-export** — commands like `size`, `defmt`, and `usb-reset` are NOT exported from `eab/cli/__init__.py`. Do not add a `from eab.cli.snapshot_cmd import cmd_snapshot` line to `__init__.py`. The dispatch uses `from eab.cli.snapshot_cmd import cmd_snapshot` inline.

- **Error output destination** — the task spec says errors go to `sys.stderr`. The dominant pattern in existing commands is `_print({'error': ...}, json_mode=json_mode)` to stdout. The implementer should print plain error text to `sys.stderr` (as done in `mcp_cmd.py`) to satisfy the spec, rather than using `_print`.

- **`args.device` name collision** — `_preprocess_argv` documents that `--device` before the subcommand is treated as a global target device. Once a subcommand is seen, `--device` arguments are subcommand-specific. Since `snapshot` uses `--device` as a required argument with its own argparse definition on `p_snapshot`, the dispatch will read `args.device` from the subcommand namespace (not the global target device), which is correct — but confirm the `--device` arg name doesn't conflict with `args.target_device` used for the daemon session path.

---

## Uncertainty

- **UNCERTAIN:** Exact API of `capture_snapshot()` (return type, exception types raised) — depends on subtask 1 output. The implementer must read `eab/snapshot.py` before implementing `cmd_snapshot`.