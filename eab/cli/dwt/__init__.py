"""DWT CLI commands — non-halting watchpoints via DWT comparators."""

from .clear_cmd import cmd_dwt_clear
from .explain_cmd import cmd_dwt_explain
from .halt_cmd import cmd_dwt_halt
from .list_cmd import cmd_dwt_list
from .watch_cmd import cmd_dwt_watch

__all__ = ["cmd_dwt_watch", "cmd_dwt_halt", "cmd_dwt_list", "cmd_dwt_clear", "cmd_dwt_explain"]
