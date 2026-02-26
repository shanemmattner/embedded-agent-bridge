I'll read the relevant files before writing the plan.
Now let me read the test file for the snapshot module.
The file already exists. Let me check what's missing by running the tests and looking at any referenced files that might not exist yet.
The module at `eab/snapshot.py` already exists and is **fully implemented**. All 29 unit tests in `tests/unit/test_snapshot.py` pass, all 17 CLI snapshot tests in `tests/test_cli_snapshot.py` pass, and the module imports cleanly. No implementation work is needed.

---

### Findings

**`eab/snapshot.py` is already complete.** The file was read in full (563 lines) and contains every element specified in the task:

1. **`SnapshotResult` dataclass** — defined at line 79 with `output_path`, `regions` (list of `MemoryRegion`), `registers`, `total_size`, and `timestamp` fields.

2. **`capture_snapshot(device, elf_path, output_path, *, chip, target)`** — implemented at line 484, orchestrating:
   - `_parse_elf_load_segments()` (line 103) — uses pyelftools to extract `PT_LOAD` segments as `MemoryRegion` objects.
   - `_read_registers()` (line 152) — issues `monitor halt`, `info registers`, and `p/x` prints for MSP, PSP, CONTROL, FAULTMASK, BASEPRI, PRIMASK via `run_gdb_batch`.
   - `_read_memory_regions()` (line 208) — uses `generate_memory_dump_script` + `run_gdb_python` per region.
   - `_write_elf_core()` (line 363) — produces an ELF32 `ET_CORE` file with `PT_NOTE` (containing `NT_PRSTATUS` with ARM register layout) and `PT_LOAD` segments.

3. **Error handling** — `ValueError` for missing ELF (lines 126, 530), `ImportError` guard for pyelftools (line 119), `ValueError` for output write failure (line 474). `RuntimeError` from GDB propagates naturally (test at line 547 confirms this).

4. **Conventions** — Google-style docstrings, type hints, grouped imports (stdlib → pyelftools with try/except guard → internal `eab.gdb_bridge`).

### Test Results

| Test suite | Collected | Passed |
|---|---|---|
| `tests/unit/test_snapshot.py` | 29 | **29** |
| `tests/test_cli_snapshot.py` | 17 | **17** |

**No implementation work is required.** The task is already done.