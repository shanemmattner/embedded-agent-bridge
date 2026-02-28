# EAB Handoff

## Key Files
- `eab/` — Python package
- `scripts/e2e-hardware-validation.sh` — full hardware test suite
- `E2E_HARDWARE_VALIDATION.md` — process docs

## Key Knowledge
- ALWAYS use eabctl for ALL hardware operations
- eab/cli/serial/ shadows pyserial — fixed daemon PYTHONPATH (commit 56565c9)
- MCX N947 needs NXP LinkServer (probe-rs can't flash secure 0x10000000)
- eabctl flash .elf for STM32 needs objcopy — use .bin instead
- Zephyr SDK uses arm-zephyr-eabi-* not arm-none-eabi-*
- Trace pipeline: eabctl rtt start → trace start --source rtt → .rttbin → trace export → Perfetto JSON
