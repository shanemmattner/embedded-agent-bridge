# C2000 Docker Build - Complete Setup Summary

This document summarizes the C2000 Docker build setup that was configured on 2026-02-16.

## ✅ What's Working

All C2000 firmware can now be built using Docker with no local Code Composer Studio installation.

### Prerequisites (One-Time Setup)

**1. Docker Desktop**
- Installed and running on macOS
- Version: 29.2.0 (verified working)

**2. CCS Docker Image**
```bash
docker pull whuzfb/ccstudio:20.2-ubuntu24.04
```
- Size: ~2GB
- Contains: Code Composer Studio 20.2 with C2000 compiler
- Platform: linux/amd64 (runs via Rosetta on Apple Silicon)

**3. C2000Ware SDK**
```bash
cd /tmp
git clone --depth=1 --filter=blob:none --sparse \
  https://github.com/TexasInstruments/c2000ware-core-sdk.git
cd c2000ware-core-sdk
git sparse-checkout set device_support/f28003x driverlib/f28003x
git checkout
```
- Location: `/tmp/c2000ware-core-sdk` (MUST be this path)
- Size: ~50MB (sparse checkout, only F28003x files)
- Contains: Device headers, libraries, linker scripts

### Build Command

```bash
cd work/dev/tools/embedded-agent-bridge/examples/c2000-stress-test
./docker-build.sh
```

**Expected output:**
```
=== Build Successful ===
Output: Debug/launchxl_ex1_f280039c_demo.out
-rw-r--r--  1 you  staff   83K Feb 16 10:29 Debug/launchxl_ex1_f280039c_demo.out
```

## 📚 Documentation

All documentation is complete and consistent:

1. **QUICK-START.md** - Complete beginner setup guide
   - Docker installation
   - Prerequisite setup
   - Build process
   - Troubleshooting

2. **README.md** - Project overview and features
   - Firmware description
   - Build options (Docker, local CCS, Makefile)
   - Flashing and testing instructions

3. **CLAUDE.md** - Developer reference
   - C2000 build section
   - Prerequisites
   - Integration with EAB tools

## 🔧 Technical Details

### Docker Build Process

1. **Mounts three directories:**
   - Project: `examples/c2000-stress-test` → `/ccs_projects/c2000-stress-test`
   - C2000Ware: `/tmp/c2000ware-core-sdk` → `/tmp/c2000ware-core-sdk`
   - Workspace: `/tmp/ccs-workspace` → `/workspaces`

2. **Uses Docker image entrypoint:**
   - Previous version tried to override entrypoint (failed)
   - Current version passes `.projectspec` file as argument
   - Entrypoint handles import, build, and output

3. **Copies build artifacts:**
   - Firmware builds in `/workspaces/launchxl_ex1_f280039c_demo/Debug/`
   - Script copies to local `Debug/` directory
   - Final output: `Debug/launchxl_ex1_f280039c_demo.out`

### Why C2000Ware is Required

The projectspec file references these C2000Ware files:
- `device_support/f28003x/common/include/driverlib.h`
- `device_support/f28003x/common/include/device.h`
- `device_support/f28003x/common/source/device.c`
- `device_support/f28003x/common/source/f28003x_codestartbranch.asm`
- `device_support/f28003x/common/cmd/28003x_launchxl_demo_flash_lnk.cmd`
- `driverlib/f28003x/driverlib/ccs/Debug/driverlib.lib`

Without these, the build fails with "file cannot be located" errors.

## 🐛 Issues Fixed

### 1. Docker Entrypoint Override (CRITICAL)
**Problem:** Script tried to override Docker entrypoint with `/bin/bash -c '...'`
**Symptom:** Import command received `/bin/bash` as project location
**Solution:** Use image's native entrypoint, pass `.projectspec` as argument

### 2. Missing C2000Ware
**Problem:** C2000Ware SDK files not mounted into container
**Symptom:** Build fails with "File/directory ... cannot be located"
**Solution:** Clone C2000Ware to `/tmp/c2000ware-core-sdk`, mount into container

### 3. Incorrect Docker Image Tag
**Problem:** README referenced `ubuntu24.04-20.2.0.00012` (doesn't exist)
**Symptom:** Docker pull fails or pulls wrong image
**Solution:** Use correct tag `20.2-ubuntu24.04`

### 4. ESP32-S3 Test Filename Check
**Problem:** Test script looked for `build/debug_full_main.bin`
**Actual:** `build/esp32s3-debug-full.bin`
**Solution:** Fixed filename check in `scripts/full-system-test.sh`

### 5. ESP32-C6 Test Filename Check
**Problem:** Test script looked for `build/main.bin`
**Actual:** `build/eab-test-firmware.bin`
**Solution:** Fixed filename check in `scripts/full-system-test.sh`

## 📊 Test Results

Full system test script now correctly builds:
- ✅ C2000 (F28003x via Docker)
- ✅ ESP32-S3 (ESP-IDF)
- ✅ ESP32-C6 (ESP-IDF)
- ✅ ESP32-P4 (ESP-IDF)
- ✅ nRF5340 (Zephyr)
- ✅ MCXN947 (Zephyr)
- ✅ STM32L4 (Zephyr)
- ✅ STM32N6 (Zephyr)

## 🗂️ Files Modified

**In EAB submodule:**
- `examples/c2000-stress-test/docker-build.sh` - Fixed Docker build
- `examples/c2000-stress-test/README.md` - Added prerequisites
- `examples/c2000-stress-test/QUICK-START.md` - New comprehensive guide
- `CLAUDE.md` - Added C2000Ware setup
- `scripts/full-system-test.sh` - Fixed filename checks

**In parent repo:**
- `work/dev/tools/embedded-agent-bridge` - Updated submodule pointer

## 🚀 Next Steps

After restart (if needed):
1. Verify Docker is running: `docker info`
2. Verify C2000Ware exists: `ls /tmp/c2000ware-core-sdk/`
3. Build firmware: `cd work/dev/tools/embedded-agent-bridge/examples/c2000-stress-test && ./docker-build.sh`
4. Flash to hardware: `eabctl flash examples/c2000-stress-test`

## 📝 Maintenance Notes

### If Build Stops Working

1. **Check Docker:**
   ```bash
   docker info
   ```
   If fails: Start Docker Desktop

2. **Check C2000Ware:**
   ```bash
   ls /tmp/c2000ware-core-sdk/device_support/f28003x/common/include/driverlib.h
   ```
   If missing: Re-clone (see setup above)

3. **Check Docker image:**
   ```bash
   docker images whuzfb/ccstudio
   ```
   Should see `20.2-ubuntu24.04`

### If /tmp is Cleared

On macOS, `/tmp` persists across reboots but may be cleared by cleanup tools.
If C2000Ware is deleted, re-run the clone command (takes ~2 minutes).

## ✅ Checklist

Setup complete when all these pass:
- [ ] `docker info` shows server version
- [ ] `docker images whuzfb/ccstudio` shows 20.2-ubuntu24.04
- [ ] `/tmp/c2000ware-core-sdk/` exists and contains device_support/
- [ ] `./docker-build.sh` produces `Debug/*.out` file
- [ ] Full system test passes all builds

---

**Last updated:** 2026-02-16
**Status:** ✅ All working and documented
