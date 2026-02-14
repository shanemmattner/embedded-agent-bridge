# EAB CLI Refactoring Plan

Splitting large monolithic CLI command files into modular packages for better maintainability and LLM comprehension.

## Completed Phases

### ✅ Phase 3b: flash_cmds.py → flash/ package (PR #110, merged)
- **Original**: 1,116 lines
- **Split into**: 11 files
- **Test results**: 48/48 passing
- **Structure**:
  ```
  eab/cli/flash/
  ├── __init__.py           # Public API exports
  ├── _detection.py         # ESP-IDF project detection
  ├── _execute.py           # Flash execution logic
  ├── _helpers.py           # Port detection utilities
  ├── _retries.py           # Retry logic
  ├── chip_info_cmd.py      # Chip info command
  ├── erase_cmd.py          # Erase command
  ├── flash_cmd.py          # Main flash orchestrator
  ├── preflight_cmd.py      # Pre-flight checks
  └── reset_cmd.py          # Reset command
  ```

### ✅ Phase 3a: daemon_cmds.py → daemon/ package (PR #111, merged)
- **Original**: 486 lines
- **Split into**: 5 files
- **Test results**: 60/60 passing
- **Structure**:
  ```
  eab/cli/daemon/
  ├── __init__.py              # Public API exports
  ├── _helpers.py              # Internal helpers
  ├── lifecycle_cmds.py        # start, stop, pause, resume
  ├── health_cmds.py           # diagnose
  └── device_mgmt_cmds.py      # devices, device_add, device_remove
  ```

### ✅ Phase 3c: debug_cmds.py → debug/ package (PR #112, ready)
- **Original**: 692 lines
- **Split into**: 5 files
- **Test results**: 12/12 passing
- **Structure**:
  ```
  eab/cli/debug/
  ├── __init__.py              # Public API exports
  ├── _helpers.py              # _build_probe helper
  ├── openocd_cmds.py          # OpenOCD server management (4 commands)
  ├── gdb_cmds.py              # GDB batch/script execution (2 commands)
  └── inspection_cmds.py       # Variable/memory inspection (4 commands)
  ```

## Remaining Phases

### Phase 3d: serial_cmds.py → serial/ package
- **Current**: 453 lines, 14K
- **Commands**: cmd_status, cmd_tail, cmd_alerts, cmd_events, cmd_send, cmd_wait, cmd_wait_event, cmd_capture_between
- **Proposed structure**:
  ```
  eab/cli/serial/
  ├── __init__.py              # Public API exports
  ├── _helpers.py              # Internal helpers
  ├── status_cmds.py           # status, tail, alerts, events
  ├── interaction_cmds.py      # send, wait, wait_event
  └── capture_cmds.py          # capture_between
  ```

### Phase 3e: profile_cmds.py → profile/ package
- **Current**: 450 lines, 17K
- **Commands**: cmd_profile_function, cmd_profile_region, cmd_dwt_status
- **Proposed structure**:
  ```
  eab/cli/profile/
  ├── __init__.py              # Public API exports
  ├── _helpers.py              # Shared DWT/profiling helpers
  ├── function_cmds.py         # profile_function
  ├── region_cmds.py           # profile_region
  └── dwt_cmds.py              # dwt_status
  ```

## Files NOT Being Refactored

### parser.py - 459 lines (SKIP)
**Reason**: Single cohesive function (_build_parser) with all subcommand definitions. Splitting would make it harder to see all CLI arguments at once. Already well-organized.

### dispatch.py - 15K (SKIP for now)
**Reason**: Main dispatcher - can be tackled after all command modules are split.

### Smaller files (<10K) - SKIP
- fault_cmds.py - 2.5K
- stream_cmds.py - 4.5K
- var_cmds.py - 6.6K
- rtt_cmds.py - 3.1K
- binary_capture_cmds.py - 4.3K
- reset_cmds.py - 1.8K
- backtrace_cmds.py - 2.5K
- helpers.py - 3.4K

These are already manageable sizes.

## Refactoring Pattern

All refactors follow this pattern (established in PRs #110, #111):

1. **Create package directory**: `eab/cli/{name}/`
2. **Create __init__.py**: Export all public cmd_* functions
3. **Split by logical groupings**: Group related commands together
4. **Internal helpers**: Prefix with `_` and put in `_helpers.py`
5. **Update main __init__.py**: Change import from module to package
6. **Find and update tests**: Search for old imports and update
7. **Fix test patches**: Point to where functions are USED, not defined
8. **Delete old file**: After tests pass
9. **Commit with standard message**: Include structure, test results
10. **Create PR**: Don't merge yet (wait for review)

## Testing Strategy

For each refactor:
```bash
# Find affected tests
grep -r "from eab.cli.{module}_cmds import" tests/ eab/tests/

# Run affected tests
python3 -m pytest tests/test_*{module}* -v

# Verify imports work
python3 -c "from eab.cli.{module} import cmd_*; print('OK')"
```

## Success Criteria

Each refactor must:
- ✅ All tests passing (100%)
- ✅ Imports work correctly
- ✅ No breaking changes to public API
- ✅ Clear separation of concerns
- ✅ File sizes 100-400 lines each
- ✅ Hardware tested (daemon commands)

## Timeline

- ✅ Completed: flash, daemon, debug (3/5 major refactors)
- 🔄 Remaining: serial, profile (2/5 major refactors)
- Target: Complete all by end of session
