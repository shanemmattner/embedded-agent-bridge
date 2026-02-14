"""Flash command subpackage — split from flash_cmds.py for maintainability."""

from eab.cli.flash.flash_cmd import cmd_flash
from eab.cli.flash.erase_cmd import cmd_erase
from eab.cli.flash.reset_cmd import cmd_reset
from eab.cli.flash.preflight_cmd import cmd_preflight_hw
from eab.cli.flash.chip_info_cmd import cmd_chip_info

__all__ = [
    "cmd_flash",
    "cmd_erase",
    "cmd_reset",
    "cmd_preflight_hw",
    "cmd_chip_info",
]
