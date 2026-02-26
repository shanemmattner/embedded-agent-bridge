"""cmd_dwt_explain — capture DWT data for symbols and produce an AI narrative."""

from __future__ import annotations

import json
from typing import Optional

from eab.dwt_explain import run_dwt_explain


def cmd_dwt_explain(
    *,
    device: Optional[str],
    symbols: str,
    elf: str,
    duration: int = 5,
    json_mode: bool = False,
) -> int:
    """Capture DWT watchpoint data for symbols and produce an AI narrative.

    Args:
        device:    Device identifier (e.g., NRF5340_XXAA_APP). Optional.
        symbols:   Comma-separated list of symbol names.
        elf:       Path to the ELF file.
        duration:  Capture duration in seconds.
        json_mode: If True, print full result as JSON; otherwise print ai_prompt.

    Returns:
        0 on success.
    """
    symbols_list = [s.strip() for s in symbols.split(",")]
    result = run_dwt_explain(
        device=device,
        symbols=symbols_list,
        elf=elf,
        duration=duration,
    )
    if json_mode:
        print(json.dumps(result, indent=2))
    else:
        print(result["ai_prompt"])
    return 0
