Now I have all the context I need. Let me verify the exact location in dispatch.py where the `dwt` block ends:
All files are now fully understood. Here is the plan:

---

## Files to Modify

| File | Change |
|------|--------|
| `eab/cli/parser.py` | Add `p_dwt_explain` subparser with 5 arguments inside the existing `dwt_sub` subparsers block |
| `eab/cli/dispatch.py` | Add `if args.dwt_action == "explain":` branch inside the existing `if args.cmd == "dwt":` block; add `cmd_dwt_explain` to the import line |
| `eab/cli/dwt/explain_cmd.py` | New file containing `cmd_dwt_explain` function |
| `eab/cli/dwt/__init__.py` | Add `cmd_dwt_explain` to the imports and `__all__` list |

---

## Approach

### `eab/cli/parser.py`

After the `p_dwt_clear` block (line 619, after `p_dwt_clear.add_argument("--probe-selector", default=None)`), add a new `# dwt explain` comment block and register `p_dwt_explain = dwt_sub.add_parser("explain", ...)`. Then add five arguments:
- `--device` as optional str (default None), mirroring `p_dwt_list.add_argument("--device", ...)` — no `required=True`
- `--symbols` as required str
- `--elf` as required str
- `--duration` as `type=int`, default 5
- `--json` is **not** registered here — it is a global flag on the top-level parser (see line 87: `parser.add_argument("--json", ...)`); the subcommand inherits it via `args.json`

Mirror the style of `p_dwt_clear` and `p_dwt_list` argument blocks for argument help text and kwarg ordering.

### `eab/cli/dispatch.py`

In the `if args.cmd == "dwt":` block (starting at line 547), the import line on line 548 currently imports four names from `eab.cli.dwt`. Extend it to also import `cmd_dwt_explain`. Then, after the `if args.dwt_action == "clear":` block (line 585–590), add an `if args.dwt_action == "explain":` block that calls `cmd_dwt_explain` passing `device`, `symbols`, `elf`, `duration`, and `json_mode=args.json`.

### `eab/cli/dwt/explain_cmd.py`

Create this new file following the exact structure of `watch_cmd.py`: `from __future__ import annotations`, stdlib imports (`json`), then `from eab.dwt_explain import run_dwt_explain`. Define `cmd_dwt_explain(*, device, symbols, elf, duration, json_mode)` with type hints (`Optional[str]`, `list[str]`, `str`, `int`, `bool`) and a Google-style docstring. Inside:
1. Split the `symbols` string on commas and strip whitespace to get a `list[str]`.
2. Call `run_dwt_explain(device=device, symbols=symbols_list, elf=elf, duration=duration)` and capture the return value.
3. If `json_mode` is True, print `json.dumps(result, indent=2)`.
4. Otherwise, print `result["ai_prompt"]`.
5. Return `0`.

### `eab/cli/dwt/__init__.py`

Add `from .explain_cmd import cmd_dwt_explain` on a new line after the four existing imports. Add `"cmd_dwt_explain"` to `__all__`.

---

## Patterns to Follow

1. **`eab/cli/parser.py` lines 615–619** — `p_dwt_clear` argument registration block: use this exact style (same indentation, comment prefix `# dwt explain`, `dwt_sub.add_parser(...)`) for the new `p_dwt_explain` block.

2. **`eab/cli/parser.py` lines 610–613** — `p_dwt_list` uses `default=None` for `--device` (no `required=True`): mirror this for the optional `--device` in `explain`.

3. **`eab/cli/dispatch.py` lines 547–590** — the `if args.cmd == "dwt":` dispatch block with its import line and `if args.dwt_action == ...:` branches: add `cmd_dwt_explain` to the import tuple and append a new branch after `clear`.

4. **`eab/cli/dwt/watch_cmd.py`** — `cmd_dwt_watch` function structure: header imports, optional-dep guard, function signature with keyword-only args and type hints, Google docstring, body logic.

5. **`eab/cli/dwt/__init__.py`** — four-line import + `__all__` pattern: extend both lists by one entry.

---

## Watch Out For

- **`--json` is a global flag**, not a subcommand flag. Do not add `--json` to `p_dwt_explain`. The handler accesses it via `args.json` because `_preprocess_argv` hoists it to the front and the top-level parser owns it (line 87 of `parser.py`).

- **`eab.dwt_explain` does not yet exist** in the repo. The `explain_cmd.py` must import `run_dwt_explain` from it, but this module will need to exist for the handler to run. The parser and CLI wiring can be added without the module being present; the import is deferred into the handler function (or at module top-level — follow the style of the other cmd files, which import at module top).

- **`--symbols` stores a comma-separated string** in the parsed namespace. The splitting into a list happens inside `cmd_dwt_explain`, not in the parser. The parser registers `--symbols` as a plain `str` (not `nargs`).

- **`--duration` is `type=int`** (not `type=float` as used in `dwt watch` and `dwt halt`). The task explicitly says `int`.

- **Do not touch** `eab/cli/dwt/watch_cmd.py`, `halt_cmd.py`, `list_cmd.py`, `clear_cmd.py`, or `_helpers.py` — they are not in scope.

---

## Uncertainty

**UNCERTAIN**: The exact signature expected by `run_dwt_explain` in `eab.dwt_explain` is unknown since the module does not exist yet. The plan assumes it accepts `device`, `symbols` (as a list), `elf`, and `duration` as keyword arguments based solely on the task description. If the actual signature differs when that module is created, the call in `cmd_dwt_explain` will need to match it.