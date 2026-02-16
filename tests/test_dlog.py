"""Tests for DLOG buffer capture (Phase 5)."""

from __future__ import annotations

import csv
import io
import json
import struct
import time
from unittest.mock import MagicMock

import pytest

from eab.analyzers.dlog import (
    DLOG_STATUS_COMPLETE,
    DLOG_STATUS_IDLE,
    DLOG_STATUS_TRIGGERED,
    DLOG_STATUS_WAIT,
    DLOGCapture,
    DLOGResult,
)


# =========================================================================
# Test fixtures
# =========================================================================

BUFFERS = {"dBuff1": 0xC100, "dBuff2": 0xC200}
STATUS_ADDR = 0xC000
SIZE_ADDR = 0xC004
TRIGGER_ADDR = 0xC006
BUFFER_SIZE = 4  # Small for testing


def make_float_bytes(values: list[float]) -> bytes:
    """Pack a list of floats as little-endian float32."""
    return b"".join(struct.pack("<f", v) for v in values)


def make_uint16_bytes(value: int) -> bytes:
    """Pack a uint16 as little-endian bytes."""
    return struct.pack("<H", value)


def make_memory(regions: dict[int, bytes]):
    """Create a mock memory_reader from address→bytes mapping."""
    def reader(address: int, size: int):
        if address in regions:
            data = regions[address]
            return data[:size] if len(data) >= size else None
        return None
    return reader


def make_capture(
    status: int = DLOG_STATUS_COMPLETE,
    buf1_values: list[float] | None = None,
    buf2_values: list[float] | None = None,
    memory_writer=None,
    buffer_size: int = BUFFER_SIZE,
):
    """Create a DLOGCapture with mock memory."""
    if buf1_values is None:
        buf1_values = [1.0, 2.0, 3.0, 4.0]
    if buf2_values is None:
        buf2_values = [10.0, 20.0, 30.0, 40.0]

    regions = {
        STATUS_ADDR: make_uint16_bytes(status),
        SIZE_ADDR: make_uint16_bytes(buffer_size),
        0xC100: make_float_bytes(buf1_values),
        0xC200: make_float_bytes(buf2_values),
    }
    reader = make_memory(regions)

    return DLOGCapture(
        memory_reader=reader,
        buffers=BUFFERS,
        status_addr=STATUS_ADDR,
        size_addr=SIZE_ADDR,
        buffer_size=buffer_size,
        memory_writer=memory_writer,
        trigger_addr=TRIGGER_ADDR,
    )


# =========================================================================
# Status reading
# =========================================================================


class TestReadStatus:
    def test_read_idle(self):
        cap = make_capture(status=DLOG_STATUS_IDLE)
        assert cap.read_status() == DLOG_STATUS_IDLE

    def test_read_wait(self):
        cap = make_capture(status=DLOG_STATUS_WAIT)
        assert cap.read_status() == DLOG_STATUS_WAIT

    def test_read_triggered(self):
        cap = make_capture(status=DLOG_STATUS_TRIGGERED)
        assert cap.read_status() == DLOG_STATUS_TRIGGERED

    def test_read_complete(self):
        cap = make_capture(status=DLOG_STATUS_COMPLETE)
        assert cap.read_status() == DLOG_STATUS_COMPLETE

    def test_read_status_failure(self):
        reader = lambda addr, size: None
        cap = DLOGCapture(
            memory_reader=reader,
            buffers=BUFFERS,
            status_addr=STATUS_ADDR,
            size_addr=SIZE_ADDR,
        )
        assert cap.read_status() is None


class TestIsComplete:
    def test_complete(self):
        cap = make_capture(status=DLOG_STATUS_COMPLETE)
        assert cap.is_complete() is True

    def test_not_complete(self):
        cap = make_capture(status=DLOG_STATUS_WAIT)
        assert cap.is_complete() is False

    def test_read_failure_not_complete(self):
        reader = lambda addr, size: None
        cap = DLOGCapture(
            memory_reader=reader,
            buffers=BUFFERS,
            status_addr=STATUS_ADDR,
            size_addr=SIZE_ADDR,
        )
        assert cap.is_complete() is False


