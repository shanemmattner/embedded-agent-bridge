"""Integration tests for GDB scripting CLI commands.

Tests verify that argument parsing works correctly and that the commands
are properly wired into the CLI dispatcher.
"""

from __future__ import annotations

from unittest.mock import patch


from eab.cli import main


class TestGdbScriptCLI:
    """Test gdb-script command CLI integration."""

    @patch("eab.cli.cmd_gdb_script")
    def test_gdb_script_basic_args(self, mock_cmd):
        """Test gdb-script with basic arguments."""
        mock_cmd.return_value = 0

        result = main([
            "gdb-script",
            "/path/to/script.py",
            "--chip", "nrf5340",
            "--device", "NRF5340_XXAA_APP",
            "--json",
        ])

        assert result == 0
        mock_cmd.assert_called_once()
        call_kwargs = mock_cmd.call_args[1]
        assert call_kwargs["script_path"] == "/path/to/script.py"
        assert call_kwargs["chip"] == "nrf5340"
        assert call_kwargs["device"] == "NRF5340_XXAA_APP"
        assert call_kwargs["json_mode"] is True

    @patch("eab.cli.cmd_gdb_script")
    def test_gdb_script_with_elf(self, mock_cmd):
        """Test gdb-script with ELF file."""
        mock_cmd.return_value = 0

        result = main([
            "gdb-script",
            "/path/to/script.py",
            "--elf", "/path/to/app.elf",
        ])

        assert result == 0
        call_kwargs = mock_cmd.call_args[1]
        assert call_kwargs["elf"] == "/path/to/app.elf"

    @patch("eab.cli.cmd_gdb_script")
    def test_gdb_script_with_openocd_probe(self, mock_cmd):
        """Test gdb-script with OpenOCD probe type."""
        mock_cmd.return_value = 0

        result = main([
            "gdb-script",
            "/path/to/script.py",
            "--probe", "openocd",
            "--chip", "mcxn947",
        ])

        assert result == 0
        call_kwargs = mock_cmd.call_args[1]
        assert call_kwargs["probe_type"] == "openocd"
        assert call_kwargs["chip"] == "mcxn947"

    @patch("eab.cli.cmd_gdb_script")
    def test_gdb_script_with_port(self, mock_cmd):
        """Test gdb-script with custom port."""
        mock_cmd.return_value = 0

        result = main([
            "gdb-script",
            "/path/to/script.py",
            "--port", "9999",
        ])

        assert result == 0
        call_kwargs = mock_cmd.call_args[1]
        assert call_kwargs["port"] == 9999


class TestInspectCLI:
    """Test inspect command CLI integration."""

    @patch("eab.cli.cmd_inspect")
    def test_inspect_basic_args(self, mock_cmd):
        """Test inspect with variable name."""
        mock_cmd.return_value = 0

        result = main([
            "inspect",
            "_kernel",
            "--chip", "nrf5340",
            "--json",
        ])

        assert result == 0
        mock_cmd.assert_called_once()
        call_kwargs = mock_cmd.call_args[1]
        assert call_kwargs["variable"] == "_kernel"
        assert call_kwargs["chip"] == "nrf5340"
        assert call_kwargs["json_mode"] is True

    @patch("eab.cli.cmd_inspect")
    def test_inspect_with_device_and_elf(self, mock_cmd):
        """Test inspect with device and ELF file."""
        mock_cmd.return_value = 0

        result = main([
            "inspect",
            "g_state",
            "--device", "NRF5340_XXAA_APP",
            "--elf", "/path/to/app.elf",
        ])

        assert result == 0
        call_kwargs = mock_cmd.call_args[1]
        assert call_kwargs["variable"] == "g_state"
        assert call_kwargs["device"] == "NRF5340_XXAA_APP"
        assert call_kwargs["elf"] == "/path/to/app.elf"


class TestThreadsCLI:
    """Test threads command CLI integration."""

    @patch("eab.thread_inspector.inspect_threads")
    def test_threads_basic_args(self, mock_inspect):
        """Test threads snapshot with basic args."""
        mock_inspect.return_value = []

        result = main([
            "--json",
            "threads", "snapshot",
            "--device", "NRF5340_XXAA_APP",
            "--elf", "/tmp/zephyr.elf",
        ])

        assert result == 0
        mock_inspect.assert_called_once()

    @patch("eab.thread_inspector.inspect_threads")
    def test_threads_with_rtos(self, mock_inspect):
        """Test threads snapshot with device and elf."""
        mock_inspect.return_value = []

        result = main([
            "threads", "snapshot",
            "--device", "NRF5340_XXAA_APP",
            "--elf", "/tmp/zephyr.elf",
        ])

        assert result == 0
        call_kwargs = mock_inspect.call_args[1]
        assert call_kwargs["device"] == "NRF5340_XXAA_APP"


