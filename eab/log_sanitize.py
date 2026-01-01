"""
Serial/log sanitization helpers.

Goals:
- Keep logs grep-friendly even if the device emits binary/control bytes.
- Strip ANSI color codes by default (ESP-IDF often emits these).
- Avoid losing meaningful leading whitespace (don't use `.strip()`).
"""

from __future__ import annotations

from typing import Final

from .device_control import strip_ansi


_DEFAULT_MAX_CHARS: Final[int] = 20_000


def sanitize_serial_bytes(data: bytes, *, max_chars: int = _DEFAULT_MAX_CHARS) -> str:
    """
    Convert a serial "line" of bytes to safe text for logging.

    - Drops trailing CR/LF only (preserves leading/trailing spaces).
    - Removes NUL bytes.
    - Decodes as UTF-8 with replacement.
    - Strips ANSI escape sequences.
    - Escapes remaining control characters (except tab).
    - Truncates very long lines to keep logs manageable.
    """
    data = data.rstrip(b"\r\n")
    if b"\x00" in data:
        data = data.replace(b"\x00", b"")

    text = data.decode("utf-8", errors="replace")
    text = strip_ansi(text)

    out: list[str] = []
    for ch in text:
        if ch == "\t" or ch.isprintable():
            out.append(ch)
            continue
        out.append(f"\\x{ord(ch):02x}")

    sanitized = "".join(out)
    if max_chars > 0 and len(sanitized) > max_chars:
        sanitized = sanitized[:max_chars] + "...[truncated]"
    return sanitized

