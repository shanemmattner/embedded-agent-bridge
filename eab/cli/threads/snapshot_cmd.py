"""cmd_threads_snapshot — one-shot Zephyr thread inspection."""

from __future__ import annotations

import json

from eab.cli.helpers import _print


def cmd_threads_snapshot(
    *,
    device: str,
    elf: str,
    json_mode: bool,
) -> int:
    """Inspect Zephyr RTOS threads and print results.

    Args:
        device: J-Link device string (e.g., ``"NRF5340_XXAA_APP"``).
        elf: Path to the ELF file with DWARF debug symbols.
        json_mode: If True, output JSON array; otherwise print a table.

    Returns:
        0 on success, 1 on error.
    """
    from eab.thread_inspector import inspect_threads

    try:
        threads = inspect_threads(device=device, elf_path=elf)
    except ImportError as exc:
        _print({"error": str(exc)}, json_mode=json_mode)
        return 1
    except Exception as exc:
        _print({"error": str(exc)}, json_mode=json_mode)
        return 1

    if json_mode:
        print(json.dumps([t.to_dict() for t in threads]))
        return 0

    _print_thread_table(threads)
    return 0


def _print_thread_table(threads: list) -> None:
    """Print threads as a fixed-width human-readable table."""
    header = f"{'Name':<24} {'State':<12} {'Priority':>8} {'Stack Used':>10} {'Stack Size':>10} {'Stack Free':>10}"
    separator = "-" * len(header)
    print(header)
    print(separator)
    for t in threads:
        print(f"{t.name:<24} {t.state:<12} {t.priority:>8} {t.stack_used:>10} {t.stack_size:>10} {t.stack_free:>10}")
