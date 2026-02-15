"""Convert SEGGER SystemView traces to Perfetto format."""

from __future__ import annotations

import json
import logging
import os
import shutil
import subprocess
from pathlib import Path

logger = logging.getLogger(__name__)


def export_systemview_to_perfetto(
    input_path: str | Path, output_path: str | Path
) -> dict:
    """Convert SystemView .svdat file to Perfetto Chrome JSON format.

    This function wraps ESP-IDF's sysviewtrace_proc.py tool, which must be
    available via the IDF_PATH environment variable.

    Args:
        input_path: Path to SystemView .svdat file.
        output_path: Path to output Perfetto .json file.

    Returns:
        Summary dict with ``event_count``, ``output_path``, and
        ``output_size_bytes``.

    Raises:
        RuntimeError: If IDF_PATH is not set or sysviewtrace_proc.py not found.
        subprocess.CalledProcessError: If conversion fails.
        subprocess.TimeoutExpired: If conversion times out.
    """
    input_path = Path(input_path)
    output_path = Path(output_path)

    # Find sysviewtrace_proc.py via IDF_PATH
    idf_path = os.environ.get("IDF_PATH")
    if not idf_path:
        raise RuntimeError(
            "IDF_PATH environment variable not set. "
            "Install ESP-IDF and set IDF_PATH to use SystemView conversion."
        )

    sysview_tool = Path(idf_path) / "tools" / "esp_app_trace" / "sysviewtrace_proc.py"
    if not sysview_tool.exists():
        raise RuntimeError(
            f"sysviewtrace_proc.py not found at {sysview_tool}. "
            "Check your ESP-IDF installation."
        )

    # Check if python3 is available
    python_exe = shutil.which("python3") or shutil.which("python")
    if not python_exe:
        raise RuntimeError("Python executable not found in PATH")

    # Run sysviewtrace_proc.py to convert to JSON
    # Usage: sysviewtrace_proc.py <svdat_file> <output_json>
    try:
        logger.debug(f"Running sysviewtrace_proc.py: {input_path} -> {output_path}")
        result = subprocess.run(
            [python_exe, str(sysview_tool), str(input_path), str(output_path)],
            capture_output=True,
            text=True,
            timeout=60,
        )

        if result.returncode != 0:
            raise subprocess.CalledProcessError(
                result.returncode, result.args, result.stdout, result.stderr
            )

        # Parse the output to count events
        event_count = 0
        if output_path.exists():
            try:
                with open(output_path, "r") as f:
                    data = json.load(f)
                    if "traceEvents" in data:
                        event_count = len(data["traceEvents"])
            except Exception as e:
                logger.warning(f"Could not count events in output file: {e}")

        return {
            "event_count": event_count,
            "output_path": str(output_path),
            "output_size_bytes": output_path.stat().st_size,
        }

    except subprocess.TimeoutExpired:
        raise subprocess.TimeoutExpired(
            "sysviewtrace_proc.py conversion timed out after 60 seconds",
            timeout=60,
        )
