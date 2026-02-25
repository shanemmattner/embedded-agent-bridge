"""C2000-specific CLI commands for eabctl."""

from .reg_cmds import cmd_erad_status, cmd_reg_read
from .stream_cmds import cmd_dlog_capture, cmd_stream_vars
from .telemetry_cmd import cmd_c2000_telemetry_decode
from .trace_cmds import cmd_c2000_trace_export

__all__ = [
    "cmd_reg_read",
    "cmd_erad_status",
    "cmd_stream_vars",
    "cmd_dlog_capture",
    "cmd_c2000_trace_export",
    "cmd_c2000_telemetry_decode",
]
