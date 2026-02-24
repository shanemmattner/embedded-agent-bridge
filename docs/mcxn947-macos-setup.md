# FRDM-MCXN947 Development on macOS (Apple Silicon)

## Hardware

- **Board**: FRDM-MCXN947 (NXP MCX N947, dual Cortex-M33 @ 150 MHz)
- **Debug probe**: Onboard MCU-LINK CMSIS-DAP V3.128 (VID:PID `1fc9:0143`)
- **Serial port**: `/dev/cu.usbmodemI2WZW2OTY3RUW3` (115200 baud)
- **Flash**: 2 MB on-chip + 8 MB external FlexSPI

## Software Requirements

| Tool | Purpose | Install |
|------|---------|---------|
| Zephyr SDK 0.17.0 | Compiler (arm-zephyr-eabi-gcc) | Already at `/Users/shane/zephyr-sdk-0.17.0/` |
| west | Zephyr build/flash tool | `pip install west` |
| LinkServer | NXP flash/debug (only supported runner) | See below |
| probe-rs | Alternative flash tool | `cargo install probe-rs-tools` |

## Installing LinkServer (macOS aarch64)

The standard `.pkg` installer fails on macOS with a postinstall script error. Manual extraction works:

### Step 1: Download

Go to NXP's LinkServer page (free NXP account required):
https://www.nxp.com/design/design-center/software/development-software/mcuxpresso-software-and-tools-/linkserver-for-microcontrollers:LINKERSERVER

Download "Linkserver installer for MacOS Arch 64" (the `.pkg` for aarch64).

### Step 2: Transfer to target machine (if needed)

```bash
scp ~/Downloads/LinkServer_25.12.83.aarch64.pkg studio:~/
```

### Step 3: Extract manually (bypass broken postinstall)

The `.pkg` installer's postinstall script fails trying to install sub-packages (LPCScrypt, MCU-LINK firmware updater). Extract the payload directly:

```bash
# Expand the pkg
pkgutil --expand ~/LinkServer_25.12.83.aarch64.pkg /tmp/linkserver-expand

# Extract payload to /usr/local/LinkServer
sudo mkdir -p /usr/local/LinkServer
cd /tmp/linkserver-expand/flatten_LinkServer_25.12.83.pkg
sudo tar xzf Payload -C /usr/local/LinkServer
```

### Step 4: Add to PATH

Add to `~/.zshrc`:
```bash
export PATH="/usr/local/LinkServer:$PATH"
```

### Step 5: Verify

```bash
LinkServer --version
# LinkServer v25.12.83 [Build 83] [2025-12-09 17:25:54]

LinkServer probes
# Should show: MCU-LINK FRDM-MCXN947 (r0E7) CMSIS-DAP V3.128
```

## What Does NOT Work on macOS

| Tool | Status |
|------|--------|
| MCUXpresso IDE | macOS builds exist but M1/M2+ issues reported. Heavy Eclipse IDE, overkill for CLI |
| OpenOCD | Board not supported in Zephyr's `board.cmake` |
| pyocd | No MCXN947 target support |
| probe-rs (official) | Not officially supported — GitHub discussion #2371 shows timeouts and flash algorithm failures. Custom YAML target definition required |
| `west flash -r openocd` | "board does not support runner openocd" |
| `west flash -r pyocd` | "board does not support runner pyocd" |

## Build + Flash Workflow

### Build

```bash
cd /Users/shane/zephyrproject
west build -b frdm_mcxn947/mcxn947/cpu0 \
  /path/to/your/app \
  -d /path/to/build-dir \
  --pristine
```

**Board qualifier**: `frdm_mcxn947/mcxn947/cpu0` (NOT just `frdm_mcxn947`)

### Flash with LinkServer (recommended)

```bash
# Via west (uses LinkServer automatically)
west flash -d /path/to/build-dir

# Or directly with LinkServer CLI
LinkServer flash MCXN947:FRDM-MCXN947 load --addr 0 /path/to/zephyr.bin
```

### Flash with probe-rs (alternative)

```bash
probe-rs download --chip MCXN947 --probe 1fc9:0143 \
  --binary-format bin --base-address 0x00000000 zephyr.bin
```

**Note**: Flash address is `0x00000000` (NVM), NOT `0x10000000` (secure mirror — probe-rs sees it as "Generic" not "NVM").

### Serial monitor

```bash
minicom -D /dev/cu.usbmodemI2WZW2OTY3RUW3 -b 115200
# Or via EAB daemon:
eabctl tail 50
```

## Troubleshooting

### MCU-Link firmware warning

```
MCU-Link firmware update `check`: MCU-Link firmware not found at /usr/local/LinkServer/MCU-LINK_installer/probe_firmware.
```

This is harmless — the MCU-LINK firmware updater sub-package was skipped during manual extraction. The onboard probe works fine without updating.

### DAP fault / flash failure with probe-rs

```bash
# Mass erase to recover
probe-rs erase --chip MCXN947 --probe 1fc9:0143
# Then reflash
```

### Brand new board won't flash (secure mode)

Per NXP community (confirmed by NXP employee on Zephyr Discord):

1. Unplug the board
2. Hold SW3 "ISP" button
3. Plug back in (holding SW3 prevents app from booting)
4. Flash with `west flash` or LinkServer
5. Release SW3
6. Power cycle — only needed once, subsequent flashes work normally

### LinkServer `.pkg` install fails

Use the manual extraction method in Step 3 above. The postinstall script tries to run nested `installer` commands for LPCScrypt and MCU-LINK firmware updater sub-packages, which fail on some macOS versions.

## Known Good Versions (Tested Feb 2026)

- macOS 15.x (Darwin 25.3.0) on Mac Studio M4
- LinkServer v25.12.83
- Zephyr SDK 0.17.0
- probe-rs 0.24.x
- Board firmware: MCU-LINK CMSIS-DAP V3.128
