"""Device registry for multi-device EAB sessions.

Manages per-device session directories under /tmp/eab-devices/.
Each device gets a directory with a daemon.info file containing
device metadata (name, type, chip, port, etc.).
"""

from __future__ import annotations

import os
import shutil
from datetime import datetime
from typing import Optional

from eab.singleton import SingletonDaemon, ExistingDaemon


def _get_devices_dir() -> str:
    """Return the devices root directory.

    Uses EAB_RUN_DIR env var if set, otherwise /tmp.
    Implemented as a function (not module-level constant) so tests
    can monkeypatch EAB_RUN_DIR after import.
    """
    return os.path.join(os.environ.get("EAB_RUN_DIR", "/tmp"), "eab-devices")


def _parse_info_file(path: str) -> dict[str, str]:
    """Parse a daemon.info key=value file into a dict.

    Args:
        path: Absolute path to the daemon.info file.

    Returns:
        Dict mapping keys to values. Empty dict on read failure.
    """
    result: dict[str, str] = {}
    try:
        with open(path, "r") as f:
            for line in f:
                key_val = line.strip().split("=", 1)
                if len(key_val) != 2:
                    continue
                result[key_val[0]] = key_val[1]
    except IOError:
        pass
    return result


def _write_info_file(path: str, *, pid: int = 0, port: str = "",
                     base_dir: str = "", device_name: str = "",
                     device_type: str = "debug", chip: str = "") -> None:
    """Write a daemon.info file with the given metadata.

    Args:
        path: Absolute path to write.
        pid: Daemon process ID (0 if no daemon).
        port: Serial port.
        base_dir: Session directory path.
        device_name: Device name.
        device_type: 'serial' or 'debug'.
        chip: Chip identifier.
    """
    with open(path, "w") as f:
        f.write(f"pid={pid}\n")
        f.write(f"port={port}\n")
        f.write(f"base_dir={base_dir}\n")
        f.write(f"started={datetime.now().isoformat()}\n")
        f.write(f"device_name={device_name}\n")
        f.write(f"type={device_type}\n")
        f.write(f"chip={chip}\n")


def _info_to_existing(info: dict[str, str], *, name: str,
                      device_dir: str) -> ExistingDaemon:
    """Build an ExistingDaemon from parsed info dict (no PID file).

    Used for debug-only devices that were registered but never
    started a serial daemon.
    """
    return ExistingDaemon(
        pid=0,
        is_alive=False,
        port=info.get("port", ""),
        base_dir=info.get("base_dir", device_dir),
        started=info.get("started", ""),
        device_name=name,
        device_type=info.get("type", "debug"),
        chip=info.get("chip", ""),
    )


def list_devices() -> list[ExistingDaemon]:
    """Scan the devices directory for all registered devices.

    Returns:
        List of ExistingDaemon objects, one per device directory
        that contains a daemon.info file.
    """
    devices_dir = _get_devices_dir()
    devices: list[ExistingDaemon] = []
    if not os.path.isdir(devices_dir):
        return devices

    for name in sorted(os.listdir(devices_dir)):
        device_dir = os.path.join(devices_dir, name)
        info_file = os.path.join(device_dir, "daemon.info")
        if not os.path.isfile(info_file):
            continue

        singleton = SingletonDaemon(device_name=name)
        existing = singleton.get_existing()
        if existing:
            devices.append(existing)
        else:
            # No PID file — debug-only device, never started a daemon
            info = _parse_info_file(info_file)
            devices.append(_info_to_existing(info, name=name, device_dir=device_dir))

    return devices


def register_device(name: str, device_type: str = "debug", chip: str = "") -> str:
    """Register a device (creates session dir and daemon.info without starting a daemon).

    Args:
        name: Device name (e.g., 'nrf5340').
        device_type: 'serial' or 'debug'.
        chip: Chip identifier (e.g., 'nrf5340', 'stm32l476rg').

    Returns:
        Path to the device session directory.
    """
    devices_dir = _get_devices_dir()
    device_dir = os.path.join(devices_dir, name)
    os.makedirs(device_dir, exist_ok=True)

    info_file = os.path.join(device_dir, "daemon.info")
    _write_info_file(
        info_file,
        pid=0,
        port="",
        base_dir=device_dir,
        device_name=name,
        device_type=device_type,
        chip=chip,
    )
    return device_dir


def unregister_device(name: str) -> bool:
    """Unregister a device (removes session dir).

    Refuses to remove if a daemon is still running for this device.

    Note: There is an inherent TOCTOU race between checking daemon liveness
    and removing the directory. A daemon could theoretically start between
    the check and the rmtree. In practice this is low-risk because device
    registration/unregistration is a manual CLI operation, not automated.

    Args:
        name: Device name.

    Returns:
        True if removed, False if device not found or daemon still running.
    """
    devices_dir = _get_devices_dir()
    device_dir = os.path.join(devices_dir, name)
    if not os.path.isdir(device_dir):
        return False

    from eab.singleton import check_singleton
    existing = check_singleton(device_name=name)
    if existing and existing.is_alive:
        return False

    shutil.rmtree(device_dir, ignore_errors=True)
    return True
