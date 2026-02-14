"""Device registry management commands."""

from __future__ import annotations

from eab.singleton import check_singleton
from eab.device_registry import list_devices, register_device, unregister_device
from eab.cli.helpers import _now_iso, _print


def cmd_devices(*, json_mode: bool) -> int:
    """List all registered devices and their status.

    Args:
        json_mode: Emit machine-parseable JSON output.

    Returns:
        Exit code: always 0.
    """
    devices = list_devices()

    if json_mode:
        payload = {
            "schema_version": 1,
            "timestamp": _now_iso(),
            "devices": [
                {
                    "name": d.device_name,
                    "type": d.device_type,
                    "chip": d.chip,
                    "status": "running" if d.is_alive else "stopped",
                    "pid": d.pid,
                    "port": d.port,
                    "base_dir": d.base_dir,
                    "started": d.started,
                }
                for d in devices
            ],
        }
        _print(payload, json_mode=True)
    else:
        if not devices:
            print("No devices registered. Use: eabctl device add <name> --type debug --chip <chip>")
        else:
            for d in devices:
                status = "running" if d.is_alive else "stopped"
                chip_str = f" ({d.chip})" if d.chip else ""
                port_str = f" port={d.port}" if d.port else ""
                pid_str = f" pid={d.pid}" if d.pid else ""
                print(f"  {d.device_name:<16} {d.device_type:<8} {status:<10}{chip_str}{port_str}{pid_str}")

    return 0


def cmd_device_add(*, name: str, device_type: str, chip: str, json_mode: bool) -> int:
    """Register a new device.

    Args:
        name: Device name (e.g., 'nrf5340').
        device_type: 'serial' or 'debug'.
        chip: Chip identifier.
        json_mode: Emit machine-parseable JSON output.

    Returns:
        Exit code: 0 on success.
    """
    device_dir = register_device(name, device_type=device_type, chip=chip)
    payload = {
        "schema_version": 1,
        "timestamp": _now_iso(),
        "registered": True,
        "name": name,
        "type": device_type,
        "chip": chip,
        "base_dir": device_dir,
    }
    _print(payload, json_mode=json_mode)
    return 0


def cmd_device_remove(*, name: str, json_mode: bool) -> int:
    """Unregister a device.

    Args:
        name: Device name to remove.
        json_mode: Emit machine-parseable JSON output.

    Returns:
        Exit code: 0 on success, 1 if device not found or daemon running.
    """
    ok = unregister_device(name)
    if ok:
        payload = {
            "schema_version": 1,
            "timestamp": _now_iso(),
            "removed": True,
            "name": name,
        }
        _print(payload, json_mode=json_mode)
        return 0
    else:
        # Check if daemon is running
        existing = check_singleton(device_name=name)
        if existing and existing.is_alive:
            msg = f"Cannot remove '{name}': daemon still running (PID {existing.pid}). Stop it first."
        else:
            msg = f"Device '{name}' not found"
        payload = {
            "schema_version": 1,
            "timestamp": _now_iso(),
            "removed": False,
            "name": name,
            "message": msg,
        }
        _print(payload, json_mode=json_mode)
        return 1
