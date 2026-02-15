"""Tests for trace format detection and conversion."""

from __future__ import annotations

import json
import os
from pathlib import Path
from unittest.mock import patch, MagicMock

import pytest

from eab.cli.trace.formats import detect_trace_format
from eab.cli.trace.converters import export_systemview_to_perfetto, export_ctf_to_perfetto


class TestFormatDetection:
    """Test trace format auto-detection."""

    def test_detect_rttbin_by_extension(self, tmp_path):
        """Test detection of .rttbin files by extension."""
        test_file = tmp_path / "trace.rttbin"
        test_file.write_bytes(b"dummy data")
        
        assert detect_trace_format(test_file) == "rttbin"

    def test_detect_systemview_by_extension(self, tmp_path):
        """Test detection of .svdat files by extension."""
        test_file = tmp_path / "trace.svdat"
        test_file.write_bytes(b"dummy data")
        
        assert detect_trace_format(test_file) == "systemview"

    def test_detect_log_by_extension(self, tmp_path):
        """Test detection of .log files by extension."""
        test_file = tmp_path / "trace.log"
        test_file.write_text("log data")
        
        assert detect_trace_format(test_file) == "log"

    def test_detect_systemview_by_magic(self, tmp_path):
        """Test detection of SystemView files by magic bytes."""
        test_file = tmp_path / "trace.dat"
        # SystemView file with SEGGER signature
        test_file.write_bytes(b"SEGGER SystemView trace data...")
        
        assert detect_trace_format(test_file) == "systemview"

    def test_detect_ctf_by_magic(self, tmp_path):
        """Test detection of CTF files by magic bytes."""
        test_file = tmp_path / "trace.dat"
        # CTF magic: 0xC1FC1FC1 (little-endian)
        magic = (0xC1FC1FC1).to_bytes(4, byteorder="little")
        test_file.write_bytes(magic + b"dummy ctf data")
        
        assert detect_trace_format(test_file) == "ctf"

    def test_detect_ctf_by_metadata(self, tmp_path):
        """Test detection of CTF traces by metadata file."""
        trace_dir = tmp_path / "ctf_trace"
        trace_dir.mkdir()
        metadata = trace_dir / "metadata"
        metadata.write_text("/* CTF metadata */")
        
        assert detect_trace_format(trace_dir) == "ctf"

    def test_detect_zephyr_ctf_structure(self, tmp_path):
        """Test detection of Zephyr CTF directory structure."""
        trace_dir = tmp_path / "zephyr_trace"
        trace_dir.mkdir()
        channel_dir = trace_dir / "channel0_0"
        channel_dir.mkdir()
        metadata = trace_dir / "metadata"
        metadata.write_text("/* CTF metadata */")
        
        # Test detection from a file in channel directory
        test_file = channel_dir / "trace.ctf"
        test_file.write_bytes(b"dummy")
        
        assert detect_trace_format(test_file) == "ctf"

    def test_detect_default_to_rttbin(self, tmp_path):
        """Test default to rttbin for unknown formats."""
        test_file = tmp_path / "unknown.bin"
        test_file.write_bytes(b"unknown format data")
        
        assert detect_trace_format(test_file) == "rttbin"


class TestSystemViewConverter:
    """Test SystemView to Perfetto conversion."""

    def test_systemview_no_idf_path(self, tmp_path):
        """Test error when IDF_PATH is not set."""
        input_file = tmp_path / "trace.svdat"
        output_file = tmp_path / "output.json"
        input_file.write_bytes(b"dummy")
        
        # Clear IDF_PATH if set
        env_backup = os.environ.copy()
        try:
            os.environ.pop("IDF_PATH", None)
            
            with pytest.raises(RuntimeError, match="IDF_PATH environment variable not set"):
                export_systemview_to_perfetto(input_file, output_file)
        finally:
            os.environ.clear()
            os.environ.update(env_backup)

    def test_systemview_idf_path_invalid(self, tmp_path):
        """Test error when IDF_PATH points to invalid location."""
        input_file = tmp_path / "trace.svdat"
        output_file = tmp_path / "output.json"
        input_file.write_bytes(b"dummy")
        
        env_backup = os.environ.copy()
        try:
            os.environ["IDF_PATH"] = str(tmp_path / "fake_idf")
            
            with pytest.raises(RuntimeError, match="sysviewtrace_proc.py not found"):
                export_systemview_to_perfetto(input_file, output_file)
        finally:
            os.environ.clear()
            os.environ.update(env_backup)

    @patch("subprocess.run")
    @patch("shutil.which")
    def test_systemview_conversion_success(self, mock_which, mock_run, tmp_path):
        """Test successful SystemView conversion."""
        input_file = tmp_path / "trace.svdat"
        output_file = tmp_path / "output.json"
        input_file.write_bytes(b"dummy")
        
        # Mock IDF_PATH and tool
        idf_path = tmp_path / "esp-idf"
        tool_dir = idf_path / "tools" / "esp_app_trace"
        tool_dir.mkdir(parents=True)
        tool_file = tool_dir / "sysviewtrace_proc.py"
        tool_file.write_text("#!/usr/bin/env python3")
        
        # Mock subprocess result
        mock_which.return_value = "/usr/bin/python3"
        mock_run.return_value = MagicMock(returncode=0, stdout="", stderr="")
        
        # Create mock output file
        output_data = {"traceEvents": [{"name": "event1"}, {"name": "event2"}]}
        output_file.write_text(json.dumps(output_data))
        
        env_backup = os.environ.copy()
        try:
            os.environ["IDF_PATH"] = str(idf_path)
            
            result = export_systemview_to_perfetto(input_file, output_file)
            
            assert result["event_count"] == 2
            assert result["output_path"] == str(output_file)
            assert result["output_size_bytes"] > 0
        finally:
            os.environ.clear()
            os.environ.update(env_backup)


