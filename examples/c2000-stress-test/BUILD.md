# C2000 Stress Test - Build Instructions

## Quick Status

**Current blocker**: Code Composer Studio (CCS) and TI C2000 compiler not installed locally.

**What's ready**:
- ✅ Firmware source (`main.c`) with controlled test pattern
- ✅ CCS project configured (`CCS/launchxl_ex1_f280039c_demo.projectspec`)
- ✅ C2000Ware driverlib (sparse checkout at `/tmp/c2000ware-core-sdk`)
- ❌ Missing: Full C2000Ware device_support files
- ❌ Missing: TI C2000 compiler (cl2000)
- ❌ Missing: Code Composer Studio

## Options to Proceed

### Option 1: Install CCS Locally (Recommended)

1. Download Code Composer Studio from TI: https://www.ti.com/tool/CCSTUDIO
2. Install with C2000 compiler support (select during installation)
3. Clone full C2000Ware SDK:
   ```bash
   cd /tmp
   git clone https://github.com/TexasInstruments/c2000ware-core-sdk.git c2000ware-full
   ```
4. Open CCS and import project:
   - File → Import → C/C++ → CCS Projects
   - Select `examples/c2000-stress-test/CCS/`
   - Update `C2000WARE_ROOT` if prompted
5. Build project (Ctrl+B or Project → Build Project)
6. Output: `Debug/launchxl_ex1_f280039c_demo.out`

### Option 2: Build on Machine with CCS

If you have access to another machine with CCS installed:

1. Copy entire `examples/c2000-stress-test/` directory
2. Ensure C2000Ware is available at `/tmp/c2000ware-core-sdk/` (or update projectspec paths)
3. Import and build in CCS
4. Copy resulting `.out` file back to this machine
5. Flash via EAB: (details TBD once we have .out file)

### Option 3: Command-Line Build (If CCS Installed)

```bash
# Set environment
export C2000WARE_ROOT=/tmp/c2000ware-full

# Create workspace and import project
mkdir -p /tmp/ccs-workspace
ccs -noSplash -data /tmp/ccs-workspace \
    -application com.ti.ccstudio.apps.projectImport \
    -ccs.location $(pwd)/examples/c2000-stress-test/CCS

# Build project
ccs -noSplash -data /tmp/ccs-workspace \
    -application com.ti.ccstudio.apps.projectBuild \
    -ccs.projects launchxl_ex1_f280039c_demo \
    -ccs.configuration CPU1_LAUNCHXL_FLASH
```

## Missing C2000Ware Files

The projectspec references these files from C2000Ware (not in sparse checkout):

```
device_support/f28003x/common/include/driverlib.h
device_support/f28003x/common/include/device.h
device_support/f28003x/common/source/device.c
device_support/f28003x/common/source/f28003x_codestartbranch.asm
device_support/f28003x/common/targetConfigs/TMS320f280039c_LaunchPad.ccxml
device_support/f28003x/common/cmd/28003x_launchxl_demo_flash_lnk.cmd
driverlib/f28003x/driverlib/ccs/Debug/driverlib.lib
```

To download these:
```bash
cd /tmp/c2000ware-core-sdk
git sparse-checkout set device_support/f28003x driverlib/f28003x
```

## What's Next

Once you have a `.out` file:

1. Verify with EAB:
   ```bash
   eabctl status
   ```

2. Flash firmware (once we figure out the flash command for C2000)

3. Start controlled test:
   - Connect via debugger
   - Set `test_enabled = 1` at address TBD (check .map file)
   - Monitor output via EAB:
     ```bash
     eabctl tail 50
     ```

## Firmware Features

The stress test firmware (`main.c`):
- Waits for `test_enabled = 1` flag (set via debugger)
- Generates sine wave data (64-sample lookup table)
- Outputs to SCI UART at 115200 baud
- Reports stats every 10K samples
- Auto-stops after 1M samples
- Enters IDLE mode when complete

Expected throughput: ~11.5 KB/s (SCI UART) or ~31 KB/s (DSS DLOG)
