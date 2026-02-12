"""
Tests for chip recovery state detection.
"""

import os
import sys

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

