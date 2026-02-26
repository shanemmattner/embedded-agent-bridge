Now I have a comprehensive view of the codebase. Let me check one remaining detail about the `size_cmd` as a similar "lazy import" pattern:
I now have all the information needed to write the plan. Let me produce it.

---

## Files to Modify

### `eab/cli/parser.py`

Add the `snapshot` subparser registration — the block at lines 702–706 only registers `--device`, `--elf`, and `--output` (as `required=True`). The parser entry is present but **`--output` must stay `required=True`** (see Watch Out For below). No other changes are needed to this file; the subparser block is already at the correct location (just before `return parser`, after the anomaly block).

### `eab/cli/snapshot_cmd.py`

Create (or verify) the `cmd_snapshot()` command function. The file already exists with a full implementation — the function imports `capture_snapshot` lazily, calls it, catches `ValueError/FileNotFoundError/ImportError/RuntimeError`, prints human-readable or JSON output, and returns 0/1. No changes are needed if the file is already present with this logic.

### `eab/cli/dispatch.py`

Add the `snapshot` dispatch case. Lines 526–533 already contain the `if args.cmd == "snapshot"` block that lazy-imports `cmd_snapshot` from `eab.cli.snapshot_cmd` and calls it with `device`, `elf`, `output`, and `json_mode`. No changes are needed if this block is present.

### `eab/cli/__init__.py`

**No change needed.** `cmd_snapshot` is intentionally NOT re-exported from `eab.cli.__init__` — it uses the same lazy-import pattern as `cmd_size`, `cmd_mcp_server`, `cmd_usb_reset`, and `cmd_multi`, which are also absent from `__init__.py`'s import block and `__all__`.

---

## Approach

### `eab/cli/parser.py` — snapshot subparser block

Locate the `# --- snapshot ---` comment near the end of `_build_parser()`, just before `return parser` (currently lines 702–706). The subparser must register `--device` (required), `--elf` (required), and `--output` (required). The global `--json` flag is handled by the top-level parser and `_preprocess_argv()`, so no `--json` argument belongs on the snapshot subparser itself. This mirrors the pattern of `p_size` (lines 547–549) and `p_fault` (lines 166–174): required arguments, no local `--json`, and the subparser is a flat `sub.add_parser(...)` call (not a nested subparser group).

### `eab/cli/snapshot_cmd.py` — `cmd_snapshot()`

The file lives alongside `size_cmd.py` and `defmt_cmd.py` (same directory, same lazy-import convention). The function signature is `cmd_snapshot(device, elf, output, json_mode=False) -> int`. It must:
1. Lazy-import `capture_snapshot` from `eab.snapshot` inside a try/except ImportError block.
2. Call `capture_snapshot(device=device, elf_path=elf, output_path=output)`.
3. Catch `ValueError, FileNotFoundError, ImportError, RuntimeError` and print `f"ERROR: {exc}"` to `sys.stderr`, return 1.
4. On success, call `_print({"path": result.output_path, "regions": [{"start": r.start, "size": r.size} for r in result.regions], "registers": result.registers, "size_bytes": result.total_size}, json_mode=True)` for JSON mode, or three plain `print()` lines for human-readable mode.

Mirror the error-handling and output style of `cmd_size` in `eab/cli/size_cmd.py` and the JSON shape of `_print` calls in `eab/cli/helpers.py`.

### `eab/cli/dispatch.py` — snapshot case

Insert an `if args.cmd == "snapshot":` block in the command-dispatch chain, after the `"size"` block and before the `"defmt"` block. It must lazy-import `cmd_snapshot` from `eab.cli.snapshot_cmd` (same pattern as the `size` and `defmt` cases at lines 519–543) and pass `device=args.device`, `elf=args.elf`, `output=args.output`, `json_mode=args.json`.

---

## Patterns to Follow

- **`eab/cli/size_cmd.py` → `cmd_size()`**: Minimal standalone command module, lazy-imported in dispatch; error paths return 1 after printing to `_print` or stderr; no re-export from `__init__.py`.
- **`eab/cli/dispatch.py` lines 519–525** (`"size"` case): The canonical lazy-import dispatch pattern — `from eab.cli.XXX_cmd import cmd_XXX` inside the `if args.cmd == "..."` block.
- **`eab/cli/parser.py` lines 547–549** (`"size"` subparser): Flat `sub.add_parser(...)` with positional or `required=True` arguments, no local `--json`, no subparser nesting.
- **`eab/cli/helpers.py` → `_print()`**: Used for all JSON output; pass a plain dict with snake-case keys; `sort_keys=True` is applied automatically.
- **`eab/cli/fault_cmds.py`** (referenced in `__init__.py` line 23): Example of a command that IS imported in `__init__.py` — snapshot deliberately does NOT follow this, matching `size_cmd.py` and `defmt_cmd.py` instead.

---

## Watch Out For

- **`--output` must remain `required=True`, not `default="snapshot.core"`**. `tests/test_cli_snapshot.py::TestSnapshotParser::test_snapshot_missing_output_raises` explicitly asserts `SystemExit` when `--output` is absent. Giving it a default would make that test fail.
- **No `--json` argument on the snapshot subparser**. The `--json` flag is global, moved to the front by `_preprocess_argv()`, and parsed by the top-level parser. Adding a local `--json` to `p_snapshot` would create an argparse conflict.
- **`args.json` in dispatch, not `args.json_mode`**. The top-level parser stores the global `--json` flag as `args.json` (a boolean). Do not rename it.
- **JSON regions key is `"start"`, not `"address"`**. `tests/test_cli_snapshot.py` line 239 asserts `data["regions"][0]["start"]`. The task description says `address` — the test wins.
- **`capture_snapshot` is called with keyword arguments `device=`, `elf_path=`, `output_path=`** (not positional). The `SnapshotResult.regions` list holds `MemoryRegion` objects with `.start` and `.size` attributes; `.registers` is `dict[str, int]`; `.total_size` is `int`; `.output_path` is `str`.

---

## Uncertainty

**UNCERTAIN**: Whether the `eab/cli/snapshot_cmd.py` file is being created from scratch or already exists. At read-time it was fully populated — if it was scaffolded by a prior subtask, the implementer only needs to verify correctness rather than write from scratch. The same applies to the `dispatch.py` snapshot block (lines 526–533) and the `parser.py` snapshot block (lines 702–706). All three locations appeared complete with passing tests when examined. The implementer should run `python3 -m pytest tests/test_cli_snapshot.py --tb=short -q` as a first step; if all 17 tests pass, no code changes are required.