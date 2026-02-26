"""Tests for the eabctl snapshot CLI command."""

from __future__ import annotations

import json
from unittest.mock import MagicMock, patch

import pytest


class TestSnapshotParser:
    """Tests for the snapshot subparser registration."""

    def test_snapshot_registered_in_help(self):
        """snapshot should appear as a subcommand in eabctl --help."""
        from eab.cli.parser import _build_parser

        parser = _build_parser()
        # Verify snapshot is a known subcommand by parsing valid args
        args = parser.parse_args(
            [
                "snapshot",
                "--device",
                "NRF5340_XXAA_APP",
                "--elf",
                "/path/to/fw.elf",
                "--output",
                "/tmp/snap.core",
            ]
        )
        assert args.cmd == "snapshot"

    def test_snapshot_device_parsed(self):
        """--device argument should be stored in args.device."""
        from eab.cli.parser import _build_parser

        parser = _build_parser()
        args = parser.parse_args(
            [
                "snapshot",
                "--device",
                "NRF5340_XXAA_APP",
                "--elf",
                "fw.elf",
                "--output",
                "out.core",
            ]
        )
        assert args.device == "NRF5340_XXAA_APP"

    def test_snapshot_elf_parsed(self):
        """--elf argument should be stored in args.elf."""
        from eab.cli.parser import _build_parser

        parser = _build_parser()
        args = parser.parse_args(
            [
                "snapshot",
                "--device",
                "NRF5340_XXAA_APP",
                "--elf",
                "/build/zephyr.elf",
                "--output",
                "out.core",
            ]
        )
        assert args.elf == "/build/zephyr.elf"

    def test_snapshot_output_parsed(self):
        """--output argument should be stored in args.output."""
        from eab.cli.parser import _build_parser

        parser = _build_parser()
        args = parser.parse_args(
            [
                "snapshot",
                "--device",
                "NRF5340_XXAA_APP",
                "--elf",
                "fw.elf",
                "--output",
                "/tmp/my.core",
            ]
        )
        assert args.output == "/tmp/my.core"

    def test_snapshot_missing_device_raises(self):
        """Missing --device should cause SystemExit."""
        from eab.cli.parser import _build_parser

        parser = _build_parser()
        with pytest.raises(SystemExit):
            parser.parse_args(
                [
                    "snapshot",
                    "--elf",
                    "fw.elf",
                    "--output",
                    "out.core",
                ]
            )

    def test_snapshot_missing_elf_raises(self):
        """Missing --elf should cause SystemExit."""
        from eab.cli.parser import _build_parser

        parser = _build_parser()
        with pytest.raises(SystemExit):
            parser.parse_args(
                [
                    "snapshot",
                    "--device",
                    "NRF5340_XXAA_APP",
                    "--output",
                    "out.core",
                ]
            )

    def test_snapshot_missing_output_raises(self):
        """Missing --output should cause SystemExit."""
        from eab.cli.parser import _build_parser

        parser = _build_parser()
        with pytest.raises(SystemExit):
            parser.parse_args(
                [
                    "snapshot",
                    "--device",
                    "NRF5340_XXAA_APP",
                    "--elf",
                    "fw.elf",
                ]
            )

    def test_global_json_flag_parsed(self):
        """--json flag (global) should be available when using snapshot."""
        from eab.cli.parser import _build_parser, _preprocess_argv

        argv = _preprocess_argv(
            [
                "--json",
                "snapshot",
                "--device",
                "NRF5340_XXAA_APP",
                "--elf",
                "fw.elf",
                "--output",
                "out.core",
            ]
        )
        parser = _build_parser()
        args = parser.parse_args(argv)
        assert args.json is True


class TestSnapshotDispatch:
    """Tests for snapshot command dispatch and routing."""

    def _make_mock_result(self):
        """Build a mock SnapshotResult-like object."""
        from eab.snapshot import MemoryRegion, SnapshotResult

        return SnapshotResult(
            output_path="/tmp/snap.core",
            regions=[MemoryRegion(start=0x20000000, size=0x40000)],
            registers={"r0": 0, "pc": 0x1234},
            total_size=262244,
        )

    def test_dispatch_calls_cmd_snapshot(self, tmp_path):
        """main() with snapshot args should invoke cmd_snapshot."""
        from eab.control import main

        mock_cmd = MagicMock(return_value=0)
        with patch("eab.cli.snapshot_cmd.cmd_snapshot", mock_cmd):
            result = main(
                [
                    "snapshot",
                    "--device",
                    "NRF5340_XXAA_APP",
                    "--elf",
                    str(tmp_path / "fw.elf"),
                    "--output",
                    str(tmp_path / "snap.core"),
                ]
            )
        assert result == 0
        mock_cmd.assert_called_once()
        kwargs = mock_cmd.call_args.kwargs
        assert kwargs["device"] == "NRF5340_XXAA_APP"
        assert kwargs["elf"] == str(tmp_path / "fw.elf")
        assert kwargs["output"] == str(tmp_path / "snap.core")
        assert kwargs["json_mode"] is False

    def test_dispatch_passes_json_mode(self, tmp_path):
        """--json flag should be forwarded to cmd_snapshot as json_mode=True."""
        from eab.control import main

        mock_cmd = MagicMock(return_value=0)
        with patch("eab.cli.snapshot_cmd.cmd_snapshot", mock_cmd):
            result = main(
                [
                    "--json",
                    "snapshot",
                    "--device",
                    "NRF5340_XXAA_APP",
                    "--elf",
                    "fw.elf",
                    "--output",
                    "snap.core",
                ]
            )
        assert result == 0
        kwargs = mock_cmd.call_args.kwargs
        assert kwargs["json_mode"] is True

    def test_dispatch_propagates_failure(self, tmp_path):
        """When cmd_snapshot returns non-zero, main() should return same code."""
        from eab.control import main

        mock_cmd = MagicMock(return_value=1)
        with patch("eab.cli.snapshot_cmd.cmd_snapshot", mock_cmd):
            result = main(
                [
                    "snapshot",
                    "--device",
                    "NRF5340_XXAA_APP",
                    "--elf",
                    "fw.elf",
                    "--output",
                    "snap.core",
                ]
            )
        assert result == 1


