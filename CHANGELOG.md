# Changelog

All notable changes to this project will be documented in this file.

The format is based on [Keep a Changelog](https://keepachangelog.com/en/1.1.0/),
and this project adheres to [Semantic Versioning](https://semver.org/spec/v2.0.0.html).

## [Unreleased]

### Added
- C2000 DSS transport — persistent JTAG session via TI CCS Python scripting API
- C2000 register decode (`eabctl reg-read`), ERAD profiler status, DLOG buffer capture
- C2000 variable streaming from live targets (`eabctl stream-vars`)
- Perfetto trace export for C2000 debug data (ERAD spans, DLOG tracks, log events)
- ML inference benchmarking with DWT cycle counting (TFLite Micro + CMSIS-NN)
- Cross-board ML comparison: STM32N6 (Cortex-M55/Helium) vs MCXN947 (Cortex-M33)
- STM32N6 SRAM boot automation via GDB for boards without on-chip flash
- `bench_capture` and `sram_boot` regression test step types
- Example firmware for 8 board families (25+ projects)

### Fixed
- DSS transport tests rewritten to match CCS scripting API (was testing removed subprocess interface)

### Changed
- Removed internal planning/session docs from repository
- Updated .gitignore with session artifact patterns

## [1.0.0] - 2026-02-14

### Added
- Multi-device support with named sessions (#106)
- Binary RTT capture library with transport abstraction (#65)
- RTT reset workaround for J-Link single-client limitation (#103)
- Multi-board sensor network demo with BLE scanner (#102)
- Zephyr cross-platform arch detection from board/DT (#99)
- ZephyrProfile CMakeCache.txt fallback for out-of-tree builds (#100)
- `--no-stub` and `--extra-esptool-args` CLI flags (#98)
- Log rotation (#45, #97)
- ESP-IDF project directory flash support (#72, #95)
- J-Link and Zephyr west flash integration (#75, #93)
- Live variable inspector with ELF/MAP symbol discovery (#92)
- Zephyr RTOS support and activity-based running detection (#88)
- Cortex-M fault analysis via GDB (#68)
- Debug probe abstraction with pluggable backends (#69)
- Windows compatibility via portalocker (#61)
- DWT profiling for function/region execution timing
- RTT real-time plotter (browser-based uPlot + WebSocket)
- SECURITY.md, CODE_OF_CONDUCT.md, contributing guidelines
- CI and lint GitHub Actions workflows
- py.typed marker for PEP 561 type checking support

### Fixed
- Restore single-responsibility to `_find_workspace` (#101)
- Update esptool commands for deprecated flags (#73, #94)
- Clear stale session files on daemon start
- Prevent log spam with `_gave_up` flag for max recovery attempts
- Fix recursion bug in probe building

### Changed
- Migrated from requirements-dev.txt to pyproject.toml optional dependencies
- Added ruff configuration for consistent code style
- Restructured .gitignore for Python packaging best practices
