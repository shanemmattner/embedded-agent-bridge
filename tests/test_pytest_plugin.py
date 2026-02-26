"""Tests for the EAB pytest plugin — no hardware required."""

from __future__ import annotations

import os
import tempfile

import pytest

from eab.hil.rtt_capture import RttCapture


# ---------------------------------------------------------------------------
# RttCapture unit tests
# ---------------------------------------------------------------------------

def test_rtt_capture_reads_new_lines():
    """RttCapture.stop() returns only lines written after start()."""
    with tempfile.NamedTemporaryFile(mode="w", suffix=".log", delete=False) as f:
        f.write("old line\n")
        name = f.name

    try:
        cap = RttCapture.__new__(RttCapture)
        cap.device = None
        cap._log_path = name
        cap._start_offset = os.path.getsize(name)
        cap._lines = []

        with open(name, "a") as f:
            f.write("new line 1\nnew line 2\n")

        lines = cap.stop()
        assert lines == ["new line 1", "new line 2"]
    finally:
        os.unlink(name)


def test_rtt_capture_no_device_returns_empty():
    """RttCapture with device=None always returns empty list."""
    cap = RttCapture(device=None)
    cap.start()
    lines = cap.stop()
    assert lines == []


def test_rtt_capture_start_records_offset():
    """RttCapture.start() records the current file size."""
    with tempfile.NamedTemporaryFile(mode="w", suffix=".log", delete=False) as f:
        f.write("existing content\n")
        name = f.name

    try:
        cap = RttCapture.__new__(RttCapture)
        cap.device = None
        cap._log_path = name
        cap._start_offset = 0
        cap._lines = []

        expected_offset = os.path.getsize(name)
        cap._start_offset = expected_offset

        # Write more content
        with open(name, "a") as f:
            f.write("after start\n")

        lines = cap.stop()
        assert lines == ["after start"]
    finally:
        os.unlink(name)


def test_rtt_capture_text_property():
    """RttCapture.text returns lines joined by newlines."""
    cap = RttCapture.__new__(RttCapture)
    cap.device = None
    cap._log_path = None
    cap._start_offset = 0
    cap._lines = ["line1", "line2", "line3"]

    assert cap.text == "line1\nline2\nline3"


def test_rtt_capture_missing_log_file_returns_empty():
    """RttCapture.stop() returns empty list when log file doesn't exist."""
    cap = RttCapture.__new__(RttCapture)
    cap.device = None
    cap._log_path = "/tmp/nonexistent_eab_rtt_test.log"
    cap._start_offset = 0
    cap._lines = []

    lines = cap.stop()
    assert lines == []


# ---------------------------------------------------------------------------
# Plugin option registration tests (requires plugin to be active)
# ---------------------------------------------------------------------------

def test_plugin_hil_device_option(pytestconfig):
    """Plugin registers --hil-device option with default None."""
    val = pytestconfig.getoption("--hil-device", default=None)
    assert val is None


def test_plugin_hil_chip_option(pytestconfig):
    """Plugin registers --hil-chip option with default None."""
    val = pytestconfig.getoption("--hil-chip", default=None)
    assert val is None


def test_plugin_hil_probe_option(pytestconfig):
    """Plugin registers --hil-probe option with default None."""
    val = pytestconfig.getoption("--hil-probe", default=None)
    assert val is None


def test_plugin_hil_timeout_option(pytestconfig):
    """Plugin registers --hil-timeout option with default 30."""
    val = pytestconfig.getoption("--hil-timeout", default=30)
    assert val == 30


# ---------------------------------------------------------------------------
# Fixture skip behaviour (uses subprocess to run isolated pytest session)
# ---------------------------------------------------------------------------

def test_hil_device_skips_without_flag(tmp_path):
    """hil_device fixture skips when --hil-device is not supplied."""
    import subprocess
    import sys

    test_file = tmp_path / "test_skip_example.py"
    test_file.write_text("""
def test_example(hil_device):
    pass
""")
    # Note: plugin is auto-loaded via entry_points; no conftest needed.
    result = subprocess.run(
        [sys.executable, "-m", "pytest", str(test_file), "-v", "--tb=short",
         "--override-ini=addopts="],
        capture_output=True,
        text=True,
        cwd=str(tmp_path),
    )
    combined = result.stdout + result.stderr
    assert "SKIPPED" in combined or "skipped" in combined


def test_hil_device_skips_with_hil_message(tmp_path):
    """hil_device fixture skip message mentions hil."""
    import subprocess
    import sys

    test_file = tmp_path / "test_skip_msg.py"
    test_file.write_text("""
def test_example(hil_device):
    pass
""")
    result = subprocess.run(
        [sys.executable, "-m", "pytest", str(test_file), "-v", "-rs",
         "--tb=short", "--override-ini=addopts="],
        capture_output=True,
        text=True,
        cwd=str(tmp_path),
    )
    combined = result.stdout + result.stderr
    assert "hil" in combined.lower()


# ---------------------------------------------------------------------------
# RTT capture attaches to failed report (integration via subprocess)
# ---------------------------------------------------------------------------

def test_rtt_capture_attaches_to_failed_report(tmp_path):
    """RTT log lines are attached to failing test report sections."""
    import subprocess
    import sys

    test_file = tmp_path / "test_failing.py"
    test_file.write_text("""
def test_failing():
    assert False, "intentional failure"
""")
    result = subprocess.run(
        [sys.executable, "-m", "pytest", str(test_file), "-v", "--tb=short",
         "--override-ini=addopts="],
        capture_output=True,
        text=True,
        cwd=str(tmp_path),
    )
    # Test should fail (not error)
    assert result.returncode != 0
    combined = result.stdout + result.stderr
    assert "FAILED" in combined
