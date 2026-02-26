"""Step executor — maps YAML step types to eabctl subprocess calls."""

from __future__ import annotations

import json
import os
import struct
import subprocess
import time
from typing import Any, Optional

from eab.cli.regression.models import StepResult, StepSpec
from eab.cli.usb_reset import reset_usb_device
from eab.thread_inspector import inspect_threads


def _graceful_kill(proc: subprocess.Popen, timeout: int = 5, usb_delay: float = 2.0):
    """Stop a process gracefully (SIGTERM first), with USB recovery delay."""
    proc.terminate()
    try:
        proc.wait(timeout=timeout)
    except subprocess.TimeoutExpired:
        proc.kill()
        proc.wait()
    time.sleep(usb_delay)


_USB_ERRORS = ["timed out", "dev_usb_comm_err", "usb_comm", "no stlink detected"]


def _is_usb_error(stderr: str) -> bool:
    """Check if an error message indicates USB communication failure."""
    lower = stderr.lower()
    return any(err in lower for err in _USB_ERRORS)


def _try_usb_reset_recovery(probe_selector: Optional[str]) -> bool:
    """Attempt USB device reset to recover from corrupted state.

    Uses pyusb to send a USB bus reset, which can recover ST-Link V3
    (and other probes) from libusb timeout corruption without physical re-plug.

    Returns True if reset succeeded and device re-enumerated.
    """
    if not probe_selector:
        return False
    try:
        parts = probe_selector.split(":")
        if len(parts) != 2:
            return False
        vid = int(parts[0], 16)
        pid = int(parts[1], 16)
    except (ValueError, IndexError):
        return False

    result = reset_usb_device(vid, pid, wait_seconds=5.0)
    return result.get("success", False)


def _elf_load_address(binary_path: str) -> Optional[str]:
    """Extract load address from ELF program headers. Returns hex string or None."""
    elf_path = binary_path.replace('.bin', '.elf')
    if not os.path.exists(elf_path):
        return None
    try:
        result = subprocess.run(
            ['arm-none-eabi-readelf', '-l', elf_path],
            capture_output=True, text=True, timeout=10
        )
        for line in result.stdout.splitlines():
            if line.strip().startswith('LOAD'):
                parts = line.split()
                if len(parts) >= 4:
                    return parts[3]  # PhysAddr column
    except Exception:
        pass
    return None


def run_step(step: StepSpec, *, device: Optional[str] = None,
             chip: Optional[str] = None, timeout: int = 60,
             log_offset: Optional[int] = None) -> StepResult:
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
    return fn(step, device=device, chip=chip, timeout=timeout,
              log_offset=log_offset)


def _run_eabctl(args: list[str], *, device: Optional[str] = None,
                timeout: int = 60) -> tuple[int, dict[str, Any]]:
    """Run an eabctl command with --json, return (returncode, parsed_output)."""
    prefix = ["eabctl"]
    if device:
        prefix.extend(["--device", device])
    cmd = prefix + args + ["--json"]
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
               chip: Optional[str], timeout: int, **_kw: Any) -> StepResult:
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
    flash_result = StepResult(
        step_type="flash", params=step.params,
        passed=(rc == 0), duration_ms=ms, output=output,
        error=output.get("error") if rc != 0 else None,
    )

    # If debug_mode == 'monitor', enable debug monitor after successful flash
    debug_mode = p.get("debug_mode")
    if flash_result.passed and debug_mode == "monitor" and device:
        priority = int(p.get("monitor_priority", 3))
        dm_args = ["debug-monitor", "enable", "--device", device, "--priority", str(priority)]
        _run_eabctl(dm_args, timeout=30)

    return flash_result