# =========================================================================
# Size reading
# =========================================================================


class TestReadSize:
    def test_read_size(self):
        cap = make_capture(buffer_size=200)
        assert cap.read_size() == 200

    def test_read_size_failure(self):
        reader = lambda addr, size: None
        cap = DLOGCapture(
            memory_reader=reader,
            buffers=BUFFERS,
            status_addr=STATUS_ADDR,
            size_addr=SIZE_ADDR,
        )
        assert cap.read_size() is None


# =========================================================================
# Trigger
# =========================================================================


class TestTrigger:
    def test_trigger_writes_zero(self):
        writer = MagicMock(return_value=True)
        cap = make_capture(memory_writer=writer)
        assert cap.trigger() is True
        writer.assert_called_once_with(TRIGGER_ADDR, struct.pack("<H", 0))

    def test_trigger_no_writer(self):
        cap = make_capture()
        assert cap.trigger() is False

    def test_trigger_no_trigger_addr(self):
        writer = MagicMock(return_value=True)
        cap = DLOGCapture(
            memory_reader=lambda a, s: None,
            buffers=BUFFERS,
            status_addr=STATUS_ADDR,
            size_addr=SIZE_ADDR,
            memory_writer=writer,
            trigger_addr=None,
        )
        assert cap.trigger() is False

    def test_trigger_write_failure(self):
        writer = MagicMock(return_value=False)
        cap = make_capture(memory_writer=writer)
        assert cap.trigger() is False


# =========================================================================
# Buffer reading
# =========================================================================


class TestReadBuffer:
    def test_read_single_buffer(self):
        values = [1.5, 2.5, 3.5, 4.5]
        cap = make_capture(buf1_values=values)
        result = cap.read_buffer(0xC100, 4)
        assert result is not None
        for i, v in enumerate(values):
            assert abs(result[i] - v) < 1e-6

    def test_read_buffer_failure(self):
        reader = lambda addr, size: None
        cap = DLOGCapture(
            memory_reader=reader,
            buffers=BUFFERS,
            status_addr=STATUS_ADDR,
            size_addr=SIZE_ADDR,
        )
        assert cap.read_buffer(0xC100, 4) is None

    def test_read_buffer_short_data(self):
        """Buffer read with insufficient data returns None."""
        reader = lambda addr, size: b"\x00\x00"  # Only 2 bytes, need 16
        cap = DLOGCapture(
            memory_reader=reader,
            buffers=BUFFERS,
            status_addr=STATUS_ADDR,
            size_addr=SIZE_ADDR,
        )
        assert cap.read_buffer(0xC100, 4) is None


class TestReadBuffers:
    def test_read_all_buffers(self):
        buf1 = [1.0, 2.0, 3.0, 4.0]
        buf2 = [10.0, 20.0, 30.0, 40.0]
        cap = make_capture(buf1_values=buf1, buf2_values=buf2)
        result = cap.read_buffers()

        assert result is not None
        assert result.status == DLOG_STATUS_COMPLETE
        assert result.buffer_size == BUFFER_SIZE
        assert len(result.buffers) == 2

        for i, v in enumerate(buf1):
            assert abs(result.buffers["dBuff1"][i] - v) < 1e-6
        for i, v in enumerate(buf2):
            assert abs(result.buffers["dBuff2"][i] - v) < 1e-6

    def test_read_buffers_status_failure(self):
        reader = lambda addr, size: None
        cap = DLOGCapture(
            memory_reader=reader,
            buffers=BUFFERS,
            status_addr=STATUS_ADDR,
            size_addr=SIZE_ADDR,
        )
        assert cap.read_buffers() is None

    def test_read_buffers_partial_failure(self):
        """If one buffer read fails, entire read_buffers returns None."""
        regions = {
            STATUS_ADDR: make_uint16_bytes(DLOG_STATUS_COMPLETE),
            0xC100: make_float_bytes([1.0, 2.0, 3.0, 4.0]),
            # 0xC200 missing — will cause read failure
        }
        reader = make_memory(regions)
        cap = DLOGCapture(
            memory_reader=reader,
            buffers=BUFFERS,
            status_addr=STATUS_ADDR,
            size_addr=SIZE_ADDR,
            buffer_size=BUFFER_SIZE,
        )
        assert cap.read_buffers() is None

    def test_read_buffers_has_timestamp(self):
        cap = make_capture()
        before = time.time()
        result = cap.read_buffers()
        after = time.time()
        assert result is not None
        assert before <= result.timestamp <= after


