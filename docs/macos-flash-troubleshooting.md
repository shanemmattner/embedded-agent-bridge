# macOS Flash Troubleshooting (Apple Silicon)

Known issues and proven fixes for flashing embedded dev boards from macOS on Apple Silicon Macs.

## STM32L4 + ST-Link V3: "interfaces are claimed"

### Problem

macOS AppleUSBCDCACM driver claims the ST-Link V3's VCP USB interface, blocking probe-rs and libusb. Error: `cannot perform this operation while interfaces are claimed`.

Additionally, Apple Silicon Macs use an eUSB2-to-USB2.0 HS repeater that violates USB 2.0 spec, causing intermittent USB communication failures. ST published an official FAQ (Oct 2024) confirming this as a known hardware-level interoperability issue with no software fix.

### Root Cause

1. **eUSB2 repeater** (hardware) — Apple's USB-C ports use an eUSB2 repeater that doesn't respect original USB2 HS SYNC timing. Affects all ST-Link V3 boards.
2. **macOS CDC ACM driver** — auto-claims VCP interface before libusb/probe-rs can access it.

### Fixes (in order of preference)

1. **Use a USB-A port or USB-C to USB-A adapter** — bypasses the eUSB2 repeater entirely.

2. **Use a USB HS hub** — tested working: Anker 332 5in1. Plug ST-Link into the hub's USB-A port.

3. **Use OpenOCD** — different USB access path than libusb:
   ```bash
   openocd -f interface/stlink.cfg -f target/stm32l4x.cfg \
     -c "program /path/to/firmware.elf verify reset exit"
   ```

4. **Use st-flash** (`brew install stlink`) — for .bin files:
   ```bash
   # Convert ELF to BIN first
   arm-none-eabi-objcopy -O binary firmware.elf firmware.bin
   # Flash
   st-flash --reset write firmware.bin 0x08000000
   ```

5. **probe-rs** — may work IF connected through USB hub. Without hub, typically fails.

### References

- ST FAQ: "Possible communication failure between STLINK-V3 and some recent computers" (community.st.com/t5/stm32-mcus/faq-possible-communication-failure-between-stlink-v3-and-some/ta-p/736578)
- USB-IF eUSB2 Rev 1.2 spec (ECN: "Repeater HS SYNC Forward")
- probe-rs issue #3716: panic on ST-Link connect (fixed in 0.31+)

---

## nRF5340: "Failed to power up DAP"

### Problem

After erasing an nRF5340 (via J-Link erase or probe-rs), the debug access port (DAP) enters a locked state. Subsequent attempts fail with `Failed to power up DAP` or `Could not unlock core 0`.

### Root Cause

nRF5340 CTRL-AP (Control Access Port) with APPROTECT. After ERASEALL, debug port protection is disabled only until the next **pin reset or power-on reset**. Without a clean power cycle, DAP stays inaccessible.

### Fixes

1. **Physical power cycle** — unplug USB completely (both power and debug), wait 3 seconds, replug. Most reliable fix.

2. **nrfjprog --recover** — install Nordic CLI tools first:
   ```bash
   brew install --cask nordic-nrf-command-line-tools
   nrfjprog --recover
   ```

3. **J-Link Commander** — create `recover.jlink`:
   ```
   exec EnableEraseAllFlashBanks
   erase
   r
   q
   ```
   Then:
   ```bash
   JLinkExe -device NRF5340_XXAA_APP -if SWD -speed 4000 \
     -autoconnect 1 -CommanderScript recover.jlink
   ```

4. **After recovery**, flash firmware immediately:
   ```bash
   eabctl flash --chip nrf5340 --runner jlink
   ```

### Prevention

- Never erase without immediately flashing new firmware
- Always use `eabctl flash` which handles erase+flash+reset atomically
- Keep `nrfjprog` installed as a recovery tool

---

## ESP32 Multi-Probe Disambiguation

### Problem

Multiple ESP32 boards with USB-Serial/JTAG share VID:PID `303a:1001`. OpenOCD connects to the wrong device.

### Fix

Use `adapter serial` with OpenOCD (proven working):
```bash
# ESP32-C6 (serial F0:F5:BD:01:88:2C)
openocd -f board/esp32c6-builtin.cfg \
  -c "adapter serial F0:F5:BD:01:88:2C" \
  -c "program_esp app.bin 0x10000 verify" \
  -c "reset run" -c "shutdown"

# ESP32-P4 (serial 60:55:F9:FA:FF:19)
openocd -f board/esp32p4-builtin.cfg \
  -c "adapter serial 60:55:F9:FA:FF:19" \
  -c "program_esp app.bin 0x10000 verify" \
  -c "reset run" -c "shutdown"
```

Find serial numbers:
```bash
ioreg -p IOUSB -l -w0 | grep -E '"USB (Serial Number|Product Name)"' | paste - -
```

---

## ESP32-S3: esptool "Inflate error"

### Problem

esptool fails at ~58% with `Inflate error` when flashing ESP32-S3 via built-in USB-Serial/JTAG at high baud rates.

### Fix

Use `--no-stub --no-compress` at 115200 baud:
```bash
esptool.py --chip esp32s3 --port /dev/cu.usbmodem* --baud 115200 \
  --no-stub write_flash --no-compress 0x10000 app.bin
```

Or use probe-rs (JTAG transport, avoids serial issues):
```bash
probe-rs run --chip esp32s3 firmware.elf
```

---

## General macOS Tips

- **Check USB devices first**: `system_profiler SPUSBDataType`
- **Kill stale processes**: `lsof /dev/cu.usbmodem*`
- **Prefer USB-A ports or hubs** for all debug probes on Apple Silicon Macs
- **Keep probe firmware updated** (ST-Link, J-Link)
- **Install recovery tools**: `brew install stlink && brew install --cask nordic-nrf-command-line-tools`
