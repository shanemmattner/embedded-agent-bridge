# Issue #15: Automatic Backtrace/Address Decoding with addr2line

## Summary

Implemented multi-target backtrace decoding for embedded systems using addr2line. The implementation automatically detects backtrace formats from ESP-IDF, Zephyr, and GDB outputs, then resolves addresses to source file:line locations.

## Changes

### 1. New Module: `eab/backtrace.py`

Created comprehensive backtrace decoder with:

- **Multi-format detection and parsing:**
  - ESP-IDF: `Backtrace:0x400d1234:0x3ffb5678 0x400d5678:0x3ffb9abc`
  - Zephyr fatal errors: `E: r15/pc: 0x0000xxxx` and register dumps
  - GDB backtraces: `#0  0x0000xxxx in func_name () at file.c:123`

- **Toolchain discovery:**
  - Auto-detects correct addr2line binary for architecture (arm, xtensa, riscv)
  - Searches PATH and SDK directories (Zephyr SDK, ESP-IDF toolchains)
  - Supports explicit toolchain path override

- **Address resolution:**
  - Batch addr2line invocation for efficiency
  - Handles missing ELF files gracefully
  - Filters unknown symbols (`??:0`)
  - Timeout protection (10s default)

- **Human-readable and JSON output:**
  - Formatted multi-line output with source locations
  - Optional raw backtrace line display
  - Machine-parseable JSON for agent integration

### 2. CLI Command: `eabctl decode-backtrace`

Added `eab/cli/backtrace_cmds.py` with new command:

```bash
# Decode from stdin
cat crash.log | eabctl decode-backtrace --elf build/app.elf --arch esp32

# Decode from text argument
eabctl decode-backtrace --elf build/zephyr.elf --arch nrf5340 --text "E: r15/pc: 0x0800abcd"

# JSON output for agents
eabctl decode-backtrace --elf app.elf --arch arm --json < backtrace.txt

# Show raw backtrace lines
eabctl decode-backtrace --elf app.elf --arch stm32 --show-raw
```

**CLI arguments:**
- `--elf` (required): Path to ELF file with debug symbols
- `--text` (optional): Backtrace text (reads from stdin if omitted)
- `--arch` (default: arm): Architecture hint for toolchain selection
- `--toolchain` (optional): Explicit path to addr2line binary
- `--show-raw`: Include raw backtrace lines in output
- `--json`: Machine-parseable JSON output

### 3. Integration Points

Wired into `eab/cli/__init__.py`:
- Added backtrace command to subparser list
- Added command dispatcher in `main()`
- Import from `eab.cli.backtrace_cmds`

### 4. Comprehensive Test Suite: `tests/test_backtrace.py`

45 tests covering:

**Format Parsers (12 tests):**
- ESP-IDF single/multiple address pairs
- Zephyr PC register and fatal error dumps
- GDB full frames, frames without addresses, frames without source
- Edge cases: no backtrace, case insensitivity, leading whitespace

**Toolchain Discovery (6 tests):**
- Auto-detection for ESP32 Xtensa, ESP32 RISC-V, ARM, nRF
- Fallback to generic addr2line
- Explicit path override

**BacktraceDecoder (13 tests):**
- Format detection (esp-idf, zephyr, gdb, unknown)
- Parse-only (no addr2line resolution)
- Address resolution with mocked addr2line output
- Multiple addresses in batch
- Unknown symbols (`??:0`)
- Missing ELF file handling
- Missing addr2line binary handling
- Full decode pipeline (parse + resolve)
- Formatting (with/without source, with raw lines, empty, errors)

**Integration Tests (2 tests):**
- ESP32 crash with full decode (Guru Meditation → source locations)
- Zephyr hard fault with register dump → source locations

**Malformed Input (5 tests):**
- Empty input
- Garbage input
- Partial ESP backtrace
- addr2line subprocess failure
- addr2line timeout

**All 45 tests pass.**

## Architecture Decisions

### 1. Multi-Format Support

Rather than ESP32-only, implemented universal backtrace decoder supporting three major formats:
- ESP-IDF (Espressif chips)
- Zephyr RTOS (nRF, STM32, NXP MCX)
- GDB output (all targets)

This covers the majority of embedded development workflows in the EAB ecosystem.

### 2. Toolchain Auto-Discovery

Reuses existing `eab.toolchain.which_or_sdk()` infrastructure to find addr2line binaries:
- Searches PATH first
- Falls back to Zephyr SDK directories (`~/zephyr-sdk-*/arm-zephyr-eabi/bin/`)
- Falls back to ESP-IDF toolchain directories (`~/.espressif/tools/*/bin/`)

Supports architecture hints: `arm`, `xtensa`, `riscv`, `esp32`, `nrf5340`, `stm32`, `mcxn947`, etc.

### 3. Batch Address Resolution

Instead of calling addr2line once per address:
```python
# Efficient: one subprocess call for all addresses
result = subprocess.run(
    [addr2line, '-e', elf_path, '-f', '-C'] + addresses,
    ...
)
```

