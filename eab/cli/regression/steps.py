"""Step executor — maps YAML step types to eabctl subprocess calls."""

from __future__ import annotations

import json
import subprocess
import time
from typing import Any, Optional

from eab.cli.regression.models import StepResult, StepSpec


def run_step(step: StepSpec, *, device: Optional[str] = None,
             chip: Optional[str] = None, timeout: int = 60) -> StepResult:
    """Execute a single test step and return the result."""
    fn = _STEP_DISPATCH.get(step.step_type)
    if fn is None:
        return StepResult(
            step_type=step.step_type,
            params=step.params,
            passed=False,
            duration_ms=0,
            error=f"Unknown step type: {step.step_type}",
        )
    return fn(step, device=device, chip=chip, timeout=timeout)


def _run_eabctl(args: list[str], *, timeout: int = 60) -> tuple[int, dict[str, Any]]:
    """Run an eabctl command with --json, return (returncode, parsed_output)."""
    cmd = ["eabctl"] + args + ["--json"]
    try:
        result = subprocess.run(
            cmd, capture_output=True, text=True, timeout=timeout,
        )
        try:
            output = json.loads(result.stdout)
        except (json.JSONDecodeError, ValueError):
            output = {"stdout": result.stdout, "stderr": result.stderr}
        return result.returncode, output
    except subprocess.TimeoutExpired:
        return 1, {"error": "timeout", "timeout_seconds": timeout}
    except FileNotFoundError:
        return 1, {"error": "eabctl not found"}


def _run_flash(step: StepSpec, *, device: Optional[str],
               chip: Optional[str], timeout: int) -> StepResult:
    t0 = time.monotonic()
    args = ["flash"]
    p = step.params
    if p.get("firmware"):
        args.append(str(p["firmware"]))
    if p.get("chip") or chip:
        args.extend(["--chip", p.get("chip") or chip])
    if p.get("runner"):
        args.extend(["--runner", p["runner"]])
    if p.get("address"):
        args.extend(["--address", str(p["address"])])
    if device:
        args.extend(["--device", device])
    rc, output = _run_eabctl(args, timeout=timeout)
    ms = int((time.monotonic() - t0) * 1000)
    return StepResult(
        step_type="flash", params=step.params,
        passed=(rc == 0), duration_ms=ms, output=output,
        error=output.get("error") if rc != 0 else None,
    )


def _run_reset(step: StepSpec, *, device: Optional[str],
               chip: Optional[str], timeout: int) -> StepResult:
    t0 = time.monotonic()
    args = ["reset"]
    p = step.params
    if p.get("chip") or chip:
        args.extend(["--chip", p.get("chip") or chip])
    if p.get("method"):
        args.extend(["--method", p["method"]])
    if device:
        args.extend(["--device", device])
    rc, output = _run_eabctl(args, timeout=timeout)
    ms = int((time.monotonic() - t0) * 1000)
    return StepResult(
        step_type="reset", params=step.params,
        passed=(rc == 0), duration_ms=ms, output=output,
        error=output.get("error") if rc != 0 else None,
    )


def _run_send(step: StepSpec, *, device: Optional[str],
              chip: Optional[str], timeout: int) -> StepResult:
    t0 = time.monotonic()
    p = step.params
    args = ["send", p.get("text", "")]
    if p.get("await_ack"):
        args.append("--await-ack")
    step_timeout = p.get("timeout", timeout)
    args.extend(["--timeout", str(step_timeout)])
    rc, output = _run_eabctl(args, timeout=step_timeout + 5)
    ms = int((time.monotonic() - t0) * 1000)
    return StepResult(
        step_type="send", params=step.params,
        passed=(rc == 0), duration_ms=ms, output=output,
        error=output.get("error") if rc != 0 else None,
    )


def _run_wait(step: StepSpec, *, device: Optional[str],
              chip: Optional[str], timeout: int) -> StepResult:
    t0 = time.monotonic()
    p = step.params
    pattern = p.get("pattern", "")
    step_timeout = p.get("timeout", timeout)
    args = ["wait", pattern, "--timeout", str(step_timeout)]
    rc, output = _run_eabctl(args, timeout=step_timeout + 5)
    ms = int((time.monotonic() - t0) * 1000)
    return StepResult(
        step_type="wait", params=step.params,
        passed=(rc == 0), duration_ms=ms, output=output,
        error=output.get("error") if rc != 0 else None,
    )


