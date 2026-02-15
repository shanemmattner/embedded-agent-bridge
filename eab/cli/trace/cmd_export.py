"""Export trace files to visualization formats (Perfetto, tband).

Supports RTTbin, SystemView, and CTF trace formats with auto-detection.
"""

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
    fmt: str = "auto",
    json_mode: bool = False,
) -> int:
    """Export trace file to a visualization format.

    Args:
        input_file: Path to input trace file (.rttbin, .svdat, CTF directory).
        output_file: Path to output file (.json for Perfetto).
        fmt: Output format (``"auto"``, ``"perfetto"``, ``"tband"``, ``"systemview"``, ``"ctf"``).
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

    # Auto-detect format if requested
    if fmt == "auto":
        from eab.cli.trace.formats import detect_trace_format
        detected_fmt = detect_trace_format(input_path)
        logger.info(f"Auto-detected format: {detected_fmt}")
        
        # Map detected format to export handler
        if detected_fmt == "systemview":
            return _export_systemview(input_path, output_path, json_mode)
        elif detected_fmt == "ctf":
            return _export_ctf(input_path, output_path, json_mode)
        elif detected_fmt == "rttbin":
            return _export_perfetto(input_path, output_path, json_mode)
        else:
            result = {"error": f"Unsupported auto-detected format: {detected_fmt}"}
            if json_mode:
                print(json.dumps(result))
            else:
                print(f"Error: Unsupported format: {detected_fmt}")
            return 1

    # Explicit format specified
    if fmt == "perfetto":
        return _export_perfetto(input_path, output_path, json_mode)
    elif fmt == "tband":
        return _export_tband(input_path, output_path, json_mode)
    elif fmt == "systemview":
        return _export_systemview(input_path, output_path, json_mode)
    elif fmt == "ctf":
        return _export_ctf(input_path, output_path, json_mode)
    else:
        result = {"error": f"Unsupported format: {fmt}"}
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


def _export_systemview(
    input_path: Path, output_path: Path, json_mode: bool
) -> int:
    """Export SystemView .svdat file to Perfetto format.

    Requires ESP-IDF with IDF_PATH environment variable set.

    Args:
        input_path: Resolved path to the .svdat file.
        output_path: Resolved path to the output .json file.
        json_mode: Emit machine-parseable JSON output.

    Returns:
        0 on success, 1 on failure.
    """
    try:
        from eab.cli.trace.converters import export_systemview_to_perfetto

        summary = export_systemview_to_perfetto(input_path, output_path)

        result = {"exported": True, "format": "systemview", **summary}
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


def _export_ctf(input_path: Path, output_path: Path, json_mode: bool) -> int:
    """Export CTF trace to Perfetto format.

    Requires babeltrace to be installed.

    Args:
        input_path: Resolved path to the CTF trace directory or file.
        output_path: Resolved path to the output .json file.
        json_mode: Emit machine-parseable JSON output.

    Returns:
        0 on success, 1 on failure.
    """
    try:
        from eab.cli.trace.converters import export_ctf_to_perfetto

        summary = export_ctf_to_perfetto(input_path, output_path)

        result = {"exported": True, "format": "ctf", **summary}
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
