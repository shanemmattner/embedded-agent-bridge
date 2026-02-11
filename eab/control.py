"""Backwards-compatible shim. Real implementation in eab.cli."""
from __future__ import annotations

from eab.cli import main  # noqa: F401

if __name__ == "__main__":
    raise SystemExit(main())