# =========================================================================
# Wait and read
# =========================================================================


class TestWaitAndRead:
    def test_already_complete(self):
        cap = make_capture(status=DLOG_STATUS_COMPLETE)
        result = cap.wait_and_read(timeout_s=1.0, poll_interval_s=0.01)
        assert result is not None
        assert result.status == DLOG_STATUS_COMPLETE

    def test_timeout_returns_none(self):
        cap = make_capture(status=DLOG_STATUS_WAIT)
        result = cap.wait_and_read(timeout_s=0.05, poll_interval_s=0.01)
        assert result is None

    def test_becomes_complete(self):
        """Status transitions from WAIT to COMPLETE during polling."""
        call_count = [0]
        regions_wait = {
            STATUS_ADDR: make_uint16_bytes(DLOG_STATUS_WAIT),
            SIZE_ADDR: make_uint16_bytes(BUFFER_SIZE),
            0xC100: make_float_bytes([1.0, 2.0, 3.0, 4.0]),
            0xC200: make_float_bytes([10.0, 20.0, 30.0, 40.0]),
        }
        regions_complete = {
            STATUS_ADDR: make_uint16_bytes(DLOG_STATUS_COMPLETE),
            SIZE_ADDR: make_uint16_bytes(BUFFER_SIZE),
            0xC100: make_float_bytes([1.0, 2.0, 3.0, 4.0]),
            0xC200: make_float_bytes([10.0, 20.0, 30.0, 40.0]),
        }

        def reader(addr, size):
            call_count[0] += 1
            # After a few reads, switch to complete
            if call_count[0] > 3:
                return make_memory(regions_complete)(addr, size)
            return make_memory(regions_wait)(addr, size)

        cap = DLOGCapture(
            memory_reader=reader,
            buffers=BUFFERS,
            status_addr=STATUS_ADDR,
            size_addr=SIZE_ADDR,
            buffer_size=BUFFER_SIZE,
        )
        result = cap.wait_and_read(timeout_s=2.0, poll_interval_s=0.01)
        assert result is not None
        assert result.status == DLOG_STATUS_COMPLETE


# =========================================================================
# Trigger and read
# =========================================================================


class TestTriggerAndRead:
    def test_trigger_and_read_success(self):
        writer = MagicMock(return_value=True)
        cap = make_capture(
            status=DLOG_STATUS_COMPLETE,
            memory_writer=writer,
        )
        result = cap.trigger_and_read(timeout_s=1.0, poll_interval_s=0.01)
        assert result is not None
        writer.assert_called_once()

    def test_trigger_failure_returns_none(self):
        writer = MagicMock(return_value=False)
        cap = make_capture(memory_writer=writer)
        result = cap.trigger_and_read(timeout_s=0.1, poll_interval_s=0.01)
        assert result is None

    def test_trigger_and_timeout(self):
        writer = MagicMock(return_value=True)
        cap = make_capture(
            status=DLOG_STATUS_WAIT,
            memory_writer=writer,
        )
        result = cap.trigger_and_read(timeout_s=0.05, poll_interval_s=0.01)
        assert result is None


# =========================================================================
# DLOGResult output formats
# =========================================================================


