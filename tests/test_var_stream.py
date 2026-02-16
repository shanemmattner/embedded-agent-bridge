"""Tests for variable streaming and type decode (Phase 4)."""

from __future__ import annotations

import io
import json
import struct

import pytest

from eab.analyzers.type_decode import (
    C2000Type,
    TypeInfo,
    byte_size,
    decode_value,
    parse_type_string,
    type_info,
    word_size,
)
from eab.analyzers.var_stream import StreamVar, VarStream


# =========================================================================
# Type decode — basic types
# =========================================================================


class TestTypeInfo:
    def test_int16_word_size(self):
        assert word_size(C2000Type.INT16) == 1

    def test_int32_word_size(self):
        assert word_size(C2000Type.INT32) == 2

    def test_float64_word_size(self):
        assert word_size(C2000Type.FLOAT64) == 4

    def test_iq24_word_size(self):
        assert word_size(C2000Type.IQ24) == 2

    def test_byte_sizes(self):
        assert byte_size(C2000Type.INT16) == 2
        assert byte_size(C2000Type.INT32) == 4
        assert byte_size(C2000Type.FLOAT32) == 4
        assert byte_size(C2000Type.FLOAT64) == 8

    def test_type_info_has_description(self):
        info = type_info(C2000Type.IQ24)
        assert "IQ24" in info.description
        assert info.word_size == 2


# =========================================================================
# Type decode — integer types
# =========================================================================


class TestDecodeIntegers:
    def test_int16_positive(self):
        data = struct.pack("<h", 1500)
        assert decode_value(data, C2000Type.INT16) == 1500

    def test_int16_negative(self):
        data = struct.pack("<h", -1500)
        assert decode_value(data, C2000Type.INT16) == -1500

    def test_uint16(self):
        data = struct.pack("<H", 65535)
        assert decode_value(data, C2000Type.UINT16) == 65535

    def test_int32(self):
        data = struct.pack("<i", -100000)
        assert decode_value(data, C2000Type.INT32) == -100000

    def test_uint32(self):
        data = struct.pack("<I", 4000000000)
        assert decode_value(data, C2000Type.UINT32) == 4000000000

    def test_int16_zero(self):
        assert decode_value(b"\x00\x00", C2000Type.INT16) == 0

    def test_int16_max(self):
        data = struct.pack("<h", 32767)
        assert decode_value(data, C2000Type.INT16) == 32767

    def test_int16_min(self):
        data = struct.pack("<h", -32768)
        assert decode_value(data, C2000Type.INT16) == -32768


# =========================================================================
# Type decode — float types
# =========================================================================


class TestDecodeFloats:
    def test_float32(self):
        data = struct.pack("<f", 3.14)
        result = decode_value(data, C2000Type.FLOAT32)
        assert result == pytest.approx(3.14, rel=1e-6)

    def test_float32_negative(self):
        data = struct.pack("<f", -1.5)
        result = decode_value(data, C2000Type.FLOAT32)
        assert result == pytest.approx(-1.5)

    def test_float32_zero(self):
        data = struct.pack("<f", 0.0)
        assert decode_value(data, C2000Type.FLOAT32) == 0.0

    def test_float64(self):
        data = struct.pack("<d", 3.141592653589793)
        result = decode_value(data, C2000Type.FLOAT64)
        assert result == pytest.approx(3.141592653589793)


# =========================================================================
# Type decode — IQ fixed-point formats
# =========================================================================


class TestDecodeIQ:
    def test_iq24_one(self):
        """IQ24 representation of 1.0 = 2^24 = 16777216"""
        raw = 1 << 24
        data = struct.pack("<i", raw)
        result = decode_value(data, C2000Type.IQ24)
        assert result == pytest.approx(1.0)

    def test_iq24_half(self):
        raw = 1 << 23  # 0.5 in IQ24
        data = struct.pack("<i", raw)
        assert decode_value(data, C2000Type.IQ24) == pytest.approx(0.5)

    def test_iq24_negative(self):
        raw = -(1 << 24)  # -1.0 in IQ24
        data = struct.pack("<i", raw)
        assert decode_value(data, C2000Type.IQ24) == pytest.approx(-1.0)

    def test_iq24_small_fraction(self):
        raw = 1  # Smallest positive IQ24 = 1/2^24 ≈ 5.96e-8
        data = struct.pack("<i", raw)
        result = decode_value(data, C2000Type.IQ24)
        assert result == pytest.approx(1.0 / (1 << 24))

    def test_iq24_max_positive(self):
        """IQ24 max = (2^31 - 1) / 2^24 ≈ 127.999999940"""
        raw = 0x7FFFFFFF
        data = struct.pack("<i", raw)
        result = decode_value(data, C2000Type.IQ24)
        assert result == pytest.approx(127.999999940, rel=1e-6)

    def test_iq20_one(self):
        raw = 1 << 20
        data = struct.pack("<i", raw)
        assert decode_value(data, C2000Type.IQ20) == pytest.approx(1.0)

    def test_iq15_one(self):
        raw = 1 << 15
        data = struct.pack("<i", raw)
        assert decode_value(data, C2000Type.IQ15) == pytest.approx(1.0)

    def test_iq10_one(self):
        raw = 1 << 10
        data = struct.pack("<i", raw)
        assert decode_value(data, C2000Type.IQ10) == pytest.approx(1.0)

    def test_iq15_motor_speed(self):
        """Typical motor speed: 1500.0 RPM in IQ15"""
        raw = int(1500.0 * (1 << 15))
        data = struct.pack("<i", raw)
        result = decode_value(data, C2000Type.IQ15)
        assert result == pytest.approx(1500.0, rel=1e-4)

    def test_iq24_zero(self):
        data = struct.pack("<i", 0)
        assert decode_value(data, C2000Type.IQ24) == 0.0


