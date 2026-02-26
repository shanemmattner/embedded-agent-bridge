"""eabctl: Agent-friendly CLI for Embedded Agent Bridge (EAB)."""

from eab.cli.backtrace_cmds import cmd_decode_backtrace
from eab.cli.binary_capture_cmds import cmd_rtt_capture_convert, cmd_rtt_capture_info, cmd_rtt_capture_start
from eab.cli.daemon import (
    cmd_device_add,
    cmd_device_remove,
    cmd_devices,
    cmd_diagnose,
    cmd_pause,
    cmd_resume,
    cmd_start,
    cmd_stop,
)
from eab.cli.debug import (
    cmd_debug_monitor_disable,
    cmd_debug_monitor_enable,
    cmd_debug_monitor_status,
    cmd_gdb,
    cmd_gdb_script,
    cmd_inspect,
    cmd_memdump,
    cmd_openocd_cmd,
    cmd_openocd_start,
    cmd_openocd_status,
    cmd_openocd_stop,
    cmd_preflight_ble_safe,
    cmd_threads,
    cmd_watch,
)
from eab.cli.dispatch import main
from eab.cli.fault_cmds import cmd_fault_analyze
from eab.cli.flash import cmd_chip_info, cmd_erase, cmd_flash, cmd_preflight_hw, cmd_reset
from eab.cli.helpers import _print, _resolve_base_dir
from eab.cli.parser import _build_parser, _preprocess_argv
from eab.cli.profile import cmd_dwt_status, cmd_profile_function, cmd_profile_region
from eab.cli.reset_cmds import cmd_resets
from eab.cli.rtt_cmds import cmd_rtt_reset, cmd_rtt_start, cmd_rtt_status, cmd_rtt_stop, cmd_rtt_tail

# Re-export command functions so tests can patch eab.cli.cmd_xxx
from eab.cli.serial import (
    cmd_alerts,
    cmd_capture_between,
    cmd_events,
    cmd_send,
    cmd_status,
    cmd_tail,
    cmd_wait,
    cmd_wait_event,
)
from eab.cli.stream_cmds import cmd_recv, cmd_recv_latest, cmd_stream_start, cmd_stream_stop
from eab.cli.threads import cmd_threads_snapshot, cmd_threads_watch
from eab.cli.trace import cmd_trace_export, cmd_trace_start, cmd_trace_stop
from eab.cli.var_cmds import cmd_read_vars, cmd_vars

# Lazy import: regression depends on PyYAML which may not be installed.
# Imported in dispatch.py only when the regression command is used.

__all__ = [
    "main",
    "_build_parser",
    "_preprocess_argv",
    "_print",
    "_resolve_base_dir",
    "cmd_status",
    "cmd_tail",
    "cmd_alerts",
    "cmd_events",
    "cmd_send",
    "cmd_wait",
    "cmd_wait_event",
    "cmd_capture_between",
    "cmd_start",
    "cmd_stop",
    "cmd_pause",
    "cmd_resume",
    "cmd_diagnose",
    "cmd_devices",
    "cmd_device_add",
    "cmd_device_remove",
    "cmd_flash",
    "cmd_erase",
    "cmd_reset",
    "cmd_chip_info",
    "cmd_preflight_hw",
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
    "cmd_fault_analyze",
    "cmd_profile_function",
    "cmd_profile_region",
    "cmd_dwt_status",
    "cmd_stream_start",
    "cmd_stream_stop",
    "cmd_recv",
    "cmd_recv_latest",
    "cmd_vars",
    "cmd_read_vars",
    "cmd_resets",
    "cmd_decode_backtrace",
    "cmd_rtt_start",
    "cmd_rtt_stop",
    "cmd_rtt_status",
    "cmd_rtt_reset",
    "cmd_rtt_tail",
    "cmd_rtt_capture_start",
    "cmd_rtt_capture_convert",
    "cmd_rtt_capture_info",
    "cmd_trace_start",
    "cmd_trace_stop",
    "cmd_trace_export",
    "cmd_threads_snapshot",
    "cmd_threads_watch",
]