class TestWatchCLI:
    """Test watch command CLI integration."""

    @patch("eab.cli.cmd_watch")
    def test_watch_basic_args(self, mock_cmd):
        """Test watch with variable name."""
        mock_cmd.return_value = 0

        result = main([
            "watch",
            "g_counter",
            "--chip", "nrf5340",
        ])

        assert result == 0
        mock_cmd.assert_called_once()
        call_kwargs = mock_cmd.call_args[1]
        assert call_kwargs["variable"] == "g_counter"
        assert call_kwargs["max_hits"] == 100  # Default

    @patch("eab.cli.cmd_watch")
    def test_watch_with_max_hits(self, mock_cmd):
        """Test watch with custom max hits."""
        mock_cmd.return_value = 0

        result = main([
            "watch",
            "g_counter",
            "--max-hits", "50",
        ])

        assert result == 0
        call_kwargs = mock_cmd.call_args[1]
        assert call_kwargs["max_hits"] == 50


class TestMemdumpCLI:
    """Test memdump command CLI integration."""

    @patch("eab.cli.cmd_memdump")
    def test_memdump_basic_args(self, mock_cmd):
        """Test memdump with hex address."""
        mock_cmd.return_value = 0

        result = main([
            "memdump",
            "0x20000000",
            "1024",
            "/tmp/memdump.bin",
            "--chip", "nrf5340",
        ])

        assert result == 0
        mock_cmd.assert_called_once()
        call_kwargs = mock_cmd.call_args[1]
        assert call_kwargs["start_addr"] == "0x20000000"
        assert call_kwargs["size"] == 1024
        assert call_kwargs["output_path"] == "/tmp/memdump.bin"

    @patch("eab.cli.cmd_memdump")
    def test_memdump_with_device_and_elf(self, mock_cmd):
        """Test memdump with device and ELF."""
        mock_cmd.return_value = 0

        result = main([
            "memdump",
            "0x20000000",
            "2048",
            "/tmp/out.bin",
            "--device", "NRF5340_XXAA_APP",
            "--elf", "/path/to/app.elf",
        ])

        assert result == 0
        call_kwargs = mock_cmd.call_args[1]
        assert call_kwargs["device"] == "NRF5340_XXAA_APP"
        assert call_kwargs["elf"] == "/path/to/app.elf"


class TestJSONModeFlag:
    """Test that --json flag works with all new commands."""

    @patch("eab.cli.cmd_gdb_script")
    def test_json_flag_gdb_script(self, mock_cmd):
        """--json flag should enable JSON mode for gdb-script."""
        mock_cmd.return_value = 0
        main(["gdb-script", "/script.py", "--json"])
        assert mock_cmd.call_args[1]["json_mode"] is True

    @patch("eab.cli.cmd_inspect")
    def test_json_flag_inspect(self, mock_cmd):
        """--json flag should enable JSON mode for inspect."""
        mock_cmd.return_value = 0
        main(["inspect", "_kernel", "--json"])
        assert mock_cmd.call_args[1]["json_mode"] is True

    @patch("eab.thread_inspector.inspect_threads")
    def test_json_flag_threads(self, mock_inspect):
        """--json flag should enable JSON mode for threads snapshot."""
        mock_inspect.return_value = []
        result = main([
            "--json",
            "threads", "snapshot",
            "--device", "NRF5340_XXAA_APP",
            "--elf", "/tmp/zephyr.elf",
        ])
        assert result == 0

    @patch("eab.cli.cmd_watch")
    def test_json_flag_watch(self, mock_cmd):
        """--json flag should enable JSON mode for watch."""
        mock_cmd.return_value = 0
        main(["watch", "g_counter", "--json"])
        assert mock_cmd.call_args[1]["json_mode"] is True

    @patch("eab.cli.cmd_memdump")
    def test_json_flag_memdump(self, mock_cmd):
        """--json flag should enable JSON mode for memdump."""
        mock_cmd.return_value = 0
        main(["memdump", "0x20000000", "1024", "/tmp/out.bin", "--json"])
        assert mock_cmd.call_args[1]["json_mode"] is True


class TestBaseDirResolution:
    """Test that base_dir resolution works for all new commands."""

    @patch("eab.cli.cmd_gdb_script")
    @patch("eab.cli._resolve_base_dir")
    def test_base_dir_gdb_script(self, mock_resolve, mock_cmd):
        """base_dir should be resolved and passed to cmd_gdb_script."""
        mock_resolve.return_value = "/custom/base/dir"
        mock_cmd.return_value = 0

        main(["gdb-script", "/script.py"])
        
        call_kwargs = mock_cmd.call_args[1]
        assert call_kwargs["base_dir"] == "/custom/base/dir"

    @patch("eab.cli.cmd_inspect")
    @patch("eab.cli._resolve_base_dir")
    def test_base_dir_inspect(self, mock_resolve, mock_cmd):
        """base_dir should be resolved and passed to cmd_inspect."""
        mock_resolve.return_value = "/custom/base/dir"
        mock_cmd.return_value = 0

        main(["inspect", "_kernel"])
        
        call_kwargs = mock_cmd.call_args[1]
        assert call_kwargs["base_dir"] == "/custom/base/dir"