class TestSnapshotCmd:
    """Unit tests for cmd_snapshot()."""

    def _make_mock_result(self):
        from eab.snapshot import MemoryRegion, SnapshotResult

        return SnapshotResult(
            output_path="/tmp/snap.core",
            regions=[
                MemoryRegion(start=0x20000000, size=0x40000),
                MemoryRegion(start=0x20040000, size=0x8000),
            ],
            registers={"r0": 0, "pc": 0x1234},
            total_size=327788,
        )

    def test_success_human_readable(self, capsys):
        """On success without --json, output should include path, regions, size."""
        from eab.cli.snapshot_cmd import cmd_snapshot

        mock_result = self._make_mock_result()
        with patch("eab.snapshot.capture_snapshot", return_value=mock_result):
            ret = cmd_snapshot(
                device="NRF5340_XXAA_APP",
                elf="/build/fw.elf",
                output="/tmp/snap.core",
                json_mode=False,
            )

        assert ret == 0
        captured = capsys.readouterr()
        assert "/tmp/snap.core" in captured.out
        assert "2" in captured.out  # number of regions
        assert "327788" in captured.out

    def test_success_json_output(self, capsys):
        """On success with json_mode=True, output should be valid JSON."""
        from eab.cli.snapshot_cmd import cmd_snapshot

        mock_result = self._make_mock_result()
        with patch("eab.snapshot.capture_snapshot", return_value=mock_result):
            ret = cmd_snapshot(
                device="NRF5340_XXAA_APP",
                elf="/build/fw.elf",
                output="/tmp/snap.core",
                json_mode=True,
            )

        assert ret == 0
        captured = capsys.readouterr()
        data = json.loads(captured.out)
        assert data["path"] == "/tmp/snap.core"
        assert isinstance(data["regions"], list)
        assert len(data["regions"]) == 2
        assert data["regions"][0]["start"] == 0x20000000
        assert data["regions"][0]["size"] == 0x40000
        assert isinstance(data["registers"], dict)
        assert data["size_bytes"] == 327788

    def test_failure_value_error(self, capsys):
        """ValueError from capture_snapshot should print to stderr and return 1."""
        from eab.cli.snapshot_cmd import cmd_snapshot

        with patch(
            "eab.snapshot.capture_snapshot",
            side_effect=ValueError("ELF file not found: /nonexistent.elf"),
        ):
            ret = cmd_snapshot(
                device="NRF5340_XXAA_APP",
                elf="/nonexistent.elf",
                output="/tmp/snap.core",
                json_mode=False,
            )

        assert ret == 1
        captured = capsys.readouterr()
        assert "ERROR" in captured.err
        assert "ELF file not found" in captured.err

    def test_failure_runtime_error(self, capsys):
        """RuntimeError from capture_snapshot should print to stderr and return 1."""
        from eab.cli.snapshot_cmd import cmd_snapshot

        with patch(
            "eab.snapshot.capture_snapshot",
            side_effect=RuntimeError("GDB failed"),
        ):
            ret = cmd_snapshot(
                device="NRF5340_XXAA_APP",
                elf="/build/fw.elf",
                output="/tmp/snap.core",
                json_mode=False,
            )

        assert ret == 1
        captured = capsys.readouterr()
        assert "ERROR" in captured.err

    def test_failure_import_error(self, capsys):
        """ImportError from capture_snapshot should print to stderr and return 1."""
        from eab.cli.snapshot_cmd import cmd_snapshot

        with patch(
            "eab.snapshot.capture_snapshot",
            side_effect=ImportError("pyelftools is required"),
        ):
            ret = cmd_snapshot(
                device="NRF5340_XXAA_APP",
                elf="/build/fw.elf",
                output="/tmp/snap.core",
                json_mode=False,
            )

        assert ret == 1
        captured = capsys.readouterr()
        assert "ERROR" in captured.err

    def test_json_regions_serialized(self, capsys):
        """JSON output regions should contain start and size fields."""
        from eab.cli.snapshot_cmd import cmd_snapshot

        mock_result = self._make_mock_result()
        with patch("eab.snapshot.capture_snapshot", return_value=mock_result):
            cmd_snapshot(
                device="NRF5340_XXAA_APP",
                elf="/build/fw.elf",
                output="/tmp/snap.core",
                json_mode=True,
            )

        data = json.loads(capsys.readouterr().out)
        for region in data["regions"]:
            assert "start" in region
            assert "size" in region
