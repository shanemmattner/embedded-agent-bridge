# ⚠️ DO NOT USE PROBE-RS RTT

**Last attempted**: 2026-02-15  
**Attempts**: 2  
**Time wasted**: ~14 hours  
**Status**: DOES NOT WORK

## Summary

probe-rs RTT integration has been attempted **twice** and fails on all hardware tested. The implementation is technically correct but **blocked by upstream probe-rs driver bugs**.

## What Doesn't Work

**RTT data capture fails on every board:**

- STM32L432KC + ST-Link: Memory access bug
- FRDM-MCXN947 + CMSIS-DAP: ARM-specific error
- nRF5340 + J-Link: ARM-specific error

## What DOES Work

**Use JLinkBridge instead** - tested and working:

```bash
eabctl rtt start --device NRF5340_XXAA_APP --transport jlink
```

Works perfectly on nRF5340 with J-Link. Use this.

## Branch (DO NOT MERGE)

`feat/probe-rs-native-rtt` - Contains:
- Rust/PyO3 extension with ELF symbol reading
- Full RTT transport implementation
- All code quality standards met
- **ZERO working RTT capture**

## Upstream Issues

1. **ST-Link**: probe-rs/probe-rs#3495 - Cannot read RAM
2. **ARM errors**: Unknown cause

## DO NOT ATTEMPT AGAIN

Unless you can confirm:
1. ✅ Upstream probe-rs fixed ST-Link memory bug
2. ✅ Someone independently verified RTT works with probe-rs
3. ✅ You have hardware where it's proven working

## References

- GitHub Issue #37: Full investigation
- PR #118: Failed implementation
- `docs/probe-rs-test-results.md`: Hardware test results
