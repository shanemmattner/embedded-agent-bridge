"""Suite orchestration — discover, parse, run tests, emit results."""

from __future__ import annotations

import fnmatch
import os
import time
from dataclasses import asdict
from pathlib import Path
from typing import Optional

import yaml

from eab.cli.daemon.lifecycle_cmds import cmd_pause, cmd_resume
from eab.cli.helpers import _print
from eab.cli.regression.models import (
    StepSpec, TestSpec, TestResult, StepResult, SuiteResult, DeviceSpec,
)
from eab.cli.regression.steps import run_step


def discover_tests(suite_dir: str, filter_pattern: Optional[str] = None) -> list[str]:
    """Glob *.yaml in suite_dir, optionally filtered by name pattern."""
    p = Path(suite_dir)
    if not p.is_dir():
        return []
    paths = sorted(p.glob("*.yaml")) + sorted(p.glob("*.yml"))
    seen: set[str] = set()
    unique: list[str] = []
    for fp in paths:
        if str(fp) not in seen:
            seen.add(str(fp))
            unique.append(str(fp))
    if filter_pattern:
        unique = [f for f in unique if fnmatch.fnmatch(os.path.basename(f), filter_pattern)]
    return unique


def _parse_steps(raw: list[dict]) -> list[StepSpec]:
    """Parse a list of YAML step dicts into StepSpec objects."""
    steps = []
    for entry in raw:
        if not isinstance(entry, dict):
            continue
        for step_type, params in entry.items():
            if params is None:
                params = {}
            steps.append(StepSpec(step_type=step_type, params=params))
    return steps


def _parse_devices(raw: dict) -> dict[str, DeviceSpec]:
    """Parse the 'devices:' block into DeviceSpec objects."""
    result = {}
    for slot_name, spec in raw.items():
        if not isinstance(spec, dict):
            raise ValueError(f"devices.{slot_name} must be a mapping")
        result[slot_name] = DeviceSpec(
            device=spec["device"],
            chip=spec.get("chip"),
            probe=spec.get("probe"),
        )
    return result


def parse_test(yaml_path: str) -> TestSpec:
    """Parse a YAML test file into a TestSpec."""
    with open(yaml_path, "r", encoding="utf-8") as f:
        data = yaml.safe_load(f)

    if not isinstance(data, dict):
        raise ValueError(f"Invalid test file (expected mapping): {yaml_path}")

    devices: dict[str, DeviceSpec] = {}
    if "devices" in data and isinstance(data["devices"], dict):
        devices = _parse_devices(data["devices"])

    return TestSpec(
        name=data.get("name", os.path.basename(yaml_path)),
        file=yaml_path,
        device=data.get("device"),
        chip=data.get("chip"),
        timeout=data.get("timeout", 60),
        devices=devices,
        setup=_parse_steps(data.get("setup", [])),
        steps=_parse_steps(data.get("steps", [])),
        teardown=_parse_steps(data.get("teardown", [])),
    )


def _get_log_offset(device: Optional[str]) -> Optional[int]:
    """Get current byte offset of device log file for scan-from tracking.

    Falls back to rtt-raw.log (device dir, then default dir) for RTT-only
    targets like nRF5340 that don't have a serial daemon latest.log.
    """
    if not device:
        return None
    base = os.path.join("/tmp/eab-devices", device)
    candidates = [
        os.path.join(base, "latest.log"),
        os.path.join(base, "rtt-raw.log"),
        "/tmp/eab-devices/default/rtt-raw.log",
    ]
    for log_path in candidates:
        try:
            size = os.path.getsize(log_path)
            return size
        except OSError:
            continue
    return None


def _run_step_with_usb_guard(
    step: StepSpec,
    *,
    device: Optional[str],
    chip: Optional[str],
    timeout: int,
    log_offset: Optional[int],
    base_dir: str,
) -> StepResult:
    """Run a step, pausing/resuming the daemon when exclusive_usb is set."""
    exclusive_usb = step.params.get("exclusive_usb")
    if exclusive_usb:
        cmd_pause(base_dir=base_dir, seconds=timeout + 30, json_mode=True)
        time.sleep(1)
    try:
        return run_step(step, device=device, chip=chip,
                        timeout=timeout, log_offset=log_offset)
    finally:
        if exclusive_usb:
            cmd_resume(base_dir=base_dir, json_mode=True)
            time.sleep(2)