def _run_wait_event(step: StepSpec, *, device: Optional[str],
                    chip: Optional[str], timeout: int) -> StepResult:
    t0 = time.monotonic()
    p = step.params
    step_timeout = p.get("timeout", timeout)
    args = ["wait-event", "--timeout", str(step_timeout)]
    if p.get("event_type"):
        args.extend(["--event-type", p["event_type"]])
    if p.get("contains"):
        args.extend(["--contains", p["contains"]])
    rc, output = _run_eabctl(args, timeout=step_timeout + 5)
    ms = int((time.monotonic() - t0) * 1000)
    return StepResult(
        step_type="wait_event", params=step.params,
        passed=(rc == 0), duration_ms=ms, output=output,
        error=output.get("error") if rc != 0 else None,
    )


def _run_assert_log(step: StepSpec, *, device: Optional[str],
                    chip: Optional[str], timeout: int) -> StepResult:
    """Alias for wait — readable name for asserting log output."""
    aliased = StepSpec(step_type="wait", params=step.params)
    result = _run_wait(aliased, device=device, chip=chip, timeout=timeout)
    result.step_type = "assert_log"
    return result


def _run_sleep(step: StepSpec, *, device: Optional[str],
               chip: Optional[str], timeout: int) -> StepResult:
    t0 = time.monotonic()
    seconds = step.params.get("seconds", 1)
    time.sleep(seconds)
    ms = int((time.monotonic() - t0) * 1000)
    return StepResult(
        step_type="sleep", params=step.params,
        passed=True, duration_ms=ms,
    )


def _run_read_vars(step: StepSpec, *, device: Optional[str],
                   chip: Optional[str], timeout: int) -> StepResult:
    t0 = time.monotonic()
    p = step.params
    elf = p.get("elf", "")
    var_specs = p.get("vars", [])
    var_names = [v["name"] for v in var_specs]

    args = ["read-vars", "--elf", elf]
    for name in var_names:
        args.extend(["--var", name])
    if device:
        args.extend(["--device", device])
    if p.get("chip") or chip:
        args.extend(["--chip", p.get("chip") or chip])

    rc, output = _run_eabctl(args, timeout=timeout)
    ms = int((time.monotonic() - t0) * 1000)

    if rc != 0:
        return StepResult(
            step_type="read_vars", params=step.params,
            passed=False, duration_ms=ms, output=output,
            error=output.get("error", "read-vars failed"),
        )

    # Validate expectations
    read_values = output.get("variables", output.get("vars", {}))
    errors = []
    for spec in var_specs:
        name = spec["name"]
        val = read_values.get(name)
        if val is None:
            errors.append(f"{name}: not found in output")
            continue
        if isinstance(val, dict):
            val = val.get("value", val)
        if "expect_eq" in spec:
            if val != spec["expect_eq"]:
                errors.append(f"{name}: expected {spec['expect_eq']}, got {val}")
        if "expect_gt" in spec:
            if not (isinstance(val, (int, float)) and val > spec["expect_gt"]):
                errors.append(f"{name}: expected > {spec['expect_gt']}, got {val}")
        if "expect_lt" in spec:
            if not (isinstance(val, (int, float)) and val < spec["expect_lt"]):
                errors.append(f"{name}: expected < {spec['expect_lt']}, got {val}")

    return StepResult(
        step_type="read_vars", params=step.params,
        passed=(len(errors) == 0), duration_ms=ms, output=output,
        error="; ".join(errors) if errors else None,
    )


def _run_fault_check(step: StepSpec, *, device: Optional[str],
                     chip: Optional[str], timeout: int) -> StepResult:
    t0 = time.monotonic()
    p = step.params
    args = ["fault-analyze"]
    if p.get("device") or device:
        args.extend(["--device", p.get("device") or device])
    if p.get("elf"):
        args.extend(["--elf", p["elf"]])
    if p.get("chip") or chip:
        args.extend(["--chip", p.get("chip") or chip])

    rc, output = _run_eabctl(args, timeout=timeout)
    ms = int((time.monotonic() - t0) * 1000)

    expect_clean = p.get("expect_clean", True)
    has_fault = output.get("fault_detected", False) or output.get("faulted", False)
    passed = (not has_fault) if expect_clean else has_fault

    return StepResult(
        step_type="fault_check", params=step.params,
        passed=passed, duration_ms=ms, output=output,
        error="Fault detected" if (expect_clean and has_fault) else None,
    )


_STEP_DISPATCH = {
    "flash": _run_flash,
    "reset": _run_reset,
    "send": _run_send,
    "wait": _run_wait,
    "wait_event": _run_wait_event,
    "assert_log": _run_assert_log,
    "sleep": _run_sleep,
    "read_vars": _run_read_vars,
    "fault_check": _run_fault_check,
}
