# C2000 Docker Build - Quick Start

Complete setup guide for building C2000 firmware using Docker (no local CCS installation required).

## One-Time Setup

### 1. Install Docker Desktop

Download and install Docker Desktop for Mac from: https://www.docker.com/products/docker-desktop

**Verify Docker is running:**
```bash
docker info
```

If you see "Cannot connect to the Docker daemon", start Docker Desktop from Applications.

### 2. Pull CCS Docker Image

```bash
docker pull whuzfb/ccstudio:20.2-ubuntu24.04
```

**Size:** ~2GB download
**Contains:** Code Composer Studio 20.2 with C2000 compiler

### 3. Clone C2000Ware SDK

The C2000 firmware requires TI's C2000Ware SDK for device headers and libraries.

```bash
cd /tmp
git clone --depth=1 --filter=blob:none --sparse \
  https://github.com/TexasInstruments/c2000ware-core-sdk.git
cd c2000ware-core-sdk
git sparse-checkout set device_support/f28003x driverlib/f28003x
git checkout
```

**Size:** ~50MB (sparse checkout, only F28003x files)
**Location:** Must be at `/tmp/c2000ware-core-sdk` (hardcoded in project)

**Verify:**
```bash
ls /tmp/c2000ware-core-sdk/device_support/f28003x/common/include/driverlib.h
```

You should see the file exists.

## Build Firmware

```bash
cd path/to/embedded-agent-bridge/examples/c2000-stress-test
./docker-build.sh
```

**Expected output:**
```
=== Build Successful ===
Output: Debug/launchxl_ex1_f280039c_demo.out
-rw-r--r--  1 you  staff   83K Feb 16 10:29 Debug/launchxl_ex1_f280039c_demo.out

Ready to flash with: eabctl flash examples/c2000-stress-test
```

## Troubleshooting

### Docker not running
```
Error: Docker is not running
```

**Solution:** Start Docker Desktop from Applications.

### C2000Ware not found
```
!ERROR: File/directory 'file:/tmp/c2000ware-core-sdk/...' cannot be located
```

**Solution:** Clone C2000Ware to `/tmp/c2000ware-core-sdk` (see step 3 above).

### Build fails with "already exists"
```
!ERROR: A file or directory already exists at location '/workspaces/...'
```

**Solution:** This is safe to ignore - the build reuses the existing workspace and succeeds.

### Permission denied on Docker
```
permission denied while trying to connect to the Docker daemon socket
```

**Solution:** On macOS, this usually means Docker Desktop isn't running.

## What Happens During Build

1. **Docker mounts directories:**
   - Project directory → `/ccs_projects/c2000-stress-test`
   - C2000Ware → `/tmp/c2000ware-core-sdk`
   - Workspace → `/tmp/ccs-workspace`

2. **CCS imports project:**
   - Reads `CCS/launchxl_ex1_f280039c_demo.projectspec`
   - Copies device headers from C2000Ware
   - Links driverlib

3. **Build firmware:**
   - Compiles `main.c`, device drivers, etc.
   - Links with driverlib.lib
   - Produces `launchxl_ex1_f280039c_demo.out`

4. **Copy output:**
   - Copies binary from container workspace to host `Debug/` directory

## Next Steps

After building, flash to hardware:

```bash
# From repo root
eabctl flash examples/c2000-stress-test
```

See `README.md` for full firmware features and testing instructions.
