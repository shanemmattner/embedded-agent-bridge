Now I have a complete picture. Let me write the plan.

---

## Files to Modify

### `eab/cli/dwt/explain_cmd.py`
Fix the `run_dwt_explain` keyword argument names (they don't match the actual function signature in `eab/dwt_explain.py`), and add `ValueError` handling that prints an error message and returns exit code `1`.

### `eab/cli/parser.py`
No change required. The `explain` subparser registration is already complete and correct in this file: it adds `--device` (optional), `--symbols` (required), `--elf` (required), and `--duration` (int, default 5). The `--json` flag is the global top-level flag, consistent with all other DWT subcommands.

---

## Approach

### `eab/cli/parser.py`
The `explain` subparser is already registered inside the `_build_parser` function, directly after the `dwt clear` block. All four arguments (`--device`, `--symbols`, `--elf`, `--duration`) are defined with the correct types, defaults, and `required=` flags as specified by the task. The global `--json` flag (defined on the top-level parser) is passed through by `dispatch.py` as `json_mode=args.json`. No edits are needed here.

### `eab/cli/dwt/explain_cmd.py`
The existing `cmd_dwt_explain` function calls `run_dwt_explain` with the keyword arguments `elf=elf` and `duration=duration`, but the actual signature of `run_dwt_explain` in `eab/dwt_explain.py` uses `elf_path` and `duration_s`. These two kwargs must be corrected to `elf_path=elf` and `duration_s=duration`. Additionally, a `try/except ValueError` block must wrap the call to `run_dwt_explain`; on `ValueError`, the handler should print the error message to stderr (or stdout, matching the pattern in `watch_cmd.py` which uses plain `print`) and return `1`. Mirror the error-handling pattern from `eab/cli/dwt/watch_cmd.py` which catches `SymbolNotFoundError` and returns `2` (adapt for `ValueError` → return `1` as the task specifies).

---

## Patterns to Follow

- **`eab/cli/dwt/watch_cmd.py` — `cmd_dwt_watch`**: Shows the convention for catching domain-specific errors and returning integer exit codes (`1` for missing deps, `2` for user input errors). Use this for the ValueError catch-and-return-1 pattern.
- **`eab/cli/dwt/list_cmd.py` — `cmd_dwt_list`**: Shows the pattern for `json_mode` branching: `print(json.dumps(...))` vs plain `print(...)`.
- **`eab/cli/dispatch.py` — `dwt` block (lines 546–598)**: Shows how `args.json` (the global flag) is passed as `json_mode=args.json` to all DWT handlers including `cmd_dwt_explain`.
- **`eab/dwt_explain.py` — `run_dwt_explain`**: Authoritative source for the correct parameter names: `symbols`, `duration_s`, `elf_path`, `device`.
- **`eab/cli/dwt/__init__.py`**: Confirms `cmd_dwt_explain` is already exported; no change needed there.

---

## Watch Out For

- **Wrong kwarg names are the critical bug.** `run_dwt_explain`'s signature uses `elf_path` and `duration_s`; calling it with `elf=` and `duration=` will raise `TypeError` at runtime, not `ValueError` — so the ValueError handler alone won't catch this. The kwarg fix must be applied first.
- **`--json` is not a subcommand-level flag.** It is defined on the top-level parser and reordered before the subcommand by `_preprocess_argv`. Do not add a second `--json` argument to `p_dwt_explain`; doing so would conflict with the global flag.
- **`run_dwt_explain` raises `ValueError` (not `SymbolNotFoundError`)** because it internally re-raises `SymbolNotFoundError` as `ValueError`. The catch block must target `ValueError` specifically, not a broader type.
- **Return `1`, do not call `sys.exit(1)`.** All other DWT command handlers return integer exit codes; the `main` function in `dispatch.py` returns this value to the shell. Calling `sys.exit` directly would bypass any cleanup in the caller.
- **`parser.py` and `dispatch.py` are already correct** — do not modify them. All the dispatch wiring and parser arguments are present and complete.

---

## Uncertainty

No significant uncertainty. All referenced files were read and all cited names verified:
- `run_dwt_explain` signature confirmed in `eab/dwt_explain.py` line 395.
- `cmd_dwt_explain` confirmed in `eab/cli/dwt/explain_cmd.py` line 11.
- Explain subparser registration confirmed in `eab/cli/parser.py` lines 622–630.
- Dispatch block confirmed in `eab/cli/dispatch.py` lines 591–598.