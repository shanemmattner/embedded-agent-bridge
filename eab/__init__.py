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

from .device_control import DeviceController, strip_ansi
from .port_lock import PortLock, find_port_users, list_all_locks
from .chip_recovery import ChipRecovery, ChipState, ChipHealth

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
    "DeviceController",
    "strip_ansi",
    "PortLock",
    "find_port_users",
    "list_all_locks",
    "ChipRecovery",
    "ChipState",
    "ChipHealth",
]
