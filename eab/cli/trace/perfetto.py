"""Convert .rttbin to Chrome JSON trace format for Perfetto."""
from __future__ import annotations
import json
from pathlib import Path
from eab.rtt_binary import BinaryReader


def rttbin_to_perfetto(input_path: str | Path, output_path: str | Path) -> dict:
    """Convert .rttbin to Chrome JSON trace format.

    Args:
        input_path: Path to .rttbin file
        output_path: Path to output .json file

    Returns:
        Summary dict with frame_count, event_count, duration info
    """
    input_path = Path(input_path)
    output_path = Path(output_path)
    reader = BinaryReader(input_path)
    trace_events = []
    frame_count = 0
    text_buffer = {}
    msg_counts = {}

    while True:
        frame = reader.read_frame()
        if frame is None:
            break
        timestamp, channel, payload = frame
        frame_count += 1

        try:
            text = payload.decode('utf-8', errors='replace')
        except Exception:
            continue

        if channel not in text_buffer:
            text_buffer[channel] = ''
        text_buffer[channel] += text

        while '\n' in text_buffer[channel]:
            line, text_buffer[channel] = text_buffer[channel].split('\n', 1)
            line = line.strip()
            if not line:
                continue

            if reader.timestamp_hz > 0:
                ts_us = (timestamp / reader.timestamp_hz) * 1_000_000
            else:
                ts_us = frame_count * 1000

            if channel not in msg_counts:
                msg_counts[channel] = 0
            msg_counts[channel] += 1

            trace_events.append({
                'pid': 1, 'tid': channel, 'ts': ts_us, 'ph': 'i',
                'name': line[:80], 'cat': 'rtt', 's': 'g',
                'args': {'channel': channel, 'raw': line},
            })
            trace_events.append({
                'pid': 1, 'tid': channel, 'ts': ts_us, 'ph': 'C',
                'name': f'messages_ch{channel}',
                'args': {f'ch{channel}_count': msg_counts[channel]},
            })

    metadata = [
        {'pid': 1, 'tid': 0, 'name': 'process_name', 'ph': 'M',
         'cat': '__metadata', 'args': {'name': 'RTT Trace'}},
    ]
    for ch in sorted(msg_counts):
        metadata.append({
            'pid': 1, 'tid': ch, 'name': 'thread_name', 'ph': 'M',
            'cat': '__metadata', 'args': {'name': f'RTT Channel {ch}'},
        })

    output = {'traceEvents': metadata + trace_events, 'displayTimeUnit': 'ms'}
    with open(output_path, 'w') as f:
        json.dump(output, f)

    reader.close()

    return {
        'frame_count': frame_count,
        'event_count': len(trace_events),
        'channels': sorted(msg_counts.keys()),
        'output_path': str(output_path),
        'output_size_bytes': output_path.stat().st_size,
    }