class TestCTFConverter:
    """Test CTF to Perfetto conversion."""

    def test_ctf_no_babeltrace(self, tmp_path):
        """Test error when babeltrace is not installed."""
        input_dir = tmp_path / "ctf_trace"
        input_dir.mkdir()
        output_file = tmp_path / "output.json"
        
        with patch("shutil.which", return_value=None):
            with pytest.raises(RuntimeError, match="babeltrace not found"):
                export_ctf_to_perfetto(input_dir, output_file)

    @patch("subprocess.run")
    @patch("shutil.which")
    def test_ctf_conversion_success(self, mock_which, mock_run, tmp_path):
        """Test successful CTF conversion."""
        input_dir = tmp_path / "ctf_trace"
        input_dir.mkdir()
        output_file = tmp_path / "output.json"
        
        # Mock babeltrace output
        babeltrace_output = """[00:00:00.123456789] (+0.000000000) kernel:sched_switch: { cpu_id = 0 }, { prev_comm = "swapper", next_comm = "task1" }
[00:00:00.234567890] (+0.111111101) kernel:irq_handler_entry: { cpu_id = 0 }, { irq = 42, name = "timer" }
"""
        
        mock_which.return_value = "/usr/bin/babeltrace"
        mock_run.return_value = MagicMock(
            returncode=0,
            stdout=babeltrace_output,
            stderr=""
        )
        
        result = export_ctf_to_perfetto(input_dir, output_file)
        
        assert result["event_count"] == 2
        assert result["output_path"] == str(output_file)
        assert result["output_size_bytes"] > 0
        
        # Verify output file structure
        with open(output_file, "r") as f:
            data = json.load(f)
            assert "traceEvents" in data
            assert "displayTimeUnit" in data
            assert len([e for e in data["traceEvents"] if e.get("ph") == "i"]) == 2

    @patch("subprocess.run")
    @patch("shutil.which")
    def test_ctf_conversion_failure(self, mock_which, mock_run, tmp_path):
        """Test CTF conversion failure."""
        input_dir = tmp_path / "ctf_trace"
        input_dir.mkdir()
        output_file = tmp_path / "output.json"
        
        mock_which.return_value = "/usr/bin/babeltrace"
        mock_run.return_value = MagicMock(
            returncode=1,
            stdout="",
            stderr="Error: invalid CTF trace"
        )
        
        with pytest.raises(Exception):
            export_ctf_to_perfetto(input_dir, output_file)

    @patch("subprocess.run")
    @patch("shutil.which")
    def test_ctf_conversion_timeout(self, mock_which, mock_run, tmp_path):
        """Test CTF conversion timeout."""
        input_dir = tmp_path / "ctf_trace"
        input_dir.mkdir()
        output_file = tmp_path / "output.json"
        
        mock_which.return_value = "/usr/bin/babeltrace"
        mock_run.side_effect = Exception("babeltrace conversion timed out after 60 seconds")
        
        with pytest.raises(Exception, match="timed out"):
            export_ctf_to_perfetto(input_dir, output_file)


class TestCTFParsing:
    """Test CTF babeltrace output parsing."""

    @patch("subprocess.run")
    @patch("shutil.which")
    def test_parse_various_field_types(self, mock_which, mock_run, tmp_path):
        """Test parsing of various CTF field types."""
        input_dir = tmp_path / "ctf_trace"
        input_dir.mkdir()
        output_file = tmp_path / "output.json"
        
        # Test with different field types
        babeltrace_output = """[00:00:01.000000000] (+0.000000000) kernel:test_event: { int_field = 123 }, { float_field = 45.67, str_field = "hello" }
"""
        
        mock_which.return_value = "/usr/bin/babeltrace"
        mock_run.return_value = MagicMock(
            returncode=0,
            stdout=babeltrace_output,
            stderr=""
        )
        
        result = export_ctf_to_perfetto(input_dir, output_file)
        
        with open(output_file, "r") as f:
            data = json.load(f)
            events = [e for e in data["traceEvents"] if e.get("ph") == "i"]
            assert len(events) == 1
            
            event = events[0]
            assert event["name"] == "test_event"
            assert event["cat"] == "kernel"
            assert "int_field" in event["args"]
            assert event["args"]["int_field"] == 123
