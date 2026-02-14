"""probe-rs CLI commands for eabctl."""

from __future__ import annotations

import json
import logging
from typing import Optional

from eab.probe_rs import ProbeRsBackend
from eab.cli.helpers import _print, _now_iso

logger = logging.getLogger(__name__)


def cmd_probe_rs_list(
    *,
    base_dir: str,
    json_mode: bool,
) -> int:
    """List all connected debug probes.
    
    Args:
        base_dir: Base directory for probe-rs state files.
        json_mode: Emit machine-parseable JSON output.
        
    Returns:
        Exit code: 0 on success, 1 on failure.
    """
    backend = ProbeRsBackend(base_dir)
    
    if not backend.is_available():
        _print({
            "error": "probe-rs not found. Install with: cargo install probe-rs --features cli",
            "success": False,
        }, json_mode=json_mode)
        return 1
    
    try:
        probes = backend.list_probes()
        
        payload = {
            "schema_version": 1,
            "timestamp": _now_iso(),
            "success": True,
            "count": len(probes),
            "probes": [
                {
                    "identifier": p.identifier,
                    "type": p.probe_type,
                    "vid": p.vendor_id,
                    "pid": p.product_id,
                    "serial": p.serial_number,
                }
                for p in probes
            ],
        }
        
        _print(payload, json_mode=json_mode)
        return 0
        
    except Exception as e:
        _print({
            "error": str(e),
            "success": False,
        }, json_mode=json_mode)
        return 1


def cmd_probe_rs_info(
    *,
    base_dir: str,
    chip: str,
    json_mode: bool,
) -> int:
    """Get information about a chip.
    
    Args:
        base_dir: Base directory for probe-rs state files.
        chip: Target chip identifier (e.g., "nrf52840", "stm32f407vg").
        json_mode: Emit machine-parseable JSON output.
        
    Returns:
        Exit code: 0 on success, 1 on failure.
    """
    backend = ProbeRsBackend(base_dir)
    
    if not backend.is_available():
        _print({
            "error": "probe-rs not found. Install with: cargo install probe-rs --features cli",
            "success": False,
        }, json_mode=json_mode)
        return 1
    
    try:
        info = backend.chip_info(chip)
        
        if "error" in info:
            _print({
                "schema_version": 1,
                "timestamp": _now_iso(),
                "success": False,
                "chip": chip,
                "error": info["error"],
            }, json_mode=json_mode)
            return 1
        
        payload = {
            "schema_version": 1,
            "timestamp": _now_iso(),
            "success": True,
            "chip": chip,
            "info": info["info"],
        }
        
        _print(payload, json_mode=json_mode)
        return 0
        
    except Exception as e:
        _print({
            "error": str(e),
            "success": False,
        }, json_mode=json_mode)
        return 1


def cmd_probe_rs_rtt(
    *,
    base_dir: str,
    chip: str,
    channel: int,
    probe: Optional[str],
    stop: bool,
    json_mode: bool,
) -> int:
    """Start or stop RTT streaming with probe-rs.
    
    Args:
        base_dir: Base directory for probe-rs state files.
        chip: Target chip identifier.
        channel: RTT up channel number (default: 0).
        probe: Probe selector string (e.g., "VID:PID:Serial").
        stop: Stop RTT streaming instead of starting.
        json_mode: Emit machine-parseable JSON output.
        
    Returns:
        Exit code: 0 on success, 1 on failure.
    """
    backend = ProbeRsBackend(base_dir)
    
    if not backend.is_available():
        _print({
            "error": "probe-rs not found. Install with: cargo install probe-rs --features cli",
            "success": False,
        }, json_mode=json_mode)
        return 1
    
    try:
        if stop:
            status = backend.stop_rtt()
            payload = {
                "schema_version": 1,
                "timestamp": _now_iso(),
                "success": True,
                "action": "stop",
                "running": status.running,
            }
        else:
            status = backend.start_rtt(
                chip=chip,
                channel=channel,
                probe_selector=probe,
            )
            payload = {
                "schema_version": 1,
                "timestamp": _now_iso(),
                "success": status.running,
                "action": "start",
                "running": status.running,
                "pid": status.pid,
                "chip": status.chip,
                "channel": status.channel,
                "log_path": status.log_path,
                "last_error": status.last_error,
            }
        
        _print(payload, json_mode=json_mode)
        return 0 if (stop or status.running) else 1
        
    except Exception as e:
        _print({
            "error": str(e),
            "success": False,
        }, json_mode=json_mode)
        return 1


