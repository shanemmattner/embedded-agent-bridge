"""Tests for eab/rtt_convert.py — .rttbin to CSV/WAV/numpy conversion."""

from __future__ import annotations

import csv
import struct
import wave
from pathlib import Path
from unittest.mock import MagicMock, patch

import pytest


# We need to mock BinaryReader since we don't have real .rttbin files
@pytest.fixture
def mock_reader():
    """Create a mock BinaryReader that yields test frames."""
    reader = MagicMock()
    reader.sample_width = 2
    reader.sample_rate = 44100
    reader.timestamp_hz = 1000

    # Frames: (timestamp, channel, payload)
    frames = [
        (0, 0, struct.pack("<hh", 100, 200)),
        (1, 0, struct.pack("<hh", 300, 400)),
        (2, 1, struct.pack("<h", 500)),
    ]
    reader.read_all.return_value = frames
    reader.__enter__ = MagicMock(return_value=reader)
    reader.__exit__ = MagicMock(return_value=False)
    return reader


class TestToCsv:
    def test_writes_csv(self, tmp_path, mock_reader):
        from eab.rtt_convert import to_csv

        output = tmp_path / "out.csv"
        with patch("eab.rtt_convert.BinaryReader", return_value=mock_reader):
            result = to_csv("fake.rttbin", output)

        assert result == output
        assert output.exists()

        with open(output) as f:
            rows = list(csv.reader(f))
        assert rows[0] == ["timestamp", "channel", "payload_hex", "payload_length"]
        assert len(rows) == 4  # header + 3 frames

    def test_timestamp_hz_conversion(self, tmp_path, mock_reader):
        from eab.rtt_convert import to_csv

        output = tmp_path / "out.csv"
        with patch("eab.rtt_convert.BinaryReader", return_value=mock_reader):
            to_csv("fake.rttbin", output)

        with open(output) as f:
            rows = list(csv.reader(f))
        # timestamp_hz=1000, ts=1 → "0.001000"
        assert rows[2][0] == "0.001000"


class TestToWav:
    def test_writes_wav(self, tmp_path, mock_reader):
        from eab.rtt_convert import to_wav

        output = tmp_path / "out.wav"
        with patch("eab.rtt_convert.BinaryReader", return_value=mock_reader):
            result = to_wav("fake.rttbin", output, channel=0)

        assert result == output
        with wave.open(str(output), "rb") as wf:
            assert wf.getnchannels() == 1
            assert wf.getsampwidth() == 2
            assert wf.getframerate() == 44100

    def test_zero_sample_rate_raises(self, tmp_path, mock_reader):
        from eab.rtt_convert import to_wav

        mock_reader.sample_rate = 0
        with patch("eab.rtt_convert.BinaryReader", return_value=mock_reader):
            with pytest.raises(ValueError, match="sample_rate"):
                to_wav("fake.rttbin", tmp_path / "out.wav")

    def test_unsupported_sample_width_raises(self, tmp_path, mock_reader):
        from eab.rtt_convert import to_wav

        mock_reader.sample_width = 3
        with patch("eab.rtt_convert.BinaryReader", return_value=mock_reader):
            with pytest.raises(ValueError, match="sample_width"):
                to_wav("fake.rttbin", tmp_path / "out.wav")

    def test_channel_filter(self, tmp_path, mock_reader):
        from eab.rtt_convert import to_wav

        output = tmp_path / "ch1.wav"
        with patch("eab.rtt_convert.BinaryReader", return_value=mock_reader):
            to_wav("fake.rttbin", output, channel=1)

        with wave.open(str(output), "rb") as wf:
            frames = wf.readframes(wf.getnframes())
        # Channel 1 only has one frame with 1 sample (2 bytes)
        assert len(frames) == 2

    def test_override_sample_rate(self, tmp_path, mock_reader):
        from eab.rtt_convert import to_wav

        output = tmp_path / "out.wav"
        with patch("eab.rtt_convert.BinaryReader", return_value=mock_reader):
            to_wav("fake.rttbin", output, sample_rate=8000)

        with wave.open(str(output), "rb") as wf:
            assert wf.getframerate() == 8000


class TestToNumpy:
    def test_converts_to_arrays(self, tmp_path, mock_reader):
        np = pytest.importorskip("numpy")
        from eab.rtt_convert import to_numpy

        with patch("eab.rtt_convert.BinaryReader", return_value=mock_reader):
            result = to_numpy("fake.rttbin")

        assert 0 in result
        assert 1 in result
        # Channel 0: 2 frames × 2 samples = 4 int16 values
        assert list(result[0]) == [100, 200, 300, 400]
        # Channel 1: 1 frame × 1 sample = 1 int16 value
        assert list(result[1]) == [500]

    def test_unsupported_sample_width(self, tmp_path, mock_reader):
        pytest.importorskip("numpy")
        from eab.rtt_convert import to_numpy

        mock_reader.sample_width = 3
        with patch("eab.rtt_convert.BinaryReader", return_value=mock_reader):
            with pytest.raises(ValueError, match="sample_width"):
                to_numpy("fake.rttbin")
