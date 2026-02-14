"""Converters for .rttbin files: numpy, CSV, WAV.

All functions work on closed .rttbin files (not live captures).
"""

from __future__ import annotations

import csv
import wave
from pathlib import Path

from eab.rtt_binary import BinaryReader


def to_numpy(rttbin_path: str | Path, sample_width: int | None = None) -> dict:
    """Convert .rttbin to numpy arrays.

    Args:
        rttbin_path: Path to .rttbin file.
        sample_width: Override bytes per sample (1, 2, or 4).
            If None, uses the value from the file header.

    Returns:
        dict mapping channel (int) → numpy.ndarray of samples.
    """
    try:
        import numpy as np
    except ImportError:
        raise ImportError("numpy is required for to_numpy(). Install with: pip install numpy")

    dtype_map = {1: np.uint8, 2: np.int16, 4: np.int32}

    with BinaryReader(rttbin_path) as reader:
        sw = sample_width if sample_width is not None else reader.sample_width
        if sw not in dtype_map:
            raise ValueError(f"Unsupported sample_width: {sw} (must be 1, 2, or 4)")

        dt = dtype_map[sw]
        channel_data: dict[int, list[bytes]] = {}

        for _ts, channel, payload in reader.read_all():
            channel_data.setdefault(channel, []).append(payload)

    result = {}
    for ch, payloads in channel_data.items():
        raw = b"".join(payloads)
        # Trim to multiple of sample_width
        trim = len(raw) - (len(raw) % sw)
        if trim > 0:
            result[ch] = np.frombuffer(raw[:trim], dtype=dt)
        else:
            result[ch] = np.array([], dtype=dt)

    return result


def to_csv(rttbin_path: str | Path, output_path: str | Path) -> Path:
    """Convert .rttbin to CSV.

    Each row: timestamp, channel, payload_hex, payload_length

    Args:
        rttbin_path: Path to .rttbin file.
        output_path: Path for output CSV.

    Returns:
        Path to written CSV file.
    """
    output_path = Path(output_path)

    with BinaryReader(rttbin_path) as reader:
        frames = reader.read_all()
        timestamp_hz = reader.timestamp_hz

    with open(output_path, "w", newline="") as f:
        writer = csv.writer(f)
        writer.writerow(["timestamp", "channel", "payload_hex", "payload_length"])

        for ts, channel, payload in frames:
            ts_str = str(ts)
            if timestamp_hz > 0:
                ts_str = f"{ts / timestamp_hz:.6f}"
            writer.writerow([ts_str, channel, payload.hex(), len(payload)])

    return output_path


def to_wav(
    rttbin_path: str | Path,
    output_path: str | Path,
    *,
    channel: int = 0,
    sample_rate: int | None = None,
    sample_width: int | None = None,
) -> Path:
    """Convert .rttbin single-channel data to WAV.

    Useful for audio captures or audible inspection of ADC data.

    Args:
        rttbin_path: Path to .rttbin file.
        output_path: Path for output WAV.
        channel: RTT channel to extract (default 0).
        sample_rate: Override sample rate. Uses file header if None.
        sample_width: Override sample width. Uses file header if None.

    Returns:
        Path to written WAV file.
    """
    output_path = Path(output_path)

    with BinaryReader(rttbin_path) as reader:
        sr = sample_rate if sample_rate is not None else reader.sample_rate
        sw = sample_width if sample_width is not None else reader.sample_width

        if sr == 0:
            raise ValueError("sample_rate required for WAV (file header has 0)")
        if sw not in (1, 2, 4):
            raise ValueError(f"Unsupported sample_width for WAV: {sw}")

        payloads = []
        for _ts, ch, payload in reader.read_all():
            if ch == channel:
                payloads.append(payload)

    raw = b"".join(payloads)
    # Trim to multiple of sample_width
    trim = len(raw) - (len(raw) % sw)
    raw = raw[:trim]

    with wave.open(str(output_path), "wb") as wf:
        wf.setnchannels(1)
        wf.setsampwidth(sw)
        wf.setframerate(sr)
        wf.writeframes(raw)

    return output_path