def _resolve_step_device(
    step: StepSpec,
    spec: TestSpec,
) -> tuple[Optional[str], Optional[str]]:
    """Return (device_name, chip) for a step, respecting the devices: map.

    Priority:
      1. step.params['device'] resolved through spec.devices map
      2. spec.device / spec.chip (legacy single-device)
    """
    slot = step.params.get("device")
    if slot and slot in spec.devices:
        ds = spec.devices[slot]
        return ds.device, ds.chip
    if slot and not spec.devices:
        # device param is a literal EAB device name (no devices: block)
        return slot, spec.chip
    return spec.device, spec.chip


def run_test(spec: TestSpec, global_timeout: Optional[int] = None) -> TestResult:
    """Execute a single test: setup → steps → teardown."""
    timeout = global_timeout or spec.timeout
    all_steps: list[StepResult] = []
    t0 = time.monotonic()
    error: Optional[str] = None
    passed = True

    base_dir = os.path.join("/tmp/eab-devices", spec.device) if spec.device else "/tmp/eab-devices/_unknown"

    # Record log offset before test starts — wait steps scan from here
    log_offset = _get_log_offset(spec.device)

    # Setup — fail fast
    for step in spec.setup:
        step_device, step_chip = _resolve_step_device(step, spec)
        result = _run_step_with_usb_guard(
            step, device=step_device, chip=step_chip,
            timeout=timeout, log_offset=log_offset, base_dir=base_dir)
        all_steps.append(result)
        if not result.passed:
            passed = False
            error = f"Setup failed at {step.step_type}: {result.error}"
            break

    # Steps — stop on first failure (only if setup passed)
    if passed:
        for step in spec.steps:
            step_device, step_chip = _resolve_step_device(step, spec)
            result = _run_step_with_usb_guard(
                step, device=step_device, chip=step_chip,
                timeout=timeout, log_offset=log_offset, base_dir=base_dir)
            all_steps.append(result)
            if not result.passed:
                passed = False
                error = f"Step failed: {step.step_type}: {result.error}"
                break

    # Teardown — always runs, errors logged but don't cause failure
    for step in spec.teardown:
        step_device, step_chip = _resolve_step_device(step, spec)
        result = _run_step_with_usb_guard(
            step, device=step_device, chip=step_chip,
            timeout=timeout, log_offset=log_offset, base_dir=base_dir)
        all_steps.append(result)

    ms = int((time.monotonic() - t0) * 1000)
    return TestResult(
        name=spec.name, file=spec.file,
        passed=passed, duration_ms=ms,
        steps=all_steps, error=error,
    )


def run_suite(suite_dir: Optional[str] = None, test_file: Optional[str] = None,
              filter_pattern: Optional[str] = None,
              timeout: Optional[int] = None) -> SuiteResult:
    """Run a full test suite or a single test file."""
    t0 = time.monotonic()
    results: list[TestResult] = []

    if test_file:
        files = [test_file]
    elif suite_dir:
        files = discover_tests(suite_dir, filter_pattern)
    else:
        return SuiteResult()

    for f in files:
        try:
            spec = parse_test(f)
        except Exception as e:
            results.append(TestResult(
                name=os.path.basename(f), file=f,
                passed=False, duration_ms=0,
                error=f"Parse error: {e}",
            ))
            continue
        result = run_test(spec, global_timeout=timeout)
        results.append(result)

    ms = int((time.monotonic() - t0) * 1000)
    passed = sum(1 for r in results if r.passed)
    failed = sum(1 for r in results if not r.passed)
    return SuiteResult(
        passed=passed, failed=failed, skipped=0,
        duration_ms=ms, results=results,
    )


def cmd_regression(suite: Optional[str] = None, test: Optional[str] = None,
                   filter_pattern: Optional[str] = None,
                   timeout: Optional[int] = None,
                   json_mode: bool = False) -> int:
    """Entry point for ``eabctl regression``."""
    if not suite and not test:
        _print({"error": "Specify --suite <dir> or --test <file>"}, json_mode=json_mode)
        return 2

    result = run_suite(suite_dir=suite, test_file=test,
                       filter_pattern=filter_pattern, timeout=timeout)
    _print(asdict(result), json_mode=json_mode)
    return 0 if result.failed == 0 else 1
