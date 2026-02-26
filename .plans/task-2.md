Now I have enough context to write the plan. Let me verify one last detail:
---

## Files to Modify

### New files to create:

1. **`eab/thread_inspector.py`** — New module defining `ThreadInfo` TypedDict and `inspect_threads()` function
2. **`eab/cli/threads/__init__.py`** — Package init exporting `cmd_threads_snapshot` and `cmd_threads_watch`
3. **`eab/cli/threads/snapshot_cmd.py`** — Implements `cmd_threads_snapshot()`
4. **`eab/cli/threads/watch_cmd.py`** — Implements `cmd_threads_watch()`
5. **`tests/test_cli_threads_cmds.py`** — Unit tests for both new CLI commands

### Existing files to modify:

6. **`eab/cli/parser.py`** — Replace the flat `threads` subparser with a subcommand group containing `snapshot` and `watch`
7. **`eab/cli/dispatch.py`** — Replace the flat `threads` dispatch block with a `threads_action`-based dispatch
8. **`eab/cli/__init__.py`** — Add imports and `__all__` entries for `cmd_threads_snapshot` and `cmd_threads_watch`

---

## Approach

### `eab/thread_inspector.py`

Define a `ThreadInfo` TypedDict with fields: `name` (str), `state` (str), `priority` (int), `stack_used` (int), `stack_size` (int), `stack_free` (int). Define `inspect_threads(device: str, elf: str) -> list[ThreadInfo]` as a public function with a Google-style docstring. The implementation connects to the J-Link device using pylink (mirroring the pattern in `eab/dwt_profiler.py` — guard the import with a try/except and raise `ImportError` with a helpful message if absent), uses the ELF file for Zephyr kernel symbol resolution, reads the thread linked list from memory, and returns populated `ThreadInfo` dicts. Use `_ensure_pylink_available()` as a private guard (same pattern as `dwt_profiler.py`'s `_ensure_pylink_available`).

### `eab/cli/threads/snapshot_cmd.py`

Define `cmd_threads_snapshot(*, device: str, elf: str, json_mode: bool) -> int`. Call `inspect_threads(device=device, elf=elf)`. On `--json`, print `json.dumps([dict(t) for t in threads])` to stdout. Without `--json`, print a fixed-width table with header row (Name, State, Priority, Stack Used, Stack Size, Stack Free) and one row per thread using ljust/rjust string formatting — mirror how `dwt_watch_cmd.py` handles its plain-text vs JSON output path. Return 0 on success, 1 on `ImportError` (pylink missing), printing the error via `_print` from `eab.cli.helpers`.

### `eab/cli/threads/watch_cmd.py`

Define `cmd_threads_watch(*, device: str, elf: str, interval: float, json_mode: bool) -> int`. In a `try`/`except KeyboardInterrupt` loop, call `inspect_threads(device=device, elf=elf)`, then either: (a) without `--json` — clear the terminal with `print("\033[2J\033[H", end="")` and reprint the same fixed-width table as snapshot, or (b) with `--json` — emit one JSON object per iteration via `print(json.dumps({...thread_list..., "timestamp": ...}), flush=True)` (JSONL format, adding a `timestamp` field via `_now_iso()` from `eab.cli.helpers`). Sleep `interval` seconds between polls using `time.sleep`. On `KeyboardInterrupt`, return 0 cleanly. Mirror the loop pattern from `cmd_anomaly_watch()` in `eab/cli/anomaly_cmds.py`.

### `eab/cli/threads/__init__.py`

Export `cmd_threads_snapshot` and `cmd_threads_watch` from their respective modules, following the pattern of `eab/cli/dwt/__init__.py`.

### `eab/cli/parser.py`

Locate the existing block starting at `p_threads = sub.add_parser("threads", ...)` and replace it entirely with a subcommand group. Define `p_threads = sub.add_parser("threads", help="Thread inspection commands")`, then `threads_sub = p_threads.add_subparsers(dest="threads_action", required=True)`. Add `p_threads_snapshot = threads_sub.add_parser("snapshot", ...)` with `--device` (required), `--elf` (required), `--json` (store_true). Add `p_threads_watch = threads_sub.add_parser("watch", ...)` with `--device` (required), `--elf` (required), `--interval` (type=float, default=5), `--json` (store_true). Follow the exact pattern of the `p_rtt`/`rtt_sub` and `p_dwt`/`dwt_sub` blocks already in the file.

Note: The `--json` flag for these subcommands should be a local argument on each subparser, since the subparsers don't inherit the global `--json` flag from the top-level parser by default in this codebase (the global one lives on the top-level parser and is accessed as `args.json`).

### `eab/cli/dispatch.py`

Locate the existing block `if args.cmd == "threads":` and replace its body. The new body should import `cmd_threads_snapshot` and `cmd_threads_watch` from `eab.cli.threads` and dispatch on `args.threads_action`. The `snapshot` branch calls `cmd_threads_snapshot(device=args.device, elf=args.elf, json_mode=args.json)`. The `watch` branch calls `cmd_threads_watch(device=args.device, elf=args.elf, interval=args.interval, json_mode=args.json)`. Follow the pattern of the `dwt` block in dispatch.py (lazy import inside the branch, dispatch on `args.dwt_action`).

### `eab/cli/__init__.py`

Add `from eab.cli.threads import cmd_threads_snapshot, cmd_threads_watch` after the existing `from eab.cli.debug import ...` import group, and add both names to `__all__`. Keep the existing `cmd_threads` and `cmd_watch` imports from `eab.cli.debug` untouched, since those functions still exist in `eab/cli/debug/inspection_cmds.py` and existing tests reference them.

### `tests/test_cli_threads_cmds.py`

Write tests for `cmd_threads_snapshot` and `cmd_threads_watch` following the class/method pattern in `tests/test_cli_debug_gdb_commands.py`. Use `unittest.mock.patch` to mock `eab.cli.threads.snapshot_cmd.inspect_threads` and `eab.cli.threads.watch_cmd.inspect_threads`. Test: (1) snapshot JSON output is a valid JSON array of thread dicts, (2) snapshot table output contains header row, (3) watch JSON mode emits JSONL with timestamp field, (4) watch handles KeyboardInterrupt and returns 0, (5) ImportError from inspect_threads returns exit code 1. Use `capsys` for output capture.

---

## Patterns to Follow

- **`eab/cli/dwt/__init__.py`** — template for the new `eab/cli/threads/__init__.py` (minimal re-export pattern)
- **`eab/cli/dwt/watch_cmd.py`** (`cmd_dwt_watch`) — plain-text vs JSON output branching with `_emit_error`, KeyboardInterrupt loop, pylink guard
- **`eab/cli/anomaly_cmds.py`** (`cmd_anomaly_watch`) — streaming loop with `try`/`except KeyboardInterrupt: return 0` at the outermost level
- **`eab/dwt_profiler.py`** (`_ensure_pylink_available`, pylink import guard pattern) — template for the `inspect_threads` module's optional dependency handling
- **`eab/cli/parser.py`** (`p_rtt`/`rtt_sub` block, `p_dwt`/`dwt_sub` block) — template for converting the flat `threads` parser into a subcommand group with `dest="threads_action"` and `required=True`

---

## Watch Out For

- **Existing `threads` dispatch collision**: `dispatch.py` currently has `if args.cmd == "threads": return cli.cmd_threads(...)`. The old block must be replaced entirely; leaving it alongside a new block would shadow the new dispatch.
- **Global `--json` flag vs subcommand `--json`**: The top-level `--json` is parsed before the subcommand and stored as `args.json`. Subcommand-local parsers in this codebase (like `dwt watch`) do NOT define their own `--json`; they rely on the global one. The new `snapshot` and `watch` parsers should follow this same convention — do not add `--json` to the subparsers; `args.json` is already set by the top-level parser.
- **`cmd_threads` and `cmd_watch` in `eab/cli/__init__.py` and `eab/cli/debug/__init__.py`**: These names are still exported because existing tests in `tests/test_cli_debug_gdb_commands.py` import them directly. Do not remove them.
- **`threads_action` dest name**: Must be `threads_action` (not `action` or `cmd`) to avoid clobbering `args.action` used by `openocd` and other commands that also use `action` as their subparser dest.
- **`_now_iso()` is private in `eab/cli/helpers.py`**: It is not listed in any `__all__` but is accessible via direct import. Import it as `from eab.cli.helpers import _now_iso` — following the same pattern as `_print`.

---

## Uncertainty

- **UNCERTAIN: `inspect_threads()` internal mechanism** — The task says to create `eab/thread_inspector.py` with this function, but gives no hint about whether it uses pylink, GDB, or another approach internally. The plan describes a pylink-based approach mirroring `dwt_profiler.py`, but the exact Zephyr memory layout traversal details are not established by any existing code in the codebase.
- **UNCERTAIN: `--json` flag scope** — Verified that all existing subcommand groups (rtt, dwt, dwt halt, trace, etc.) do NOT add a local `--json` argument; they rely on the top-level parser's `args.json`. The plan assumes the same for the new `threads` subcommands, which means `args.json` is available in dispatch.py when handling `threads snapshot`/`watch`. If a subcommand test patches at the command function level and passes `json_mode` directly, this is unaffected.