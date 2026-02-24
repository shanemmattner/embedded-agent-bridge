# STM32N6 SRAM Boot Guide (NUCLEO-N657X0-Q)

## Why SRAM Boot?
- STM32N6 has NO internal flash — code runs from external XSPI flash or SRAM
- SRAM boot loads firmware to AXISRAM2 (0x34000000) via SWD and starts it with GDB
- Faster iteration than flashing external flash
- Used by regression tests and development workflow

## Prerequisites
- BOOT1=HIGH (SW1 right position) for DEV boot mode
- ST-Link V3 connected via USB-A adapter (macOS eUSB2 workaround — direct USB-C unreliable)
- Serial port: /dev/cu.usbmodem83402
- Tools: STM32_Programmer_CLI, probe-rs, arm-zephyr-eabi-gdb (Zephyr SDK)

## Complete Procedure

### Step 1: Clean Core State
```bash
CUBE_CLI=/Applications/STMicroelectronics/STM32Cube/STM32CubeProgrammer/STM32CubeProgrammer.app/Contents/Resources/bin/STM32_Programmer_CLI
$CUBE_CLI -c port=SWD mode=HOTPLUG -hardRst -halt
```
This hard-resets the MCU and halts it. Required to recover from locked-up state (PC=0xEFFFFFFE).

### Step 2: Load Binary to SRAM
```bash
$CUBE_CLI -c port=SWD mode=HOTPLUG -w zephyr.bin 0x34000000
```
Loads firmware to AXISRAM2 base address.

### Step 3: Extract Vector Table
```bash
xxd -l 8 -e zephyr.bin
```
Word 0 = Initial SP, Word 1 = Reset handler address. Example: SP=0x34280000, PC=0x340001BD

### Step 4: Start GDB Server
```bash
# probe-rs GDB server (default port 1337)
nohup probe-rs gdb --chip STM32N657 --probe 0483:3754 > /tmp/probe-rs-gdb.log 2>&1 &
GDB_PID=$!
```
IMPORTANT: Use nohup. probe-rs gdb does NOT support --port flag (use --gdb-connection-string to change port).

### Step 5: Set Registers and Run
```bash
GDB=/Users/shane/zephyr-sdk-0.17.0/arm-zephyr-eabi/bin/arm-zephyr-eabi-gdb
$GDB -batch -ex "target remote localhost:1337" \
  -ex "set \$sp = 0x34280000" \
  -ex "set \$msp = 0x34280000" \
  -ex "set \$pc = 0x340001BD" \
  -ex "continue &" \
  -ex "disconnect"
```
Replace SP/PC values with actual values from Step 3.

### Step 6: Stop GDB Server (Gracefully!)
```bash
kill -TERM $GDB_PID
wait $GDB_PID 2>/dev/null
sleep 2  # USB recovery time
```
NEVER use kill -9 (SIGKILL) — causes ST-Link V3 USB corruption on macOS.

### Step 7: Monitor Serial Output
```bash
minicom -D /dev/cu.usbmodem83402 -b 115200
# Or via EAB:
eabctl tail 50
```

## What Does NOT Work (Tested)

| Approach | Result |
|----------|--------|
| CubeProgrammer `-s <addr>` | Goes through boot ROM — firmware crashes |
| CubeProgrammer `-run` | Unhalts but PC drifts past binary end |
| CubeProgrammer `-w32 0xE000ED08` (VTOR) | Treats MMIO as flash — attempts erase — fails |
| CubeProgrammer `-coreReg PC=` then `-run` | Register writes don't persist between CLI invocations |
| `probe-rs run` | Corrupts core state to 0xEFFFFFFE — do NOT use |

**Why only GDB works**: GDB maintains a live debug session. Register writes are immediate and verified. CubeProgrammer opens/closes SWD per invocation — registers may not survive.

## macOS USB Issues

### ST-Link V3 eUSB2
- macOS USB-C ports use eUSB2 which has timing issues with ST-Link V3
- **Fix**: Use USB-A adapter (not direct USB-C)
- Port appears as `/dev/cu.usbmodem83402`

### probe-rs USB Corruption
- **Symptom**: After killing probe-rs, ST-Link enters `DEV_USB_COMM_ERR` state
- **Cause**: macOS eUSB2 timing + ungraceful disconnect
- **Prevention**: Always SIGTERM + wait + 2s delay (never SIGKILL)
- **Recovery**: Physical USB re-plug is the ONLY fix

### EAB Daemon Port Holding
- EAB daemon holds /dev/cu.usbmodem83402 (ST-Link VCP)
- This blocks probe-rs from claiming USB interfaces
- **Solution**: Stop EAB daemon before probe-rs operations, restart after

## Clock Configuration (Zephyr)
- HSI 64MHz — CKPER — USART1
- PLL1 — 800MHz CPU clock (Cortex-M55)
- USART1 at 115200 baud on PE5 (TX) / PE6 (RX)
- VCP confirmed connected to USART1 (ST UM3417)

## Troubleshooting

### Core Locked Up (PC=0xEFFFFFFE)
Run Step 1 (-hardRst -halt) to recover.

### No Serial Output
1. Verify USART1 pins: PE5=TX, PE6=RX (default in Zephyr DTS)
2. Verify baud rate: 115200 (Zephyr default)
3. Check firmware actually started (GDB info registers after continue)
4. Try minicom directly (bypass EAB) to rule out daemon issues
5. Verify VCP driver: ls /dev/cu.usbmodem*

### probe-rs Can't Connect
1. Stop EAB daemon first
2. Check USB: system_profiler SPUSBDataType | grep -A5 ST-Link
3. Try CubeProgrammer connection test: $CUBE_CLI -c port=SWD mode=HOTPLUG

## Automated Regression

The sram_boot step in regression tests automates this procedure:
```yaml
steps:
  - sram_boot:
      binary: build/zephyr/zephyr.bin
      load_address: "0x34000000"
      cubeprogrammer: /path/to/STM32_Programmer_CLI
```

See [EAB regression docs](../CLAUDE.md#regression-testing-hardware-in-the-loop).

## See Also
- [Flash Debug Guide](stm32n6-flash-debug.md) — external flash troubleshooting
- [EAB CLAUDE.md](../CLAUDE.md) — eabctl commands and known issues
- [ML Bench Example](../examples/stm32n6-ml-bench/) — multi-model CPU benchmark
- [Gait Bench Example](../examples/stm32n6-gait-bench/) — exoboot gait phase benchmark
