"""
Pattern Matcher for Serial Daemon.

Detects configurable patterns in serial output and logs alerts.
"""

from typing import Optional, List, Dict
from datetime import datetime
import re

from .interfaces import FileSystemInterface, ClockInterface, AlertMatch


# Default patterns for embedded systems (ESP32 focused)
DEFAULT_PATTERNS = {
    # General errors
    "ERROR": r"\bE\s*\(\d+\)|error",
    "FAIL": r"fail",
    "DISCONNECT": r"disconnect",
    "TIMEOUT": r"timeout|timed?\s*out",

    # ESP32 crash patterns
    "CRASH": r"crash|guru\s*meditation|Backtrace:",
    "panic": r"panic|abort\(\)|Rebooting\.\.\.",
    "assert": r"assert\s*failed|ESP_ERROR_CHECK",

    # ESP32 memory issues
    "MEMORY": r"heap|out\s*of\s*memory|alloc\s*failed|stack\s*overflow",

    # ESP32 watchdog
    "WATCHDOG": r"wdt|watchdog|Task\s+watchdog",

    # ESP32 boot issues
    "BOOT": r"rst:0x|boot:0x|flash\s*read\s*err",

    # ESP32 Wi-Fi/BLE
    "WIFI": r"wifi:.*fail|WIFI_EVENT_STA_DISCONNECTED",
    "BLE": r"BLE.*error|GAP.*fail|GATT.*fail",
}


class PatternMatcher:
    """
    Matches patterns in serial output lines.

    Features:
    - String and regex patterns
    - Case-insensitive matching by default
    - Multiple pattern detection per line
    - Pattern match counting
    """

    def __init__(
        self,
        clock: Optional[ClockInterface] = None,
        load_defaults: bool = False,
    ):
        self._clock = clock
        self._patterns: Dict[str, re.Pattern] = {}
        self._counts: Dict[str, int] = {}

        if load_defaults:
            for name, pattern in DEFAULT_PATTERNS.items():
                self.add_pattern(name, pattern, is_regex=True)

    def add_pattern(self, name: str, pattern: str, is_regex: bool = False) -> None:
        """
        Add a pattern to watch for.

        Args:
            name: Pattern identifier
            pattern: String or regex pattern
            is_regex: If False, pattern is escaped for literal matching
        """
        if not is_regex:
            pattern = re.escape(pattern)

        self._patterns[name] = re.compile(pattern, re.IGNORECASE)
        self._counts[name] = 0

    def remove_pattern(self, name: str) -> None:
        """Remove a pattern."""
        if name in self._patterns:
            del self._patterns[name]
            del self._counts[name]

    def get_patterns(self) -> List[str]:
        """Get list of pattern names."""
        return list(self._patterns.keys())

    def check_line(self, line: str) -> List[AlertMatch]:
        """
        Check line against all patterns.

        Returns list of AlertMatch for each pattern that matched.
        """
        matches = []
        timestamp = self._clock.now() if self._clock else datetime.now()

        for name, pattern in self._patterns.items():
            if pattern.search(line):
                self._counts[name] += 1
                matches.append(AlertMatch(
                    timestamp=timestamp,
                    pattern=name,
                    line=line,
                ))

        return matches

    def get_counts(self) -> Dict[str, int]:
        """Get count of matches per pattern."""
        return self._counts.copy()

    def reset_counts(self) -> None:
        """Reset all pattern counts to zero."""
        for name in self._counts:
            self._counts[name] = 0


class AlertLogger:
    """
    Logs pattern matches to a separate alerts file.

    Alert format: [HH:MM:SS.mmm] [PATTERN] line
    """

    def __init__(
        self,
        filesystem: FileSystemInterface,
        clock: ClockInterface,
        alerts_path: str,
    ):
        self._fs = filesystem
        self._clock = clock
        self._alerts_path = alerts_path
        self._alert_count = 0

    @property
    def alert_count(self) -> int:
        """Total number of alerts logged."""
        return self._alert_count

    def log_alert(self, match: AlertMatch) -> None:
        """
        Log an alert match to the alerts file.

        Format: [HH:MM:SS.mmm] [PATTERN] line
        """
        timestamp = match.timestamp.strftime("%H:%M:%S.%f")[:-3]
        formatted = f"[{timestamp}] [{match.pattern}] {match.line}\n"

        self._fs.write_file(self._alerts_path, formatted, append=True)
        self._alert_count += 1
