# End-to-End Testing Log

**Date:** 2026-02-15
**Goal:** Build, flash, test, and validate all 5 debug-full examples
**Status:** IN PROGRESS

## Test Plan

### Phase 1: Build Validation
- [ ] nRF5340 debug-full
- [ ] ESP32-C6 debug-full
- [ ] ESP32-S3 debug-full
- [ ] MCXN947 debug-full
- [ ] STM32L4 debug-full

### Phase 2: Hardware Testing
- [ ] Flash and test nRF5340
- [ ] Flash and test ESP32-C6
- [ ] Flash and test ESP32-S3
- [ ] Flash and test MCXN947
- [ ] Flash and test STM32L4

### Phase 3: Trace Capture
- [ ] Capture nRF5340 CTF trace
- [ ] Capture ESP32-C6 SystemView trace
- [ ] Export to Perfetto JSON
- [ ] Validate in Perfetto UI

### Phase 4: Integration
- [ ] Integrate sysviewtrace_proc.py
- [ ] Integrate babeltrace
- [ ] Create automated test scripts

## Connected Hardware

```
/dev/cu.usbmodem0010500636591  - Unknown
/dev/cu.usbmodem0010500636593  - Unknown
/dev/cu.usbmodem101            - nRF5340 (identified)
/dev/cu.usbmodem5AF71054031    - Unknown
/dev/cu.usbmodem83303          - Unknown
/dev/cu.usbmodemCL3910781      - Unknown
/dev/cu.usbmodemCL3910784      - Unknown
/dev/cu.usbmodemI2WZW2OTY3RUW3 - Unknown
```

## Test Results

### Test 1: nRF5340 Build
**Time:** Starting...
**Command:** `west build -b nrf5340dk_nrf5340_cpuapp`
**Result:**