def _run_debug_monitor(step: StepSpec, *, device: Optional[str],
                       chip: Optional[str], timeout: int, **_kw: Any) -> StepResult:
    """Enable or disable ARM debug monitor mode as a regression step."""
    t0 = time.monotonic()
    p = step.params
    action = p.get("action", "enable")
    step_device = p.get("device") or device
    priority = int(p.get("priority", 3))

    if not step_device:
        ms = int((time.monotonic() - t0) * 1000)
        return StepResult(
            step_type="debug_monitor", params=step.params,
            passed=False, duration_ms=ms,
            error="debug_monitor step requires 'device' param or global --device",
        )

    if action == "enable":
        args = ["debug-monitor", "enable", "--device", step_device, "--priority", str(priority)]
    elif action == "disable":
        args = ["debug-monitor", "disable", "--device", step_device]
    else:
        args = ["debug-monitor", "status", "--device", step_device]

    rc, output = _run_eabctl(args, timeout=timeout)
    ms = int((time.monotonic() - t0) * 1000)
    return StepResult(
        step_type="debug_monitor", params=step.params,
        passed=(rc == 0), duration_ms=ms, output=output,
        error=output.get("error") if rc != 0 else None,
    )


def _run_reset(step: StepSpec, *, device: Optional[str],
               chip: Optional[str], timeout: int, **_kw: Any) -> StepResult:
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
              chip: Optional[str], timeout: int, **_kw: Any) -> StepResult:
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
              chip: Optional[str], timeout: int,
              log_offset: Optional[int] = None, **_kw: Any) -> StepResult:
    t0 = time.monotonic()
    p = step.params
    pattern = p.get("pattern", "")
    step_timeout = p.get("timeout", timeout)
    args = ["wait", pattern, "--timeout", str(step_timeout)]
    if log_offset is not None:
        args.extend(["--scan-from", str(log_offset)])
    rc, output = _run_eabctl(args, device=device, timeout=step_timeout + 5)
    ms = int((time.monotonic() - t0) * 1000)
    passed = rc == 0 and output.get("matched", True)
    error = None
    if not passed:
        error = output.get("error") or f"Pattern '{pattern}' not matched within {step_timeout}s"
    return StepResult(
        step_type="wait", params=step.params,
        passed=passed, duration_ms=ms, output=output,
        error=error,
    )


def _run_wait_event(step: StepSpec, *, device: Optional[str],
                    chip: Optional[str], timeout: int, **_kw: Any) -> StepResult:
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
                    chip: Optional[str], timeout: int,
                    log_offset: Optional[int] = None, **_kw: Any) -> StepResult:
    """Alias for wait — readable name for asserting log output."""
    aliased = StepSpec(step_type="wait", params=step.params)
    result = _run_wait(aliased, device=device, chip=chip, timeout=timeout,
                       log_offset=log_offset)
    result.step_type = "assert_log"
    return result


def _run_bench_capture(step: StepSpec, *, device: Optional[str],
                       chip: Optional[str], timeout: int,
                       log_offset: Optional[int] = None, **_kw: Any) -> StepResult:
    t0 = time.monotonic()
    p = step.params
    pattern = p.get('pattern', '')
    step_timeout = p.get('timeout', timeout)
    expect = p.get('expect', {})

    # Use eabctl wait to find the line (scan from test-start offset)
    args = ['wait', pattern, '--timeout', str(step_timeout)]
    if log_offset is not None:
        args.extend(['--scan-from', str(log_offset)])
    rc, output = _run_eabctl(args, device=device, timeout=step_timeout + 5)
    ms = int((time.monotonic() - t0) * 1000)
    
    if rc != 0:
        return StepResult(
            step_type='bench_capture', params=step.params,
            passed=False, duration_ms=ms, output=output,
            error=output.get('error') or f"Pattern '{pattern}' not matched within {step_timeout}s",
        )
    
    # Parse key=value pairs from matched line
    line_data = output.get('line') or output.get('matched_line') or output.get('stdout', '')
    if isinstance(line_data, dict):
        matched = line_data.get('raw') or line_data.get('content', '')
    else:
        matched = str(line_data)
    bench = {}
    for token in matched.split():
        if '=' in token:
            k, v = token.split('=', 1)
            # Try numeric conversion
            try:
                bench[k] = int(v)
            except ValueError:
                try:
                    bench[k] = float(v)
                except ValueError:
                    bench[k] = v
    
    # Validate expectations
    errors = []
    for assertion, expected_val in expect.items():
        # Parse assertion: field_op (e.g. cycles_gt, time_us_lt)
        parts = assertion.rsplit('_', 1)
        if len(parts) != 2:
            errors.append(f'Invalid assertion: {assertion}')
            continue
        field_name, op = parts
        actual = bench.get(field_name)
        if actual is None:
            errors.append(f'{field_name}: not found in bench data')
            continue
        if op == 'gt' and not (actual > expected_val):
            errors.append(f'{field_name}: expected > {expected_val}, got {actual}')
        elif op == 'lt' and not (actual < expected_val):
            errors.append(f'{field_name}: expected < {expected_val}, got {actual}')
        elif op == 'eq' and actual != expected_val:
            errors.append(f'{field_name}: expected {expected_val}, got {actual}')
    
    output['bench'] = bench
    return StepResult(
        step_type='bench_capture', params=step.params,
        passed=(rc == 0 and len(errors) == 0), duration_ms=ms, output=output,
        error='; '.join(errors) if errors else None,
    )


