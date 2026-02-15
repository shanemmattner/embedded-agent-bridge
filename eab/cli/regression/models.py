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
class TestSpec:
    """A complete test parsed from YAML."""
    name: str
    file: str
    device: Optional[str] = None
    chip: Optional[str] = None
    timeout: int = 60
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
