"""
Tests for capture helpers (extracting payloads from timestamped logs).
"""

from __future__ import annotations

import base64


def test_capture_between_markers_base64_text(tmp_path):
    from eab.capture import capture_between_markers

    payload_bytes = b"hello world"
    payload_b64 = base64.b64encode(payload_bytes).decode("ascii")
    # Split across lines like a device would.
    payload_lines = [payload_b64[:8], payload_b64[8:]]

    log_path = tmp_path / "latest.log"
    out_path = tmp_path / "out.b64"

    log_path.write_text(
        "\n".join(
            [
                "[00:00:01.000] booting",
                "[00:00:02.000] ===WAV_START===",
                f"[00:00:02.100] {payload_lines[0]}",
                "[00:00:02.200] [EAB] Chip state: crashed",
                f"[00:00:02.300] {payload_lines[1]}",
                "[00:00:03.000] I (26) boot: ESP-IDF v5.4.1",
                "[00:00:04.000] ===WAV_END===",
            ]
        )
        + "\n"
    )

    result = capture_between_markers(
        log_path=str(log_path),
        start_marker="===WAV_START===",
        end_marker="===WAV_END===",
        output_path=str(out_path),
        timeout_s=0.1,
        from_end=False,
        strip_timestamps=True,
        filter_mode="base64",
        decode_base64=False,
    )

    assert result.start_seen is True
    assert result.end_seen is True
    assert result.lines_captured == 2
    assert out_path.read_text().splitlines() == payload_lines


def test_capture_between_markers_decode_base64(tmp_path):
    from eab.capture import capture_between_markers

    payload_bytes = b"\x00\x01\x02binary"
    payload_b64 = base64.b64encode(payload_bytes).decode("ascii")

    log_path = tmp_path / "latest.log"
    out_path = tmp_path / "out.bin"

    log_path.write_text(
        "\n".join(
            [
                "===START===",
                payload_b64,
                "===END===",
            ]
        )
        + "\n"
    )

    result = capture_between_markers(
        log_path=str(log_path),
        start_marker="===START===",
        end_marker="===END===",
        output_path=str(out_path),
        timeout_s=0.1,
        from_end=False,
        strip_timestamps=True,
        filter_mode="base64",
        decode_base64=True,
    )

    assert result.decode_base64 is True
    assert out_path.read_bytes() == payload_bytes