addr2line outputs 2 lines per address (function name, then file:line), which we parse in pairs.

### 4. Graceful Degradation

- **No ELF file?** → Parse addresses but skip resolution (show `??`)
- **No addr2line?** → Parse addresses but skip resolution (log warning)
- **addr2line fails?** → Parse addresses but skip resolution (log error)
- **Unknown symbols?** → Filter out `??:0` responses from addr2line

Never crashes. Always returns parsed addresses even if resolution fails.

### 5. Separate Parse and Resolve

`BacktraceDecoder` has two methods:
- `parse(text)` → Extract addresses without resolving (fast, no deps)
- `decode(text)` → Parse + resolve (slower, needs ELF + addr2line)

Allows users to inspect backtrace structure without full symbol resolution.

## Example Usage

### ESP32 Crash Decode

```bash
# Device output:
# Guru Meditation Error: Core 0 panic'ed (LoadProhibited)
# Backtrace:0x400d1234:0x3ffb5678 0x400d5678:0x3ffb9abc

cat crash.log | eabctl decode-backtrace --elf build/app.elf --arch esp32
```

Output:
```
BACKTRACE DECODE (ESP-IDF)
============================================================
  [#0] 0x400d1234 -> src/main.c:100 (app_main)
  [#1] 0x400d5678 -> components/freertos/port.c:141 (main_task)
============================================================
```

### Zephyr Hard Fault Decode

```bash
# Device output:
# E: ***** HARD FAULT *****
# E: r15/pc: 0x0800abcd

echo "E: r15/pc: 0x0800abcd" | eabctl decode-backtrace \
  --elf build/zephyr/zephyr.elf --arch nrf5340 --json
```

Output:
```json
{
  "schema_version": 1,
  "format": "zephyr",
  "entries": [
    {
      "address": "0x0800abcd",
      "function": "z_arm_hard_fault",
      "file": "/zephyr/arch/arm/core/fault.c",
      "line": 42,
      "pc_address": null,
      "raw_line": "E: r15/pc: 0x0800abcd"
    }
  ]
}
```

### GDB Backtrace Decode

```bash
# GDB output from `eabctl fault-analyze`
eabctl fault-analyze --device NRF5340_XXAA_APP --elf build/zephyr.elf --json \
  | jq -r '.backtrace' \
  | eabctl decode-backtrace --elf build/zephyr.elf --arch nrf5340
```

## Future Integration

Ready for integration into `eab/pattern_matcher.py`:

```python
from eab.backtrace import BacktraceDecoder

class AlertLogger:
    def __init__(self, elf_path=None, arch='arm'):
        self._decoder = BacktraceDecoder(elf_path=elf_path, arch=arch) if elf_path else None
    
    def log_alert(self, match: AlertMatch) -> None:
        # Existing alert logging...
        
        # If backtrace detected and decoder configured, decode and append
        if self._decoder and self._decoder.detect_format(match.line) != 'unknown':
            result = self._decoder.decode(match.line)
            if result.entries:
                decoded = self._decoder.format_result(result)
                self._fs.write_file(self._alerts_path, decoded + "\n", append=True)
```

This would automatically append decoded backtraces to `alerts.log` when:
1. ELF path is configured in daemon config
2. A crash pattern is detected
3. addr2line is available

## Testing Results

