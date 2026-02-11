"""Tests for RTT stream processor."""

import json
import pytest
from pathlib import Path

from eab.rtt_stream import RTTStreamProcessor, LogFormat


def test_feed_text_basic():
    """Test feeding text with DATA key=value pattern via feed_text()."""
    proc = RTTStreamProcessor()
    results = proc.feed_text("DATA: x=1.5 y=2.3\n")
    
    assert len(results) == 1
    record = results[0]
    assert record["type"] == "data"
    assert record["values"] == {"x": 1.5, "y": 2.3}


def test_feed_bytes():
    """Test feeding bytes with DATA key=value pattern via feed()."""
    proc = RTTStreamProcessor()
    results = proc.feed(b"DATA: x=1.5 y=2.3\n")
    
    assert len(results) == 1
    record = results[0]
    assert record["type"] == "data"
    assert record["values"] == {"x": 1.5, "y": 2.3}


def test_flush_partial_line():
    """Test flush() emits partial line without newline."""
    proc = RTTStreamProcessor()
    # Feed without newline
    results = proc.feed_text("DATA: x=1.0")
    assert len(results) == 0  # No newline, so no results yet
    
    # Flush should emit the partial line
    results = proc.flush()
    assert len(results) == 1
    record = results[0]
    assert record["type"] == "data"
    assert record["values"] == {"x": 1.0}


def test_close_handles(tmp_path):
    """Test close() closes all file handles."""
    log_path = tmp_path / "rtt.log"
    jsonl_path = tmp_path / "rtt.jsonl"
    csv_path = tmp_path / "rtt.csv"
    
    proc = RTTStreamProcessor(
        log_path=log_path,
        jsonl_path=jsonl_path,
        csv_path=csv_path,
    )
    
    # Feed data to open file handles
    proc.feed_text("DATA: x=1.5\n")
    
    # Verify handles are open
    assert proc._log_f is not None
    assert proc._jsonl_f is not None
    assert proc._csv_f is not None
    assert not proc._log_f.closed
    assert not proc._jsonl_f.closed
    assert not proc._csv_f.closed
    
    # Close
    proc.close()
    
    # Verify handles are None or closed
    assert proc._log_f is None
    assert proc._jsonl_f is None
    assert proc._csv_f is None


def test_reset_clears_state():
    """Test reset() clears format detection state."""
    proc = RTTStreamProcessor()
    
    # Feed Zephyr-style line to trigger format detection
    proc.feed_text("[00:00:01.000] <inf> mod: hello\n")
    assert proc._format == LogFormat.ZEPHYR
    assert proc._detect_count > 0
    
    # Reset should clear state
    proc.reset()
    assert proc._format == LogFormat.UNKNOWN
    assert proc._detect_count == 0


def test_write_csv_auto_columns(tmp_path):
    """Test CSV writing auto-discovers columns."""
    csv_path = tmp_path / "rtt.csv"
    proc = RTTStreamProcessor(csv_path=csv_path)
    
    # Feed DATA record
    proc.feed_text("DATA: a=1.0 b=2.0\n")
    proc.close()
    
    # Read CSV
    content = csv_path.read_text()
    lines = content.strip().split("\n")
    
    # Verify header
    assert lines[0] == "timestamp,a,b"
    
    # Verify data row (timestamp + two values)
    assert len(lines) == 2
    parts = lines[1].split(",")
    assert len(parts) == 3  # timestamp, a, b
    assert parts[1] == "1.0"
    assert parts[2] == "2.0"


def test_write_csv_new_columns(tmp_path):
    """Test CSV header expansion when new columns appear."""
    csv_path = tmp_path / "rtt.csv"
    proc = RTTStreamProcessor(csv_path=csv_path)
    
    # Feed first record with column 'a'
    proc.feed_text("DATA: a=1.0\n")
    
    # Feed second record with columns 'a' and 'b'
    proc.feed_text("DATA: a=2.0 b=3.0\n")
    proc.close()
    
    # Read CSV
    content = csv_path.read_text()
    lines = content.strip().split("\n")
    
    # Verify header includes both columns
    assert lines[0] == "timestamp,a,b"
    
    # Verify first row (a=2.0, b=3.0)
    parts = lines[1].split(",")
    assert parts[1] == "2.0"
    assert parts[2] == "3.0"


def test_write_log_rotation(tmp_path):
    """Test log file rotation when max_log_bytes exceeded."""
    log_path = tmp_path / "rtt.log"
    proc = RTTStreamProcessor(log_path=log_path, max_log_bytes=100)
    
    # Write enough lines to exceed 100 bytes
    for i in range(20):
        proc.feed_text(f"This is a log line number {i}\n")
    
    proc.close()
    
    # Verify rotation occurred (rtt.log.1 should exist)
    rotated = tmp_path / "rtt.log.1"
    assert rotated.exists()
    
    # Verify rotated file has content
    assert rotated.stat().st_size > 0


def test_write_jsonl(tmp_path):
    """Test JSONL writing with valid JSON records."""
    jsonl_path = tmp_path / "rtt.jsonl"
    proc = RTTStreamProcessor(jsonl_path=jsonl_path)
    
    # Feed DATA record
    proc.feed_text("DATA: x=1.5\n")
    proc.close()
    
    # Read and parse JSONL
    content = jsonl_path.read_text()
    record = json.loads(content.strip())
    
    # Verify record structure
    assert record["type"] == "data"
    assert record["values"] == {"x": 1.5}


def test_boot_pattern_triggers_reset():
    """Test boot pattern triggers automatic reset."""
    proc = RTTStreamProcessor()
    
    # Detect Zephyr format first
    proc.feed_text("[00:00:01.000] <inf> mod: hello\n")
    assert proc._format == LogFormat.ZEPHYR
    initial_count = proc._detect_count
    assert initial_count > 0
    
    # Feed boot pattern
    proc.feed_text("*** Booting Zephyr OS\n")
    
    # Verify reset occurred (format cleared and detect_count reset)
    # Note: The boot line itself gets processed after reset, so detect_count will be 1
    assert proc._format == LogFormat.UNKNOWN
    assert proc._detect_count == 1  # Reset to 0, then boot line incremented it


def test_zephyr_format_detection():
    """Test Zephyr log format auto-detection."""
    proc = RTTStreamProcessor()
    
    # Feed Zephyr-style line
    results = proc.feed_text("[00:00:01.000] <inf> mod: hello\n")
    
    # Verify format detected
    assert proc._format == LogFormat.ZEPHYR
    
    # Verify parsed record
    assert len(results) == 1
    record = results[0]
    assert record["type"] == "log"
    assert record["level"] == "inf"
    assert record["module"] == "mod"


def test_banner_filtering():
    """Test RTT client banner lines are filtered out."""
    proc = RTTStreamProcessor()
    
    # Feed banner line
    results = proc.feed_text("###RTT Client: connected\n")
    
    # Verify no results (banner filtered)
    assert len(results) == 0
    
    # Also test SEGGER banner
    results = proc.feed_text("SEGGER J-Link RTT Control Panel\n")
    assert len(results) == 0
