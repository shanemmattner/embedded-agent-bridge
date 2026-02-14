"""eabctl: Agent-friendly CLI for Embedded Agent Bridge (EAB)."""

from eab.cli.dispatch import main
from eab.cli.parser import _build_parser, _preprocess_argv
from eab.cli.helpers import _print, _resolve_base_dir

# Re-export command functions so tests can patch eab.cli.cmd_xxx
from eab.cli.serial_cmds import (
    cmd_status, cmd_tail, cmd_alerts, cmd_events, cmd_send,
    cmd_wait, cmd_wait_event, cmd_capture_between,
)
from eab.cli.daemon import (
    cmd_start, cmd_stop, cmd_pause, cmd_resume, cmd_diagnose,
    cmd_devices, cmd_device_add, cmd_device_remove,
)
from eab.cli.flash import cmd_flash, cmd_erase, cmd_reset, cmd_chip_info, cmd_preflight_hw
from eab.cli.debug import (
    cmd_openocd_status, cmd_openocd_start, cmd_openocd_stop, cmd_openocd_cmd,
    cmd_gdb, cmd_gdb_script, cmd_inspect, cmd_threads, cmd_watch, cmd_memdump,
)
from eab.cli.fault_cmds import cmd_fault_analyze
from eab.cli.profile_cmds import cmd_profile_function, cmd_profile_region, cmd_dwt_status
from eab.cli.stream_cmds import cmd_stream_start, cmd_stream_stop, cmd_recv, cmd_recv_latest
from eab.cli.var_cmds import cmd_vars, cmd_read_vars
from eab.cli.reset_cmds import cmd_resets
from eab.cli.backtrace_cmds import cmd_decode_backtrace
from eab.cli.rtt_cmds import cmd_rtt_start, cmd_rtt_stop, cmd_rtt_status, cmd_rtt_reset, cmd_rtt_tail
from eab.cli.binary_capture_cmds import cmd_rtt_capture_start, cmd_rtt_capture_convert, cmd_rtt_capture_info

__all__ = ["main"]
