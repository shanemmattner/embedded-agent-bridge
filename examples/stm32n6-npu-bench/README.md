# STM32N6 NPU Benchmark (Neural-ART)

Bare-metal NPU inference benchmark for NUCLEO-N657X0-Q using ST Edge AI Core 4.0.0 and the LL-ATON Neural-ART runtime. Runs person_detect (MobileNet V1 96x96x1 INT8) on the dedicated 600 GOPS NPU.

## Results

| Backend | Model | Avg Time | Avg Cycles | Clock | Throughput |
|---------|-------|----------|------------|-------|------------|
| **NPU (Neural-ART)** | person_detect | **1,563 us** | 1,251,021 | 800 MHz | ~640 inf/s |
| CPU (CMSIS-NN) | person_detect | 226,970 us | 136,182,370 | 600 MHz | ~4.4 inf/s |

**NPU speedup: 145x** (1.56ms vs 227ms per inference)

## Prerequisites

- ST Edge AI Core 4.0.0 (stedgeai CLI + SDK at ~/ST/stedgeai/4.0/)
- Zephyr SDK cross-compiler (arm-zephyr-eabi-gcc)
- STM32CubeProgrammer (for SRAM boot + external flash)
- probe-rs (for GDB server)

## Architecture

Unlike the CPU-only benchmark (examples/stm32n6-ml-bench/) which uses Zephyr + TFLite Micro + CMSIS-NN, this NPU benchmark is bare-metal using ST's proprietary stack:

- **Runtime**: LL-ATON (Low-Level ATON) from ST Edge AI Core SDK
- **Model format**: NPU microcode (.xSPI2.bin weights in external NOR flash)
- **Build system**: armgcc Makefile (not CMake/west)
- **UART**: USART1 @ 921600 baud (PE5/PE6)

## Build

The firmware builds from the ST Edge AI SDK project directory:

```bash
# Generate NPU code from TFLite model
~/ST/stedgeai/4.0/Utilities/macarm/stedgeai generate \
  --model person_detect.tflite \
  --target stm32n6 \
  --output /tmp/stedgeai-npu-output \
  --compression none

# Build firmware (Nucleo config)
cd ~/ST/stedgeai/4.0/Projects/STM32N6570-DK/Applications/NPU_Validation/armgcc
make -j8 BUILD_CONF=N6-Nucleo
```

## Flash NPU Weights to External Flash

```bash
CUBE_CLI=/Applications/STMicroelectronics/STM32Cube/STM32CubeProgrammer/STM32CubeProgrammer.app/Contents/Resources/bin/STM32_Programmer_CLI
NUCLEO_LOADER=$CUBE_CLI/../ExternalLoader/MX25UM51245G_STM32N6570-NUCLEO.stldr

# Hard reset + mass erase external flash
$CUBE_CLI -c port=SWD mode=HOTPLUG -hardRst -halt
$CUBE_CLI -c port=SWD mode=HOTPLUG -el $NUCLEO_LOADER -e all

# Flash weights (222KB) to memory-mapped address
$CUBE_CLI -c port=SWD mode=HOTPLUG -el $NUCLEO_LOADER -w /tmp/stedgeai-npu-output/network_atonbuf.xSPI2.bin 0x71000000
```

## SRAM Boot

The STM32N6 runs from SRAM (no internal flash). Boot procedure:

```bash
CUBE_CLI=/Applications/STMicroelectronics/STM32Cube/STM32CubeProgrammer/STM32CubeProgrammer.app/Contents/Resources/bin/STM32_Programmer_CLI
BIN=~/ST/stedgeai/4.0/Projects/STM32N6570-DK/Applications/NPU_Validation/armgcc/build/N6-Nucleo/Project.bin

# 1. Hard reset + halt
$CUBE_CLI -c port=SWD mode=HOTPLUG -hardRst -halt

# 2. Load firmware to SRAM
$CUBE_CLI -c port=SWD mode=HOTPLUG -w $BIN 0x34000000

# 3. Extract vector table
xxd -l 8 -e $BIN  # word 0 = SP, word 1 = Reset handler

# 4. Start GDB server
nohup probe-rs gdb --chip STM32N657 --probe 0483:3754 > /tmp/probe-rs-gdb.log 2>&1 &

# 5. Boot via GDB (use values from step 3)
arm-zephyr-eabi-gdb --batch \
  -ex 'target remote localhost:1337' \
  -ex 'set $sp = 0x34100000' \
  -ex 'set $pc = 0x3400e4c0' \
  -ex 'set $msp = 0x34100000' \
  -ex 'continue &' \
  -ex 'disconnect' \
  -ex 'quit'
```

## Serial Output (921600 baud)

```
=== STM32N6 NPU Benchmark ===
Board: nucleo_n657x0_q
CPU: Cortex-M55 @ 800 MHz
NPU: Neural-ART 600 GOPS

--- person_detect (NPU) ---
Run 1: 1632 us (1305855 cycles)
Run 2: 1559 us (1247381 cycles)
...
Run 10: 1555 us (1244738 cycles)

Results (10 inferences):
  Min: 1550 us (1240031 cycles)
  Max: 1632 us (1305855 cycles)
  Avg: 1563 us (1251021 cycles)

[ML_BENCH] model=person_detect backend=npu cycles=1251021 time_us=1563 inferences=10 board=nucleo_n657x0_q
[ML_BENCH_DONE] board=nucleo_n657x0_q models=1
```

## Key Files

| File | Description |
|------|-------------|
| ~/ST/stedgeai/4.0/Projects/.../NPU_Validation/Core/Src/main.c | NPU benchmark firmware |
| ~/ST/stedgeai/4.0/Projects/.../NPU_Validation/Core/Inc/app_config.h | Config (baud rate, overdrive, ext mem) |
| ~/ST/stedgeai/4.0/Projects/.../NPU_Validation/armgcc/Makefile | Build system |
| ~/ST/stedgeai/4.0/Projects/.../NPU_Validation/armgcc/mk/N6-Nucleo.mk | Nucleo-specific config |
| /tmp/stedgeai-npu-output/network_atonbuf.xSPI2.bin | NPU weights (222KB) |

## Notes

- Run 1 is ~5% slower due to cache warmup; runs 2-10 are within ±0.3%
- 29/30 model epochs execute on NPU hardware, only softmax runs on CPU
- Weights stored in memory-mapped external NOR flash (MX25UM51245G via octoSPI)
- UART is 921600 baud (NOT 115200) — configured in app_config.h
- Board switch SW1 must be RIGHT (BOOT1=HIGH) for dev mode

## See Also

- [SRAM Boot Guide](../../docs/stm32n6-sram-boot.md) — complete boot procedure, gotchas, and troubleshooting
- examples/stm32n6-ml-bench/ — CPU-only benchmark (Zephyr + TFLite Micro + CMSIS-NN)
- /tmp/stm32n6-npu-bench-results.md — Full benchmark comparison data