def _run_bench_done(step: StepSpec, *, device: Optional[str],
                    chip: Optional[str], timeout: int,
                    log_offset: Optional[int] = None, **_kw: Any) -> StepResult:
    aliased = StepSpec(step_type='wait', params=step.params)
    result = _run_wait(aliased, device=device, chip=chip, timeout=timeout,
                       log_offset=log_offset)
    result.step_type = 'bench_done'
    return result


def _run_sleep(step: StepSpec, *, device: Optional[str],
               chip: Optional[str], timeout: int, **_kw: Any) -> StepResult:
    t0 = time.monotonic()
    seconds = step.params.get("seconds", 1)
    time.sleep(seconds)
    ms = int((time.monotonic() - t0) * 1000)
    return StepResult(
        step_type="sleep", params=step.params,
        passed=True, duration_ms=ms,
    )


def _run_read_vars(step: StepSpec, *, device: Optional[str],
                   chip: Optional[str], timeout: int, **_kw: Any) -> StepResult:
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
                     chip: Optional[str], timeout: int, **_kw: Any) -> StepResult:
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


def _run_sram_boot(step: StepSpec, *, device: Optional[str],
                   chip: Optional[str], timeout: int, **_kw: Any) -> StepResult:
    """Run SRAM boot: load firmware to SRAM via CubeProgrammer, start with GDB."""
    t0 = time.monotonic()
    p = step.params

    # Get parameters with defaults
    binary_path = p.get("binary")
    if not binary_path:
        return StepResult(
            step_type="sram_boot", params=step.params,
            passed=False, duration_ms=int((time.monotonic() - t0) * 1000),
            error="binary parameter is required",
        )

    load_address = p.get("load_address", "0x34000000")
    probe_chip = p.get("probe_chip", "STM32N657")
    probe_selector = p.get("probe_selector")
    gdb_path = p.get("gdb_path", "arm-none-eabi-gdb")
    cubeprogrammer = p.get("cubeprogrammer", "STM32_Programmer_CLI")

    if load_address == '0x34000000':  # default — try ELF auto-detect
        detected = _elf_load_address(binary_path)
        if detected:
            load_address = detected

    # Build CubeProgrammer halt command
    halt_cmd = [cubeprogrammer, "-c", "port=SWD", "mode=HOTPLUG", "-hardRst", "-halt"]

    # Build CubeProgrammer load command
    load_cmd = [cubeprogrammer, "-c", "port=SWD", "mode=HOTPLUG", "-w", binary_path, load_address]

    # Add probe_selector if provided
    if probe_selector:
        halt_cmd.insert(3, f"serial={probe_selector}")
        load_cmd.insert(3, f"serial={probe_selector}")

    # Step a: CubeProgrammer halt (with USB reset recovery on failure)
    result = subprocess.run(halt_cmd, capture_output=True, text=True, timeout=timeout)
    if result.returncode != 0 and _is_usb_error(result.stderr):
        if _try_usb_reset_recovery(probe_selector):
            result = subprocess.run(halt_cmd, capture_output=True, text=True, timeout=timeout)
    if result.returncode != 0:
        return StepResult(
            step_type="sram_boot", params=step.params,
            passed=False, duration_ms=int((time.monotonic() - t0) * 1000),
            error=f"CubeProgrammer halt failed: {result.stderr}",
        )

    # Step b: CubeProgrammer load (with USB reset recovery on failure)
    result = subprocess.run(load_cmd, capture_output=True, text=True, timeout=timeout)
    if result.returncode != 0 and _is_usb_error(result.stderr):
        if _try_usb_reset_recovery(probe_selector):
            result = subprocess.run(load_cmd, capture_output=True, text=True, timeout=timeout)
    if result.returncode != 0:
        return StepResult(
            step_type="sram_boot", params=step.params,
            passed=False, duration_ms=int((time.monotonic() - t0) * 1000),
            error=f"CubeProgrammer load failed: {result.stderr}",
        )

    # Step c: Sleep 1 second
    time.sleep(1)

    # Step d: Extract vector table from binary
    try:
        with open(binary_path, "rb") as f:
            vector_bytes = f.read(8)
        if len(vector_bytes) < 8:
            return StepResult(
                step_type="sram_boot", params=step.params,
                passed=False, duration_ms=int((time.monotonic() - t0) * 1000),
                error="Binary file too small to contain vector table",
            )
        sp_value, reset_handler = struct.unpack("<II", vector_bytes)
    except Exception as e:
        return StepResult(
            step_type="sram_boot", params=step.params,
            passed=False, duration_ms=int((time.monotonic() - t0) * 1000),
            error=f"Failed to parse vector table: {e}",
        )

    # Step e: Start probe-rs GDB server in background
    gdb_server_cmd = ["probe-rs", "gdb", "--chip", probe_chip]
    if probe_selector:
        gdb_server_cmd.extend(["--probe", probe_selector])

    try:
        gdb_server = subprocess.Popen(
            gdb_server_cmd,
            stdout=subprocess.DEVNULL,
            stderr=subprocess.PIPE,
        )
    except Exception as e:
        return StepResult(
            step_type="sram_boot", params=step.params,
            passed=False, duration_ms=int((time.monotonic() - t0) * 1000),
            error=f"Failed to start probe-rs GDB server: {e}",
        )

    # Step f: Sleep 0.5 second
    time.sleep(0.5)

    # Step g: Connect GDB, set registers, issue continue & disconnect
    gdb_cmds = [
        'target remote localhost:1337',
        'monitor halt',
        f'set $sp = 0x{sp_value:08X}',
        f'set $msp = 0x{sp_value:08X}',
        f'set $pc = 0x{reset_handler:08X}',
        'continue &',
        'shell sleep 2',
        'disconnect',
    ]
    gdb_cmd = [gdb_path, '--batch']
    for cmd in gdb_cmds:
        gdb_cmd.extend(['-ex', cmd])

    try:
        result = subprocess.run(gdb_cmd, capture_output=True, text=True, timeout=30)
        if result.returncode != 0:
            _graceful_kill(gdb_server)
            return StepResult(
                step_type="sram_boot", params=step.params,
                passed=False, duration_ms=int((time.monotonic() - t0) * 1000),
                error=f"GDB register setup failed: {result.stderr}",
            )
    except Exception as e:
        _graceful_kill(gdb_server)
        return StepResult(
            step_type="sram_boot", params=step.params,
            passed=False, duration_ms=int((time.monotonic() - t0) * 1000),
            error=f"GDB execution failed: {e}",
        )

    # Step h: Kill the probe-rs GDB server gracefully
    _graceful_kill(gdb_server)

    ms = int((time.monotonic() - t0) * 1000)
    return StepResult(
        step_type="sram_boot", params=step.params,
        passed=True, duration_ms=ms,
        output={
            "binary": binary_path,
            "load_address": load_address,
            "sp": f"0x{sp_value:08X}",
            "reset_handler": f"0x{reset_handler:08X}",
        },
    )


