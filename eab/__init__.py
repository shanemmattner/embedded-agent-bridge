"""
Embedded Agent Bridge - Serial Daemon

A reliable serial daemon with file-based agent interface.
"""

from .interfaces import (
    ConnectionState,
    PortInfo,
    SerialConfig,
    SerialPortInterface,
    FileSystemInterface,
    ClockInterface,
    LoggerInterface,
    PatternMatcherInterface,
    StatsCollectorInterface,
    AlertMatch,
    SessionStats,
)

__all__ = [
    "ConnectionState",
    "PortInfo",
    "SerialConfig",
    "SerialPortInterface",
    "FileSystemInterface",
    "ClockInterface",
    "LoggerInterface",
    "PatternMatcherInterface",
    "StatsCollectorInterface",
    "AlertMatch",
    "SessionStats",
]
