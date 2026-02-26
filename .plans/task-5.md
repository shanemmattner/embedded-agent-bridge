Now I have enough context to write the plan. Let me also check one more file for context on how a test ELF can be created.
---

## Files to Modify

### New files to create:

1. **`eab/snapshot.py`** — New module containing `capture_snapshot` and `SnapshotResult`. This does not exist yet and must be created for the tests to import.
2. **`tests/unit/test_snapshot.py`** — New test file with all unit tests described in the task.

---

## Approach

### `eab/snapshot.py`

Create this module with two public items:

- **`SnapshotResult`** — a `@dataclass(frozen=True)` with fields: `timestamp: str`, `regions: list[dict[str, Any]]` (each region has `address`, `size`, `data`), and `size_bytes: int`. Mirror the `CaptureResult` dataclass pattern from `eab/capture.py`.

- **`capture_snapshot`** — a function accepting `elf_path: str`, a GDB-bridge callable or object (pass `read_memory` and `read_registers` as injectable callables for testability), and `output_path: str`. It should:
  1. Validate that `elf_path` exists, raising `FileNotFoundError` if not.
  2. Open the ELF with `ELFFile` from pyelftools and extract all segments where `p_type == 'PT_LOAD'`, collecting `(p_vaddr, p_filesz)` tuples for RAM regions.
  3. Call the GDB bridge's register-read function to obtain all Cortex-M registers (R0–R15 as `r0`–`r15`, `xpsr`, `msp`, `psp`, `control`, `faultmask`, `basepri`, `primask`).
  4. For each region, call the GDB bridge's memory-read function to read `p_filesz` bytes from `p_vaddr`.
  5. Write an ELF32 little-endian core file (type `ET_CORE = 4`) with one `PT_NOTE` segment (containing register values encoded as a `prstatus`-like note) and one `PT_LOAD` segment per RAM region with the captured bytes as file content.
  6. Return a `SnapshotResult` with the current UTC timestamp (ISO format), the regions list, and total `size_bytes` of the written file.

The GDB bridge interface should be injectable (pass callables `read_registers` and `read_memory` as parameters, defaulting to calling `eab.gdb_bridge.run_gdb_batch` under the hood). This allows tests to pass mock callables without patching.

The ELF core file writing should use the `struct` module to hand-craft the binary layout (ELF32 header + program headers + note + region data), since pyelftools is read-only and doesn't support writing.

Place `capture_snapshot` after any helper functions in the file. Import ordering: stdlib (`datetime`, `io`, `struct`, `pathlib`) then external (`elftools`) then internal (`eab.gdb_bridge`).

### `tests/unit/test_snapshot.py`

Create this file following the class-per-feature pattern used in `tests/unit/test_ble_central.py` and `tests/test_fault_analyzer.py`. File structure:

- Module docstring describing what is tested.
- `from __future__ import annotations` followed by grouped stdlib / external / internal imports.
- A helper function `_make_minimal_elf(tmp_path, regions)` (not a fixture) that programmatically builds a minimal ELF32 LE binary with `ET_EXEC` type and one `PT_LOAD` segment per region entry `(vaddr, size)` using `struct.pack`. Write it to `tmp_path / "test.elf"` and return the path. This replaces the need for a binary fixture file.
- A `_make_mock_gdb(registers, memory_map)` helper returning a mock object whose `.read_registers()` returns `registers` dict and `.read_memory(addr, size)` returns `memory_map[addr]`.

Test classes:

**`TestElfParsing`** — call `eab.snapshot._parse_elf_load_segments(elf_path)` (a private helper) with a `_make_minimal_elf` output and assert the returned list of `(vaddr, size)` tuples matches what was passed to the builder.

**`TestRegisterReading`** — call `capture_snapshot` with a mock GDB whose `read_registers` returns a known dict for all 14 Cortex-M registers. Verify the returned `SnapshotResult` (or a parsed PT_NOTE) contains those values. Alternatively, mock at the module level with `patch("eab.snapshot.read_registers_via_gdb", return_value=...)`.

**`TestMemoryReading`** — call `capture_snapshot` with a mock GDB that returns distinct byte patterns per region. Assert that the PT_LOAD segments in the output `.core` file contain those exact bytes (verified by re-parsing the `.core` with pyelftools).

**`TestCoreFileFormat`** — end-to-end: build a minimal ELF with two LOAD regions, call `capture_snapshot` with mocked GDB, open the resulting `.core` with pyelftools, assert `e_type == ET_CORE (4)`, assert PT_LOAD count and vaddr/size match, assert a PT_NOTE segment exists.

