"""Formatting helpers for C2000 register display."""

from __future__ import annotations


def format_register_info(reg) -> str:
    """Format register info for human display.

    Args:
        reg: Register object with name, address, size, description, bit_fields.

    Returns:
        Multi-line string with register details.
    """
    lines = [f"{reg.name} @ 0x{reg.address:X} ({reg.size}B)"]
    lines.append(f"  {reg.description}")
    if reg.bit_fields:
        lines.append("  Fields:")
        for f in reg.bit_fields:
            lines.append(f"    {f.name:20s} mask=0x{f.mask:X}  {f.description}")
    return "\n".join(lines)


def format_group_info(grp) -> str:
    """Format register group info for human display.

    Args:
        grp: RegisterGroup object with name and registers dict.

    Returns:
        Multi-line string with group and register list.
    """
    lines = [f"Group: {grp.name}"]
    for r in grp.registers.values():
        lines.append(f"  {r.name:25s} 0x{r.address:05X}  ({r.size}B)  {r.description}")
    return "\n".join(lines)
