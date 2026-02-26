I'll read the relevant files to understand the codebase structure before writing the plan.
Now let me check the toolchain module and look at how data_stream.py or capture.py handles JSONL streaming:
Now I have sufficient context to write the plan. Let me verify one thing about the `__init__.py` to understand public exports:
Good — `eab/__init__.py` doesn't auto-import DWT modules, so no need to register the new module there.

---

## Plan: `eab/dwt_explain.py`

### Files to Modify

- **`eab/dwt_explain.py`** — New file to create from scratch. Contains all five public functions plus TypedDicts for structured return types.

---

### Approach

**File structure and imports:**

The file opens with a module docstring mirroring the style in `eab/dwt_watchpoint.py` and `eab/dwt_profiler.py` (architectural summary, then register/constant sections). Imports are grouped in three blocks:

1. **stdlib**: `json`, `logging`, `os`, `subprocess`, `tempfile`, `time`, `typing.Optional`, `typing_extensions.TypedDict` (or `typing.TypedDict` on Python ≥3.8).
2. **external (optional)**: `pyelftools` import wrapped in try/except with `_PYELFTOOLS_AVAILABLE` flag, matching the exact pattern in `eab/cli/dwt/_helpers.py` lines 20–25. `pylink` wrapped in try/except matching `eab/dwt_watchpoint.py` lines 26–27.
3. **internal**: `from eab.toolchain import which_or_sdk`, `from eab.dwt_watchpoint import Comparator, ComparatorAllocator, DwtWatchpointDaemon, SymbolNotFoundError, _requires_write_to_clear_matched`, `from eab.cli.dwt._helpers import _resolve_symbol, _open_jlink`.

**TypedDicts** are defined after imports and before functions (mirroring the dataclass section in `dwt_profiler.py`):

- `SourceLocation` with keys `source_file: str`, `line_number: int`, `function_name: str`.
- `RawEvent` with keys `ts: int`, `label: str`, `addr: str`, `value: str`.
- `EnrichedEvent` extending the raw fields plus the three source-location keys.
- `ExplainResult` with keys `events: list[EnrichedEvent]`, `source_context: str`, `ai_prompt: str`, `suggested_watchpoints: list[str]`.

**`resolve_source_line(address: int, elf_path: str) -> SourceLocation`:**

Placed first, after the TypedDicts section. Validates that `elf_path` exists (`os.path.isfile`), raising `ValueError` if not. Discovers addr2line by trying `which_or_sdk` for `arm-none-eabi-addr2line`, `arm-zephyr-eabi-addr2line`, then `addr2line` — mirroring the ARM branch of `_get_addr2line_for_arch` in `eab/backtrace.py` lines 67–74. Runs `subprocess.run([addr2line, '-e', elf_path, '-f', '-C', hex(address)], ...)` and parses the two-line output (function name on line 0, `file:line` on line 1) exactly as `BacktraceDecoder.resolve_addresses` does in `eab/backtrace.py` lines 184–209. Returns a `SourceLocation` dict with `"??"` or `0` as fallbacks when addr2line cannot resolve.

**`capture_events(comparators: list[Comparator], jlink: Any, duration_s: float) -> list[RawEvent]`:**

Placed after `resolve_source_line`. Creates a `tempfile.NamedTemporaryFile` (suffix `.jsonl`, `delete=False`) to collect events, closes it, then starts one `DwtWatchpointDaemon` per comparator (all sharing the same `events_file` path) using `write_to_clear` defaulting to `False`. Calls `time.sleep(duration_s)`, then stops all daemons. Opens the temp file, reads and parses each line with `json.loads`, returns the list. Uses a `try/finally` to stop daemons and remove the temp file. Mirrors the daemon start/stop pattern in `watch_cmd.py` lines 139–163.

**`enrich_events(events: list[RawEvent], elf_path: str) -> list[EnrichedEvent]`:**

Placed after `capture_events`. Iterates over raw events, converts each `addr` string to int via `int(event["addr"], 16)`, calls `resolve_source_line`, merges dicts, returns `list[EnrichedEvent]`. Raises `ValueError` if `elf_path` does not exist (delegated naturally via `resolve_source_line`).

**`format_explain_prompt(enriched_events: list[EnrichedEvent]) -> ExplainResult`:**