def _run_anomaly_watch(
    step: "StepSpec", *,
    device: Optional[str],
    chip: Optional[str],
    timeout: int,
    **_kw: Any,
) -> "StepResult":
    """
    Run `eabctl anomaly compare` for the given baseline/duration, check for anomalies.
    """
    t0 = time.monotonic()
    p = step.params

    baseline = p.get("baseline")
    if not baseline:
        return StepResult(
            step_type="anomaly_watch", params=step.params,
            passed=False, duration_ms=int((time.monotonic() - t0) * 1000),
            error="anomaly_watch step requires 'baseline' param",
        )

    duration = float(p.get("duration", 30))
    max_sigma = float(p.get("max_sigma", 3.0))
    fail_on_anomaly = bool(p.get("fail_on_anomaly", True))
    min_anomaly_count = int(p.get("min_anomaly_count", 1))
    log_source = p.get("log_source")

    args = [
        "anomaly", "compare",
        "--baseline", baseline,
        "--duration", str(duration),
        "--sigma", str(max_sigma),
    ]
    if log_source:
        args.extend(["--log-source", log_source])

    # Use duration + 15s buffer for subprocess timeout
    rc, output = _run_eabctl(args, device=device, timeout=int(duration) + 15)
    ms = int((time.monotonic() - t0) * 1000)

    anomaly_count = output.get("anomaly_count", 0)
    if fail_on_anomaly and anomaly_count >= min_anomaly_count:
        anomalous_metrics = [
            name for name, m in output.get("metrics", {}).items()
            if m.get("anomalous")
        ]
        error = f"{anomaly_count} anomalous metric(s): {anomalous_metrics}"
        return StepResult(
            step_type="anomaly_watch", params=step.params,
            passed=False, duration_ms=ms, output=output, error=error,
        )

    return StepResult(
        step_type="anomaly_watch", params=step.params,
        passed=True, duration_ms=ms, output=output,
    )


