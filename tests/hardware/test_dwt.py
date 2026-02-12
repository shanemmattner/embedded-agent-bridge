"""DWT cycle counter tests (ARM Cortex-M only)."""

import time

import pytest


pytestmark = pytest.mark.hardware


def test_dwt_counter_increments(dwt):
    """Read CYCCNT twice with a gap — delta should be > 0.

    The CPU must be resumed between reads because CYCCNT only counts
    while the core is executing instructions (not while halted).
    """
    dwt.enable()
    count1 = dwt.read_cyccnt()
    assert count1 is not None, "Failed to read DWT_CYCCNT (first read)"

    # Resume so the counter actually ticks, then halt to read
    dwt.resume()
    time.sleep(0.1)
    dwt.halt()

    count2 = dwt.read_cyccnt()
    assert count2 is not None, "Failed to read DWT_CYCCNT (second read)"

    # Counter wraps at 32 bits, so handle wrap-around
    if count2 >= count1:
        delta = count2 - count1
    else:
        delta = (0xFFFFFFFF - count1) + count2 + 1

    assert delta > 0, f"CYCCNT did not increment: {count1:#x} -> {count2:#x}"


def test_dwt_enable_disable(dwt):
    """Toggle CYCCNTENA bit and verify via DWT_CTRL readback."""
    # Enable
    dwt.enable()
    ctrl = dwt.read_ctrl()
    assert ctrl is not None, "Failed to read DWT_CTRL"
    assert ctrl & 1, f"CYCCNTENA not set after enable: DWT_CTRL=0x{ctrl:08X}"

    # Disable
    dwt.disable()
    ctrl = dwt.read_ctrl()
    assert ctrl is not None, "Failed to read DWT_CTRL after disable"
    assert not (ctrl & 1), f"CYCCNTENA still set after disable: DWT_CTRL=0x{ctrl:08X}"

    # Re-enable for other tests
    dwt.enable()


def test_dwt_counter_magnitude(dwt):
    """Delta over 100ms should be in a reasonable range for typical CPU freqs.

    Most Cortex-M targets run 16-168 MHz. At 100ms:
    - 16 MHz  -> ~1.6M cycles
    - 64 MHz  -> ~6.4M cycles
    - 168 MHz -> ~16.8M cycles

    We use a generous range (100K to 100M) to avoid false failures
    from clock config variations.
    """
    dwt.enable()
    count1 = dwt.read_cyccnt()
    assert count1 is not None

    dwt.resume()
    time.sleep(0.1)
    dwt.halt()

    count2 = dwt.read_cyccnt()
    assert count2 is not None

    if count2 >= count1:
        delta = count2 - count1
    else:
        delta = (0xFFFFFFFF - count1) + count2 + 1

    assert 100_000 < delta < 100_000_000, (
        f"CYCCNT delta {delta:,} over ~100ms is outside expected range "
        f"(100K-100M cycles). Check CPU frequency."
    )
