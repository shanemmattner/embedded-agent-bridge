"""Tests for DWT profiling CLI commands.

Tests CLI argument parsing, JSON output format, error handling,
and integration with the main CLI entry point.
"""

from __future__ import annotations

from unittest.mock import MagicMock, patch


from eab.cli.profile_cmds import (
    _detect_cpu_freq,
)
from eab.dwt_profiler import ProfileResult


# =============================================================================
# CPU Frequency Auto-Detection Tests
# =============================================================================

class TestCpuFreqDetection:
    """Test CPU frequency auto-detection from device strings."""

    def test_detect_nrf5340_freq(self):
        """Should detect 128 MHz for nRF5340 devices."""
        assert _detect_cpu_freq("NRF5340_XXAA_APP") == 128_000_000
        assert _detect_cpu_freq("nrf5340_cpuapp") == 128_000_000
        assert _detect_cpu_freq("NRF5340_NET") == 128_000_000

    def test_detect_nrf52840_freq(self):
        """Should detect 64 MHz for nRF52840 devices."""
        assert _detect_cpu_freq("NRF52840_XXAA") == 64_000_000
        assert _detect_cpu_freq("nrf52840dk") == 64_000_000

    def test_detect_mcxn947_freq(self):
        """Should detect 150 MHz for MCXN947 devices."""
        assert _detect_cpu_freq("MCXN947") == 150_000_000
        assert _detect_cpu_freq("mcxn947_cpucore0") == 150_000_000

    def test_detect_stm32f4_freq(self):
        """Should detect 168 MHz for STM32F4 devices."""
        assert _detect_cpu_freq("STM32F407VG") == 168_000_000
        assert _detect_cpu_freq("stm32f4discovery") == 168_000_000

    def test_detect_stm32h7_freq(self):
        """Should detect 480 MHz for STM32H7 devices."""
        assert _detect_cpu_freq("STM32H743ZI") == 480_000_000

    def test_unknown_device_returns_none(self):
        """Should return None for unknown device strings."""
        assert _detect_cpu_freq("UNKNOWN_DEVICE") is None
        assert _detect_cpu_freq("ESP32") is None
        assert _detect_cpu_freq("") is None


# =============================================================================
# Profile Function Command Tests
# =============================================================================

