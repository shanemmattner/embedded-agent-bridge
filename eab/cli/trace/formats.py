"""Trace format auto-detection for SystemView, CTF, and RTTbin files."""

from __future__ import annotations

import logging
from pathlib import Path

logger = logging.getLogger(__name__)


def detect_trace_format(input_file: str | Path) -> str:
    """Auto-detect trace format from file extension and magic bytes.

    Args:
        input_file: Path to the trace file.

    Returns:
        Format string: 'rttbin', 'systemview', 'ctf', or 'log'.
        Defaults to 'rttbin' for backward compatibility.
    """
    input_path = Path(input_file)

    # Check file extension first
    ext = input_path.suffix.lower()
    if ext == ".svdat":
        logger.debug(f"Detected SystemView format from extension: {ext}")
        return "systemview"
    elif ext == ".rttbin":
        logger.debug(f"Detected RTTbin format from extension: {ext}")
        return "rttbin"
    elif ext == ".log":
        logger.debug(f"Detected log format from extension: {ext}")
        return "log"

    # Check for CTF metadata file in parent directory (Zephyr CTF)
    if input_path.is_dir():
        metadata_file = input_path / "metadata"
        if metadata_file.exists():
            logger.debug(f"Detected CTF format from metadata file in directory")
            return "ctf"
    else:
        # Check parent for CTF metadata (Zephyr CTF puts channel0_0 files alongside metadata)
        metadata_file = input_path.parent / "metadata"
        if metadata_file.exists():
            logger.debug(f"Detected CTF format from metadata in parent directory")
            return "ctf"
        # Also check grandparent if file is inside a channel subdirectory
        if input_path.parent.name.startswith("channel"):
            metadata_file = input_path.parent.parent / "metadata"
            if metadata_file.exists():
                logger.debug(f"Detected CTF format from Zephyr CTF structure")
                return "ctf"

    # Check magic bytes
    if input_path.is_file():
        try:
            with open(input_path, "rb") as f:
                header = f.read(32)
                
                # Check for SEGGER SystemView signature
                if b"SEGGER" in header or b"SystemView" in header:
                    logger.debug(f"Detected SystemView format from magic bytes")
                    return "systemview"
                
                # Check for CTF magic (0xC1FC1FC1 or variants)
                if len(header) >= 4:
                    magic = int.from_bytes(header[:4], byteorder="little")
                    if magic in (0xC1FC1FC1, 0x75D11D57):  # CTF 1.8 magic values
                        logger.debug(f"Detected CTF format from magic bytes: {magic:#x}")
                        return "ctf"
        except Exception as e:
            logger.debug(f"Could not read magic bytes from {input_path}: {e}")

    # Default to rttbin for backward compatibility
    logger.debug(f"No specific format detected, defaulting to rttbin")
    return "rttbin"
