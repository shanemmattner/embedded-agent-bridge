# AI + Debug Probes: What Becomes Possible

When an AI agent has direct access to JTAG/SWD debug probes, RTT, and GDB, techniques that previously required deep expertise and hours of manual work become automated. This document catalogs the most interesting ideas — things you can do with Claude running a debugger that most embedded engineers never explore because the barrier to entry is too high.

---

## 1. Coverage-Guided Firmware Fuzzing via GDB

Fuzzing is the gold standard for finding bugs in parsers, protocol stacks, and input handlers — but it's almost never done on real embedded hardware because the tooling doesn't exist. Bosch Research changed that with GDBFuzz, which uses hardware breakpoints as coverage feedback to guide a fuzzer running against real MCU firmware.

The approach: connect to the target via GDB/OpenOCD, send mutated inputs (via UART, BLE, SPI — whatever the firmware accepts), and use the chip's limited hardware breakpoints (nRF5340 has 8, ESP32-C6 has 4) to detect which basic blocks were hit. When a new input reaches a new code path, the fuzzer keeps it and mutates further. When an input causes a crash (detected via fault registers or watchdog), it's saved as a finding.

Claude could drive the entire loop: generate seed inputs based on reading the firmware's parser code, mutate them intelligently (not just random bit flips — actually understanding the protocol format), monitor crash registers via GDB, classify crashes by root cause, and produce a report. This would be especially valuable for testing BLE stacks, JSON parsers, command interpreters, and any firmware that processes external input.