**`TestSnapshotResult`** — verify the returned `SnapshotResult` has a non-empty `timestamp`, the correct `regions` list length, and `size_bytes > 0`.

**`TestEdgeCases`** — two test methods: `test_missing_elf_raises` calls `capture_snapshot` with a nonexistent path and asserts `FileNotFoundError` (or `ValueError`); `test_gdb_failure_propagates` passes a mock whose `read_memory` raises `RuntimeError` and asserts that error propagates (not silently swallowed).

Use `tmp_path` from pytest for all output files. Use `unittest.mock.MagicMock` and `patch` for GDB bridge mocking, consistent with `tests/test_gdb_python_bridge.py` and `tests/test_fault_analyzer.py`.

---

## Patterns to Follow

- **`eab/capture.py` → `CaptureResult` dataclass** — mirror this frozen dataclass pattern for `SnapshotResult` (same file, same pattern of `@dataclass(frozen=True)` with typed fields).
- **`tests/unit/test_ble_central.py` → class-per-feature with `pytest.fixture` + `MagicMock`** — use the same one-class-per-concern test organization with `mock_dev = MagicMock(...)` setup in fixtures.
- **`tests/test_gdb_python_bridge.py` → `@patch("eab.gdb_bridge.subprocess.run")`** — use the same `@patch` + `MagicMock` pattern for mocking GDB bridge internals; apply `patch("eab.snapshot.<gdb_function>")` at the module level.
- **`tests/test_fault_analyzer.py` → `_make_probe()` helper** — follow the same pattern of a private `_make_*` helper function (not a fixture) that returns a pre-configured mock, used to keep individual test methods concise.
- **`eab/elf_inspect.py` → `parse_symbols()` using `ELFFile`** — the ELF reading pattern (`with open(elf_path, "rb") as f: elf = ELFFile(f)`) should be reproduced in `capture_snapshot`'s ELF loading step.

---

## Watch Out For

- **`eab/snapshot.py` does not exist yet** — the implementer must create it before the tests can be imported. The test file should import from `eab.snapshot`; if the module is missing, all tests will fail with `ImportError`.
- **pyelftools is read-only** — `ELFFile` can parse but cannot write ELF files. The core file output must be written manually using `struct.pack` to assemble the binary ELF32 layout (header, program headers, note section, region data). Do not attempt to use pyelftools for writing.
- **Cortex-M register names must match exactly** — the task specifies `R0`–`R15` (lowercase `r0`–`r15` in GDB output), `xPSR` (check whether the module uses `xpsr` or `xPSR`), `MSP`, `PSP`, `CONTROL`, `FAULTMASK`, `BASEPRI`, `PRIMASK`. The register name casing in mock data must match whatever `capture_snapshot` expects from the GDB bridge.
- **ELF core PT_NOTE format** — the `prstatus` note structure is architecture-specific. For Cortex-M (ARM 32-bit), the note type is `NT_PRSTATUS = 1`, descriptor is a fixed-size struct. Keep the note format simple enough to write and re-read in tests; if using a custom note name (e.g., `"EAB\0"`), document it clearly.
- **`tmp_path` is a `pathlib.Path`** — pass `str(tmp_path / "out.core")` to `capture_snapshot` if it expects a string path, or `Path` if it accepts `Path`. The implementer should decide on the type signature and keep it consistent.
- **pyelftools is not listed in `pyproject.toml` dependencies** — it is available in the environment but not declared as a dependency. The implementer should add it to the appropriate `[project.optional-dependencies]` group (likely `dev`) in `pyproject.toml` if the module imports it at runtime, or use a lazy import pattern.

---

## Uncertainty

**UNCERTAIN:** The exact injectable interface for the GDB bridge — the task says "Mock the GDB bridge" but `eab/gdb_bridge.py` exposes module-level functions (`run_gdb_batch`, `run_gdb_python`), not a class. The implementer may choose to either (a) pass callable arguments to `capture_snapshot` that the tests can replace with mocks, or (b) use `@patch("eab.snapshot.run_gdb_batch")` at the test level. Option (a) is more testable; option (b) is consistent with existing test patterns in the repo. Either approach is valid but the choice must be consistent between the module and the tests.

**UNCERTAIN:** Whether `_parse_elf_load_segments` should be a private helper tested directly (`TestElfParsing`) or only exercised through `capture_snapshot`. Given that the task explicitly asks to "verify that LOAD segments are correctly extracted," a private helper tested in isolation is the cleaner approach, but the implementer should confirm this matches the module design.