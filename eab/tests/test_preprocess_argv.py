"""Unit tests for _preprocess_argv() in eab.cli."""
from __future__ import annotations

import pytest

from eab.cli import _preprocess_argv


class TestPreprocessArgv:
    """Test global flag reordering for agent ergonomics."""

    # -- Basic flag positioning ---------------------------------------------

    def test_json_before_subcommand(self):
        """--json already before subcommand should stay in place."""
        result = _preprocess_argv(["--json", "status"])
        assert result == ["--json", "status"]

    def test_json_after_subcommand(self):
        """--json after subcommand should be moved to front."""
        result = _preprocess_argv(["status", "--json"])
        assert result == ["--json", "status"]

    def test_base_dir_equals_before_subcommand(self):
        """--base-dir=X before subcommand should stay in place."""
        result = _preprocess_argv(["--base-dir=/tmp/test", "status"])
        assert result == ["--base-dir=/tmp/test", "status"]

    def test_base_dir_equals_after_subcommand(self):
        """--base-dir=X after subcommand should be moved to front."""
        result = _preprocess_argv(["status", "--base-dir=/tmp/test"])
        assert result == ["--base-dir=/tmp/test", "status"]

    def test_base_dir_space_before_subcommand(self):
        """--base-dir X (space-separated) before subcommand stays in place."""
        result = _preprocess_argv(["--base-dir", "/tmp/test", "status"])
        assert result == ["--base-dir", "/tmp/test", "status"]

    def test_base_dir_space_after_subcommand(self):
        """--base-dir X after subcommand should be moved to front."""
        result = _preprocess_argv(["status", "--base-dir", "/tmp/test"])
        assert result == ["--base-dir", "/tmp/test", "status"]

    # -- Multiple flags -----------------------------------------------------

    def test_json_and_base_dir_after_subcommand(self):
        """Both --json and --base-dir after subcommand should be moved."""
        result = _preprocess_argv(["tail", "50", "--json", "--base-dir=/tmp/x"])
        assert result == ["--json", "--base-dir=/tmp/x", "tail", "50"]

    def test_json_and_base_dir_mixed(self):
        """Flags mixed around the subcommand."""
        result = _preprocess_argv(["--json", "send", "hello", "--base-dir", "/tmp/x"])
        assert result == ["--json", "--base-dir", "/tmp/x", "send", "hello"]

    # -- Subcommand arguments preserved -------------------------------------

    def test_subcommand_args_preserved(self):
        """Arguments to the subcommand must not be swallowed."""
        result = _preprocess_argv(["send", "test_msg", "--await", "--json"])
        assert result == ["--json", "send", "test_msg", "--await"]

    def test_subcommand_with_own_flags_preserved(self):
        """Subcommand-specific flags like --timeout should not be moved."""
        result = _preprocess_argv(["wait", "Ready", "--timeout", "5", "--json"])
        assert result == ["--json", "wait", "Ready", "--timeout", "5"]

    # -- Edge cases ---------------------------------------------------------

    def test_empty_argv(self):
        """Empty input should produce empty output."""
        assert _preprocess_argv([]) == []

    def test_only_json(self):
        """Just --json with no subcommand."""
        assert _preprocess_argv(["--json"]) == ["--json"]

    def test_only_subcommand(self):
        """No global flags at all."""
        assert _preprocess_argv(["status"]) == ["status"]

    def test_base_dir_at_end_without_value(self):
        """--base-dir at the end with no value should remain in rest."""
        result = _preprocess_argv(["status", "--base-dir"])
        # --base-dir without value is pushed to rest
        assert result == ["status", "--base-dir"]

    def test_duplicate_json_flags(self):
        """Multiple --json flags should all be moved to front."""
        result = _preprocess_argv(["status", "--json", "--json"])
        assert result == ["--json", "--json", "status"]

    def test_order_of_globals_preserved(self):
        """Global flags should appear in the order they were found."""
        result = _preprocess_argv(["tail", "--base-dir=/a", "--json"])
        assert result == ["--base-dir=/a", "--json", "tail"]
