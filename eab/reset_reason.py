"""
Reset Reason Tracker for Embedded Agent Bridge.

Detects and tracks device reset reasons across multiple targets:
- ESP32/ESP-IDF: rst:0x patterns
- Zephyr (nRF5340): POWER.RESETREAS register
- Zephyr (STM32): RCC_CSR register
- Generic: "Reset cause:" patterns

Maintains reset history in status.json and alerts on unexpected resets.
"""

from __future__ import annotations

import re
from dataclasses import dataclass, field
from datetime import datetime
from typing import Optional

from .interfaces import ClockInterface


@dataclass
class ResetEvent:
    """Single reset event with timestamp and reason."""
    timestamp: datetime
    reason: str
    raw_line: str = ""


class ResetReasonTracker:
    """
    Tracks device reset reasons across boot cycles.
    
    Features:
    - Multi-target pattern matching (ESP32, Zephyr nRF, Zephyr STM32, generic)
    - Reset history with timestamps
    - Statistics tracking (counts by reason)
    - Alert detection for unexpected resets (watchdog, brownout, panic)
    """

    # ESP32 reset reason patterns
    # Format: rst:0x1 (POWERON_RESET),boot:0x13 (SPI_FAST_FLASH_BOOT)
    ESP32_RESET_PATTERN = re.compile(
        r'rst:0x[0-9a-fA-F]+\s*\(([^)]+)\)',
        re.IGNORECASE
    )

    # Zephyr nRF5340 reset reason patterns
    # Example: "*** Booting nRF Connect SDK v2.5.0 ***"
    #          "Reset reason: 0x00000004 (RESETPIN)"
    ZEPHYR_NRF_RESET_PATTERN = re.compile(
        r'Reset\s+reason:\s*0x[0-9a-fA-F]+\s*\(([^)]+)\)',
        re.IGNORECASE
    )

    # Zephyr STM32 reset reason patterns
    # Example: "Reset cause: PIN (RCC_CSR = 0x0C000000)"
    # Pattern requires either RCC_CSR register or a single uppercase word
    ZEPHYR_STM32_RESET_PATTERN = re.compile(
        r'Reset\s+cause:\s*([A-Z_]+)(?:\s*\(RCC_CSR\s*=\s*0x[0-9a-fA-F]+\)|(?=\s*$))',
        re.IGNORECASE
    )

    # Generic reset/boot patterns
    # Example: "Reset cause: Power-on reset"
    #          "Boot reason: Watchdog timeout"
    GENERIC_RESET_PATTERN = re.compile(
        r'(?:Reset|Boot)\s+(?:cause|reason):\s*([^(]+?)(?:\s*\(|$)',
        re.IGNORECASE
    )

    # Zephyr boot banner (helps detect boot cycles)
    ZEPHYR_BOOT_BANNER = re.compile(
        r'\*\*\*\s+Booting\s+(?:Zephyr|nRF Connect SDK)',
        re.IGNORECASE
    )

    # ESP32 boot banner alternatives
    ESP32_BOOT_BANNER = re.compile(
        r'(?:ESP-ROM:|rst:0x|configsip:)',
        re.IGNORECASE
    )

    # Reset reasons that trigger alerts (unexpected resets)
    ALERT_REASONS = {
        # Watchdog resets
        "WATCHDOG", "WDT", "TG0WDT_SYS_RESET", "TG1WDT_SYS_RESET",
        "RTCWDT_RTC_RESET", "INT_WDT", "TASK_WDT",
        # Brownout
        "BROWNOUT", "BROWNOUT_RESET",
        # Panic/crash
        "PANIC", "SW_CPU_RESET", "EXCEPTION", "DEEPSLEEP_RESET",
        # Fault resets
        "LOCKUP", "SYSRESETREQ",
    }

    def __init__(self, clock: ClockInterface):
        """
        Initialize reset reason tracker.
        
        Args:
            clock: Clock interface for timestamps
        """
        self._clock = clock
        self._history: list[ResetEvent] = []
        self._counts: dict[str, int] = {}
        self._last_reason: Optional[str] = None
        self._last_time: Optional[datetime] = None

    def check_line(self, line: str) -> Optional[ResetEvent]:
        """
        Check line for reset reason patterns.
        
        Args:
            line: Serial output line to check
            
        Returns:
            ResetEvent if reset reason detected, None otherwise
        """
        reason = None
        
        # Try ESP32 pattern first (most specific)
        match = self.ESP32_RESET_PATTERN.search(line)
        if match:
            reason = match.group(1).strip()
        
        # Try Zephyr nRF pattern
        if not reason:
            match = self.ZEPHYR_NRF_RESET_PATTERN.search(line)
            if match:
                reason = match.group(1).strip()
        
        # Try Zephyr STM32 pattern
        if not reason:
            match = self.ZEPHYR_STM32_RESET_PATTERN.search(line)
            if match:
                reason = match.group(1).strip()
        
        # Try generic pattern
        if not reason:
            match = self.GENERIC_RESET_PATTERN.search(line)
            if match:
                reason = match.group(1).strip()
        
        if reason:
            # Normalize reason (uppercase, strip whitespace)
            reason = reason.upper().strip()
            
            # Record the event
            event = ResetEvent(
                timestamp=self._clock.now(),
                reason=reason,
                raw_line=line.strip()
            )
            self._record_reset(event)
            return event
        
        return None

    def is_boot_line(self, line: str) -> bool:
        """
        Check if line indicates a boot/reset event.
        
        Useful for detecting boot cycles even when reset reason
        isn't explicitly printed.
        
        Args:
            line: Serial output line
            
        Returns:
            True if line indicates boot/reset
        """
        return bool(
            self.ZEPHYR_BOOT_BANNER.search(line) or
            self.ESP32_BOOT_BANNER.search(line)
        )

    def _record_reset(self, event: ResetEvent) -> None:
        """Record a reset event in history and update statistics."""
        self._history.append(event)
        self._last_reason = event.reason
        self._last_time = event.timestamp
        
        # Update count
        self._counts[event.reason] = self._counts.get(event.reason, 0) + 1

    def is_unexpected_reset(self, reason: str) -> bool:
        """
        Check if reset reason should trigger an alert.
        
        Args:
            reason: Reset reason string (case-insensitive)
            
        Returns:
            True if reset is unexpected (watchdog, brownout, panic, etc.)
        """
        reason_upper = reason.upper()
        
        # Check exact matches
        if reason_upper in self.ALERT_REASONS:
            return True
        
        # Check substrings (for partial matches like "TASK_WDT_RESET_CPU")
        for alert_pattern in self.ALERT_REASONS:
            if alert_pattern in reason_upper:
                return True
        
        return False

    def get_statistics(self) -> dict:
        """
        Get reset statistics for status.json.
        
        Returns:
            Dict with reset statistics:
            {
                "last_reason": "POWERON",
                "last_time": "2026-02-13T...",
                "history": {"POWERON": 5, "WATCHDOG": 2},
                "total": 7
            }
        """
        return {
            "last_reason": self._last_reason,
            "last_time": self._last_time.isoformat() if self._last_time else None,
            "history": self._counts.copy(),
            "total": len(self._history),
        }

    def get_recent_resets(self, count: int = 10) -> list[dict]:
        """
        Get recent reset events.
        
        Args:
            count: Number of recent events to return
            
        Returns:
            List of reset events (newest first) as dicts
        """
        recent = self._history[-count:] if len(self._history) > count else self._history
        return [
            {
                "timestamp": event.timestamp.isoformat(),
                "reason": event.reason,
                "raw_line": event.raw_line,
            }
            for event in reversed(recent)
        ]

    def reset_statistics(self) -> None:
        """Clear all reset history and statistics."""
        self._history.clear()
        self._counts.clear()
        self._last_reason = None
        self._last_time = None
