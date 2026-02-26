Now I have enough context to write the plan. Let me also check the `generate_memory_dump_script` function to understand how to best use GDB for reading memory.
Good. Segment fields are `p_vaddr`, `p_memsz`, `p_filesz`, etc. accessed via `segment['p_vaddr']`.

Now I have all the context needed to write the plan.

---

### Files to Modify

**New file to create:** `eab/snapshot.py`

---

### Approach

#### `eab/snapshot.py` — new module

**Module-level structure:** Start with a module docstring describing the snapshot/coredump pipeline (mirroring the architecture comment style in `eab/fault_analyzer.py`). Group imports: stdlib (`datetime`, `struct`, `tempfile`, `os`, `logging`, `pathlib`) then external (`elftools`) guarded in a try/except like `eab/cli/dwt/_helpers.py`, then internal (`eab.gdb_bridge`).

**`MemoryRegion` dataclass:** A `frozen=True` dataclass (matching the style of `GDBServerStatus` in `eab/debug_probes/base.py`) with fields `start: int` and `size: int`. This is used in `SnapshotResult`.

**`SnapshotResult` dataclass:** A plain (non-frozen) dataclass (matching `FaultReport` in `eab/fault_decoders/base.py`), with fields: `output_path: str`, `regions: list[MemoryRegion]` (defaulting to empty list via `field(default_factory=list)`), `registers: dict[str, int]` (defaulting to empty dict), `total_size: int = 0`, and `timestamp: datetime` (defaulting to `field(default_factory=datetime.utcnow)`).

**`_parse_elf_load_segments(elf_path: str) -> list[MemoryRegion]`:** Private helper. Validate that `elf_path` exists (raise `ValueError` if not, mirroring `ValueError` for validation in the conventions). Open the ELF with pyelftools (guard the import like `eab/cli/dwt/_helpers.py`'s `_PYELFTOOLS_AVAILABLE` pattern, use `with open(elf_path, "rb") as f: elf = ELFFile(f)`). Call `elf.iter_segments(type="PT_LOAD")` and collect `MemoryRegion(start=seg['p_vaddr'], size=seg['p_memsz'])` for each segment where `p_memsz > 0`. If pyelftools is not available, raise `ImportError`. Return the list sorted by `start`.

**`_read_registers(chip: str, target: str, elf: Optional[str]) -> dict[str, int]`:** Private helper. Build a list of GDB commands: `"monitor halt"`, then `"info registers"` (to get R0-R15, xPSR, sp, lr, pc), then individual reads for special registers using `"x/wx 0x<addr>"` for `CONTROL` (read via `"p/x $control"`), `FAULTMASK`, `BASEPRI`, `PRIMASK` — these are best read using GDB's `p/x $<regname>` commands since they're not visible in `info registers`. Call `run_gdb_batch(chip=chip, target=target, elf=elf, commands=commands)` (from `eab.gdb_bridge`). Parse the result using a regex matching the same `_GDB_REG_RE` pattern from `eab/fault_analyzer.py`'s `_parse_gdb_registers`. For the special registers, parse `p/x` output using a pattern like `\$\d+\s*=\s*(0x[0-9a-fA-F]+)` keyed by command order. Return the merged dict.

**`_read_memory_regions(chip: str, target: str, regions: list[MemoryRegion], elf: Optional[str]) -> list[tuple[MemoryRegion, bytes]]`:** Private helper. For each region, use `generate_memory_dump_script` from `eab.gdb_bridge` to create a GDB Python script, write it to a `tempfile.NamedTemporaryFile`, then call `run_gdb_python` (from `eab.gdb_bridge`) to read the region into a temporary binary file, and read back the bytes. Collect `(region, data_bytes)` tuples. Log a warning (using the module-level `logger = logging.getLogger(__name__)`) if any region fails and substitute empty bytes. Return the list.

**`_write_elf_core(output_path: str, regions_data: list[tuple[MemoryRegion, bytes]], registers: dict[str, int]) -> int`:** Private helper. Produce a valid ELF32 core file using `struct.pack`. The layout is: ELF header (`ET_CORE = 4`, `EM_ARM = 40`, `EV_CURRENT = 1`), then program headers — first a `PT_NOTE` segment pointing to the NT_PRSTATUS note, then one `PT_LOAD` per memory region. Build the NT_PRSTATUS note by packing registers in the standard ARM `prstatus` layout (registers are packed in order: `r0`–`r15`, `xpsr`, and padding). Use `struct.pack` with little-endian format strings throughout. Return the total bytes written. The function opens `output_path` with `open(output_path, "wb")` in a `with` block.

The ELF32 header is 52 bytes, each program header is 32 bytes. Compute offsets accordingly: note segment immediately follows all program headers, then memory regions follow in order. This is well-defined and not dependent on any existing codebase pattern.

**`capture_snapshot(device: str, elf_path: str, output_path: str, *, chip: str = "nrf5340", target: str = "localhost:3333") -> SnapshotResult`:** Public orchestration function. 1) Validate `elf_path` (raise `ValueError` if it does not exist). 2) Call `_parse_elf_load_segments(elf_path)`. 3) Call `_read_registers(chip, target, elf_path)`. 4) Call `_read_memory_regions(chip, target, regions, elf_path)`. 5) Call `_write_elf_core(output_path, regions_data, registers)`. 6) Return a `SnapshotResult` populated with all fields including `timestamp=datetime.utcnow()`. Follow the pipeline structure of `analyze_fault` in `eab/fault_analyzer.py`.

