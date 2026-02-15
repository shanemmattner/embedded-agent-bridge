"""Export RTT trace to Perfetto format."""

from __future__ import annotations

import json
import logging
import shutil
import subprocess
from pathlib import Path

logger = logging.getLogger(__name__)


def cmd_trace_export(
    *,
    input: str,
    output: str,
    format: str = "perfetto",
    json_mode: bool = False,
) -> int:
    """Export .rttbin trace to visualization format.

    Args:
        input: Path to input .rttbin file
        output: Path to output file
        format: Output format ('perfetto' or 'tband')
        json_mode: Emit JSON output

    Returns:
        Exit code: 0 on success, 1 on failure
    """
    input_path = Path(input).resolve()
    output_path = Path(output).resolve()

    if not input_path.exists():
        result = {"error": f"Input file not found: {input}"}
        if json_mode:
            print(json.dumps(result))
        else:
            print(f"Error: Input file not found: {input}")
        return 1

    if format == "perfetto":
        return _export_perfetto(input_path, output_path, json_mode)
    elif format == "tband":
        return _export_tband(input_path, output_path, json_mode)
    else:
        result = {"error": f"Unsupported format: {format} (use 'perfetto' or 'tband')"}
        if json_mode:
            print(json.dumps(result))
        else:
            print(f"Error: Unsupported format: {format}")
        return 1


def _export_perfetto(input_path: Path, output_path: Path, json_mode: bool) -> int:
    """Export using native Python converter (printk/text -> Chrome JSON)."""
    try:
        from eab.cli.trace.perfetto import rttbin_to_perfetto

        summary = rttbin_to_perfetto(input_path, output_path)

        result = {"exported": True, "format": "perfetto", **summary}
        if json_mode:
            print(json.dumps(result))
        else:
            print(f"Exported {summary['event_count']} events to {output_path}")
            print(f"View in Perfetto: open https://ui.perfetto.dev/ and load the file")
        return 0

    except Exception as e:
        result = {"error": str(e)}
        if json_mode:
            print(json.dumps(result))
        else:
            print(f"Error: {e}")
        return 1


def _export_tband(input_path: Path, output_path: Path, json_mode: bool) -> int:
    """Export using tband-cli (Tonbandgeraet COBS format)."""
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