```
============================= test session starts ==============================
tests/test_backtrace.py::TestESPBacktraceParser::test_parse_single_address_pair PASSED
tests/test_backtrace.py::TestESPBacktraceParser::test_parse_multiple_address_pairs PASSED
tests/test_backtrace.py::TestESPBacktraceParser::test_parse_no_backtrace PASSED
tests/test_backtrace.py::TestESPBacktraceParser::test_parse_case_insensitive PASSED
tests/test_backtrace.py::TestZephyrBacktraceParser::test_parse_pc_register PASSED
tests/test_backtrace.py::TestZephyrBacktraceParser::test_parse_pc_with_other_registers PASSED
tests/test_backtrace.py::TestZephyrBacktraceParser::test_parse_error_prefix PASSED
tests/test_backtrace.py::TestZephyrBacktraceParser::test_parse_filters_low_addresses PASSED
tests/test_backtrace.py::TestZephyrBacktraceParser::test_parse_no_backtrace PASSED
tests/test_backtrace.py::TestGDBBacktraceParser::test_parse_full_frame PASSED
tests/test_backtrace.py::TestGDBBacktraceParser::test_parse_multiple_frames PASSED
tests/test_backtrace.py::TestGDBBacktraceParser::test_parse_frame_without_address PASSED
tests/test_backtrace.py::TestGDBBacktraceParser::test_parse_frame_without_source PASSED
tests/test_backtrace.py::TestGDBBacktraceParser::test_parse_no_backtrace PASSED
tests/test_backtrace.py::TestToolchainDiscovery::test_get_addr2line_esp32_xtensa PASSED
tests/test_backtrace.py::TestToolchainDiscovery::test_get_addr2line_esp32_riscv PASSED
tests/test_backtrace.py::TestToolchainDiscovery::test_get_addr2line_arm PASSED
tests/test_backtrace.py::TestToolchainDiscovery::test_get_addr2line_nrf PASSED
tests/test_backtrace.py::TestToolchainDiscovery::test_get_addr2line_not_found PASSED
tests/test_backtrace.py::TestToolchainDiscovery::test_get_addr2line_explicit_path PASSED
tests/test_backtrace.py::TestBacktraceDecoder::test_detect_format_esp_idf PASSED
tests/test_backtrace.py::TestBacktraceDecoder::test_detect_format_zephyr PASSED
tests/test_backtrace.py::TestBacktraceDecoder::test_detect_format_gdb PASSED
tests/test_backtrace.py::TestBacktraceDecoder::test_detect_format_unknown PASSED
tests/test_backtrace.py::TestBacktraceDecoder::test_parse_esp_backtrace PASSED
tests/test_backtrace.py::TestBacktraceDecoder::test_parse_zephyr_backtrace PASSED
tests/test_backtrace.py::TestBacktraceDecoder::test_parse_gdb_backtrace PASSED
tests/test_backtrace.py::TestBacktraceDecoder::test_resolve_addresses PASSED
tests/test_backtrace.py::TestBacktraceDecoder::test_resolve_multiple_addresses PASSED
tests/test_backtrace.py::TestBacktraceDecoder::test_resolve_unknown_address PASSED
tests/test_backtrace.py::TestBacktraceDecoder::test_resolve_addresses_no_elf PASSED
tests/test_backtrace.py::TestBacktraceDecoder::test_resolve_addresses_no_addr2line PASSED
tests/test_backtrace.py::TestBacktraceDecoder::test_decode_full_pipeline PASSED
tests/test_backtrace.py::TestBacktraceDecoder::test_format_result_with_source PASSED
tests/test_backtrace.py::TestBacktraceDecoder::test_format_result_without_source PASSED
tests/test_backtrace.py::TestBacktraceDecoder::test_format_result_with_raw PASSED
tests/test_backtrace.py::TestBacktraceDecoder::test_format_result_empty PASSED
tests/test_backtrace.py::TestBacktraceDecoder::test_format_result_error PASSED
tests/test_backtrace.py::TestBacktraceIntegration::test_esp32_crash_decode PASSED
tests/test_backtrace.py::TestBacktraceIntegration::test_zephyr_hardfault_decode PASSED
tests/test_backtrace.py::TestMalformedInput::test_empty_input PASSED
tests/test_backtrace.py::TestMalformedInput::test_garbage_input PASSED
tests/test_backtrace.py::TestMalformedInput::test_partial_esp_backtrace PASSED
tests/test_backtrace.py::TestMalformedInput::test_addr2line_failure PASSED
tests/test_backtrace.py::TestMalformedInput::test_addr2line_timeout PASSED
============================== 45 passed in 0.05s =============================
```

## Files Modified

- **New:** `eab/backtrace.py` - Core backtrace decoder (14KB, 405 lines)
- **New:** `eab/cli/backtrace_cmds.py` - CLI command implementation (2.6KB, 85 lines)
- **New:** `tests/test_backtrace.py` - Test suite (21KB, 595 lines)
- **Modified:** `eab/cli/__init__.py` - Added command to CLI parser

## Compatibility

- **Python:** 3.8+ (uses type hints, dataclasses, pathlib)
- **Dependencies:** None (uses subprocess, re from stdlib)
- **Toolchains:** Works with any addr2line-compatible toolchain
- **Platforms:** macOS, Linux (tested on macOS)

## Known Limitations

1. **No FreeRTOS backtrace support yet** - Could be added by extending pattern matchers
2. **No ARM exception frame parsing** - Zephyr parser extracts PC but not full exception frame
3. **Daemon integration not implemented** - Ready but requires configuration changes to `pattern_matcher.py`
4. **No inline function support** - addr2line `-i` flag not used (could be added)

## Deliverables

✅ `eab/backtrace.py` with `BacktraceDecoder` class  
✅ Multi-format detection (ESP-IDF, Zephyr, GDB)  
✅ Toolchain-specific addr2line discovery  
✅ CLI command `eabctl decode-backtrace`  
✅ Human-readable and JSON output  
✅ 45 comprehensive tests (all passing)  
✅ Graceful error handling (missing ELF, missing toolchain, malformed input)

## Next Steps (Not Included in This PR)

1. **Wire into pattern_matcher.py** for automatic backtrace decoding when alerts fire
2. **Add daemon config option** for ELF path and arch (e.g., `elf_path: build/app.elf`)
3. **Extend GDB integration** - `eabctl fault-analyze` could auto-decode its backtrace output
4. **Add FreeRTOS support** - Detect FreeRTOS task stack dumps
5. **Add inline function support** - Use `addr2line -i` flag for inlined calls