class TestCmdProfileFunction:
    """Test cmd_profile_function() CLI command."""

    def test_profile_function_success_json_mode(self):
        """Should profile function and output JSON format."""
        # Mock pylink module
        mock_pylink_module = MagicMock()
        mock_jlink = MagicMock()
        mock_pylink_module.JLink.return_value = mock_jlink
        mock_pylink_module.enums.JLinkInterfaces.SWD = 1

        # Mock profiling result
        test_result = ProfileResult(
            function="test_function",
            address=0x20001000,
            cycles=1234,
            time_us=9.640625,
            cpu_freq_hz=128_000_000,
        )

        with patch.dict("sys.modules", {"pylink": mock_pylink_module}):
            with patch("eab.dwt_profiler.profile_function", return_value=test_result):
                from eab.cli.profile_cmds import cmd_profile_function

                output_lines = []
                with patch("eab.cli.profile_cmds._print") as mock_print:
                    mock_print.side_effect = lambda obj, json_mode: output_lines.append(obj)

                    result = cmd_profile_function(
                        base_dir="/tmp/eab-test",
                        device="NRF5340_XXAA_APP",
                        elf="/tmp/test.elf",
                        function="test_function",
                        cpu_freq=None,
                        json_mode=True,
                    )

                assert result == 0
                assert len(output_lines) == 1

                output = output_lines[0]
                assert output["function"] == "test_function"
                assert output["address"] == "0x20001000"
                assert output["cycles"] == 1234
                assert output["time_us"] == 9.64
                assert output["cpu_freq_hz"] == 128_000_000

                # Verify J-Link lifecycle
                mock_jlink.open.assert_called_once()
                mock_jlink.close.assert_called_once()

    def test_profile_function_success_human_readable(self):
        """Should profile function and output human-readable format."""
        mock_pylink_module = MagicMock()
        mock_jlink = MagicMock()
        mock_pylink_module.JLink.return_value = mock_jlink
        mock_pylink_module.enums.JLinkInterfaces.SWD = 1

        test_result = ProfileResult(
            function="main",
            address=0x10000,
            cycles=5000,
            time_us=39.0625,
            cpu_freq_hz=128_000_000,
        )

        with patch.dict("sys.modules", {"pylink": mock_pylink_module}):
            with patch("eab.dwt_profiler.profile_function", return_value=test_result):
                from eab.cli.profile_cmds import cmd_profile_function

                output_lines = []
                with patch("eab.cli.profile_cmds._print") as mock_print:
                    mock_print.side_effect = lambda obj, json_mode: output_lines.append(obj)

                    result = cmd_profile_function(
                        base_dir="/tmp/eab-test",
                        device="NRF5340_XXAA_APP",
                        elf="/tmp/test.elf",
                        function="main",
                        cpu_freq=128_000_000,
                        json_mode=False,
                    )

                assert result == 0
                assert len(output_lines) == 1

                output = output_lines[0]
                assert "Function: main" in output
                assert "0x00010000" in output
                assert "5000" in output
                assert "39.06" in output
                assert "128.0 MHz" in output

    def test_profile_function_missing_pylink(self):
        """Should return error code 2 when pylink import fails during execution.
        
        Note: This tests the error handling path when pylink is missing.
        The actual ImportError is raised at the try/except block within
        cmd_profile_function, not at module import time.
        """
        # Create a mock that will fail when we try to use it
        from eab.cli.profile_cmds import cmd_profile_function

        output_lines = []
        with patch("eab.cli.profile_cmds._print") as mock_print:
            mock_print.side_effect = lambda obj, json_mode: output_lines.append(obj)

            # Mock the import inside the function to raise ImportError
            with patch.dict("sys.modules", {"pylink": None}):
                result = cmd_profile_function(
                    base_dir="/tmp/eab-test",
                    device="NRF5340_XXAA_APP",
                    elf="/tmp/test.elf",
                    function="test_function",
                    cpu_freq=None,
                    json_mode=True,
                )

        # When pylink module is None, the try/except catches it
        assert result == 2
        assert len(output_lines) == 1
        output = output_lines[0]
        assert output["error"] == "missing_pylink"
        assert "pip install pylink-square" in output["message"]

    def test_profile_function_unknown_device_auto_detect(self):
        """Should return error code 2 when CPU frequency cannot be auto-detected."""
        mock_pylink_module = MagicMock()
        
        with patch.dict("sys.modules", {"pylink": mock_pylink_module}):
            from eab.cli.profile_cmds import cmd_profile_function

            output_lines = []
            with patch("eab.cli.profile_cmds._print") as mock_print:
                mock_print.side_effect = lambda obj, json_mode: output_lines.append(obj)

                result = cmd_profile_function(
                    base_dir="/tmp/eab-test",
                    device="UNKNOWN_DEVICE_XYZ",
                    elf="/tmp/test.elf",
                    function="test_function",
                    cpu_freq=None,
                    json_mode=True,
                )

            assert result == 2
            assert len(output_lines) == 1
            output = output_lines[0]
            assert output["error"] == "unknown_device"
            assert "--cpu-freq" in output["message"]

    def test_profile_function_timeout_error(self):
        """Should return error code 1 when profiling times out."""
        mock_pylink_module = MagicMock()
        mock_jlink = MagicMock()
        mock_pylink_module.JLink.return_value = mock_jlink
        mock_pylink_module.enums.JLinkInterfaces.SWD = 1

        with patch.dict("sys.modules", {"pylink": mock_pylink_module}):
            with patch("eab.dwt_profiler.profile_function", side_effect=TimeoutError("Timeout")):
                from eab.cli.profile_cmds import cmd_profile_function

                output_lines = []
                with patch("eab.cli.profile_cmds._print") as mock_print:
                    mock_print.side_effect = lambda obj, json_mode: output_lines.append(obj)

                    result = cmd_profile_function(
                        base_dir="/tmp/eab-test",
                        device="NRF5340_XXAA_APP",
                        elf="/tmp/test.elf",
                        function="test_function",
                        cpu_freq=128_000_000,
                        json_mode=True,
                    )

                assert result == 1
                output = output_lines[0]
                assert output["error"] == "timeout"


# =============================================================================
# Profile Region Command Tests  
# =============================================================================

