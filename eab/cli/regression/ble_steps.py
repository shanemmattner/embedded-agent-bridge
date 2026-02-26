"""BLE HIL step executors — maps YAML BLE step types to RTT shell operations."""

from __future__ import annotations

import time
from typing import Any, Optional

from eab.cli.regression.models import StepResult, StepSpec
from eab.cli.regression.steps import _run_send, _run_wait


def _ble_send_wait(
    *,
    device: Optional[str],
    chip: Optional[str],
    send_text: str,
    wait_pattern: str,
    timeout: int,
    step_type: str,
    step_params: dict,
    extra_output: Optional[dict] = None,
) -> StepResult:
    """Send an RTT shell command, then wait for the response pattern."""
    t0 = time.monotonic()

    send_spec = StepSpec(step_type="send", params={"text": send_text, "timeout": timeout})
    send_result = _run_send(send_spec, device=device, chip=chip, timeout=timeout)
    if not send_result.passed:
        ms = int((time.monotonic() - t0) * 1000)
        return StepResult(
            step_type=step_type, params=step_params,
            passed=False, duration_ms=ms,
            error=f"send('{send_text}') failed: {send_result.error}",
        )

    wait_spec = StepSpec(step_type="wait", params={"pattern": wait_pattern, "timeout": timeout})
    wait_result = _run_wait(wait_spec, device=device, chip=chip, timeout=timeout)
    ms = int((time.monotonic() - t0) * 1000)

    output = wait_result.output or {}
    if extra_output:
        output.update(extra_output)

    return StepResult(
        step_type=step_type, params=step_params,
        passed=wait_result.passed, duration_ms=ms, output=output,
        error=wait_result.error if not wait_result.passed else None,
    )


def _run_ble_scan(
    step: StepSpec, *, device: Optional[str], chip: Optional[str],
    timeout: int, **_kw: Any
) -> StepResult:
    """Send 'ble scan <name>' and wait for 'SCAN_RESULT:'."""
    p = step.params
    target_name = p.get("target_name", "")
    step_timeout = p.get("timeout", timeout)

    result = _ble_send_wait(
        device=device, chip=chip,
        send_text=f"ble scan {target_name}",
        wait_pattern="SCAN_RESULT: ",
        timeout=step_timeout,
        step_type="ble_scan",
        step_params=step.params,
    )
    # Parse address from matched line for downstream steps
    line = (result.output or {}).get("line", "")
    if line:
        parts = line.strip().split()
        if len(parts) >= 3:
            result.output["address"] = parts[2]
    return result


def _run_ble_connect(
    step: StepSpec, *, device: Optional[str], chip: Optional[str],
    timeout: int, **_kw: Any
) -> StepResult:
    """Send 'ble connect [<addr>]' and wait for 'CONNECTED:'."""
    p = step.params
    addr = p.get("addr", p.get("address", ""))
    step_timeout = p.get("timeout", timeout)
    cmd = f"ble connect {addr}".strip() if addr else "ble connect"

    return _ble_send_wait(
        device=device, chip=chip,
        send_text=cmd,
        wait_pattern="CONNECTED: ",
        timeout=step_timeout,
        step_type="ble_connect",
        step_params=step.params,
    )


def _run_ble_disconnect(
    step: StepSpec, *, device: Optional[str], chip: Optional[str],
    timeout: int, **_kw: Any
) -> StepResult:
    p = step.params
    step_timeout = p.get("timeout", timeout)
    return _ble_send_wait(
        device=device, chip=chip,
        send_text="ble disconnect",
        wait_pattern="DISCONNECTED",
        timeout=step_timeout,
        step_type="ble_disconnect",
        step_params=step.params,
    )


def _run_ble_subscribe(
    step: StepSpec, *, device: Optional[str], chip: Optional[str],
    timeout: int, **_kw: Any
) -> StepResult:
    p = step.params
    char_uuid = p.get("char_uuid", p.get("uuid", ""))
    step_timeout = p.get("timeout", timeout)
    return _ble_send_wait(
        device=device, chip=chip,
        send_text=f"ble subscribe {char_uuid}",
        wait_pattern="SUBSCRIBED: ",
        timeout=step_timeout,
        step_type="ble_subscribe",
        step_params=step.params,
    )


def _run_ble_assert_notify(
    step: StepSpec, *, device: Optional[str], chip: Optional[str],
    timeout: int, **_kw: Any
) -> StepResult:
    p = step.params
    char_uuid = p.get("char_uuid", p.get("uuid", ""))
    count = int(p.get("count", 1))
    step_timeout = p.get("timeout", timeout)
    expect_value = p.get("expect_value")

    result = _ble_send_wait(
        device=device, chip=chip,
        send_text=f"ble expect_notify {char_uuid} {count}",
        wait_pattern=f"NOTIFY_DONE: {char_uuid}",
        timeout=step_timeout,
        step_type="ble_assert_notify",
        step_params=step.params,
    )
    if not result.passed:
        return result

    # Parse values: "NOTIFY_DONE: EAB20002 5 0102 0304 ..."
    line = (result.output or {}).get("line", "")
    parts = line.strip().split()
    values = parts[3:] if len(parts) > 3 else []
    result.output["notify_values"] = values

    if expect_value is not None:
        last = values[-1].upper() if values else ""
        if last != expect_value.upper():
            result.passed = False
            result.error = (
                f"ble_assert_notify({char_uuid}): "
                f"expected last value '{expect_value}', got '{last}'"
            )
    return result


def _run_ble_write(
    step: StepSpec, *, device: Optional[str], chip: Optional[str],
    timeout: int, **_kw: Any
) -> StepResult:
    p = step.params
    char_uuid = p.get("char_uuid", p.get("uuid", ""))
    value = str(p.get("value", "")).replace(" ", "").upper()
    without_response = p.get("without_response", True)
    rsp_flag = "norsp" if without_response else "rsp"
    step_timeout = p.get("timeout", timeout)
    return _ble_send_wait(
        device=device, chip=chip,
        send_text=f"ble write {char_uuid} {value} {rsp_flag}",
        wait_pattern="WRITE_OK",
        timeout=step_timeout,
        step_type="ble_write",
        step_params=step.params,
    )


def _run_ble_read(
    step: StepSpec, *, device: Optional[str], chip: Optional[str],
    timeout: int, **_kw: Any
) -> StepResult:
    p = step.params
    char_uuid = p.get("char_uuid", p.get("uuid", ""))
    step_timeout = p.get("timeout", timeout)
    result = _ble_send_wait(
        device=device, chip=chip,
        send_text=f"ble read {char_uuid}",
        wait_pattern=f"READ_RESULT: {char_uuid}",
        timeout=step_timeout,
        step_type="ble_read",
        step_params=step.params,
    )
    if result.passed:
        line = (result.output or {}).get("line", "")
        parts = line.strip().split()
        result.output["value"] = parts[2].upper() if len(parts) >= 3 else ""
    return result


# BLE step dispatch table — imported and merged into _STEP_DISPATCH in steps.py
BLE_STEP_DISPATCH = {
    "ble_scan":          _run_ble_scan,
    "ble_connect":       _run_ble_connect,
    "ble_disconnect":    _run_ble_disconnect,
    "ble_subscribe":     _run_ble_subscribe,
    "ble_assert_notify": _run_ble_assert_notify,
    "ble_write":         _run_ble_write,
    "ble_read":          _run_ble_read,
}
