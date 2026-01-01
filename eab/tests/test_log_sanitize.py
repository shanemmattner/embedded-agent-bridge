"""
Tests for serial/log sanitization helpers.
"""

from __future__ import annotations


def test_sanitize_strips_ansi_and_null_and_controls():
    from eab.log_sanitize import sanitize_serial_bytes

    raw = b"\x1b[0;32mI (1) ok\x1b[0m\x00\x01\r\n"
    assert sanitize_serial_bytes(raw) == "I (1) ok\\x01"


def test_sanitize_truncates():
    from eab.log_sanitize import sanitize_serial_bytes

    raw = (b"a" * 50) + b"\n"
    out = sanitize_serial_bytes(raw, max_chars=10)
    assert out == "aaaaaaaaaa...[truncated]"

