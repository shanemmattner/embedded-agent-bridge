"""Tests for C2000 CLI commands (Phase 8)."""

from __future__ import annotations

import json
import tempfile
from pathlib import Path
from unittest.mock import patch

import pytest

from eab.cli.c2000 import (
    cmd_c2000_trace_export,
    cmd_dlog_capture,
    cmd_erad_status,
    cmd_reg_read,
    cmd_stream_vars,
)


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
