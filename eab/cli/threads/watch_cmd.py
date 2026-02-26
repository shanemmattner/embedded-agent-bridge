"""cmd_threads_watch — poll Zephyr thread inspection at a fixed interval."""

from __future__ import annotations

import json
import time

from eab.cli.helpers import _now_iso, _print
from eab.cli.threads.snapshot_cmd import _print_thread_table


def cmd_threads_watch(
    *,
    device: str,
    elf: str,
    interval: float = 5.0,
    json_mode: bool = False,
) -> int:
    """Repeatedly inspect Zephyr RTOS threads and stream results.

    Args:
        device: J-Link device string (e.g., ``"NRF5340_XXAA_APP"``).
        elf: Path to the ELF file with DWARF debug symbols.
        interval: Seconds between polls (default 5).
        json_mode: If True, emit one JSON object per line (JSONL) with a
            ``timestamp`` field.  Otherwise, clear the terminal and reprint
            the table each cycle.

    Returns:
        0 on clean exit (KeyboardInterrupt), 1 on error.
    """
    from eab.thread_inspector import inspect_threads

    try:
        while True:
            try:
                threads = inspect_threads(device=device, elf_path=elf)
            except ImportError as exc:
                _print({"error": str(exc)}, json_mode=json_mode)
                return 1
            except Exception as exc:
                _print({"error": str(exc)}, json_mode=json_mode)
                return 1

            if json_mode:
                record = {
                    "timestamp": _now_iso(),
                    "threads": [t.to_dict() for t in threads],
                }
                print(json.dumps(record), flush=True)
            else:
                print("\033[2J\033[H", end="")
                _print_thread_table(threads)

            time.sleep(interval)
    except KeyboardInterrupt:
        return 0