# =========================================================================
# Type decode — error cases
# =========================================================================


class TestDecodeErrors:
    def test_short_data(self):
        with pytest.raises(ValueError, match="Need 4 bytes"):
            decode_value(b"\x00\x00", C2000Type.INT32)

    def test_short_data_float64(self):
        with pytest.raises(ValueError, match="Need 8 bytes"):
            decode_value(b"\x00\x00\x00\x00", C2000Type.FLOAT64)


# =========================================================================
# parse_type_string
# =========================================================================


class TestParseTypeString:
    def test_lowercase(self):
        assert parse_type_string("int16") == C2000Type.INT16

    def test_uppercase(self):
        assert parse_type_string("IQ24") == C2000Type.IQ24

    def test_mixed_case(self):
        assert parse_type_string("Float32") == C2000Type.FLOAT32

    def test_invalid(self):
        with pytest.raises(ValueError, match="Unknown type"):
            parse_type_string("int8")


# =========================================================================
# StreamVar
# =========================================================================


class TestStreamVar:
    def test_auto_size(self):
        v = StreamVar(name="speed", address=0xC002, c2000_type=C2000Type.FLOAT32)
        assert v.size_bytes == 4

    def test_explicit_size(self):
        v = StreamVar(name="x", address=0xC002, c2000_type=C2000Type.INT16, size_bytes=2)
        assert v.size_bytes == 2

    def test_iq24_size(self):
        v = StreamVar(name="current", address=0xC010, c2000_type=C2000Type.IQ24)
        assert v.size_bytes == 4


# =========================================================================
# VarStream
# =========================================================================


def _make_memory(values: dict[int, bytes]):
    """Create a mock memory reader from address -> bytes."""
    def reader(address: int, size: int) -> bytes | None:
        return values.get(address)
    return reader


class TestVarStream:
    def test_read_once(self):
        mem = _make_memory({
            0xC002: struct.pack("<f", 1500.0),
            0xC004: struct.pack("<f", 1498.5),
        })
        vs = VarStream(mem, [
            StreamVar("speedRef", 0xC002, C2000Type.FLOAT32),
            StreamVar("speedFbk", 0xC004, C2000Type.FLOAT32),
        ])
        result = vs.read_once()
        assert result["speedRef"] == pytest.approx(1500.0)
        assert result["speedFbk"] == pytest.approx(1498.5)

    def test_read_once_iq24(self):
        raw = int(0.95 * (1 << 24))
        mem = _make_memory({
            0xC010: struct.pack("<i", raw),
        })
        vs = VarStream(mem, [
            StreamVar("dutyCycle", 0xC010, C2000Type.IQ24),
        ])
        result = vs.read_once()
        assert result["dutyCycle"] == pytest.approx(0.95, rel=1e-6)

    def test_read_once_missing(self):
        """Variables with failed reads should be None."""
        mem = _make_memory({})
        vs = VarStream(mem, [
            StreamVar("speed", 0xC002, C2000Type.FLOAT32),
        ])
        result = vs.read_once()
        assert result["speed"] is None

    def test_stream_jsonl(self):
        counter = [0]

        def counting_reader(addr, size):
            counter[0] += 1
            return struct.pack("<f", 1500.0 + counter[0])

        vs = VarStream(counting_reader, [
            StreamVar("speed", 0xC002, C2000Type.FLOAT32),
        ], interval_ms=1)

        buf = io.StringIO()
        samples = vs.stream_jsonl(buf, count=3)
        assert samples == 3

        buf.seek(0)
        lines = buf.read().strip().split("\n")
        assert len(lines) == 3

        for line in lines:
            record = json.loads(line)
            assert "ts" in record
            assert "speed" in record
            assert isinstance(record["ts"], float)

    def test_stream_jsonl_format(self):
        mem = _make_memory({
            0xC002: struct.pack("<f", 42.0),
        })
        vs = VarStream(mem, [
            StreamVar("val", 0xC002, C2000Type.FLOAT32),
        ], interval_ms=1)

        buf = io.StringIO()
        vs.stream_jsonl(buf, count=1)
        buf.seek(0)
        record = json.loads(buf.readline())
        assert record["val"] == pytest.approx(42.0)

    def test_read_batch(self):
        call = [0]

        def reader(addr, size):
            call[0] += 1
            return struct.pack("<H", call[0] * 100)

        vs = VarStream(reader, [
            StreamVar("counter", 0xD000, C2000Type.UINT16),
        ], interval_ms=1)

        batch = vs.read_batch(3)
        assert len(batch) == 3
        assert batch[0]["counter"] == 100
        assert batch[1]["counter"] == 200
        assert batch[2]["counter"] == 300

    def test_multiple_variables(self):
        mem = _make_memory({
            0xC002: struct.pack("<f", 1500.0),
            0xC004: struct.pack("<h", 42),
            0xC005: struct.pack("<I", 1000000),
        })
        vs = VarStream(mem, [
            StreamVar("speed", 0xC002, C2000Type.FLOAT32),
            StreamVar("state", 0xC004, C2000Type.INT16),
            StreamVar("ticks", 0xC005, C2000Type.UINT32),
        ])
        result = vs.read_once()
        assert result["speed"] == pytest.approx(1500.0)
        assert result["state"] == 42
        assert result["ticks"] == 1000000
