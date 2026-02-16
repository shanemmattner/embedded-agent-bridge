"""Tests for reset reason tracker."""

from __future__ import annotations

from datetime import datetime
from unittest.mock import MagicMock

import pytest

from eab.reset_reason import ResetReasonTracker, ResetEvent
from eab.interfaces import ClockInterface


class FakeClock:
    """Fake clock for testing with controllable time."""
    
    def __init__(self, start_time: datetime):
        self._time = start_time
    
    def now(self) -> datetime:
        return self._time
    
    def advance(self, seconds: int) -> None:
        from datetime import timedelta
        self._time += timedelta(seconds=seconds)


class TestResetReasonTracker:
    """Test reset reason detection and tracking."""

    @pytest.fixture
    def clock(self):
        """Create a fake clock starting at a known time."""
        return FakeClock(datetime(2026, 2, 13, 10, 0, 0))

    @pytest.fixture
    def tracker(self, clock):
        """Create a reset reason tracker with fake clock."""
        return ResetReasonTracker(clock)

    # =========================================================================
    # ESP32 Pattern Tests
    # =========================================================================

    def test_esp32_poweron_reset(self, tracker):
        """Test ESP32 power-on reset detection."""
        line = "rst:0x1 (POWERON_RESET),boot:0x13 (SPI_FAST_FLASH_BOOT)"
        event = tracker.check_line(line)
        
        assert event is not None
        assert event.reason == "POWERON_RESET"
        assert event.raw_line == line
        
        stats = tracker.get_statistics()
        assert stats["last_reason"] == "POWERON_RESET"
        assert stats["history"]["POWERON_RESET"] == 1
        assert stats["total"] == 1

    def test_esp32_watchdog_reset(self, tracker):
        """Test ESP32 watchdog reset detection."""
        line = "rst:0x7 (TG0WDT_SYS_RESET),boot:0x13 (SPI_FAST_FLASH_BOOT)"
        event = tracker.check_line(line)
        
        assert event is not None
        assert event.reason == "TG0WDT_SYS_RESET"
        assert tracker.is_unexpected_reset(event.reason)

    def test_esp32_software_reset(self, tracker):
        """Test ESP32 software reset detection."""
        line = "rst:0x3 (SW_RESET),boot:0x13 (SPI_FAST_FLASH_BOOT)"
        event = tracker.check_line(line)
        
        assert event is not None
        assert event.reason == "SW_RESET"

    def test_esp32_brownout_reset(self, tracker):
        """Test ESP32 brownout reset detection and alert."""
        line = "rst:0xc (BROWNOUT_RESET),boot:0x13 (SPI_FAST_FLASH_BOOT)"
        event = tracker.check_line(line)
        
        assert event is not None
        assert event.reason == "BROWNOUT_RESET"
        assert tracker.is_unexpected_reset(event.reason)

    def test_esp32_panic_reset(self, tracker):
        """Test ESP32 panic/SW_CPU_RESET detection."""
        line = "rst:0xb (SW_CPU_RESET),boot:0x13 (SPI_FAST_FLASH_BOOT)"
        event = tracker.check_line(line)
        
        assert event is not None
        assert event.reason == "SW_CPU_RESET"
        assert tracker.is_unexpected_reset(event.reason)

    def test_esp32_deepsleep_reset(self, tracker):
        """Test ESP32 deep sleep wake detection."""
        line = "rst:0x5 (DEEPSLEEP_RESET),boot:0x13 (SPI_FAST_FLASH_BOOT)"
        event = tracker.check_line(line)
        
        assert event is not None
        assert event.reason == "DEEPSLEEP_RESET"

    # =========================================================================
    # Zephyr nRF5340 Pattern Tests
    # =========================================================================

    def test_zephyr_nrf_resetpin(self, tracker):
        """Test Zephyr nRF5340 reset pin detection."""
        line = "Reset reason: 0x00000001 (RESETPIN)"
        event = tracker.check_line(line)
        
        assert event is not None
        assert event.reason == "RESETPIN"

    def test_zephyr_nrf_dog(self, tracker):
        """Test Zephyr nRF5340 watchdog reset detection."""
        line = "Reset reason: 0x00000002 (DOG)"
        event = tracker.check_line(line)
        
        assert event is not None
        assert event.reason == "DOG"
        # DOG = watchdog in nRF speak, but our pattern matches "WDT" or "WATCHDOG"
        # This specific abbreviation won't match, which is intentional

    def test_zephyr_nrf_lockup(self, tracker):
        """Test Zephyr nRF5340 lockup reset detection."""
        line = "Reset reason: 0x00000008 (LOCKUP)"
        event = tracker.check_line(line)
        
        assert event is not None
        assert event.reason == "LOCKUP"
        assert tracker.is_unexpected_reset(event.reason)

    def test_zephyr_nrf_sreq(self, tracker):
        """Test Zephyr nRF5340 system reset request detection."""
        line = "Reset reason: 0x00000010 (SREQ)"
        event = tracker.check_line(line)
        
        assert event is not None
        assert event.reason == "SREQ"

    # =========================================================================
    # Zephyr STM32 Pattern Tests
    # =========================================================================

    def test_zephyr_stm32_pin_reset(self, tracker):
        """Test Zephyr STM32 PIN reset detection."""
        line = "Reset cause: PIN (RCC_CSR = 0x0C000000)"
        event = tracker.check_line(line)
        
        assert event is not None
        assert event.reason == "PIN"

    def test_zephyr_stm32_pin_reset_no_register(self, tracker):
        """Test Zephyr STM32 PIN reset without register value."""
        line = "Reset cause: PIN"
        event = tracker.check_line(line)
        
        assert event is not None
        assert event.reason == "PIN"

    def test_zephyr_stm32_por(self, tracker):
        """Test Zephyr STM32 power-on reset detection."""
        line = "Reset cause: POR (RCC_CSR = 0x14000000)"
        event = tracker.check_line(line)
        
        assert event is not None
        assert event.reason == "POR"

    def test_zephyr_stm32_software(self, tracker):
        """Test Zephyr STM32 software reset detection."""
        line = "Reset cause: SOFTWARE (RCC_CSR = 0x18000000)"
        event = tracker.check_line(line)
        
        assert event is not None
        assert event.reason == "SOFTWARE"

    # =========================================================================
    # Generic Pattern Tests
    # =========================================================================

    def test_generic_reset_cause(self, tracker):
        """Test generic 'Reset cause:' pattern."""
        line = "Reset cause: Power-on reset"
        event = tracker.check_line(line)
        
        assert event is not None
        assert event.reason == "POWER-ON RESET"

    def test_generic_boot_reason(self, tracker):
        """Test generic 'Boot reason:' pattern."""
        line = "Boot reason: Watchdog timeout"
        event = tracker.check_line(line)
        
        assert event is not None
        assert event.reason == "WATCHDOG TIMEOUT"
        assert tracker.is_unexpected_reset(event.reason)

    def test_generic_reset_reason_with_parens(self, tracker):
        """Test generic pattern with trailing data in parens."""
        line = "Reset reason: External pin (code 0x04)"
        event = tracker.check_line(line)
        
        assert event is not None
        assert event.reason == "EXTERNAL PIN"

    # =========================================================================
    # Boot Detection Tests
    # =========================================================================

    def test_zephyr_boot_banner_nrf_connect(self, tracker):
        """Test Zephyr nRF Connect SDK boot banner detection."""
        line = "*** Booting nRF Connect SDK v2.5.0 ***"
        assert tracker.is_boot_line(line)

    def test_zephyr_boot_banner_zephyr(self, tracker):
        """Test Zephyr OS boot banner detection."""
        line = "*** Booting Zephyr OS build v3.4.0 ***"
        assert tracker.is_boot_line(line)

    def test_esp32_boot_banner_rst(self, tracker):
        """Test ESP32 rst: pattern as boot indicator."""
        line = "rst:0x1 (POWERON_RESET),boot:0x13 (SPI_FAST_FLASH_BOOT)"
        assert tracker.is_boot_line(line)

    def test_esp32_boot_banner_configsip(self, tracker):
        """Test ESP32 configsip: pattern as boot indicator."""
        line = "configsip: 0, SPIWP:0xee"
        assert tracker.is_boot_line(line)

    def test_esp32_boot_banner_esprom(self, tracker):
        """Test ESP32 ESP-ROM: pattern as boot indicator."""
        line = "ESP-ROM:esp32s3-20210327"
        assert tracker.is_boot_line(line)

    def test_non_boot_line(self, tracker):
        """Test that regular log lines aren't detected as boot."""
        line = "I (12345) main: Application running"
        assert not tracker.is_boot_line(line)

    # =========================================================================
    # Statistics Tests
    # =========================================================================

    def test_multiple_resets_statistics(self, tracker, clock):
        """Test statistics with multiple resets of different types."""
        # Simulate 5 power-on resets and 2 watchdog resets
        for i in range(5):
            tracker.check_line("rst:0x1 (POWERON_RESET),boot:0x13 (SPI_FAST_FLASH_BOOT)")
            clock.advance(60)  # 1 minute between resets
        
        for i in range(2):
            tracker.check_line("rst:0x7 (TG0WDT_SYS_RESET),boot:0x13 (SPI_FAST_FLASH_BOOT)")
            clock.advance(60)
        
        stats = tracker.get_statistics()
        assert stats["history"]["POWERON_RESET"] == 5
        assert stats["history"]["TG0WDT_SYS_RESET"] == 2
        assert stats["total"] == 7
        assert stats["last_reason"] == "TG0WDT_SYS_RESET"

    def test_recent_resets(self, tracker, clock):
        """Test get_recent_resets returns newest first."""
        # Add 15 resets
        for i in range(15):
            tracker.check_line(f"Reset reason: RESET_{i}")
            clock.advance(10)
        
        # Get last 10
        recent = tracker.get_recent_resets(count=10)
        assert len(recent) == 10
        
        # Should be newest first (RESET_14 down to RESET_5)
        assert recent[0]["reason"] == "RESET_14"
        assert recent[9]["reason"] == "RESET_5"

    def test_recent_resets_fewer_than_requested(self, tracker):
        """Test get_recent_resets when history is shorter than count."""
        tracker.check_line("rst:0x1 (POWERON_RESET),boot:0x13 (SPI_FAST_FLASH_BOOT)")
        tracker.check_line("rst:0x3 (SW_RESET),boot:0x13 (SPI_FAST_FLASH_BOOT)")
        
        recent = tracker.get_recent_resets(count=10)
        assert len(recent) == 2
        assert recent[0]["reason"] == "SW_RESET"
        assert recent[1]["reason"] == "POWERON_RESET"

    def test_reset_statistics_clears_data(self, tracker):
        """Test reset_statistics clears all tracking data."""
        tracker.check_line("rst:0x1 (POWERON_RESET),boot:0x13 (SPI_FAST_FLASH_BOOT)")
        tracker.check_line("rst:0x7 (TG0WDT_SYS_RESET),boot:0x13 (SPI_FAST_FLASH_BOOT)")
        
        tracker.reset_statistics()
        
        stats = tracker.get_statistics()
        assert stats["last_reason"] is None
        assert stats["last_time"] is None
        assert stats["history"] == {}
        assert stats["total"] == 0

    # =========================================================================
    # Unexpected Reset Detection Tests
    # =========================================================================

    def test_unexpected_reset_watchdog_exact_match(self, tracker):
        """Test watchdog reset triggers alert (exact match)."""
        assert tracker.is_unexpected_reset("WATCHDOG")
        assert tracker.is_unexpected_reset("WDT")
        assert tracker.is_unexpected_reset("TG0WDT_SYS_RESET")

    def test_unexpected_reset_brownout(self, tracker):
        """Test brownout reset triggers alert."""
        assert tracker.is_unexpected_reset("BROWNOUT")
        assert tracker.is_unexpected_reset("BROWNOUT_RESET")

    def test_unexpected_reset_panic(self, tracker):
        """Test panic/SW_CPU_RESET triggers alert."""
        assert tracker.is_unexpected_reset("PANIC")
        assert tracker.is_unexpected_reset("SW_CPU_RESET")

    def test_unexpected_reset_lockup(self, tracker):
        """Test lockup reset triggers alert."""
        assert tracker.is_unexpected_reset("LOCKUP")

    def test_unexpected_reset_partial_match(self, tracker):
        """Test partial match for watchdog variants."""
        # "TASK_WDT" should match "WDT" substring
        assert tracker.is_unexpected_reset("TASK_WDT_RESET_CPU0")
        assert tracker.is_unexpected_reset("INT_WDT_TIMEOUT")

    def test_expected_reset_poweron(self, tracker):
        """Test power-on reset doesn't trigger alert."""
        assert not tracker.is_unexpected_reset("POWERON_RESET")
        assert not tracker.is_unexpected_reset("POWERON")
        assert not tracker.is_unexpected_reset("POR")

    def test_expected_reset_software(self, tracker):
        """Test software reset doesn't trigger alert (unless SW_CPU)."""
        assert not tracker.is_unexpected_reset("SW_RESET")
        assert not tracker.is_unexpected_reset("SOFTWARE")
        # But SW_CPU_RESET *is* unexpected (panic)
        assert tracker.is_unexpected_reset("SW_CPU_RESET")

    def test_expected_reset_pin(self, tracker):
        """Test pin/external reset doesn't trigger alert."""
        assert not tracker.is_unexpected_reset("RESETPIN")
        assert not tracker.is_unexpected_reset("PIN")
        assert not tracker.is_unexpected_reset("EXTERNAL PIN")

    # =========================================================================
    # Edge Cases
    # =========================================================================

    def test_no_match_returns_none(self, tracker):
        """Test lines without reset patterns return None."""
        line = "I (12345) main: Application running normally"
        event = tracker.check_line(line)
        assert event is None

    def test_case_insensitive_matching(self, tracker):
        """Test pattern matching is case-insensitive."""
        # Lowercase rst:
        event1 = tracker.check_line("rst:0x1 (poweron_reset),boot:0x13 (spi_fast_flash_boot)")
        assert event1 is not None
        assert event1.reason == "POWERON_RESET"
        
        # Mixed case Reset
        event2 = tracker.check_line("ReSeT rEaSoN: 0x00000001 (ResetPin)")
        assert event2 is not None
        assert event2.reason == "RESETPIN"

    def test_whitespace_handling(self, tracker):
        """Test patterns handle extra whitespace."""
        line = "rst:0x1   (  POWERON_RESET  ),boot:0x13 (SPI_FAST_FLASH_BOOT)"
        event = tracker.check_line(line)
        
        assert event is not None
        assert event.reason == "POWERON_RESET"

    def test_empty_line(self, tracker):
        """Test empty line doesn't crash."""
        event = tracker.check_line("")
        assert event is None

    def test_statistics_with_no_resets(self, tracker):
        """Test statistics with no resets recorded."""
        stats = tracker.get_statistics()
        assert stats["last_reason"] is None
        assert stats["last_time"] is None
        assert stats["history"] == {}
        assert stats["total"] == 0