def cmd_probe_rs_flash(
    *,
    base_dir: str,
    firmware: str,
    chip: str,
    verify: bool,
    reset_halt: bool,
    probe: Optional[str],
    json_mode: bool,
) -> int:
    """Flash firmware using probe-rs.
    
    Args:
        base_dir: Base directory for probe-rs state files.
        firmware: Path to firmware file (.bin, .elf, .hex).
        chip: Target chip identifier.
        verify: Verify flash after write.
        reset_halt: Reset and halt target after flash.
        probe: Probe selector string.
        json_mode: Emit machine-parseable JSON output.
        
    Returns:
        Exit code: 0 on success, 1 on failure.
    """
    import time
    
    backend = ProbeRsBackend(base_dir)
    
    if not backend.is_available():
        _print({
            "error": "probe-rs not found. Install with: cargo install probe-rs --features cli",
            "success": False,
        }, json_mode=json_mode)
        return 1
    
    started = time.time()
    
    try:
        result = backend.flash(
            firmware_path=firmware,
            chip=chip,
            verify=verify,
            reset_halt=reset_halt,
            probe_selector=probe,
        )
        
        duration_ms = int((time.time() - started) * 1000)
        
        payload = {
            "schema_version": 1,
            "timestamp": _now_iso(),
            "success": result.returncode == 0,
            "firmware": firmware,
            "chip": chip,
            "verify": verify,
            "reset_halt": reset_halt,
            "stdout": result.stdout,
            "stderr": result.stderr,
            "duration_ms": duration_ms,
        }
        
        _print(payload, json_mode=json_mode)
        return 0 if result.returncode == 0 else 1
        
    except Exception as e:
        duration_ms = int((time.time() - started) * 1000)
        _print({
            "error": str(e),
            "success": False,
            "duration_ms": duration_ms,
        }, json_mode=json_mode)
        return 1


def cmd_probe_rs_reset(
    *,
    base_dir: str,
    chip: str,
    halt: bool,
    probe: Optional[str],
    json_mode: bool,
) -> int:
    """Reset target device using probe-rs.
    
    Args:
        base_dir: Base directory for probe-rs state files.
        chip: Target chip identifier.
        halt: Halt target after reset.
        probe: Probe selector string.
        json_mode: Emit machine-parseable JSON output.
        
    Returns:
        Exit code: 0 on success, 1 on failure.
    """
    import time
    
    backend = ProbeRsBackend(base_dir)
    
    if not backend.is_available():
        _print({
            "error": "probe-rs not found. Install with: cargo install probe-rs --features cli",
            "success": False,
        }, json_mode=json_mode)
        return 1
    
    started = time.time()
    
    try:
        result = backend.reset(
            chip=chip,
            halt=halt,
            probe_selector=probe,
        )
        
        duration_ms = int((time.time() - started) * 1000)
        
        payload = {
            "schema_version": 1,
            "timestamp": _now_iso(),
            "success": result.returncode == 0,
            "chip": chip,
            "halt": halt,
            "stdout": result.stdout,
            "stderr": result.stderr,
            "duration_ms": duration_ms,
        }
        
        _print(payload, json_mode=json_mode)
        return 0 if result.returncode == 0 else 1
        
    except Exception as e:
        duration_ms = int((time.time() - started) * 1000)
        _print({
            "error": str(e),
            "success": False,
            "duration_ms": duration_ms,
        }, json_mode=json_mode)
        return 1
