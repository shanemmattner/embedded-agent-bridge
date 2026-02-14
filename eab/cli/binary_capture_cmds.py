"""CLI commands for binary RTT capture (eabctl rtt-capture)."""

from __future__ import annotations

from pathlib import Path
from typing import Optional

from eab.cli.helpers import _print


def cmd_rtt_capture_start(
    *,
    device: str,
    channels: list[int],
    output: str,
    sample_width: int,
    sample_rate: int,
    timestamp_hz: int,
    interface: str,
    speed: int,
    block_address: Optional[int],
    transport: str,
    json_mode: bool,
) -> int:
    """Start binary RTT capture."""
    if transport == "jlink":
        from eab.rtt_transport import JLinkTransport
        t = JLinkTransport()
    elif transport == "probe-rs":
        from eab.rtt_transport import ProbeRSTransport
        t = ProbeRSTransport()
    else:
        _print({"error": f"Unknown transport: {transport}"}, json_mode=json_mode)
        return 2

    from eab.rtt_binary import RTTBinaryCapture

    try:
        capture = RTTBinaryCapture(
            transport=t,
            device=device,
            channels=channels,
            output_path=output,
            sample_width=sample_width,
            sample_rate=sample_rate,
            timestamp_hz=timestamp_hz,
            interface=interface,
            speed=speed,
            block_address=block_address,
        )
        capture.start()
    except Exception as e:
        _print({"error": str(e)}, json_mode=json_mode)
        return 1

    _print(
        {
            "status": "capturing",
            "output": output,
            "device": device,
            "channels": channels,
            "transport": transport,
        },
        json_mode=json_mode,
    )
    return 0


def cmd_rtt_capture_convert(
    *,
    input_path: str,
    output_path: Optional[str],
    fmt: str,
    channel: int,
    sample_rate: Optional[int],
    json_mode: bool,
) -> int:
    """Convert .rttbin file to another format."""
    inp = Path(input_path)
    if not inp.exists():
        _print({"error": f"File not found: {input_path}"}, json_mode=json_mode)
        return 1

    try:
        if fmt == "csv":
            from eab.rtt_convert import to_csv
            out = Path(output_path) if output_path else inp.with_suffix(".csv")
            result = to_csv(inp, out)
            _print({"format": "csv", "output": str(result)}, json_mode=json_mode)

        elif fmt == "wav":
            from eab.rtt_convert import to_wav
            out = Path(output_path) if output_path else inp.with_suffix(".wav")
            result = to_wav(inp, out, channel=channel, sample_rate=sample_rate)
            _print({"format": "wav", "output": str(result)}, json_mode=json_mode)

        elif fmt == "numpy":
            from eab.rtt_convert import to_numpy
            data = to_numpy(inp)
            summary = {ch: len(arr) for ch, arr in data.items()}
            _print({"format": "numpy", "channels": summary}, json_mode=json_mode)

        else:
            _print({"error": f"Unknown format: {fmt}"}, json_mode=json_mode)
            return 2

    except Exception as e:
        _print({"error": str(e)}, json_mode=json_mode)
        return 1

    return 0


def cmd_rtt_capture_info(
    *,
    input_path: str,
    json_mode: bool,
) -> int:
    """Show .rttbin file header info."""
    inp = Path(input_path)
    if not inp.exists():
        _print({"error": f"File not found: {input_path}"}, json_mode=json_mode)
        return 1

    try:
        from eab.rtt_binary import BinaryReader
        with BinaryReader(inp) as reader:
            frames = reader.read_all()
            total_bytes = sum(len(p) for _, _, p in frames)
            _print(
                {
                    "version": reader.version,
                    "channel_count": reader.channel_count,
                    "sample_width": reader.sample_width,
                    "sample_rate": reader.sample_rate,
                    "timestamp_hz": reader.timestamp_hz,
                    "start_time": reader.start_time,
                    "channel_mask": f"0x{reader.channel_mask:08X}",
                    "total_frames": len(frames),
                    "total_payload_bytes": total_bytes,
                    "file_size": inp.stat().st_size,
                },
                json_mode=json_mode,
            )
    except Exception as e:
        _print({"error": str(e)}, json_mode=json_mode)
        return 1

    return 0
