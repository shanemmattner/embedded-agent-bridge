"""Tests for C2000 CLI commands (Phase 8)."""

from __future__ import annotations

import json
import math
import struct
import tempfile
from pathlib import Path
from unittest.mock import patch

import pytest

from eab.cli.c2000 import (
    cmd_c2000_telemetry_decode,
    cmd_c2000_trace_export,
    cmd_dlog_capture,
    cmd_erad_status,
    cmd_reg_read,
    cmd_stream_vars,
)


# ---------------------------------------------------------------------------
# Shared helper — build a valid 50-byte telemetry packet
# ---------------------------------------------------------------------------


def _telemetry_packet(
    *,
    pos_ref: float = 0.0,
    theta: float = 0.0,
    sys_state: int = 2,
    fault_code: int = 0,
    isr_count: int = 0,
) -> bytes:
    """Return a fully-valid 50-byte C2000 telemetry packet."""
    SYNC = 0xBB66

    def f32w(v: float) -> tuple[int, int]:
        return struct.unpack("<HH", struct.pack("<f", v))  # type: ignore[return-value]

    def u32w(v: int) -> tuple[int, int]:
        return v & 0xFFFF, (v >> 16) & 0xFFFF

    w1, w2 = f32w(pos_ref)
    w3, w4 = f32w(theta)
    w13, w14 = u32w(isr_count)

    words = [
        SYNC, w1, w2, w3, w4, 0, 0, 0, 0, 0, 0,
        sys_state, fault_code, w13, w14,
        0, 0, 0, 0, 0, 0, 0, 0, 0, 0,
    ]
    xor = 0
    for w in words[1:24]:
        xor ^= w
    words[24] = xor
    return struct.pack("<25H", *words)


# =========================================================================
# reg-read
# =========================================================================


class TestRegRead:
    def test_list_groups(self):
        rc = cmd_reg_read(chip="f28003x", json_mode=True)
        assert rc == 0

    def test_read_register(self):
        rc = cmd_reg_read(chip="f28003x", register="NMIFLG", json_mode=True)
        assert rc == 0

    def test_read_group(self):
        rc = cmd_reg_read(chip="f28003x", group="fault_registers", json_mode=True)
        assert rc == 0

    def test_unknown_chip(self):
        rc = cmd_reg_read(chip="nonexistent_chip", json_mode=True)
        assert rc == 2

    def test_unknown_register(self):
        rc = cmd_reg_read(chip="f28003x", register="DOESNOTEXIST", json_mode=True)
        assert rc == 2

    def test_unknown_group(self):
        rc = cmd_reg_read(chip="f28003x", group="nonexistent_group", json_mode=True)
        assert rc == 2


# =========================================================================
# erad-status
# =========================================================================


class TestEradStatus:
    def test_erad_status(self):
        rc = cmd_erad_status(chip="f28003x", json_mode=True)
        assert rc == 0

    def test_erad_status_unknown_chip(self):
        rc = cmd_erad_status(chip="nonexistent", json_mode=True)
        assert rc == 2


# =========================================================================
# stream-vars
# =========================================================================


class TestStreamVars:
    def test_valid_var_spec(self):
        rc = cmd_stream_vars(
            map_file="test.map",
            var_specs=["speedRef:0xC100:float32"],
            json_mode=True,
        )
        assert rc == 0

    def test_multiple_vars(self):
        rc = cmd_stream_vars(
            map_file="test.map",
            var_specs=[
                "speedRef:0xC100:float32",
                "speedFbk:0xC102:float32",
                "iqRef:0xC104:iq24",
            ],
            json_mode=True,
        )
        assert rc == 0

    def test_invalid_var_spec_format(self):
        rc = cmd_stream_vars(
            map_file="test.map",
            var_specs=["bad_format"],
            json_mode=True,
        )
        assert rc == 2

    def test_invalid_address(self):
        rc = cmd_stream_vars(
            map_file="test.map",
            var_specs=["name:notanumber:float32"],
            json_mode=True,
        )
        assert rc == 2

    def test_invalid_type(self):
        rc = cmd_stream_vars(
            map_file="test.map",
            var_specs=["name:0xC100:badtype"],
            json_mode=True,
        )
        assert rc == 2


# =========================================================================
# dlog-capture
# =========================================================================


