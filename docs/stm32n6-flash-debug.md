# STM32N6 External Flash Debug Guide

## Decision Tree

When external flash erase/write fails on STM32N6:

### Check 1: Is the board correctly identified?
Read CubeProgrammer 'Board:' output. Does it match your assumption?
- NUCLEO-N657X0-Q → use Nucleo loader
- STM32N6570-DK → use DK loader
- **Board mislabeling is common** — devices.json said DK but tool said Nucleo

### Check 2: Is the correct external loader selected?
```bash
ls $CUBE_CLI/../ExternalLoader/ | grep -i n6
```
- **Nucleo**: MX25UM51245G_STM32N6570-NUCLEO.stldr (flash chip: MX25UM51245G)
- **DK**: MX66UW1G45G_STM32N6570-DK.stldr (flash chip: MX66UW1G45G)

Wrong loader = init succeeds (R0=1) but erase fails (R0=0). The XSPI interface config is similar between chips, but flash command sets differ.

### Check 3: Is the board in DEV boot mode?
BOOT1 must be HIGH (JP2 position [2-3]) for debug access.
If AP 0 fails but AP 1 works → debug port partially open → check boot switches.

### Check 4: Use verbose mode
```bash
$CUBE_CLI -c port=SWD mode=HOTPLUG -el $LOADER -vb 3 -e all
```
- Init R0=1, Erase R0=0 → loader talks to MCU but wrong flash chip
- Init R0=0 → loader can't init → wrong XSPI config or clock issue

### Check 5: ST-Link firmware
V3J15M6 confirmed working. Upgrade via CubeProgrammer GUI if needed.

## Flash Commands (Working)

```bash
CUBE_CLI=/Applications/STMicroelectronics/STM32Cube/STM32CubeProgrammer/STM32CubeProgrammer.app/Contents/Resources/bin/STM32_Programmer_CLI
NUCLEO_LOADER=$CUBE_CLI/../ExternalLoader/MX25UM51245G_STM32N6570-NUCLEO.stldr

# Mass erase
$CUBE_CLI -c port=SWD mode=HOTPLUG -el $NUCLEO_LOADER -e all

# Write to memory-mapped address
$CUBE_CLI -c port=SWD mode=HOTPLUG -el $NUCLEO_LOADER -w firmware.bin 0x71000000

# Write hex file (auto-addresses)
$CUBE_CLI -c port=SWD mode=HOTPLUG -el $NUCLEO_LOADER -hardRst -w firmware.hex
```

## Anti-Patterns
1. Trusting labels over tool output
2. Iterating same failing command with minor variations  
3. Researching flash protection when the loader is wrong
4. Not listing available loaders early

## See Also
- [SRAM Boot Guide](stm32n6-sram-boot.md) — loading firmware to SRAM instead of flash
- [EAB CLAUDE.md](../CLAUDE.md) — eabctl commands for flashing