def _run_stack_headroom_assert(
    step: StepSpec, *,
    device: Optional[str],
    chip: Optional[str],
    timeout: int,
    **_kw: Any,
) -> StepResult:
    t0 = time.monotonic()
    p = step.params
    min_free_bytes = int(p.get("min_free_bytes", 0))
    step_device = p.get("device") or device
    elf = p.get("elf", "")

    try:
        threads = inspect_threads(step_device, elf)
    except RuntimeError as exc:
        ms = int((time.monotonic() - t0) * 1000)
        return StepResult(
            step_type="stack_headroom_assert", params=step.params,
            passed=False, duration_ms=ms,
            error=str(exc),
        )

    offenders = [t for t in threads if t.stack_free < min_free_bytes]
    ms = int((time.monotonic() - t0) * 1000)

    if offenders:
        parts = [
            f"thread '{t.name}' has stack_free={t.stack_free} < min_free_bytes={min_free_bytes}"
            for t in offenders
        ]
        return StepResult(
            step_type="stack_headroom_assert", params=step.params,
            passed=False, duration_ms=ms,
            error="; ".join(parts),
        )

    return StepResult(
        step_type="stack_headroom_assert", params=step.params,
        passed=True, duration_ms=ms,
    )


from eab.cli.regression.trace_steps import (
    _run_trace_start, _run_trace_stop, _run_trace_export, _run_trace_validate,
)

_STEP_DISPATCH = {
    "flash": _run_flash,
    "debug_monitor": _run_debug_monitor,
    "reset": _run_reset,
    "send": _run_send,
    "wait": _run_wait,
    "wait_event": _run_wait_event,
    "assert_log": _run_assert_log,
    "bench_capture": _run_bench_capture,
    "bench_done": _run_bench_done,
    "sleep": _run_sleep,
    "read_vars": _run_read_vars,
    "fault_check": _run_fault_check,
    "sram_boot": _run_sram_boot,
    "trace_start": _run_trace_start,
    "trace_stop": _run_trace_stop,
    "trace_export": _run_trace_export,
    "trace_validate": _run_trace_validate,
    "anomaly_watch": _run_anomaly_watch,
    "stack_headroom_assert": _run_stack_headroom_assert,
}

# Register BLE step executors — late import to avoid circular dependency
from eab.cli.regression.ble_steps import BLE_STEP_DISPATCH  # noqa: E402
_STEP_DISPATCH.update(BLE_STEP_DISPATCH)
