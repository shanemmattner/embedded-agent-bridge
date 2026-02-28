# Embedded Agent Bridge (EAB) Agent

## Role
Background daemons bridging AI coding agents to debuggers and embedded hardware. Supports ESP32, STM32, nRF, NXP MCX via serial, RTT, J-Link, OpenOCD.

## Tools
- eabctl CLI for all hardware operations
- probe-rs for ARM debug
- J-Link for nRF targets
- OpenOCD for STM32
- RTT binary capture + trace export

## Communication
- CLI: `eabctl` (installed via uv)
- Python API: `from eab import ...`
- 5 boards on USB hub: ESP32-C6, nRF5340 DK, STM32L4 Nucleo, FRDM-MCXN947, TI LaunchPad
