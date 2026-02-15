"""Convert CTF (Common Trace Format) traces to Perfetto format."""

from __future__ import annotations

import json
import logging
import re
import shutil
import subprocess
from pathlib import Path

logger = logging.getLogger(__name__)


def export_ctf_to_perfetto(input_path: str | Path, output_path: str | Path) -> dict:
    """Convert CTF trace to Perfetto Chrome JSON format.

    This function wraps the babeltrace CLI tool to parse CTF traces and
    converts them to Perfetto's Chrome JSON format. Each CTF event becomes
    a Perfetto instant event.

    Args:
        input_path: Path to CTF trace directory or file.
        output_path: Path to output Perfetto .json file.

    Returns:
        Summary dict with ``event_count``, ``output_path``, and
        ``output_size_bytes``.

    Raises:
        RuntimeError: If babeltrace is not installed.
        subprocess.CalledProcessError: If conversion fails.
        subprocess.TimeoutExpired: If conversion times out.
    """
    input_path = Path(input_path)
    output_path = Path(output_path)

    # Check if babeltrace is available
    babeltrace_exe = shutil.which("babeltrace") or shutil.which("babeltrace2")
    if not babeltrace_exe:
        raise RuntimeError(
            "babeltrace not found in PATH. "
            "Install with: apt-get install babeltrace (or babeltrace2)"
        )

    # Run babeltrace to convert CTF to text format
    try:
        logger.debug(f"Running babeltrace on {input_path}")
        result = subprocess.run(
            [babeltrace_exe, str(input_path)],
            capture_output=True,
            text=True,
            timeout=60,
        )

        if result.returncode != 0:
            raise subprocess.CalledProcessError(
                result.returncode, result.args, result.stdout, result.stderr
            )

        # Parse babeltrace output into Perfetto format
        trace_events = _parse_babeltrace_output(result.stdout)

        # Add metadata
        metadata = [
            {
                "pid": 1,
                "tid": 0,
                "name": "process_name",
                "ph": "M",
                "cat": "__metadata",
                "args": {"name": "CTF Trace"},
            },
        ]

        # Extract unique thread IDs and add thread names
        tids = set()
        for event in trace_events:
            if "tid" in event:
                tids.add(event["tid"])

        for tid in sorted(tids):
            metadata.append(
                {
                    "pid": 1,
                    "tid": tid,
                    "name": "thread_name",
                    "ph": "M",
                    "cat": "__metadata",
                    "args": {"name": f"Thread {tid}"},
                }
            )

        # Write Perfetto JSON
        perfetto_output = {
            "traceEvents": metadata + trace_events,
            "displayTimeUnit": "ms",
        }

        with open(output_path, "w") as f:
            json.dump(perfetto_output, f)

        return {
            "event_count": len(trace_events),
            "output_path": str(output_path),
            "output_size_bytes": output_path.stat().st_size,
        }

    except subprocess.TimeoutExpired:
        raise subprocess.TimeoutExpired(
            "babeltrace conversion timed out after 60 seconds", timeout=60
        )


def _parse_babeltrace_output(output: str) -> list[dict]:
    """Parse babeltrace text output into Perfetto events.

    Babeltrace output format (typical):
    [HH:MM:SS.nanosec] (+offset) domain:event_name: { ... fields ... }

    Args:
        output: babeltrace text output.

    Returns:
        List of Perfetto trace events.
    """
    trace_events = []
    
    # Pattern to match babeltrace output lines
    # Example: [00:00:00.123456789] (+0.000001234) kernel:sched_switch: { cpu_id = 0 }, { prev_comm = "swapper", ... }
    pattern = re.compile(
        r'^\[(\d{2}):(\d{2}):(\d{2})\.(\d+)\]\s+\([+\-]?[\d.]+\)\s+(\S+):(\S+):\s+(.*)$'
    )

    for line in output.splitlines():
        line = line.strip()
        if not line:
            continue

        match = pattern.match(line)
        if not match:
            continue

        hours, minutes, seconds, nanosec, domain, event_name, fields_str = match.groups()

        # Convert timestamp to microseconds
        total_seconds = int(hours) * 3600 + int(minutes) * 60 + int(seconds)
        # Pad nanoseconds to 9 digits if needed
        nanosec_padded = nanosec.ljust(9, '0')[:9]
        total_nanosec = total_seconds * 1_000_000_000 + int(nanosec_padded)
        ts_us = total_nanosec / 1000  # Convert to microseconds

        # Parse fields (basic parsing, fields are in { key = value, ... } format)
        fields = {}
        try:
            fields = _parse_ctf_fields(fields_str)
        except Exception as e:
            logger.debug(f"Could not parse fields for {event_name}: {e}")

        # Extract tid from fields if available (common in kernel traces)
        tid = fields.get("tid", fields.get("cpu_id", 0))
        if isinstance(tid, str):
            try:
                tid = int(tid)
            except ValueError:
                tid = 0

        # Create Perfetto instant event
        trace_events.append(
            {
                "pid": 1,
                "tid": tid,
                "ts": ts_us,
                "ph": "i",  # Instant event
                "name": event_name,
                "cat": domain,
                "s": "g",  # Global scope
                "args": fields,
            }
        )

    return trace_events


def _parse_ctf_fields(fields_str: str) -> dict:
    """Parse CTF field string into a dict.

    Args:
        fields_str: Field string like "{ cpu_id = 0 }, { prev_comm = "swapper" }"

    Returns:
        Dictionary of field name -> value.
    """
    fields = {}
    
    # Simple regex to extract key = value pairs
    # This handles both { ... } groups and individual fields
    field_pattern = re.compile(r'(\w+)\s*=\s*("(?:[^"\\]|\\.)*"|[^,}\s]+)')
    
    for match in field_pattern.finditer(fields_str):
        key = match.group(1)
        value = match.group(2)
        
        # Remove quotes from string values
        if value.startswith('"') and value.endswith('"'):
            value = value[1:-1]
        else:
            # Try to convert to int
            try:
                value = int(value)
            except ValueError:
                # Try to convert to float
                try:
                    value = float(value)
                except ValueError:
                    pass  # Keep as string
        
        fields[key] = value
    
    return fields
