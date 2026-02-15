"""Export .rttbin trace to visualization formats (Perfetto, tband)."""

from __future__ import annotations

import json
import logging
import shutil
import subprocess
from pathlib import Path

logger = logging.getLogger(__name__)


def cmd_trace_export(
    *,
    input_file: str,
    output_file: str,
    fmt: str = "perfetto",
    json_mode: bool = False,
) -> int:
    """Export .rttbin trace to a visualization format.

    Args:
        input_file: Path to input .rttbin file.
        output_file: Path to output file (.json for Perfetto).
        fmt: Output format (``"perfetto"`` or ``"tband"``).
        json_mode: Emit machine-parseable JSON output.

    Returns:
        0 on success, 1 on failure.
    """
    input_path = Path(input_file).resolve()
    output_path = Path(output_file).resolve()

    if not input_path.exists():
        result = {"error": f"Input file not found: {input_file}"}
        if json_mode:
            print(json.dumps(result))
        else:
            print(f"Error: Input file not found: {input_file}")
        return 1

    if fmt == "perfetto":
        return _export_perfetto(input_path, output_path, json_mode)
    elif fmt == "tband":
        return _export_tband(input_path, output_path, json_mode)
    else:
        result = {"error": f"Unsupported format: {fmt} (use 'perfetto' or 'tband')"}
        if json_mode:
            print(json.dumps(result))
        else:
            print(f"Error: Unsupported format: {fmt}")
        return 1


def _export_perfetto(
    input_path: Path, output_path: Path, json_mode: bool
) -> int:
    """Export using the native Python converter (text lines → Chrome JSON).

    Args:
        input_path: Resolved path to the .rttbin file.
        output_path: Resolved path to the output .json file.
        json_mode: Emit machine-parseable JSON output.

    Returns:
        0 on success, 1 on failure.
    """
    try:
        from eab.cli.trace.perfetto import rttbin_to_perfetto

        summary = rttbin_to_perfetto(input_path, output_path)

        result = {"exported": True, "format": "perfetto", **summary}
        if json_mode:
            print(json.dumps(result))
        else:
            print(f"Exported {summary['event_count']} events to {output_path}")
            print("View in Perfetto: open https://ui.perfetto.dev/ and load the file")
        return 0

    except Exception as e:
        result = {"error": str(e)}
        if json_mode:
            print(json.dumps(result))
        else:
            print(f"Error: {e}")
        return 1


def _export_tband(
    input_path: Path, output_path: Path, json_mode: bool
) -> int:
    """Export using tband-cli (Tonbandgeraet COBS format → Perfetto).

    Requires ``tband-cli`` to be installed (``cargo install tband-cli``).

    Args:
        input_path: Resolved path to the .rttbin file.
        output_path: Resolved path to the output file.
        json_mode: Emit machine-parseable JSON output.

    Returns:
        0 on success, 1 on failure.
    """
    tband_path = shutil.which("tband-cli")
    if not tband_path:
        result = {
            "error": "tband-cli not found",
            "hint": "Install with: cargo install tband-cli",
        }
        if json_mode:
            print(json.dumps(result))
        else:
            print("Error: tband-cli not found")
            print("Install with: cargo install tband-cli")
        return 1

    try:
        result_proc = subprocess.run(
            ["tband-cli", "conv", "--to", "perfetto", str(input_path), str(output_path)],
            capture_output=True,
            text=True,
            timeout=60,
        )
        if result_proc.returncode != 0:
            result = {
                "error": "tband conversion failed",
                "stderr": result_proc.stderr,
            }
            if json_mode:
                print(json.dumps(result))
            else:
                print("Error: tband conversion failed")
                print(result_proc.stderr)
            return 1

        result = {
            "exported": True,
            "format": "tband",
            "input": str(input_path),
            "output": str(output_path),
        }
        if json_mode:
            print(json.dumps(result))
        else:
            print(f"Exported to {output_path}")
            print("View in Perfetto: open https://ui.perfetto.dev/ and load the file")
        return 0

    except subprocess.TimeoutExpired:
        result = {"error": "tband conversion timed out after 60s"}
        if json_mode:
            print(json.dumps(result))
        else:
            print("Error: tband conversion timed out")
        return 1
    except Exception as e:
        result = {"error": str(e)}
        if json_mode:
            print(json.dumps(result))
        else:
            print(f"Error: {e}")
        return 1
