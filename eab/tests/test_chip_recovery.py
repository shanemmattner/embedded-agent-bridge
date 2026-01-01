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

