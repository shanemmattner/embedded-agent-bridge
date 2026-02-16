# C2000 Stress Test Firmware

High-throughput stress test for LAUNCHXL-F280039C with controlled start/stop pattern.

## Features

- **Controlled execution**: Wait for `test_enabled=1` flag (set via debugger)
- **Deterministic stop**: Runs for 1M samples then auto-stops
- **Data generation**: Sine wave output (64-sample table)
- **Stats reporting**: Progress every 10K samples
- **Low-power idle**: Enters IDLE mode after completion

## Quick Start (Recommended)

### Docker Build (Headless, No CCS Installation Required)

```bash
# From this directory
./docker-build.sh
```

This uses a pre-configured Docker image with CCS 20.2 and all dependencies. **No local CCS installation needed!**

## Build Requirements

- **Hardware**: LAUNCHXL-F280039C (F28003x + XDS110 onboard)
- **Software** (Docker method):
  - Docker
- **Software** (Local method):
  - Code Composer Studio (CCS) 12.4+
  - C2000Ware SDK

## Build Steps

### Option 1: Docker Build (Recommended) ⭐

**Fastest and most reliable - no local CCS installation needed!**

```bash
# Pull Docker image (first time only - ~2GB)
docker pull whuzfb/ccstudio:ubuntu24.04-20.2.0.00012

# Build firmware
./docker-build.sh
```

**Output**: `Debug/launchxl_ex1_f280039c_demo.out`

**CI/CD Integration:**

```yaml
# .github/workflows/build.yml
name: Build C2000 Firmware
on: [push]
jobs:
  build:
    runs-on: ubuntu-latest
    steps:
      - uses: actions/checkout@v3
      - name: Build C2000 firmware
        run: |
          cd examples/c2000-stress-test
          ./docker-build.sh
      - name: Upload firmware
        uses: actions/upload-artifact@v3
        with:
          name: c2000-firmware
          path: examples/c2000-stress-test/Debug/*.out
```

### Option 2: Local CCS GUI

1. Open CCS
2. File → Import → CCS Projects
3. Select this directory (`c2000-stress-test`)
4. Modify `C2000WARE_ROOT` path in `.projectspec` to point to C2000Ware installation
5. Build Project

### Option 3: Local CCS Command Line

```bash
# Set C2000Ware path
export C2000WARE_ROOT=/tmp/c2000ware-core-sdk

# Build with CCS command-line
ccs-server-cli.sh -noSplash -workspace /tmp/ccs-workspace \
    -application com.ti.ccs.apps.importProject \
    -ccs.location $(pwd)

ccs-server-cli.sh -noSplash -workspace /tmp/ccs-workspace \
    -application com.ti.ccs.apps.buildProject \
    -ccs.projects launchxl_ex1_f280039c_demo
```

### Option 4: Standalone Makefile

**Note:** This approach has ELF/COFF compatibility issues. Use Docker build instead.

```bash
gmake -f Makefile all
```

## Flash via EAB

Once built, flash to the device:

```bash
# From repo root
eabctl flash examples/c2000-stress-test
```

Or manually via CCS debugger.

## Debugger Control

Start the controlled test by setting the `test_enabled` flag via debugger:

```bash
# Via GDB (if using gdbserver)
(gdb) target remote :3333
(gdb) set {uint32_t}0x<address> = 1
(gdb) continue

# Via CCS Scripting Console
test_enabled = 1
```

**Note:** The exact address of `test_enabled` can be found in the `.map` file after building.

## Expected Throughput

- **SCI UART**: ~11.5 KB/s (115200 baud)
- **DSS DLOG**: ~31 KB/s (bulk memory reads)

## Firmware Structure

```
examples/c2000-stress-test/
├── main.c                      # Controlled test pattern
├── launchxl_ex1_sci_io_driverlib.c  # UART I/O helpers
├── launchxl_ex1_sci_io_driverlib.h
├── launchxl_ex1_ti_ascii.h     # ASCII art
├── CCS/                        # CCS project files
│   └── launchxl_ex1_f280039c_demo.projectspec
├── docker-build.sh             # Docker build script
├── Makefile                    # Standalone build (has issues)
├── BUILD.md                    # Detailed build notes
└── README.md                   # This file
```

## Troubleshooting

### Docker build fails with "image not found"

```bash
docker pull whuzfb/ccstudio:ubuntu24.04-20.2.0.00012
```

### Build succeeds but no .out file

Check Docker logs:
```bash
docker run --rm -v $(pwd):/ccs_projects/c2000-stress-test \
  whuzfb/ccstudio:ubuntu24.04-20.2.0.00012 \
  ls -la /workspaces/*/Debug/
```

### EAB flash fails

Ensure the device is connected and detected:
```bash
eabctl status
```

## Next Steps

- [x] Build firmware via Docker
- [ ] Flash to device via EAB
- [ ] Test debugger control (set test_enabled=1)
- [ ] Monitor output via `eabctl tail`
- [ ] Verify controlled pattern (1M samples, auto-stop)
- [ ] Add DLOG support for higher throughput
