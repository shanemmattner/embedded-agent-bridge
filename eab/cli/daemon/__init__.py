"""Daemon management commands package."""

from eab.cli.daemon.lifecycle_cmds import cmd_start, cmd_stop, cmd_pause, cmd_resume
from eab.cli.daemon.health_cmds import cmd_diagnose
from eab.cli.daemon.device_mgmt_cmds import cmd_devices, cmd_device_add, cmd_device_remove

__all__ = [
    "cmd_start",
    "cmd_stop",
    "cmd_pause",
    "cmd_resume",
    "cmd_diagnose",
    "cmd_devices",
    "cmd_device_add",
    "cmd_device_remove",
]
