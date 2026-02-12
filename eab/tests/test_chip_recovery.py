"""
Tests for chip recovery state detection.
"""

import os
import sys
import time

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__)))))


def test_task_wdt_api_errors_do_not_trigger_recovery():
    """Benign TWDT API errors should not mark the chip as crashed."""
    from eab.chip_recovery import ChipRecovery, ChipState

    recovery = ChipRecovery(reset_callback=lambda _: True)
    recovery.process_line("E (46365) task_wdt: esp_task_wdt_reset(705): task not found")

    assert recovery.get_health().state != ChipState.CRASHED


def test_actual_task_watchdog_trigger_marks_crashed():
    """Real watchdog trigger messages should mark the chip as crashed."""
    from eab.chip_recovery import ChipRecovery, ChipState

    recovery = ChipRecovery(reset_callback=lambda _: True)
    recovery.process_line(
        "E (12345) task_wdt: Task watchdog got triggered. The following tasks/users did not reset the watchdog in time:"
    )

    assert recovery.get_health().state == ChipState.CRASHED


def test_activity_based_running_state_detection():
    """Activity-based detection should transition to RUNNING after threshold lines."""
    from eab.chip_recovery import ChipRecovery, ChipState

    # Use a smaller threshold for faster testing
    recovery = ChipRecovery(
        reset_callback=lambda _: True,
        activity_window_seconds=30.0,
        activity_threshold=10,
    )

    # Initially should be UNKNOWN
    assert recovery.get_health().state == ChipState.UNKNOWN

    # Send 9 lines - should not trigger running state yet
    for i in range(9):
        recovery.process_line(f"Some output line {i}")

    assert recovery.get_health().state == ChipState.UNKNOWN

    # Send 10th line - should trigger running state
    recovery.process_line("Some output line 10")

    assert recovery.get_health().state == ChipState.RUNNING


def test_activity_based_detection_resets_counters():
    """Activity-based running state should reset crash and recovery counters when transitioning from non-crash states."""
    from eab.chip_recovery import ChipRecovery, ChipState

    recovery = ChipRecovery(
        reset_callback=lambda _: True,
        activity_window_seconds=30.0,
        activity_threshold=5,
    )

    # Start in BOOTING state and set some counters
    recovery.process_line("rst:0x1 (POWERON),boot:0x13 (SPI_FAST_FLASH_BOOT)")
    assert recovery.get_health().state == ChipState.BOOTING

    # Manually set counters to test reset (simulate previous crash that was recovered)
    recovery._consecutive_crashes = 2
    recovery._recovery_attempts = 1

    # Send enough lines to trigger activity-based running state
    for i in range(5):
        recovery.process_line(f"Normal output line {i}")

    # Should be running with counters reset
    assert recovery.get_health().state == ChipState.RUNNING
    assert recovery.get_health().consecutive_crashes == 0
    assert recovery._recovery_attempts == 0


def test_activity_based_detection_does_not_override_crash():
    """Activity-based detection should not override CRASHED state."""
    from eab.chip_recovery import ChipRecovery, ChipState

    recovery = ChipRecovery(
        reset_callback=lambda _: True,
        activity_window_seconds=30.0,
        activity_threshold=5,
    )

    # Build up some activity first
    for i in range(3):
        recovery.process_line(f"Normal output line {i}")

    # Crash
    recovery.process_line("Guru Meditation Error")
    assert recovery.get_health().state == ChipState.CRASHED

    # More activity should not change state to RUNNING while crashed
    for i in range(5):
        recovery.process_line(f"Crash backtrace line {i}")

    # Should still be crashed
    assert recovery.get_health().state == ChipState.CRASHED