Placed after `enrich_events`. Builds a multi-line `source_context` string by grouping events by `source_file`/`line_number`/`function_name`, counting hit frequency. Builds `ai_prompt` as a structured LLM-ready string that states how many times each symbol was hit and at which source locations, and asks for an explanation of the access pattern. Derives `suggested_watchpoints` by collecting unique `label` values from events (these are symbol names from the `Comparator.label` field already set by `run_dwt_explain`). Returns an `ExplainResult` dict.

**`run_dwt_explain(symbols: list[str], duration_s: int, elf_path: str, device: str | None = None) -> ExplainResult`:**

Placed last. Validates `elf_path` exists (`os.path.isfile`), raising `ValueError` if not. Calls `_resolve_symbol(sym, elf_path)` for each symbol; catches `SymbolNotFoundError` and re-raises as `ValueError` (task requires `ValueError` for unknown symbols). Opens a jlink connection via `_open_jlink(device)` — only if `device` is not `None`; if `device` is `None`, raises `ValueError`. Allocates comparators via `ComparatorAllocator(jlink).allocate(...)` for each symbol in a try/finally that ensures `allocator.release_all()` runs. Inside the try block, calls `capture_events(comparators, jlink, duration_s)`, then `enrich_events(events, elf_path)`, then `format_explain_prompt(enriched_events)` and returns the result.

---

### Patterns to Follow

1. **Optional pyelftools import** — `eab/cli/dwt/_helpers.py` lines 20–25: try/except import with `_PYELFTOOLS_AVAILABLE` bool flag.
2. **Optional pylink import** — `eab/dwt_watchpoint.py` lines 26–27: try/except with `pylink = None` fallback.
3. **addr2line subprocess invocation and output parsing** — `eab/backtrace.py` `BacktraceDecoder.resolve_addresses()` lines 151–214: `subprocess.run([addr2line, '-e', elf_path, '-f', '-C'] + addresses, ...)`, two lines per address.
4. **Symbol resolution (pyelftools → nm fallback)** — `eab/cli/dwt/_helpers.py` `_resolve_symbol()` lines 48–77.
5. **Daemon start/stop with duration and events_file** — `eab/cli/dwt/watch_cmd.py` `cmd_dwt_watch()` lines 139–165.

---

### Watch Out For

- **`events_file` append mode**: `DwtWatchpointDaemon._emit_event` opens the events file with `open(self._events_file, "a")` each time. Multiple daemon instances sharing the same temp file will interleave JSONL lines correctly, since `json.dumps` produces single-line output and each `write` is a complete line — no locking is needed for the read phase.
- **`_requires_write_to_clear_matched` needs a device string**: If `device` is `None`, this helper cannot be called. The `run_dwt_explain` function must require a non-None `device` before calling `_open_jlink` and `_requires_write_to_clear_matched`.
- **`SymbolNotFoundError` is a custom exception** in `eab/dwt_watchpoint.py` (not a stdlib type). The task requires `ValueError` for unknown symbols, so `run_dwt_explain` must catch `SymbolNotFoundError` and re-raise as `ValueError`.
- **Do not modify `eab/dwt_watchpoint.py`, `eab/dwt_profiler.py`, or `eab/cli/dwt/_helpers.py`** — all needed building blocks can be imported as-is.
- **`_open_jlink` is in `eab/cli/dwt/_helpers.py`**, not in `eab/dwt_profiler.py` or `eab/dwt_watchpoint.py`. Import it from there exactly.

---

### Uncertainty

- **UNCERTAIN**: The task says `capture_events` takes "a list of armed DWT watchpoint descriptors". Whether "descriptors" means raw `Comparator` objects (already allocated) or symbol-name strings is not explicit. The plan assumes `Comparator` objects (already allocated by `run_dwt_explain`), consistent with the DWT subsystem design where `ComparatorAllocator.allocate()` produces `Comparator` instances that are then passed to `DwtWatchpointDaemon`.
- **UNCERTAIN**: `format_explain_prompt` `suggested_watchpoints` semantics — the task says "symbols referenced near the hit locations". With no source-AST parsing available, the plan uses unique `label` values from the hit events as the suggested watchpoints. A richer implementation scanning nearby nm symbols is possible but requires more context the task does not specify precisely.