---

### Patterns to Follow

- **`FaultReport` dataclass** in `eab/fault_decoders/base.py` — use same `@dataclass` style with `field(default_factory=...)` for mutable defaults; mirror for `SnapshotResult`.
- **`_parse_gdb_registers`** in `eab/fault_analyzer.py` — reuse the same `_GDB_REG_RE = re.compile(r"^(\w+)\s+(0x[0-9a-fA-F]+)\s", re.MULTILINE)` regex pattern for parsing `info registers` output into a dict.
- **`run_gdb_batch` / `run_gdb_python`** in `eab/gdb_bridge.py` — call these directly for GDB one-shot execution; no session management needed.
- **`generate_memory_dump_script`** in `eab/gdb_bridge.py` — use for generating the GDB Python script that calls `inferior.read_memory()` and writes the result to a temp file path; then call `run_gdb_python` to execute it.
- **pyelftools import guard** in `eab/cli/dwt/_helpers.py` — wrap `from elftools.elf.elffile import ELFFile` in a `try/except ImportError` block with `_PYELFTOOLS_AVAILABLE = True/False` flag, then raise `ImportError` with a helpful message in the parse function if unavailable.

---

### Watch Out For

- **`generate_memory_dump_script` signature**: It takes `start_addr: int`, `size: int`, `output_path: str`. The output path must be an actual filesystem path (use `tempfile.NamedTemporaryFile` with `delete=False` and `suffix=".bin"`, then `unlink` in a `finally` block after reading the bytes — same pattern as `run_gdb_python`'s cleanup in `eab/gdb_bridge.py`).
- **ELF core file offset arithmetic**: All program header offsets are computed from the start of the file. With 1 note phdr + N load phdrs, the note data starts at offset `52 + (1 + N) * 32`. If this is wrong, `arm-none-eabi-gdb` will fail to load the core. Be exact.
- **ARM NT_PRSTATUS register order**: The `prstatus` structure for ARM places general-purpose registers in a specific order. The standard ARM `elf_gregset_t` is 18 × 4-byte words: `r0`–`r15` (16 registers, indices 0–15), then `orig_r0` and `cpsr`/`xpsr`. Use the GDB register names to map correctly; do not mix up `sp` (r13), `lr` (r14), `pc` (r15).
- **`run_gdb_python` vs `run_gdb_batch`**: Only `run_gdb_python` can execute `inferior.read_memory()` (requires Python-enabled GDB). `run_gdb_batch` is for simple GDB commands. Memory reading must use `run_gdb_python` + `generate_memory_dump_script`. If Python-enabled GDB is unavailable, the memory dump will silently fail (non-zero return code) — log a warning and continue with empty bytes.
- **`_parse_gdb_registers` is private in `fault_analyzer.py`**: Do not import it from there. Reimplement it locally in `eab/snapshot.py` (or inline the same regex), keeping the modules independent.

---

### Uncertainty

- **UNCERTAIN: Special Cortex-M registers via GDB**: `CONTROL`, `FAULTMASK`, `BASEPRI`, `PRIMASK` are banked registers. GDB exposes them as `$control`, `$faultmask`, `$basepri`, `$primask` via `p/x $<name>` in batch mode, but exact availability depends on whether the GDB binary supports them. If `p/x $control` returns an error, the register dict will simply be missing those keys — the plan should note this gracefully.
- **UNCERTAIN: NT_PRSTATUS note format**: The precise byte layout of the note name (`"CORE\0"`) and the `prstatus` struct padding varies between Linux ABI versions. The plan assumes the minimal ARM32 layout common to `arm-none-eabi-gdb` core loading. If the output file is rejected by GDB, the note header format may need adjusting.