class TestCmdProfileRegion:
    """Test cmd_profile_region() CLI command."""

    def test_profile_region_success_json_mode(self):
        """Should profile region and output JSON format."""
        mock_pylink_module = MagicMock()
        mock_jlink = MagicMock()
        mock_pylink_module.JLink.return_value = mock_jlink
        mock_pylink_module.enums.JLinkInterfaces.SWD = 1

        test_result = ProfileResult(
            function="region_0x10000000_to_0x10000020",
            address=0x10000000,
            cycles=2000,
            time_us=15.625,
            cpu_freq_hz=128_000_000,
        )

        with patch.dict("sys.modules", {"pylink": mock_pylink_module}):
            with patch("eab.dwt_profiler.profile_region", return_value=test_result):
                from eab.cli.profile_cmds import cmd_profile_region

                output_lines = []
                with patch("eab.cli.profile_cmds._print") as mock_print:
                    mock_print.side_effect = lambda obj, json_mode: output_lines.append(obj)

                    result = cmd_profile_region(
                        base_dir="/tmp/eab-test",
                        start_addr=0x10000000,
                        end_addr=0x10000020,
                        device="NRF5340_XXAA_APP",
                        cpu_freq=None,
                        json_mode=True,
                    )

                assert result == 0
                assert len(output_lines) == 1

                output = output_lines[0]
                assert output["address"] == "0x10000000"
                assert output["cycles"] == 2000
                assert output["time_us"] == 15.62
                assert output["cpu_freq_hz"] == 128_000_000


# =============================================================================
# DWT Status Command Tests
# =============================================================================

class TestCmdDwtStatus:
    """Test cmd_dwt_status() CLI command."""

    def test_dwt_status_enabled_json_mode(self):
        """Should read DWT status and output JSON when DWT is enabled."""
        mock_pylink_module = MagicMock()
        mock_jlink = MagicMock()
        mock_pylink_module.JLink.return_value = mock_jlink
        mock_pylink_module.enums.JLinkInterfaces.SWD = 1

        test_status = {
            "DEMCR": 0x01000000,
            "DWT_CTRL": 0x00000001,
            "DWT_CYCCNT": 123456,
        }

        with patch.dict("sys.modules", {"pylink": mock_pylink_module}):
            with patch("eab.dwt_profiler.get_dwt_status", return_value=test_status):
                from eab.cli.profile_cmds import cmd_dwt_status

                output_lines = []
                with patch("eab.cli.profile_cmds._print") as mock_print:
                    mock_print.side_effect = lambda obj, json_mode: output_lines.append(obj)

                    result = cmd_dwt_status(
                        base_dir="/tmp/eab-test",
                        device="NRF5340_XXAA_APP",
                        json_mode=True,
                    )

                assert result == 0
                assert len(output_lines) == 1

                output = output_lines[0]
                assert output["DEMCR"] == "0x01000000"
                assert output["DWT_CTRL"] == "0x00000001"
                assert output["DWT_CYCCNT"] == 123456
                assert output["TRCENA"] is True
                assert output["CYCCNTENA"] is True
                assert output["enabled"] is True

    def test_dwt_status_disabled_human_readable(self):
        """Should read DWT status and output human-readable format when disabled."""
        mock_pylink_module = MagicMock()
        mock_jlink = MagicMock()
        mock_pylink_module.JLink.return_value = mock_jlink
        mock_pylink_module.enums.JLinkInterfaces.SWD = 1

        test_status = {
            "DEMCR": 0x00000000,
            "DWT_CTRL": 0x00000000,
            "DWT_CYCCNT": 0,
        }

        with patch.dict("sys.modules", {"pylink": mock_pylink_module}):
            with patch("eab.dwt_profiler.get_dwt_status", return_value=test_status):
                from eab.cli.profile_cmds import cmd_dwt_status

                output_lines = []
                with patch("eab.cli.profile_cmds._print") as mock_print:
                    mock_print.side_effect = lambda obj, json_mode: output_lines.append(obj)

                    result = cmd_dwt_status(
                        base_dir="/tmp/eab-test",
                        device="MCXN947",
                        json_mode=False,
                    )

                assert result == 0
                assert len(output_lines) == 1

                output = output_lines[0]
                assert "DWT Status:" in output
                assert "DEMCR:" in output
                assert "disabled" in output


# =============================================================================
# CLI Integration Tests
# =============================================================================

