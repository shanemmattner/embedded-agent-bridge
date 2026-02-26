"""Debug commands package - OpenOCD, GDB, inspection tools, and debug monitor."""

from eab.cli.debug.openocd_cmds import (
    cmd_openocd_status,
    cmd_openocd_start,
    cmd_openocd_stop,
    cmd_openocd_cmd,
)
from eab.cli.debug.gdb_cmds import cmd_gdb, cmd_gdb_script
from eab.cli.debug.inspection_cmds import cmd_inspect, cmd_threads, cmd_watch, cmd_memdump
from eab.cli.debug.debug_monitor_cmds import (
    cmd_debug_monitor_enable,
    cmd_debug_monitor_disable,
    cmd_debug_monitor_status,
    cmd_preflight_ble_safe,
)

__all__ = [
    "cmd_openocd_status",
    "cmd_openocd_start",
    "cmd_openocd_stop",
    "cmd_openocd_cmd",
    "cmd_gdb",
    "cmd_gdb_script",
    "cmd_inspect",
    "cmd_threads",
    "cmd_watch",
    "cmd_memdump",
    "cmd_debug_monitor_enable",
    "cmd_debug_monitor_disable",
    "cmd_debug_monitor_status",
    "cmd_preflight_ble_safe",
]
