"""
Tests for cmd.txt queue helpers.

These helpers provide a minimal, flock-based append/drain protocol so that
agents and the daemon don't race on cmd.txt.
"""

from __future__ import annotations


def test_append_and_drain_roundtrip(tmp_path):
    from eab.command_file import append_command, drain_commands

    cmd_path = str(tmp_path / "cmd.txt")

    append_command(cmd_path, "first")
    append_command(cmd_path, "second\n")
    append_command(cmd_path, "")  # ignored

    drained = drain_commands(cmd_path)
    assert drained == ["first", "second"]

    drained_again = drain_commands(cmd_path)
    assert drained_again == []

