#!/usr/bin/env python3
"""
Chip Recovery Module for Embedded Agent Bridge.

Provides:
- Detection of stuck/crashed states
- Automatic recovery via reset sequences
- Watchdog monitoring
- Clean shutdown protocols
- Boot loop detection
"""

import time
from collections import deque
from dataclasses import dataclass, field
from datetime import datetime, timedelta
from typing import Optional, List, Callable, Deque
from enum import Enum


class ChipState(Enum):
    """Possible chip states."""
    UNKNOWN = "unknown"
    BOOTING = "booting"
    RUNNING = "running"
    CRASHED = "crashed"
    BOOTLOOP = "bootloop"
    STUCK = "stuck"
    BOOTLOADER = "bootloader"
    RECOVERY = "recovery"


@dataclass
class BootEvent:
    """Record of a boot event."""
    timestamp: datetime
    reset_reason: str
    boot_mode: str


@dataclass
class ChipHealth:
    """Current health assessment of the chip."""
    state: ChipState
    last_output: Optional[datetime]
    boot_count_last_minute: int
    last_reset_reason: str
    consecutive_crashes: int
    uptime_seconds: float
    is_responsive: bool


class ChipRecovery:
    """
    Monitors chip health and performs automatic recovery when needed.

    Features:
    - Boot loop detection (too many boots in short time)
    - Crash detection (Guru Meditation, panic, etc.)
    - Stuck detection (no output for too long)
    - Automatic recovery via reset sequences
    - Clean shutdown that leaves chip running

    Usage:
        recovery = ChipRecovery(
            reset_callback=device_controller.reset,
            logger=logger,
        )

        # In main loop, feed it each line
        recovery.process_line(line)

        # Check if recovery needed
        if recovery.needs_recovery():
            recovery.perform_recovery()
    """

    # Patterns indicating various states (based on ESP-IDF documentation and common issues)
    BOOT_PATTERNS = [
        "rst:0x",
        "boot:0x",
        "ESP-ROM:",
        "Chip Revision:",
        "ESP-IDF",
        "boot: ESP32",
        "configsip:",
        # Zephyr patterns
        "*** Booting Zephyr",
        "Zephyr OS build",
    ]

    # Comprehensive crash patterns from ESP-IDF Fatal Errors documentation
    CRASH_PATTERNS = [
        # Core panic types
        "Guru Meditation",
        "Backtrace:",
        "abort()",
        "panic'ed",

        # CPU exceptions (LoadProhibited, StoreProhibited, etc.)
        "LoadProhibited",
        "StoreProhibited",
        "InstrFetchProhibited",
        "LoadStoreAlignment",
        "LoadStoreError",
        "IllegalInstruction",
        "IntegerDivideByZero",
        "Unhandled debug exception",

        # Cache errors (common with ISR issues)
        "Cache disabled but cached memory region accessed",
        "cache err",
        "cache_err",

        # Memory corruption
        "CORRUPT HEAP",
        "heap_caps_alloc",
        "heap corrupt",
        "Stack smashing",
        "stack overflow",
        "Out of memory",
        "alloc failed",

        # Assert failures
        "assert failed",
        "assertion",
        "ESP_ERROR_CHECK",

        # FreeRTOS panics
        "vApplicationStackOverflowHook",
        "configASSERT",

        # Brownout
        "Brownout detector",
        "brownout",

        # Double exception (very bad)
        "Double exception",

        # SPI flash errors
        "flash read err",

        # Zephyr fatal error patterns
        "E: ***** ",
        "E: r0/a0:",
        "E: Current thread:",
        ">>> ZEPHYR FATAL ERROR",
    ]

    BOOTLOADER_PATTERNS = [
        "waiting for download",
        "download mode",
        "boot mode.*DOWNLOAD",
        "DOWNLOAD(USB/UART0)",
        "boot:0x0",  # Download mode boot
        "serial flasher",
    ]

    WATCHDOG_PATTERNS = [
        "Task watchdog got triggered",
        "Interrupt wdt timeout",
        "RTC_WDT",
        "INT_WDT",
        "wdt reset",
    ]

    RUNNING_PATTERNS = [
        "app_main()",
        "Returned from app_main",
        "main_task:",
        "heap_init:",  # Early but indicates successful boot
        # Zephyr patterns
        "<inf>",  # Zephyr info log prefix
        "<dbg>",  # Zephyr debug log prefix
        "<wrn>",  # Zephyr warning log prefix
        "uart:~$",  # Zephyr shell prompt
    ]

    # Patterns indicating connectivity issues
    CONNECTIVITY_PATTERNS = [
        "wifi:.*disconnect",
        "WIFI_EVENT_STA_DISCONNECTED",
        "esp_wifi_connect",
        "BLE.*error",
    ]

    def __init__(
        self,
        reset_callback: Optional[Callable] = None,
        logger=None,
        boot_loop_threshold: int = 5,  # Max boots per minute before intervention
        stuck_timeout: float = 60.0,  # Seconds without output = stuck
        crash_recovery_delay: float = 2.0,  # Wait before recovery reset
        max_recovery_attempts: int = 3,  # Give up after this many attempts
        activity_window_seconds: float = 30.0,  # Window for activity detection
        activity_threshold: int = 10,  # Lines needed in window for running state
    ):
        self._reset_callback = reset_callback
        self._logger = logger
        self._boot_loop_threshold = boot_loop_threshold
        self._stuck_timeout = stuck_timeout
        self._crash_recovery_delay = crash_recovery_delay
        self._max_recovery_attempts = max_recovery_attempts
        self._activity_window_seconds = activity_window_seconds
        self._activity_threshold = activity_threshold

        # State tracking
        self._state = ChipState.UNKNOWN
        self._last_output_time: Optional[datetime] = None
        self._boot_events: List[BootEvent] = []
        self._consecutive_crashes = 0
        self._recovery_attempts = 0
        self._gave_up = False
        self._boot_start_time: Optional[datetime] = None
        self._last_reset_reason = ""
        self._last_boot_mode = ""

        # Activity tracking for running state detection
        self._activity_timestamps: Deque[datetime] = deque()


        # Callbacks
        self._on_state_change: Optional[Callable[[ChipState, ChipState], None]] = None
        self._on_crash_detected: Optional[Callable[[str], None]] = None
        self._on_recovery_needed: Optional[Callable[[], None]] = None

    def _log(self, msg: str) -> None:
        if self._logger:
            self._logger.info(f"[ChipRecovery] {msg}")

    def _log_warning(self, msg: str) -> None:
        if self._logger:
            self._logger.warning(f"[ChipRecovery] {msg}")

    def _log_error(self, msg: str) -> None:
        if self._logger:
            self._logger.error(f"[ChipRecovery] {msg}")

    def _set_state(self, new_state: ChipState) -> None:
        """Update state and call callback if changed."""
        if new_state != self._state:
            old_state = self._state
            self._state = new_state
            self._log(f"State: {old_state.value} -> {new_state.value}")
            if self._on_state_change:
                self._on_state_change(old_state, new_state)

    def process_line(self, line: str) -> None:
        """
        Process a line of output from the chip.

        Call this for every line received from serial.
        """
        now = datetime.now()
        self._last_output_time = now

        # Track activity for fallback running state detection
        self._activity_timestamps.append(now)

        # Check for boot indicators
        if any(p.lower() in line.lower() for p in self.BOOT_PATTERNS):
            self._handle_boot_detected(line)

        # Check for crash indicators
        if any(p.lower() in line.lower() for p in self.CRASH_PATTERNS):
            self._handle_crash_detected(line)

        # Check for bootloader mode
        if any(p.lower() in line.lower() for p in self.BOOTLOADER_PATTERNS):
            self._set_state(ChipState.BOOTLOADER)

        # Check for watchdog
        if any(p.lower() in line.lower() for p in self.WATCHDOG_PATTERNS):
            self._handle_watchdog_detected(line)

        # Check for running state
        if any(p.lower() in line.lower() for p in self.RUNNING_PATTERNS):
            self._set_state(ChipState.RUNNING)
            self._consecutive_crashes = 0  # Successful boot resets crash counter
            self._recovery_attempts = 0

        # Extract reset reason if present
        if "rst:0x" in line.lower():
            self._parse_reset_reason(line)

        # Activity-based running state detection (fallback mechanism)
        # Clean old activity timestamps outside the window
        cutoff_time = now - timedelta(seconds=self._activity_window_seconds)
        while self._activity_timestamps and self._activity_timestamps[0] < cutoff_time:
            self._activity_timestamps.popleft()

        # If we have enough activity and no crash, assume running
        if (len(self._activity_timestamps) >= self._activity_threshold and
            self._state not in (ChipState.CRASHED, ChipState.BOOTLOOP)):
            if self._state != ChipState.RUNNING:
                self._log(f"Activity-based running state detected ({len(self._activity_timestamps)} lines in {self._activity_window_seconds}s)")
                self._set_state(ChipState.RUNNING)
                self._consecutive_crashes = 0
                self._recovery_attempts = 0


    def _handle_boot_detected(self, line: str) -> None:
        """Handle boot detection."""
        now = datetime.now()

        # Record boot event
        self._boot_events.append(BootEvent(
            timestamp=now,
            reset_reason=self._last_reset_reason,
            boot_mode=self._last_boot_mode,
        ))

        # Clean old events (keep last 5 minutes)
        cutoff = now - timedelta(minutes=5)
        self._boot_events = [e for e in self._boot_events if e.timestamp > cutoff]

        # Check for boot loop
        recent_boots = sum(
            1 for e in self._boot_events
            if e.timestamp > now - timedelta(minutes=1)
        )

        if recent_boots >= self._boot_loop_threshold:
            self._set_state(ChipState.BOOTLOOP)
            self._log_error(f"Boot loop detected! {recent_boots} boots in last minute")
        else:
            self._set_state(ChipState.BOOTING)
            self._boot_start_time = now

    def _handle_crash_detected(self, line: str) -> None:
        """Handle crash detection."""
        self._consecutive_crashes += 1
        self._set_state(ChipState.CRASHED)
        self._log_error(f"Crash detected: {line[:100]}")

        if self._on_crash_detected:
            self._on_crash_detected(line)

    def _handle_watchdog_detected(self, line: str) -> None:
        """Handle watchdog trigger detection."""
        self._log_warning(f"Watchdog triggered: {line[:100]}")
        self._set_state(ChipState.CRASHED)
        self._consecutive_crashes += 1

    def _parse_reset_reason(self, line: str) -> None:
        """Parse ESP32 reset reason from boot message."""
        import re

        # rst:0x1 (POWERON),boot:0x8 (SPI_FAST_FLASH_BOOT)
        rst_match = re.search(r'rst:0x(\w+)\s*\(([^)]+)\)', line, re.IGNORECASE)
        if rst_match:
            self._last_reset_reason = rst_match.group(2)

        boot_match = re.search(r'boot:0x(\w+)\s*\(([^)]+)\)', line, re.IGNORECASE)
        if boot_match:
            self._last_boot_mode = boot_match.group(2)

    def get_health(self) -> ChipHealth:
        """Get current chip health assessment."""
        now = datetime.now()

        # Count recent boots
        recent_boots = sum(
            1 for e in self._boot_events
            if e.timestamp > now - timedelta(minutes=1)
        )

        # Calculate uptime
        uptime = 0.0
        if self._boot_start_time and self._state == ChipState.RUNNING:
            uptime = (now - self._boot_start_time).total_seconds()

        # Check responsiveness
        is_responsive = True
        if self._last_output_time:
            silence = (now - self._last_output_time).total_seconds()
            is_responsive = silence < self._stuck_timeout

        return ChipHealth(
            state=self._state,
            last_output=self._last_output_time,
            boot_count_last_minute=recent_boots,
            last_reset_reason=self._last_reset_reason,
            consecutive_crashes=self._consecutive_crashes,
            uptime_seconds=uptime,
            is_responsive=is_responsive,
        )

    def needs_recovery(self) -> bool:
        """Check if recovery is needed."""
        health = self.get_health()

        # Too many recovery attempts
        if self._recovery_attempts >= self._max_recovery_attempts:
            if not self._gave_up:
                self._log_error("Max recovery attempts reached, giving up")
                self._gave_up = True
            return False

        # Crashed state
        if health.state == ChipState.CRASHED:
            return True

        # Boot loop
        if health.state == ChipState.BOOTLOOP:
            return True

        # Stuck (no output)
        if self._last_output_time:
            silence = (datetime.now() - self._last_output_time).total_seconds()
            if silence > self._stuck_timeout:
                self._set_state(ChipState.STUCK)
                return True

        return False

    def perform_recovery(self) -> bool:
        """
        Perform recovery action.

        Returns True if recovery was attempted.
        """
        if not self._reset_callback:
            self._log_error("No reset callback configured")
            return False

        self._recovery_attempts += 1
        health = self.get_health()

        self._log_warning(
            f"Performing recovery attempt {self._recovery_attempts} "
            f"(state={health.state.value}, crashes={health.consecutive_crashes})"
        )

        # Wait a bit to let any crash output complete
        time.sleep(self._crash_recovery_delay)

        # Different recovery strategies based on state
        if health.state == ChipState.BOOTLOOP:
            # Boot loop: try entering bootloader then reset
            self._log("Boot loop recovery: entering bootloader mode...")
            try:
                self._reset_callback("bootloader")
                time.sleep(1.0)
            except Exception:
                pass
            self._log("Boot loop recovery: hard reset...")
            result = self._reset_callback("hard_reset")
        elif health.state == ChipState.BOOTLOADER:
            # In bootloader: just hard reset
            self._log("Bootloader recovery: hard reset...")
            result = self._reset_callback("hard_reset")
        else:
            # Default: hard reset
            self._log("Standard recovery: hard reset...")
            result = self._reset_callback("hard_reset")

        self._set_state(ChipState.RECOVERY)
        return True

    def clean_shutdown(self) -> None:
        """
        Perform clean shutdown that leaves chip in good state.

        Call this before disconnecting to ensure chip is running normally.
        """
        self._log("Performing clean shutdown...")

        # If in weird state, reset to normal
        if self._state in (ChipState.BOOTLOADER, ChipState.STUCK, ChipState.CRASHED):
            if self._reset_callback:
                self._log("Resetting chip to normal state before shutdown...")
                self._reset_callback("hard_reset")
                time.sleep(2.0)  # Wait for boot

        self._log("Clean shutdown complete")

    def reset_counters(self) -> None:
        """Reset all counters and state."""
        self._consecutive_crashes = 0
        self._recovery_attempts = 0
        self._gave_up = False
        self._boot_events.clear()
        self._activity_timestamps.clear()
        self._state = ChipState.UNKNOWN

    def set_callbacks(
        self,
        on_state_change: Optional[Callable[[ChipState, ChipState], None]] = None,
        on_crash_detected: Optional[Callable[[str], None]] = None,
        on_recovery_needed: Optional[Callable[[], None]] = None,
    ) -> None:
        """Set callback functions."""
        self._on_state_change = on_state_change
        self._on_crash_detected = on_crash_detected
        self._on_recovery_needed = on_recovery_needed


# Convenience functions

def create_default_recovery(
    reset_callback: Callable,
    logger=None,
) -> ChipRecovery:
    """Create a ChipRecovery with sensible defaults."""
    return ChipRecovery(
        reset_callback=reset_callback,
        logger=logger,
        boot_loop_threshold=5,
        stuck_timeout=60.0,
        crash_recovery_delay=2.0,
        max_recovery_attempts=3,
    )


def detect_chip_state_from_line(line: str) -> Optional[ChipState]:
    """
    Quick detection of chip state from a single line.

    Returns None if state cannot be determined from this line.
    """
    line_lower = line.lower()

    # Check boot
    for p in ChipRecovery.BOOT_PATTERNS:
        if p.lower() in line_lower:
            return ChipState.BOOTING

    # Check crash
    for p in ChipRecovery.CRASH_PATTERNS:
        if p.lower() in line_lower:
            return ChipState.CRASHED

    # Check bootloader
    for p in ChipRecovery.BOOTLOADER_PATTERNS:
        if p.lower() in line_lower:
            return ChipState.BOOTLOADER

    # Check running
    for p in ChipRecovery.RUNNING_PATTERNS:
        if p.lower() in line_lower:
            return ChipState.RUNNING

    return None