def test_activity_based_detection_does_not_override_bootloop():
    """Activity-based detection should not override BOOTLOOP state."""
    from eab.chip_recovery import ChipRecovery, ChipState

    recovery = ChipRecovery(
        reset_callback=lambda _: True,
        boot_loop_threshold=3,
        activity_window_seconds=30.0,
        activity_threshold=5,
    )

    # Trigger boot loop by sending multiple boot messages quickly
    for i in range(3):
        recovery.process_line("rst:0x1 (POWERON),boot:0x13 (SPI_FAST_FLASH_BOOT)")
        time.sleep(0.1)  # Small delay to ensure within 1 minute

    assert recovery.get_health().state == ChipState.BOOTLOOP

    # More activity should not change state to RUNNING while in bootloop
    for i in range(5):
        recovery.process_line(f"Boot output line {i}")

    # Should still be in bootloop
    assert recovery.get_health().state == ChipState.BOOTLOOP


def test_activity_window_cleanup():
    """Activity timestamps outside the window should be cleaned up."""
    from eab.chip_recovery import ChipRecovery, ChipState

    recovery = ChipRecovery(
        reset_callback=lambda _: True,
        activity_window_seconds=1.0,  # Very short window for testing
        activity_threshold=5,
    )

    # Add some activity
    for i in range(5):
        recovery.process_line(f"Line {i}")

    # Should be running
    assert recovery.get_health().state == ChipState.RUNNING

    # Wait for window to expire
    time.sleep(1.5)

    # Process one more line to trigger cleanup
    recovery.process_line("New line after window expired")

    # Activity deque should have been cleaned, only 1 line should remain
    assert len(recovery._activity_timestamps) == 1


def test_activity_based_detection_with_normal_patterns():
    """Activity-based detection should work alongside normal pattern matching."""
    from eab.chip_recovery import ChipRecovery, ChipState

    recovery = ChipRecovery(
        reset_callback=lambda _: True,
        activity_window_seconds=30.0,
        activity_threshold=10,
    )

    # Send some normal output
    for i in range(5):
        recovery.process_line(f"Normal output {i}")

    # Should still be UNKNOWN (not enough lines yet)
    assert recovery.get_health().state == ChipState.UNKNOWN

    # Hit a running pattern
    recovery.process_line("app_main() starting")

    # Should be RUNNING from pattern match
    assert recovery.get_health().state == ChipState.RUNNING

    # More output should keep it running
    for i in range(5):
        recovery.process_line(f"More normal output {i}")

    assert recovery.get_health().state == ChipState.RUNNING


def test_reset_counters_clears_activity():
    """reset_counters() should clear activity timestamps."""
    from eab.chip_recovery import ChipRecovery

    recovery = ChipRecovery(
        reset_callback=lambda _: True,
        activity_window_seconds=30.0,
        activity_threshold=5,
    )

    # Build up activity
    for i in range(10):
        recovery.process_line(f"Line {i}")

    # Should have timestamps
    assert len(recovery._activity_timestamps) > 0

    # Reset counters
    recovery.reset_counters()

    # Activity should be cleared
    assert len(recovery._activity_timestamps) == 0


def test_activity_threshold_configurable():
    """Activity threshold should be configurable."""
    from eab.chip_recovery import ChipRecovery, ChipState

    # Test with threshold of 3
    recovery = ChipRecovery(
        reset_callback=lambda _: True,
        activity_window_seconds=30.0,
        activity_threshold=3,
    )

    # Send 2 lines - should not trigger
    for i in range(2):
        recovery.process_line(f"Line {i}")

    assert recovery.get_health().state == ChipState.UNKNOWN

    # Send 3rd line - should trigger
    recovery.process_line("Line 3")

    assert recovery.get_health().state == ChipState.RUNNING


def test_activity_window_configurable():
    """Activity window should be configurable."""
    from eab.chip_recovery import ChipRecovery, ChipState

    # Test with very short window
    recovery = ChipRecovery(
        reset_callback=lambda _: True,
        activity_window_seconds=0.5,
        activity_threshold=3,
    )

    # Send 3 lines quickly
    for i in range(3):
        recovery.process_line(f"Line {i}")

    assert recovery.get_health().state == ChipState.RUNNING

    # Wait for window to expire
    time.sleep(0.6)

    # Reset to unknown manually
    recovery._state = ChipState.UNKNOWN

    # Send one line - should not trigger (old lines expired)
    recovery.process_line("New line")

    # Should still be UNKNOWN (only 1 line in window)
    assert recovery.get_health().state == ChipState.UNKNOWN