class TestCLIIntegration:
    """Test integration with main CLI entry point."""

    def test_profile_function_via_main_cli(self):
        """Should invoke profile-function command via main() entry point."""
        mock_pylink_module = MagicMock()
        mock_jlink = MagicMock()
        mock_pylink_module.JLink.return_value = mock_jlink
        mock_pylink_module.enums.JLinkInterfaces.SWD = 1

        test_result = ProfileResult(
            function="test_func",
            address=0x10000,
            cycles=5000,
            time_us=39.0625,
            cpu_freq_hz=128_000_000,
        )

        with patch.dict("sys.modules", {"pylink": mock_pylink_module}):
            with patch("eab.dwt_profiler.profile_function", return_value=test_result):
                from eab.cli import main

                with patch("eab.cli._print"):
                    result = main([
                        "--json",
                        "profile-function",
                        "--device", "NRF5340_XXAA_APP",
                        "--elf", "/tmp/test.elf",
                        "--function", "test_func",
                    ])

                assert result == 0

    def test_profile_region_via_main_cli(self):
        """Should invoke profile-region command via main() entry point."""
        mock_pylink_module = MagicMock()
        mock_jlink = MagicMock()
        mock_pylink_module.JLink.return_value = mock_jlink
        mock_pylink_module.enums.JLinkInterfaces.SWD = 1

        test_result = ProfileResult(
            function="region",
            address=0x20000000,
            cycles=3000,
            time_us=23.4375,
            cpu_freq_hz=128_000_000,
        )

        with patch.dict("sys.modules", {"pylink": mock_pylink_module}):
            with patch("eab.dwt_profiler.profile_region", return_value=test_result):
                from eab.cli import main

                with patch("eab.cli._print"):
                    result = main([
                        "--json",
                        "profile-region",
                        "--device", "NRF5340_XXAA_APP",
                        "--start", "0x20000000",
                        "--end", "0x20001000",
                    ])

                assert result == 0

    def test_dwt_status_via_main_cli(self):
        """Should invoke dwt-status command via main() entry point."""
        mock_pylink_module = MagicMock()
        mock_jlink = MagicMock()
        mock_pylink_module.JLink.return_value = mock_jlink
        mock_pylink_module.enums.JLinkInterfaces.SWD = 1

        test_status = {
            "DEMCR": 0x01000000,
            "DWT_CTRL": 0x00000001,
            "DWT_CYCCNT": 123456,
        }

        with patch.dict("sys.modules", {"pylink": mock_pylink_module}):
            with patch("eab.dwt_profiler.get_dwt_status", return_value=test_status):
                from eab.cli import main

                with patch("eab.cli._print"):
                    result = main([
                        "--json",
                        "dwt-status",
                        "--device", "NRF5340_XXAA_APP",
                    ])

                assert result == 0

    def test_profile_function_argument_parsing(self):
        """Should parse profile-function arguments correctly."""
        from eab.cli import _build_parser

        parser = _build_parser()
        args = parser.parse_args([
            "profile-function",
            "--device", "NRF5340_XXAA_APP",
            "--elf", "/path/to/app.elf",
            "--function", "my_function",
            "--cpu-freq", "64000000",
        ])

        assert args.cmd == "profile-function"
        assert args.device == "NRF5340_XXAA_APP"
        assert args.elf == "/path/to/app.elf"
        assert args.function == "my_function"
        assert args.cpu_freq == 64000000

    def test_profile_region_argument_parsing_hex(self):
        """Should parse profile-region arguments with hex addresses."""
        from eab.cli import _build_parser

        parser = _build_parser()
        args = parser.parse_args([
            "profile-region",
            "--device", "MCXN947",
            "--start", "0x20000000",
            "--end", "0x20001000",
        ])

        assert args.cmd == "profile-region"
        assert args.device == "MCXN947"
        assert args.start == 0x20000000
        assert args.end == 0x20001000
        assert args.cpu_freq is None

    def test_profile_region_argument_parsing_decimal(self):
        """Should parse profile-region arguments with decimal addresses."""
        from eab.cli import _build_parser

        parser = _build_parser()
        args = parser.parse_args([
            "profile-region",
            "--device", "NRF5340_XXAA_APP",
            "--start", "536870912",
            "--end", "536875008",
            "--cpu-freq", "128000000",
        ])

        assert args.start == 536870912
        assert args.end == 536875008
        assert args.cpu_freq == 128000000

    def test_dwt_status_argument_parsing(self):
        """Should parse dwt-status arguments correctly."""
        from eab.cli import _build_parser

        parser = _build_parser()
        args = parser.parse_args([
            "dwt-status",
            "--device", "STM32H743ZI",
        ])

        assert args.cmd == "dwt-status"
        assert args.device == "STM32H743ZI"