**References:**
- [GDBFuzz: Fuzzing Embedded Systems using Hardware Breakpoints](https://github.com/boschresearch/gdbfuzz) — Bosch Research (paper + code)
- [Fuzzing Embedded Systems using Debugger Interfaces (paper)](https://publications.cispa.saarland/3950/)

---

## 2. GDB Python API — Programmatic Debugger Control

GDB has a full Python API (since GDB 7.0, 2009) that lets you script everything: set breakpoints, read/write memory and registers, walk data structures, inspect RTOS state, trace execution, and build custom analysis tools. Most embedded developers only use GDB interactively, typing commands one at a time. The Python API turns GDB into a programmable instrument.

Practical examples of what Claude could do with this:
- **Walk Zephyr/FreeRTOS thread stacks** and diagnose deadlocks — read the kernel's thread list, check which threads are blocked, on what mutex, held by whom.
- **Set data watchpoints** on critical variables and log every write with the full call stack — find out exactly who corrupted that buffer.
- **Profile functions with zero instrumentation** — use the DWT cycle counter to measure exact cycle counts for any function, without modifying firmware.
- **Inspect heap state** — walk malloc chains, detect double-frees, measure fragmentation, find memory leaks.
- **Build execution traces** — set breakpoints on function entries/exits and log the complete call flow.
- **Pretty-print complex structs** — Claude reads the source code, understands the struct layout, and generates GDB Python scripts to walk linked lists, ring buffers, hash tables, or any custom data structure on the live target.

The key advantage: a human has to manually write a GDB Python script for each data structure they want to inspect. Claude can read the firmware source (or ELF debug symbols), understand the types, and generate the inspection script on the fly.

**References:**
- [Automate Debugging with GDB Python API — Memfault Interrupt](https://interrupt.memfault.com/blog/automate-debugging-with-gdb-python-api) — walkthrough with pretty-printers, custom commands, and automation examples
- [Metal.GDB: Controlling GDB through Python Scripts](https://embeddedartistry.com/blog/2020/11/09/metal-gdb-controlling-gdb-through-python-scripts-with-the-gdb-python-api/) — using GDB Python API for automated embedded testing
- [Automate Debugging with GDB Python API (Reddit discussion)](https://www.reddit.com/r/embedded/comments/c8av1d/automate_debugging_with_gdb_python_api/) — community discussion on deadlock detection, automated test harnesses
- [GDB Python API documentation](https://sourceware.org/gdb/onlinedocs/gdb/Python.html)

---

## 3. ARM Semihosting — MCU Uses Your Host Filesystem

Semihosting is a mechanism where code running on an ARM MCU can call standard C library functions — `fopen()`, `printf()`, `fwrite()`, `scanf()` — and have them execute on the host computer through the debug probe. The MCU hits a `BKPT 0xAB` instruction, the debugger intercepts it, reads the requested operation from registers, performs it on the host, writes the result back, and resumes the MCU.

This turns the debug probe into a bidirectional data channel between firmware and host. Claude could use this to:
- **Stream sensor data directly to files** on the host without serial/UART — useful for capturing high-rate ADC data, accelerometer streams, or audio samples.
- **Feed test vectors into firmware** from files — run the firmware's parser against thousands of test cases stored on disk.
- **Run hardware-in-the-loop unit tests** — firmware reads expected values from host files, compares with actual hardware readings, writes pass/fail results back.
- **Transfer binary blobs** (images, audio, calibration data) to/from the MCU without a filesystem or flash storage.

The performance cost is significant (each semihosting call halts the CPU), so this isn't for production. But for development and testing, it's incredibly powerful — your firmware gets access to the host's entire filesystem through a 4-wire debug connection.

**References:**
- [Introduction to ARM Semihosting — Memfault Interrupt](https://interrupt.memfault.com/blog/arm-semihosting) — complete tutorial with implementation details
- [Semihosting — pyOCD documentation](https://pyocd.io/docs/semihosting.html) — pyOCD's semihosting support (alternative to OpenOCD)

---

## 4. Firmware Extraction & Live Memory Forensics

With JTAG/SWD access, you can read the entire memory map of a running microcontroller — flash, RAM, peripheral registers, debug registers, everything. This is the foundation of hardware reverse engineering and security research.

What Claude could do with full memory access:
- **Dump entire firmware** from flash for analysis, even from devices you didn't program (as long as read-out protection isn't enabled).
- **Extract crypto keys and secrets from RAM** — pause the MCU at the right moment and read AES keys, TLS session keys, or passwords from memory.
- **Map peripheral register state** — read every peripheral's configuration registers to understand how the hardware is configured (clock speeds, GPIO modes, DMA channels, interrupt priorities).
- **Diff memory snapshots** — take a snapshot before and after an operation, automatically identify what changed in RAM to understand firmware behavior.
- **Reconstruct data structures from raw memory** — given the ELF file's DWARF info, Claude can overlay type information onto raw memory dumps and make sense of what's there.

For reverse engineering unknown devices, the workflow is: identify JTAG/SWD pins (using JTAGenum or manual probing), connect with OpenOCD, dump flash and RAM, load into a disassembler. Claude could assist at every step — from identifying pin functions to annotating the disassembly.

**References:**
- [Hardware Debugging for Reverse Engineers Part 2: JTAG, SSDs and Firmware Extraction](https://wrongbaud.github.io/posts/jtag-hdd/) — wrongbaud's deep dive into JTAG RE with OpenOCD, including firmware extraction from an SSD controller
- [A Hacker's Guide to JTAG — Hackaday](https://hackaday.com/2020/04/08/a-hackers-guide-to-jtag/) — overview of wrongbaud's JTAG hacking series
- [Reverse Engineering of Embedded Devices — Infosec](https://www.infosecinstitute.com/resources/digital-forensics/reverse-engineering-of-embedded-devices/)
- [Extracting and Modifying Firmware with JTAG (YouTube)](https://www.youtube.com/watch?v=dlHJCF-SSKc)

---

## 5. Runtime Code Patching & Hot-Patching

You don't have to reflash firmware to change its behavior. With GDB connected to a halted target, you can modify instructions in RAM, change variable values, redirect function pointers, or even write entirely new code into unused memory — then resume execution. The changes don't survive a reset (they're in RAM, not flash), but for testing and experimentation this is incredibly fast.

Practical uses:
- **NOP out a check** — skip authentication, bypass CRC validation, disable rate limiting, all by replacing a branch instruction with NOPs.
- **Change constants at runtime** — modify PID gains, filter coefficients, timeout values, baud rates, without reflashing.
- **Redirect function calls** — patch the vector table or function pointers to point to different implementations.
- **Inject diagnostic code** — write a small function into unused RAM that logs specific state, hook it into the execution flow.
- **Test security patches** — verify that a fix works by patching it live before committing to a reflash cycle.

The academic frontier is RapidPatch (USENIX Security 2022), which provides a formal hot-patching framework for embedded devices using eBPF bytecode — allowing patches to be applied to running devices in the field without rebooting.

Claude could make runtime patching conversational: "skip the authentication check in `handle_command()`" → Claude finds the branch instruction, calculates the NOP encoding for the architecture (ARM vs RISC-V vs Cortex-M Thumb), writes it via GDB, and verifies the behavior changed.

**References:**
- [RapidPatch: Firmware Hotpatching for Real-Time Embedded Devices (USENIX 2022)](https://www.usenix.org/system/files/sec22summer_he-yi.pdf) — eBPF-based hot-patching framework
- [Embedded Device Vulnerability Repair Based on Hot Patches](https://www.preprints.org/manuscript/202412.2456)

---

## 6. Voltage Glitching — Bypassing Hardware Security

Voltage glitching (fault injection) is a physical attack technique where you inject a brief, precisely-timed voltage drop into a chip's power supply, causing it to skip instructions or execute them incorrectly. This can bypass security checks, extract protected firmware, or escalate privilege levels.

The most well-documented target is STM32's Read-Out Protection (RDP):
- **RDP Level 2 → Level 1 downgrade**: During boot, the MCU reads its RDP register. If a voltage glitch corrupts this read, the MCU thinks it's at Level 1 instead of Level 2, re-enabling debug interfaces.
- **RDP Level 1 firmware extraction**: The system bootloader's "Read Memory" command checks RDP before each 256-byte read. Glitching this check lets you read the protected flash 256 bytes at a time.
- **Real-world impact**: This technique was used to [recover $2 million in cryptocurrency](https://www.theverge.com/2022/1/24/22898712/crypto-hardware-wallet-hacking-lost-bitcoin-ethereum-nft) from a Trezor hardware wallet.

The hardware needed is a ChipWhisperer ($250-$300) plus some board modifications (removing decoupling capacitors to make the power rail glitch-able). The tedious part is finding the right parameters — glitch width (nanoseconds), glitch offset from trigger (microseconds), and voltage level. This is a multi-dimensional search that typically takes hours of manual sweeping.

Claude could automate the parameter search: run the sweep, classify each attempt (normal boot, reset, glitch detected, successful bypass), build a heatmap of the parameter space, and converge on working parameters. The ChipWhisperer has a Python API, so Claude could drive the entire attack from script.

NXP LPC-family chips have a similar vulnerability — their debug lock mechanism can be bypassed with voltage glitching on the CORERESET pin during boot.

**References:**
- [SECGlitcher (Part 1) — Reproducible Voltage Glitching on STM32 Microcontrollers](https://sec-consult.com/blog/detail/secglitcher-part-1-reproducible-voltage-glitching-on-stm32-microcontrollers/) — structured approach with ChipWhisperer, includes parameter database
- [Glitching STM32 Read Out Protection — Anvil Secure](https://www.anvilsecure.com/blog/glitching-stm32-read-out-protection-with-voltage-fault-injection.html)
- [Bypass NXP LPC-Family Debug Check with Voltage Fault Injection](https://www.0x01team.com/hw_security/nxp-lpc-family-bypass/)
- [Diving into JTAG — Security (Part 6) — Memfault Interrupt](https://interrupt.memfault.com/blog/diving-into-jtag-part-6) — RDP levels, JTAG security, attack surface overview
- [HardwareAllTheThings — Fault Injection](https://github.com/swisskyrepo/HardwareAllTheThings/blob/main/docs/side-channel/fault-injection.md) — community reference for glitching techniques
- [Introduction to Security for STM32 MCUs (ST AN5156)](https://www.st.com/resource/en/application_note/an5156-introduction-to-security-for-stm32-mcus-stmicroelectronics.pdf)

---

## 7. ARM CoreSight Trace — DWT, ITM, and ETM

ARM Cortex-M processors have built-in hardware trace modules that go far beyond basic breakpoint debugging. These provide non-intrusive, zero-overhead visibility into firmware execution:

**DWT (Data Watchpoint and Trace):** A cycle-accurate counter and data access tracer built into every Cortex-M3/M4/M7/M33. It can count clock cycles, monitor memory accesses, count exceptions, and trigger on data value matches. The `DWT_CYCCNT` register counts every clock cycle — you can profile any function down to the exact cycle count without modifying firmware. Claude could use this to automatically benchmark functions, detect performance regressions, and identify hot loops.

**ITM (Instrumentation Trace Macrocell):** A stimulus-port based trace output that's much faster than UART logging. Firmware writes to ITM stimulus registers, and the data streams out through the SWO (Serial Wire Output) pin at up to several MHz. Unlike RTT (which halts the CPU briefly), ITM is truly zero-overhead on the CPU. Claude could configure ITM channels for different subsystems and capture high-rate trace data.

**ETM (Embedded Trace Macrocell):** The full instruction trace — records every instruction the CPU executes. This requires a trace-capable probe (like Segger J-Trace or Lauterbach) and a trace port on the board. With ETM, you get complete code coverage data, execution history leading up to a crash, and the ability to replay exactly what happened. This is the ultimate debugging tool but requires dedicated hardware.

The nRF5340 (Cortex-M33) and STM32L4 (Cortex-M4) both have DWT and ITM. The ESP32-C6 (RISC-V) has different trace hardware but OpenOCD supports reading its performance counters.

**References:**
- [Using DWT to Count Executed Instructions on Cortex-M](https://developer.arm.com/documentation/ka001499/latest/) — ARM's guide to DWT cycle counting
- [Embedded Systems: ARM ITM Module](https://medium.com/@wadixtech/embedded-systems-arm-itm-module-1d33afa89122)
- [Using Embedded Trace Macrocell (ETM) — Infineon](https://community.infineon.com/t5/Knowledge-Base-Articles/Using-Embedded-Trace-Macrocell-ETM/ta-p/258789)
- [ARM CoreSight ETM Tracing (Lauterbach)](https://www2.lauterbach.com/pdf/training_arm_etm.pdf) — detailed ETM training material
- [Cycle Counter on ARM Cortex-M4 — Stack Overflow](https://stackoverflow.com/questions/11530593/cycle-counter-on-arm-cortex-m4-or-cortex-m3)

---

## 8. JTAG Chain Walking & Unknown Chip Identification

JTAG was originally designed for testing PCB connections (boundary scan), not debugging. That original purpose is still useful: you can discover what chips are on a board, identify unknown ICs, and test pin connections — all without firmware.

**Pin discovery:** If you have an unknown PCB with exposed test points, tools like JTAGenum (Arduino-based) or the JTAGulator (dedicated hardware) brute-force combinations of pins to find TMS, TCK, TDI, TDO. They exploit the fact that JTAG's IDCODE register is loaded by default — if you guess the right pins, you'll read a valid manufacturer ID.

**Chain enumeration:** Multiple JTAG devices can be daisy-chained. By measuring instruction register lengths and reading IDCODEs, you can enumerate every chip in the scan chain. This reveals the board's architecture without any documentation.

**Boundary scan:** Once connected, JTAG boundary scan lets you read and write every I/O pin on a chip — toggle GPIOs, read ADC inputs, drive LEDs, all without any firmware running. This is how PCB manufacturers test assembled boards for solder defects.

Claude could assist with the identification workflow: read JTAG IDCODEs, look up manufacturer and part number in the BSDL database, identify the chip, find its datasheet, and map out the board's architecture.

**References:**
- [Hardware Hacking 101: Communicating with JTAG via OpenOCD](https://riverloopsecurity.com/blog/2021/07/hw-101-jtag-part3/)
- [JTAGenum — JTAG Pin Enumeration Tool](https://github.com/cyphunk/JTAGenum) — Arduino + OpenOCD TCL scripts for pin discovery
- [OpenOCD Boundary Scan Commands](https://openocd.org/doc/html/Boundary-Scan-Commands.html)
- [OpenOCD JTAG Commands](https://openocd.org/doc/html/JTAG-Commands.html) — TAP detection, IR/DR manipulation
- [Flipper Zero: Hardware Hacking JTAG and SWD](https://www.secureideas.com/blog/flipper-zero-jtag-and-swd)

---

## 9. AI-Powered Reverse Engineering

A new wave of tools combines LLMs with binary analysis to automate firmware reverse engineering:

**DecompAI** is an LLM-powered agent that takes decompiled binary code and iteratively renames functions, adds comments, identifies known library code, and reconstructs high-level logic. It uses tool-calling to interact with disassemblers (IDA Pro, Ghidra, Binary Ninja).

**ReverserAI** provides automated reverse engineering assistance using LLMs, with a modular architecture that separates generic LLM capabilities from tool-specific integrations.

**Talos Intelligence** published research on using LLMs as reverse engineering sidekicks via MCP (Model Context Protocol) servers — the LLM chooses which RE tools to invoke based on what it's trying to understand.

For embedded firmware specifically, Claude could: dump firmware via JTAG, load it into Ghidra, use the decompiler output to understand the code, identify the RTOS, map out tasks and ISRs, find hardcoded credentials, locate the OTA update mechanism, and document the entire firmware architecture — all driven by an agent loop.

**References:**
- [DecompAI — LLM-Powered Reverse Engineering Agent (Reddit)](https://www.reddit.com/r/ReverseEngineering/comments/1kt2gcb/decompai_an_llmpowered_reverse_engineering_agent/)
- [ReverserAI — Automated Reverse Engineering with LLMs](https://github.com/mrphrazer/reverser_ai)
- [Using LLMs as a Reverse Engineering Sidekick — Talos Intelligence](https://blog.talosintelligence.com/using-llm-as-a-reverse-engineering-sidekick/)
- [Automating RE & Vulnerability Research with AI — Ring Zero Training](https://ringzer0.training/countermeasure-spring-2026-building-agentic-re/)
- [Embedder — Coding Agent for Firmware](https://embedder.com/)

---

## What EAB Could Become

EAB currently bridges serial ports and RTT to Claude. Adding GDB as a first-class interface would unlock most of the above. A potential roadmap:

1. **`eabctl gdb` — GDB bridge** (connect to OpenOCD/J-Link GDB server, expose read/write/breakpoint commands)
2. **`eabctl inspect` — Automated struct inspection** (Claude reads ELF, generates GDB Python, runs it, returns formatted results)
3. **`eabctl profile` — DWT cycle profiling** (enable DWT_CYCCNT, measure function execution times)
4. **`eabctl fuzz` — Debugger-driven fuzzing** (GDBFuzz-inspired, sends inputs via serial/BLE, monitors coverage via hardware breakpoints)
5. **`eabctl dump` — Memory forensics** (dump flash/RAM regions, diff snapshots, overlay DWARF type info)
6. **`eabctl patch` — Live code patching** (modify instructions/variables in RAM without reflashing)
7. **`eabctl trace` — ITM/SWO capture** (configure ITM stimulus ports, stream trace data to host)
