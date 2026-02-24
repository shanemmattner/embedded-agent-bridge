"""Trace step executors for the regression test runner.

New step types: trace_start, trace_stop, trace_export, trace_validate.
"""

from __future__ import annotations

import json
import re
import time
from typing import Any, Optional

from eab.cli.regression.models import StepResult, StepSpec
from eab.cli.regression.steps import _run_eabctl


def _run_trace_start(step: StepSpec, *, device: Optional[str] = None,
                     chip: Optional[str] = None, timeout: int = 60, **_kw: Any) -> StepResult:
    t0 = time.monotonic()
    p = step.params
    args = ["trace", "start", "--source", p.get("source", "rtt")]
    if p.get("output"):
        args.extend(["--output", str(p["output"])])
    if p.get("device") or device:
        args.extend(["--device", p.get("device") or device])
    if p.get("duration"):
        args.extend(["--duration", str(p["duration"])])
    rc, output = _run_eabctl(args, timeout=timeout)
    ms = int((time.monotonic() - t0) * 1000)
    return StepResult(
        step_type="trace_start", params=step.params,
        passed=(rc == 0), duration_ms=ms, output=output,
        error=output.get("error") if rc != 0 else None,
    )


def _run_trace_stop(step: StepSpec, *, device: Optional[str] = None,
                    chip: Optional[str] = None, timeout: int = 60, **_kw: Any) -> StepResult:
    t0 = time.monotonic()
    args = ["trace", "stop"]
    rc, output = _run_eabctl(args, timeout=timeout)
    ms = int((time.monotonic() - t0) * 1000)
    return StepResult(
        step_type="trace_stop", params=step.params,
        passed=(rc == 0), duration_ms=ms, output=output,
        error=output.get("error") if rc != 0 else None,
    )


def _run_trace_export(step: StepSpec, *, device: Optional[str] = None,
                      chip: Optional[str] = None, timeout: int = 60, **_kw: Any) -> StepResult:
    t0 = time.monotonic()
    p = step.params
    args = ["trace", "export"]
    if p.get("input"):
        args.extend(["--input", str(p["input"])])
    if p.get("output"):
        args.extend(["--output", str(p["output"])])
    args.extend(["--format", p.get("format", "auto")])
    rc, output = _run_eabctl(args, timeout=timeout)
    ms = int((time.monotonic() - t0) * 1000)
    return StepResult(
        step_type="trace_export", params=step.params,
        passed=(rc == 0), duration_ms=ms, output=output,
        error=output.get("error") if rc != 0 else None,
    )


def _run_trace_validate(step: StepSpec, *, device: Optional[str] = None,
                        chip: Optional[str] = None, timeout: int = 60, **_kw: Any) -> StepResult:
    """Validate exported Perfetto JSON against expectations.

    No subprocess call — reads the JSON file and checks structure/content.
    """
    t0 = time.monotonic()
    p = step.params
    input_path = p.get("input", "")
    errors: list[str] = []

    # Load the trace file
    try:
        with open(input_path) as f:
            data = json.load(f)
    except FileNotFoundError:
        ms = int((time.monotonic() - t0) * 1000)
        return StepResult(
            step_type="trace_validate", params=step.params,
            passed=False, duration_ms=ms,
            error=f"Trace file not found: {input_path}",
        )
    except json.JSONDecodeError as exc:
        ms = int((time.monotonic() - t0) * 1000)
        return StepResult(
            step_type="trace_validate", params=step.params,
            passed=False, duration_ms=ms,
            error=f"Invalid JSON: {exc}",
        )

    # Schema validation (perfetto top-level structure)
    if p.get("schema") == "perfetto":
        if not isinstance(data, dict):
            errors.append("Expected top-level JSON object")
        elif "traceEvents" not in data:
            errors.append("Missing 'traceEvents' key (Perfetto schema)")
        if isinstance(data, dict) and "displayTimeUnit" not in data:
            errors.append("Missing 'displayTimeUnit' key (Perfetto schema)")

    events = data.get("traceEvents", []) if isinstance(data, dict) else []
    # Separate metadata events (ph=="M") from data events
    data_events = [ev for ev in events if ev.get("ph") != "M"]

    # Event count bounds (data events only)
    if "min_events" in p and len(data_events) < p["min_events"]:
        errors.append(
            f"Too few events: got {len(data_events)}, expected >= {p['min_events']}"
        )
    if "max_events" in p and len(data_events) > p["max_events"]:
        errors.append(
            f"Too many events: got {len(data_events)}, expected <= {p['max_events']}"
        )

    # Required fields in every data event (metadata events excluded)
    required_fields = p.get("required_fields", [])
    for i, ev in enumerate(data_events):
        missing = [f for f in required_fields if f not in ev]
        if missing:
            errors.append(
                f"Data event {i}: missing fields {missing}"
            )
            break  # report first offender only

    # Event name patterns — at least one data event must match each pattern
    for pattern in p.get("event_names", []):
        if not any(re.search(pattern, ev.get("name", "")) for ev in data_events):
            errors.append(f"No event matching pattern '{pattern}'")

    # Timing validation (data events with timestamps only)
    timing = p.get("timing", {})
    timed_events = [ev for ev in data_events if "ts" in ev]
    if timing and timed_events:
        timestamps = sorted(ev["ts"] for ev in timed_events)
        if "min_duration_us" in timing:
            span = timestamps[-1] - timestamps[0]
            if span < timing["min_duration_us"]:
                errors.append(
                    f"Trace duration {span}us < min {timing['min_duration_us']}us"
                )
        if "max_gap_us" in timing:
            for a, b in zip(timestamps, timestamps[1:]):
                gap = b - a
                if gap > timing["max_gap_us"]:
                    errors.append(
                        f"Gap {gap}us between events exceeds max {timing['max_gap_us']}us"
                    )
                    break

    ms = int((time.monotonic() - t0) * 1000)
    return StepResult(
        step_type="trace_validate", params=step.params,
        passed=(len(errors) == 0), duration_ms=ms,
        output={
            "total_events": len(events),
            "data_events": len(data_events),
            "metadata_events": len(events) - len(data_events),
            "errors": errors,
        },
        error="; ".join(errors) if errors else None,
    )
