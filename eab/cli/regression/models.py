"""Data models for the regression test runner."""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any, Optional


@dataclass
class StepSpec:
    """A single test step parsed from YAML."""
    step_type: str
    params: dict[str, Any] = field(default_factory=dict)


@dataclass
class DeviceSpec:
    """A named device entry in a multi-device YAML config."""
    device: str                    # EAB device name (directory under /tmp/eab-devices/)
    chip: Optional[str] = None     # chip string for flash/reset/fault-analyze
    probe: Optional[str] = None    # probe selector (J-Link serial or VID:PID)


@dataclass
class TestSpec:
    """A complete test parsed from YAML."""
    name: str
    file: str
    device: Optional[str] = None   # legacy single-device
    chip: Optional[str] = None     # legacy single-device
    timeout: int = 60
    devices: dict[str, DeviceSpec] = field(default_factory=dict)  # multi-device map
    setup: list[StepSpec] = field(default_factory=list)
    steps: list[StepSpec] = field(default_factory=list)
    teardown: list[StepSpec] = field(default_factory=list)


@dataclass
class StepResult:
    """Result of executing a single step."""
    step_type: str
    params: dict[str, Any]
    passed: bool
    duration_ms: int
    output: dict[str, Any] = field(default_factory=dict)
    error: Optional[str] = None


@dataclass
class TestResult:
    """Result of executing a single test file."""
    name: str
    file: str
    passed: bool
    duration_ms: int
    steps: list[StepResult] = field(default_factory=list)
    error: Optional[str] = None


@dataclass
class SuiteResult:
    """Aggregate result of all tests in a suite."""
    passed: int = 0
    failed: int = 0
    skipped: int = 0
    duration_ms: int = 0
    results: list[TestResult] = field(default_factory=list)