class TestDlogCapture:
    def test_valid_buffer_spec(self):
        rc = cmd_dlog_capture(
            buffer_specs=["dBuff1:0xC100"],
            json_mode=True,
        )
        assert rc == 0

    def test_multiple_buffers(self):
        rc = cmd_dlog_capture(
            buffer_specs=["dBuff1:0xC100", "dBuff2:0xC200"],
            json_mode=True,
        )
        assert rc == 0

    def test_invalid_buffer_spec(self):
        rc = cmd_dlog_capture(
            buffer_specs=["bad_format"],
            json_mode=True,
        )
        assert rc == 2

    def test_invalid_address(self):
        rc = cmd_dlog_capture(
            buffer_specs=["dBuff1:notanumber"],
            json_mode=True,
        )
        assert rc == 2


# =========================================================================
# c2000-trace-export
# =========================================================================


class TestC2000TraceExport:
    def test_empty_export(self, tmp_path):
        output = tmp_path / "trace.json"
        rc = cmd_c2000_trace_export(
            output_file=str(output),
            json_mode=True,
        )
        assert rc == 0
        assert output.exists()
        with open(output) as f:
            trace = json.load(f)
        assert "traceEvents" in trace

    def test_export_with_dlog(self, tmp_path):
        # Create a DLOG data file
        dlog_file = tmp_path / "dlog.json"
        dlog_file.write_text(json.dumps({
            "buffers": {"dBuff1": [1.0, 2.0, 3.0]},
        }))

        output = tmp_path / "trace.json"
        rc = cmd_c2000_trace_export(
            output_file=str(output),
            dlog_data=str(dlog_file),
            json_mode=True,
        )
        assert rc == 0
        with open(output) as f:
            trace = json.load(f)
        counters = [e for e in trace["traceEvents"] if e.get("ph") == "C"]
        assert len(counters) == 3

    def test_export_with_erad(self, tmp_path):
        erad_file = tmp_path / "erad.json"
        erad_file.write_text(json.dumps({
            "spans": [
                {"name": "motor_isr", "start_us": 0, "duration_us": 25.5, "cpu_cycles": 3060},
            ],
        }))

        output = tmp_path / "trace.json"
        rc = cmd_c2000_trace_export(
            output_file=str(output),
            erad_data=str(erad_file),
            json_mode=True,
        )
        assert rc == 0
        with open(output) as f:
            trace = json.load(f)
        spans = [e for e in trace["traceEvents"] if e.get("ph") == "X"]
        assert len(spans) == 1

    def test_export_with_log(self, tmp_path):
        log_file = tmp_path / "serial.log"
        log_file.write_text("Boot complete\nISR started\n")

        output = tmp_path / "trace.json"
        rc = cmd_c2000_trace_export(
            output_file=str(output),
            log_file=str(log_file),
            json_mode=True,
        )
        assert rc == 0
        with open(output) as f:
            trace = json.load(f)
        instants = [e for e in trace["traceEvents"] if e.get("ph") == "i"]
        assert len(instants) == 2

    def test_export_combined(self, tmp_path):
        erad_file = tmp_path / "erad.json"
        erad_file.write_text(json.dumps({
            "spans": [{"name": "f", "duration_us": 10}],
        }))
        dlog_file = tmp_path / "dlog.json"
        dlog_file.write_text(json.dumps({
            "buffers": {"b": [1.0]},
        }))
        log_file = tmp_path / "log.txt"
        log_file.write_text("msg\n")

        output = tmp_path / "trace.json"
        rc = cmd_c2000_trace_export(
            output_file=str(output),
            erad_data=str(erad_file),
            dlog_data=str(dlog_file),
            log_file=str(log_file),
            json_mode=True,
        )
        assert rc == 0

    def test_missing_erad_file(self, tmp_path):
        output = tmp_path / "trace.json"
        rc = cmd_c2000_trace_export(
            output_file=str(output),
            erad_data="/nonexistent/erad.json",
            json_mode=True,
        )
        assert rc == 2

    def test_missing_dlog_file(self, tmp_path):
        output = tmp_path / "trace.json"
        rc = cmd_c2000_trace_export(
            output_file=str(output),
            dlog_data="/nonexistent/dlog.json",
            json_mode=True,
        )
        assert rc == 2

    def test_missing_log_file(self, tmp_path):
        output = tmp_path / "trace.json"
        rc = cmd_c2000_trace_export(
            output_file=str(output),
            log_file="/nonexistent/log.txt",
            json_mode=True,
        )
        assert rc == 2


# =========================================================================
# c2000-telemetry-decode
# =========================================================================


