"""C2000 register read and ERAD status commands."""

from __future__ import annotations

from typing import Optional

from eab.cli.helpers import _print
from .formatters import format_group_info, format_register_info


def _find_register(reg_map, name: str):
    """Find a register by name across all groups.

    Args:
        reg_map: RegisterMap instance.
        name: Register name to search for.

    Returns:
        Register object if found, None otherwise.
    """
    for grp in reg_map.groups.values():
        if name in grp.registers:
            return grp.registers[name]
    return None


def cmd_reg_read(
    *,
    chip: str,
    register: Optional[str] = None,
    group: Optional[str] = None,
    ccxml: Optional[str] = None,
    json_mode: bool = False,
) -> int:
    """Read and decode a register or register group.

    Args:
        chip: Chip name (e.g., "f28003x").
        register: Optional register name to look up.
        group: Optional register group name to list.
        ccxml: Unused (kept for API compatibility).
        json_mode: If True, output JSON instead of human-readable text.

    Returns:
        Exit code (0 = success, 2 = error).
    """
    from eab.register_maps import load_register_map

    try:
        reg_map = load_register_map(chip)
    except FileNotFoundError as e:
        _print({"error": str(e)}, json_mode=json_mode)
        return 2

    if register:
        reg = _find_register(reg_map, register)
        if reg is None:
            _print({"error": f"Register '{register}' not found in {chip}"}, json_mode=json_mode)
            return 2

        result = {
            "register": reg.name,
            "address": f"0x{reg.address:X}",
            "size": reg.size,
            "description": reg.description,
            "fields": {f.name: {"mask": f"0x{f.mask:X}", "description": f.description}
                       for f in reg.bit_fields},
        }
        _print(result if json_mode else format_register_info(reg), json_mode=json_mode)
        return 0

    if group:
        grp = reg_map.get_group(group)
        if grp is None:
            _print({"error": f"Group '{group}' not found in {chip}"}, json_mode=json_mode)
            return 2

        result = {
            "group": grp.name,
            "registers": [
                {
                    "name": r.name,
                    "address": f"0x{r.address:X}",
                    "size": r.size,
                    "description": r.description,
                }
                for r in grp.registers.values()
            ],
        }
        _print(result if json_mode else format_group_info(grp), json_mode=json_mode)
        return 0

    # List all available groups and registers
    all_regs = reg_map.all_registers()
    result = {
        "chip": chip,
        "groups": list(reg_map.groups.keys()),
        "register_count": len(all_regs),
    }
    _print(
        result if json_mode
        else f"Chip: {chip}\nGroups: {', '.join(result['groups'])}\nRegisters: {result['register_count']}",
        json_mode=json_mode,
    )
    return 0


def cmd_erad_status(
    *,
    chip: str = "f28003x",
    json_mode: bool = False,
) -> int:
    """Show ERAD register definitions and configuration info.

    Args:
        chip: Chip name (default "f28003x").
        json_mode: If True, output JSON instead of human-readable text.

    Returns:
        Exit code (0 = success, 2 = error).
    """
    from eab.register_maps import load_register_map

    try:
        reg_map = load_register_map(chip)
    except FileNotFoundError as e:
        _print({"error": str(e)}, json_mode=json_mode)
        return 2

    erad_group = reg_map.get_group("erad")
    if erad_group is None:
        _print({"error": f"No ERAD registers defined for {chip}"}, json_mode=json_mode)
        return 2

    result = {
        "chip": chip,
        "erad_registers": [
            {
                "name": r.name,
                "address": f"0x{r.address:X}",
                "size": r.size,
                "description": r.description,
            }
            for r in erad_group.registers.values()
        ],
    }
    if json_mode:
        _print(result, json_mode=True)
    else:
        lines = [f"ERAD Registers ({chip}):"]
        for r in erad_group.registers.values():
            lines.append(f"  {r.name:25s} 0x{r.address:05X}  ({r.size}B)  {r.description}")
        _print("\n".join(lines), json_mode=False)
    return 0
