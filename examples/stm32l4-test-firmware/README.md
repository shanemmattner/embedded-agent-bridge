# STM32L4 Test Firmware (Bare Metal)

Minimal bare-metal firmware for STM32L476RG Nucleo. No HAL, no RTOS — just register-level UART and GPIO.

## What it does

- Blinks PA5 (Nucleo user LED)
- Prints heartbeat counter over UART2 (115200 baud)
- Uses the ST-Link VCP (PA2 TX, PA3 RX)

Output:
```
[EAB-TEST] STM32L4 firmware booted
[EAB-TEST] heartbeat 1
[EAB-TEST] heartbeat 2
```

## Requirements

- STM32L476RG Nucleo board (or compatible STM32L4)
- `st-flash` (stlink tools) or STM32CubeProgrammer

## Build

```bash
cd examples/stm32l4-test-firmware
make
```

Requires `arm-none-eabi-gcc`. Pre-built binary included: `eab-test-firmware.bin`.

## Flash

```bash
# Via EAB
eabctl flash examples/stm32l4-test-firmware --chip stm32l4

# Or directly
st-flash write eab-test-firmware.bin 0x08000000
```

## Use with EAB

```bash
eabctl start --chip stm32l4 --port /dev/ttyACM0
eabctl tail 50
```