class TestC2000TelemetryDecode:
    # ------------------------------------------------------------------
    # Error paths
    # ------------------------------------------------------------------

    def test_missing_file(self):
        rc = cmd_c2000_telemetry_decode(
            input_path="/nonexistent/data.bin",
            json_mode=True,
        )
        assert rc == 2

    def test_invalid_format(self, tmp_path):
        data_file = tmp_path / "data.bin"
        data_file.write_bytes(b"")
        rc = cmd_c2000_telemetry_decode(
            input_path=str(data_file),
            format="xml",
            json_mode=True,
        )
        assert rc == 2

    # ------------------------------------------------------------------
    # Empty / no packets
    # ------------------------------------------------------------------

    def test_empty_file_table(self, tmp_path, capsys):
        data_file = tmp_path / "data.bin"
        data_file.write_bytes(b"")
        rc = cmd_c2000_telemetry_decode(
            input_path=str(data_file),
            format="table",
        )
        assert rc == 0
        out = capsys.readouterr().out
        # Header should still be printed.
        assert "t(s)" in out

    def test_empty_file_summary(self, tmp_path, capsys):
        data_file = tmp_path / "data.bin"
        data_file.write_bytes(b"")
        rc = cmd_c2000_telemetry_decode(
            input_path=str(data_file),
            summary_only=True,
        )
        assert rc == 0
        out = capsys.readouterr().out
        summary = json.loads(out)
        assert summary["total_packets"] == 0
        assert summary["checksum_failures"] == 0

    # ------------------------------------------------------------------
    # Table format
    # ------------------------------------------------------------------

    def test_table_single_packet(self, tmp_path, capsys):
        pkt = _telemetry_packet(
            pos_ref=math.pi / 4, theta=0.1, sys_state=2, isr_count=10_000
        )
        data_file = tmp_path / "data.bin"
        data_file.write_bytes(pkt)
        rc = cmd_c2000_telemetry_decode(
            input_path=str(data_file),
            format="table",
        )
        assert rc == 0
        out = capsys.readouterr().out
        assert "RUN" in out

    def test_table_multiple_packets(self, tmp_path, capsys):
        p1 = _telemetry_packet(isr_count=0, sys_state=1)
        p2 = _telemetry_packet(isr_count=5_000, sys_state=2)
        p3 = _telemetry_packet(isr_count=10_000, sys_state=2)
        data_file = tmp_path / "data.bin"
        data_file.write_bytes(p1 + p2 + p3)
        rc = cmd_c2000_telemetry_decode(
            input_path=str(data_file),
            format="table",
        )
        assert rc == 0
        out = capsys.readouterr().out
        # t=0.0, t=0.5, t=1.0 should appear.
        assert "0.000" in out
        assert "0.500" in out
        assert "1.000" in out

    def test_table_max_packets(self, tmp_path, capsys):
        pkts = b"".join(
            _telemetry_packet(isr_count=i * 100) for i in range(10)
        )
        data_file = tmp_path / "data.bin"
        data_file.write_bytes(pkts)
        rc = cmd_c2000_telemetry_decode(
            input_path=str(data_file),
            format="table",
            max_packets=3,
        )
        assert rc == 0
        out = capsys.readouterr().out
        # Only 3 data rows: lines containing "|" that are not the header.
        data_rows = [
            line for line in out.splitlines()
            if "|" in line and "t(s)" not in line
        ]
        assert len(data_rows) == 3

    # ------------------------------------------------------------------
    # JSON format
    # ------------------------------------------------------------------

    def test_json_format_structure(self, tmp_path, capsys):
        pkt = _telemetry_packet(sys_state=2, fault_code=0)
        data_file = tmp_path / "data.bin"
        data_file.write_bytes(pkt)
        rc = cmd_c2000_telemetry_decode(
            input_path=str(data_file),
            format="json",
        )
        assert rc == 0
        out = capsys.readouterr().out
        obj = json.loads(out)
        assert "packets" in obj
        assert "summary" in obj
        assert len(obj["packets"]) == 1
        p = obj["packets"][0]
        assert p["sys_state"] == "RUN"

    def test_json_format_two_packets(self, tmp_path, capsys):
        data = _telemetry_packet(isr_count=0) + _telemetry_packet(isr_count=1000)
        data_file = tmp_path / "data.bin"
        data_file.write_bytes(data)
        rc = cmd_c2000_telemetry_decode(
            input_path=str(data_file),
            format="json",
        )
        assert rc == 0
        obj = json.loads(capsys.readouterr().out)
        assert len(obj["packets"]) == 2
        assert obj["summary"]["total_packets"] == 2

    # ------------------------------------------------------------------
    # CSV format
    # ------------------------------------------------------------------

    def test_csv_format_has_header(self, tmp_path, capsys):
        data_file = tmp_path / "data.bin"
        data_file.write_bytes(_telemetry_packet())
        rc = cmd_c2000_telemetry_decode(
            input_path=str(data_file),
            format="csv",
        )
        assert rc == 0
        out = capsys.readouterr().out
        first_line = out.splitlines()[0]
        assert "pos_ref" in first_line
        assert "theta" in first_line
        assert "sys_state" in first_line

    def test_csv_format_data_row(self, tmp_path, capsys):
        pkt = _telemetry_packet(sys_state=4, fault_code=0, isr_count=42)
        data_file = tmp_path / "data.bin"
        data_file.write_bytes(pkt)
        rc = cmd_c2000_telemetry_decode(
            input_path=str(data_file),
            format="csv",
        )
        assert rc == 0
        out = capsys.readouterr().out
        lines = out.strip().splitlines()
        assert len(lines) == 2  # header + 1 data row
        assert "STOP" in lines[1]
        assert "42" in lines[1]

    # ------------------------------------------------------------------
    # Summary-only mode
    # ------------------------------------------------------------------

    def test_summary_only_keys(self, tmp_path, capsys):
        data = (
            _telemetry_packet(isr_count=0, sys_state=2)
            + _telemetry_packet(isr_count=10_000, sys_state=2)
        )
        data_file = tmp_path / "data.bin"
        data_file.write_bytes(data)
        rc = cmd_c2000_telemetry_decode(
            input_path=str(data_file),
            summary_only=True,
        )
        assert rc == 0
        summary = json.loads(capsys.readouterr().out)
        assert summary["total_packets"] == 2
        assert abs(summary["duration_s"] - 1.0) < 1e-4
        assert summary["final_state"] == "RUN"
        assert "faults" in summary
        assert "checksum_failures" in summary

    def test_summary_only_with_fault(self, tmp_path, capsys):
        pkt = _telemetry_packet(sys_state=3, fault_code=0x000A)
        data_file = tmp_path / "data.bin"
        data_file.write_bytes(pkt)
        rc = cmd_c2000_telemetry_decode(
            input_path=str(data_file),
            summary_only=True,
        )
        assert rc == 0
        summary = json.loads(capsys.readouterr().out)
        assert "0x000A" in summary["faults"]

    # ------------------------------------------------------------------
    # Output file
    # ------------------------------------------------------------------

    def test_output_to_file_table(self, tmp_path):
        pkt = _telemetry_packet()
        data_file = tmp_path / "data.bin"
        data_file.write_bytes(pkt)
        out_file = tmp_path / "result.txt"
        rc = cmd_c2000_telemetry_decode(
            input_path=str(data_file),
            output=str(out_file),
            format="table",
        )
        assert rc == 0
        assert out_file.exists()
        assert "t(s)" in out_file.read_text()

    def test_output_to_file_json(self, tmp_path):
        pkt = _telemetry_packet()
        data_file = tmp_path / "data.bin"
        data_file.write_bytes(pkt)
        out_file = tmp_path / "result.json"
        rc = cmd_c2000_telemetry_decode(
            input_path=str(data_file),
            output=str(out_file),
            format="json",
        )
        assert rc == 0
        obj = json.loads(out_file.read_text())
        assert "packets" in obj

    def test_output_to_file_csv(self, tmp_path):
        pkt = _telemetry_packet()
        data_file = tmp_path / "data.bin"
        data_file.write_bytes(pkt)
        out_file = tmp_path / "result.csv"
        rc = cmd_c2000_telemetry_decode(
            input_path=str(data_file),
            output=str(out_file),
            format="csv",
        )
        assert rc == 0
        assert "pos_ref" in out_file.read_text()

    # ------------------------------------------------------------------
    # Garbage-in-stream resilience
    # ------------------------------------------------------------------

    def test_garbage_prefix_decoded(self, tmp_path, capsys):
        garbage = bytes(range(256))  # 256 bytes of garbage
        pkt = _telemetry_packet(sys_state=2)
        data_file = tmp_path / "data.bin"
        data_file.write_bytes(garbage + pkt)
        rc = cmd_c2000_telemetry_decode(
            input_path=str(data_file),
            format="json",
        )
        assert rc == 0
        obj = json.loads(capsys.readouterr().out)
        assert obj["summary"]["total_packets"] == 1
