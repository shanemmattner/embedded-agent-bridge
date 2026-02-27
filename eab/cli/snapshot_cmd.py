"""eabctl snapshot - Capture a core snapshot from a running embedded target."""

from __future__ import annotations

import sys

from eab.cli.helpers import _print


def cmd_snapshot(
    device: str,
    elf: str,
    output: str,
    json_mode: bool = False,
) -> int:
    """Capture a full memory snapshot from a live embedded target.

    Calls capture_snapshot() to halt the target, dump RAM regions, read
    Cortex-M registers, and write an ELF32 ET_CORE file.

    Args:
        device:    J-Link / probe device identifier (e.g. "NRF5340_XXAA_APP").
        elf:       Path to the firmware ELF file.
        output:    Output path for the generated .core file.
        json_mode: If True, print JSON output; otherwise print human-readable text.

    Returns:
        0 on success, 1 on failure.
    """
    try:
        from eab.snapshot import capture_snapshot  # noqa: PLC0415
    except ImportError as exc:
        print(f"ERROR: {exc}", file=sys.stderr)
        return 1

    try:
        result = capture_snapshot(
            device=device,
            elf_path=elf,
            output_path=output,
        )
    except (ValueError, FileNotFoundError, ImportError, RuntimeError) as exc:
        print(f"ERROR: {exc}", file=sys.stderr)
        return 1

    if json_mode:
        _print(
            {
                "path": result.output_path,
                "regions": [{"start": r.start, "size": r.size} for r in result.regions],
                "registers": result.registers,
                "size_bytes": result.total_size,
            },
            json_mode=True,
        )
    else:
        print(f"Snapshot written to: {result.output_path}")
        print(f"Regions captured:    {len(result.regions)}")
        print(f"Total size:          {result.total_size} bytes ({result.total_size / 1024:.1f} KB)")

    return 0
