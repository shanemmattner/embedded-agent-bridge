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


def test_gave_up_flag_initialized():
    """The _gave_up flag should be initialized to False."""
    from eab.chip_recovery import ChipRecovery

    recovery = ChipRecovery(reset_callback=lambda _: True)

    # Verify the flag exists and is initialized to False
    assert hasattr(recovery, "_gave_up")
    assert recovery._gave_up is False


def test_gave_up_flag_persists_across_operations():
    """The _gave_up flag should remain False during normal operations."""
    from eab.chip_recovery import ChipRecovery

    recovery = ChipRecovery(reset_callback=lambda _: True)

    # Process some lines
    recovery.process_line("ESP-ROM:esp32c6-20220919")
    recovery.process_line("app_main()")

    # Flag should still be False
    assert recovery._gave_up is False

    # Check health
    health = recovery.get_health()
    assert recovery._gave_up is False

    # Check needs_recovery
    recovery.needs_recovery()
    assert recovery._gave_up is False


def test_gave_up_flag_reset_by_reset_counters():
    """The _gave_up flag should be reset to False by reset_counters()."""
    from eab.chip_recovery import ChipRecovery

    recovery = ChipRecovery(reset_callback=lambda _: True)

    # Manually set the flag to True (simulating it being set after max recovery attempts)
    recovery._gave_up = True

    # Reset counters
    recovery.reset_counters()

    # The flag should be False after reset_counters
    # This ensures proper logging if recovery attempts restart
    assert recovery._gave_up is False


def test_max_recovery_attempts_logs_only_once():
    """The 'giving up' message should be logged exactly once when max recovery attempts is reached."""
    from eab.chip_recovery import ChipRecovery

    # Create a mock logger to track error log calls
    error_messages = []

    class MockLogger:
        def info(self, msg):
            pass

        def warning(self, msg):
            pass

        def error(self, msg):
            error_messages.append(msg)

    mock_logger = MockLogger()

    # Create recovery with max_recovery_attempts=3
    recovery = ChipRecovery(
        reset_callback=lambda _: True,
        logger=mock_logger,
        max_recovery_attempts=3
    )

    # Simulate reaching max recovery attempts
    recovery._recovery_attempts = 3

    # First call to needs_recovery() should log the message
    result1 = recovery.needs_recovery()
    assert result1 is False  # Should return False when max attempts reached
    assert len(error_messages) == 1
    assert "Max recovery attempts reached, giving up" in error_messages[0]
    assert recovery._gave_up is True

    # Clear messages for clarity
    error_messages.clear()

    # Second call to needs_recovery() should NOT log the message again
    result2 = recovery.needs_recovery()
    assert result2 is False
    assert len(error_messages) == 0  # No new error messages
    assert recovery._gave_up is True  # Flag should remain True

    # Third call to needs_recovery() should still NOT log
    result3 = recovery.needs_recovery()
    assert result3 is False
    assert len(error_messages) == 0  # Still no new error messages
    assert recovery._gave_up is True


def test_max_recovery_attempts_resets_after_reset_counters():
    """After reset_counters(), the 'giving up' message should be logged again if max attempts is reached again."""
    from eab.chip_recovery import ChipRecovery

    error_messages = []

    class MockLogger:
        def info(self, msg):
            pass

        def warning(self, msg):
            pass

        def error(self, msg):
            error_messages.append(msg)

    mock_logger = MockLogger()

    recovery = ChipRecovery(
        reset_callback=lambda _: True,
        logger=mock_logger,
        max_recovery_attempts=2
    )

    # Reach max recovery attempts
    recovery._recovery_attempts = 2

    # First time: should log
    recovery.needs_recovery()
    assert len(error_messages) == 1
    assert recovery._gave_up is True

    # Call again: should not log
    error_messages.clear()
    recovery.needs_recovery()
    assert len(error_messages) == 0

    # Reset counters
    recovery.reset_counters()
    assert recovery._gave_up is False

    # Reach max recovery attempts again
    recovery._recovery_attempts = 2

    # Should log again after reset
    recovery.needs_recovery()
    assert len(error_messages) == 1
    assert "Max recovery attempts reached, giving up" in error_messages[0]
    assert recovery._gave_up is True


def test_reset_counters_resets_all_state():
    """reset_counters() should reset all counters and state including _gave_up."""
    from eab.chip_recovery import ChipRecovery, ChipState

    recovery = ChipRecovery(reset_callback=lambda _: True, max_recovery_attempts=3)

    # Simulate some activity
    recovery._consecutive_crashes = 5
    recovery._recovery_attempts = 3
    recovery._gave_up = True
    recovery._state = ChipState.CRASHED
    recovery._boot_events.append(object())  # Add something to the list

    # Verify pre-conditions
    assert recovery._consecutive_crashes == 5
    assert recovery._recovery_attempts == 3
    assert recovery._gave_up is True
    assert recovery._state == ChipState.CRASHED
    assert len(recovery._boot_events) > 0

    # Reset counters
    recovery.reset_counters()

    # Verify all counters and state are reset
    assert recovery._consecutive_crashes == 0
    assert recovery._recovery_attempts == 0
    assert recovery._gave_up is False
    assert recovery._state == ChipState.UNKNOWN
    assert len(recovery._boot_events) == 0


def test_max_recovery_attempts_logs_once():
    """
    Regression test for log spam fix.

    When max_recovery_attempts is reached, the error message should be
    logged exactly once, not repeatedly on every needs_recovery() call.
    """
    from eab.chip_recovery import ChipRecovery

    # Create a mock logger that counts error calls
    class MockLogger:
        def __init__(self):
            self.error_count = 0
            self.error_messages = []

        def error(self, msg):
            self.error_count += 1
            self.error_messages.append(msg)

        def info(self, msg):
            pass

        def warning(self, msg):
            pass

    mock_logger = MockLogger()

    # Create recovery with max_recovery_attempts=3
    recovery = ChipRecovery(
        reset_callback=lambda _: True,
        logger=mock_logger,
        max_recovery_attempts=3
    )

    # Set recovery_attempts to 3 to trigger the max threshold
    recovery._recovery_attempts = 3

    # Call needs_recovery() multiple times (e.g., 100 times)
    for i in range(100):
        recovery.needs_recovery()

    # Assert that the "Max recovery attempts reached, giving up" error
    # is logged exactly once, not 100 times
    assert mock_logger.error_count == 1
    assert len(mock_logger.error_messages) == 1
    assert "Max recovery attempts reached, giving up" in mock_logger.error_messages[0]


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