class TestDLOGResultCSV:
    def test_csv_output(self):
        result = DLOGResult(
            buffers={"dBuff1": [1.0, 2.0], "dBuff2": [10.0, 20.0]},
            buffer_size=2,
            status=DLOG_STATUS_COMPLETE,
        )
        output = io.StringIO()
        result.to_csv(output)
        output.seek(0)
        reader = csv.reader(output)
        header = next(reader)
        assert header == ["sample", "dBuff1", "dBuff2"]
        row0 = next(reader)
        assert row0[0] == "0"
        assert float(row0[1]) == 1.0
        assert float(row0[2]) == 10.0
        row1 = next(reader)
        assert row1[0] == "1"
        assert float(row1[1]) == 2.0
        assert float(row1[2]) == 20.0

    def test_csv_empty_buffers(self):
        result = DLOGResult(buffers={}, buffer_size=0, status=DLOG_STATUS_IDLE)
        output = io.StringIO()
        result.to_csv(output)
        output.seek(0)
        content = output.read()
        assert "sample" in content


class TestDLOGResultJSON:
    def test_json_output(self):
        result = DLOGResult(
            buffers={"dBuff1": [1.0, 2.0]},
            buffer_size=2,
            status=DLOG_STATUS_COMPLETE,
            timestamp=1234567890.0,
        )
        j = result.to_json()
        assert j["status"] == DLOG_STATUS_COMPLETE
        assert j["buffer_size"] == 2
        assert j["timestamp"] == 1234567890.0
        assert j["buffers"]["dBuff1"] == [1.0, 2.0]

    def test_json_serializable(self):
        result = DLOGResult(
            buffers={"dBuff1": [1.0]},
            buffer_size=1,
            status=DLOG_STATUS_COMPLETE,
        )
        # Must not raise
        json.dumps(result.to_json())


class TestDLOGResultJSONL:
    def test_jsonl_output(self):
        result = DLOGResult(
            buffers={"dBuff1": [1.0, 2.0], "dBuff2": [10.0, 20.0]},
            buffer_size=2,
            status=DLOG_STATUS_COMPLETE,
        )
        output = io.StringIO()
        result.to_jsonl(output)
        output.seek(0)
        lines = output.readlines()
        assert len(lines) == 2

        record0 = json.loads(lines[0])
        assert record0["sample"] == 0
        assert record0["dBuff1"] == 1.0
        assert record0["dBuff2"] == 10.0

        record1 = json.loads(lines[1])
        assert record1["sample"] == 1
        assert record1["dBuff1"] == 2.0
        assert record1["dBuff2"] == 20.0


# =========================================================================
# Edge cases
# =========================================================================


class TestEdgeCases:
    def test_single_sample_buffer(self):
        cap = make_capture(
            buf1_values=[42.0],
            buf2_values=[99.0],
            buffer_size=1,
        )
        result = cap.read_buffers()
        assert result is not None
        assert result.buffers["dBuff1"] == [42.0]
        assert result.buffers["dBuff2"] == [99.0]

    def test_negative_float_values(self):
        cap = make_capture(
            buf1_values=[-1.5, -2.5, -3.5, -4.5],
            buf2_values=[0.0, 0.0, 0.0, 0.0],
        )
        result = cap.read_buffers()
        assert result is not None
        assert abs(result.buffers["dBuff1"][0] - (-1.5)) < 1e-6

    def test_large_buffer_size(self):
        """Verify reading works with larger buffer sizes."""
        size = 100
        values = [float(i) for i in range(size)]
        regions = {
            STATUS_ADDR: make_uint16_bytes(DLOG_STATUS_COMPLETE),
            SIZE_ADDR: make_uint16_bytes(size),
            0xC100: make_float_bytes(values),
            0xC200: make_float_bytes(values),
        }
        reader = make_memory(regions)
        cap = DLOGCapture(
            memory_reader=reader,
            buffers=BUFFERS,
            status_addr=STATUS_ADDR,
            size_addr=SIZE_ADDR,
            buffer_size=size,
        )
        result = cap.read_buffers()
        assert result is not None
        assert len(result.buffers["dBuff1"]) == size
        assert abs(result.buffers["dBuff1"][50] - 50.0) < 1e-6
