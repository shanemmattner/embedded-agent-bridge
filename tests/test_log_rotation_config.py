"""Tests for log rotation configuration wiring."""

from unittest.mock import Mock, MagicMock, patch
from eab.session_logger import SessionLogger, LogRotationConfig
from eab.daemon import SerialDaemon
from eab.cli.daemon import cmd_start
from eab.cli import main as cli_main


class TestLogRotationConfig:
    """Test LogRotationConfig dataclass."""

    def test_default_values(self):
        """Test default values are sensible."""
        config = LogRotationConfig()
        assert config.max_size_bytes == 100_000_000
        assert config.max_files == 5
        assert config.compress is True

    def test_custom_values(self):
        """Test custom values can be set."""
        config = LogRotationConfig(max_size_bytes=200_000_000, max_files=10, compress=False)
        assert config.max_size_bytes == 200_000_000
        assert config.max_files == 10
        assert config.compress is False

    def test_partial_override(self):
        """Test partial override of defaults."""
        config = LogRotationConfig(max_size_bytes=50_000_000)
        assert config.max_size_bytes == 50_000_000
        assert config.max_files == 5  # Still default
        assert config.compress is True  # Still default


class TestSessionLoggerRotationConfig:
    """Test SessionLogger accepts and stores rotation config."""

    def test_session_logger_default_config(self):
        """Test SessionLogger uses default config when none provided."""
        fs = Mock()
        clock = Mock()
        logger = SessionLogger(
            filesystem=fs,
            clock=clock,
            base_dir="/tmp/test",
        )
        assert logger.rotation_config.max_size_bytes == 100_000_000
        assert logger.rotation_config.max_files == 5
        assert logger.rotation_config.compress is True

    def test_session_logger_custom_config(self):
        """Test SessionLogger accepts custom rotation config."""
        fs = Mock()
        clock = Mock()
        config = LogRotationConfig(max_size_bytes=250_000_000, max_files=3, compress=False)
        logger = SessionLogger(
            filesystem=fs,
            clock=clock,
            base_dir="/tmp/test",
            rotation_config=config,
        )
        assert logger.rotation_config.max_size_bytes == 250_000_000
        assert logger.rotation_config.max_files == 3
        assert logger.rotation_config.compress is False

    def test_rotation_config_property(self):
        """Test rotation_config property returns the config."""
        fs = Mock()
        clock = Mock()
        config = LogRotationConfig(max_size_bytes=75_000_000)
        logger = SessionLogger(
            filesystem=fs,
            clock=clock,
            base_dir="/tmp/test",
            rotation_config=config,
        )
        retrieved = logger.rotation_config
        assert retrieved.max_size_bytes == 75_000_000
        assert isinstance(retrieved, LogRotationConfig)


class TestSerialDaemonRotationConfig:
    """Test SerialDaemon passes rotation config to SessionLogger."""

    def test_daemon_default_rotation_params(self):
        """Test daemon uses default rotation parameters."""
        with patch('eab.daemon.ReconnectionManager'):
            with patch('eab.daemon.PatternMatcher'):
                with patch('eab.daemon.AlertLogger'):
                    with patch('eab.daemon.StatusManager'):
                        with patch('eab.daemon.EventEmitter'):
                            with patch('eab.daemon.DataStreamWriter'):
                                with patch('eab.daemon.DeviceController'):
                                    with patch('eab.daemon.ChipRecovery'):
                                        daemon = SerialDaemon(
                                            port="/dev/ttyUSB0", auto_detect=False,
                                            baud=115200,
                                            base_dir="/tmp/test",
                                        )
                                        # Check that SessionLogger was created with default config
                                        config = daemon._session_logger.rotation_config
                                        assert config.max_size_bytes == 100_000_000
                                        assert config.max_files == 5
                                        assert config.compress is True

    def test_daemon_custom_rotation_params(self):
        """Test daemon accepts custom rotation parameters."""
        with patch('eab.daemon.ReconnectionManager'):
            with patch('eab.daemon.PatternMatcher'):
                with patch('eab.daemon.AlertLogger'):
                    with patch('eab.daemon.StatusManager'):
                        with patch('eab.daemon.EventEmitter'):
                            with patch('eab.daemon.DataStreamWriter'):
                                with patch('eab.daemon.DeviceController'):
                                    with patch('eab.daemon.ChipRecovery'):
                                        daemon = SerialDaemon(
                                            port="/dev/ttyUSB0", auto_detect=False,
                                            baud=115200,
                                            base_dir="/tmp/test",
                                            log_max_size_mb=150,
                                            log_max_files=7,
                                            log_compress=False,
                                        )
                                        config = daemon._session_logger.rotation_config
                                        assert config.max_size_bytes == 150_000_000
                                        assert config.max_files == 7
                                        assert config.compress is False

    def test_daemon_partial_override(self):
        """Test daemon accepts partial override of rotation parameters."""
        with patch('eab.daemon.ReconnectionManager'):
            with patch('eab.daemon.PatternMatcher'):
                with patch('eab.daemon.AlertLogger'):
                    with patch('eab.daemon.StatusManager'):
                        with patch('eab.daemon.EventEmitter'):
                            with patch('eab.daemon.DataStreamWriter'):
                                with patch('eab.daemon.DeviceController'):
                                    with patch('eab.daemon.ChipRecovery'):
                                        daemon = SerialDaemon(
                                            port="/dev/ttyUSB0", auto_detect=False,
                                            baud=115200,
                                            base_dir="/tmp/test",
                                            log_max_size_mb=200,
                                        )
                                        config = daemon._session_logger.rotation_config
                                        assert config.max_size_bytes == 200_000_000
                                        assert config.max_files == 5  # Default
                                        assert config.compress is True  # Default


class TestCLIDaemonCmds:
    """Test CLI daemon commands pass rotation config."""

    @patch('eab.cli.daemon.lifecycle_cmds.check_singleton')
    @patch('eab.cli.daemon.lifecycle_cmds.subprocess.Popen')
    @patch('eab.cli.daemon.lifecycle_cmds.os.makedirs')
    @patch('builtins.open', new_callable=MagicMock)
    def test_cmd_start_default_rotation_args(self, mock_open, mock_makedirs, mock_popen, mock_singleton):
        """Test cmd_start passes default rotation args to daemon."""
        mock_singleton.return_value = None
        mock_proc = Mock()
        mock_proc.pid = 12345
        mock_popen.return_value = mock_proc

        result = cmd_start(
            base_dir="/tmp/test",
            port="auto",
            baud=115200,
            force=False,
            json_mode=False,
        )

        assert result == 0
        # Check that subprocess.Popen was called with rotation args
        args = mock_popen.call_args[0][0]
        assert "--log-max-size" in args
        assert "100" in args  # Default max size
        assert "--log-max-files" in args
        assert "5" in args  # Default max files
        # Should NOT have --no-log-compress (compress is True by default)
        assert "--no-log-compress" not in args

    @patch('eab.cli.daemon.lifecycle_cmds.check_singleton')
    @patch('eab.cli.daemon.lifecycle_cmds.subprocess.Popen')
    @patch('eab.cli.daemon.lifecycle_cmds.os.makedirs')
    @patch('builtins.open', new_callable=MagicMock)
    def test_cmd_start_custom_rotation_args(self, mock_open, mock_makedirs, mock_popen, mock_singleton):
        """Test cmd_start passes custom rotation args to daemon."""
        mock_singleton.return_value = None
        mock_proc = Mock()
        mock_proc.pid = 12345
        mock_popen.return_value = mock_proc

        result = cmd_start(
            base_dir="/tmp/test",
            port="auto",
            baud=115200,
            force=False,
            json_mode=False,
            log_max_size_mb=250,
            log_max_files=10,
            log_compress=False,
        )

        assert result == 0
        args = mock_popen.call_args[0][0]
        assert "--log-max-size" in args
        assert "250" in args
        assert "--log-max-files" in args
        assert "10" in args
        assert "--no-log-compress" in args

    @patch('eab.cli.daemon.lifecycle_cmds.check_singleton')
    @patch('eab.cli.daemon.lifecycle_cmds.subprocess.Popen')
    @patch('eab.cli.daemon.lifecycle_cmds.os.makedirs')
    @patch('builtins.open', new_callable=MagicMock)
    def test_cmd_start_compress_enabled(self, mock_open, mock_makedirs, mock_popen, mock_singleton):
        """Test cmd_start does NOT add --no-log-compress when compression is enabled."""
        mock_singleton.return_value = None
        mock_proc = Mock()
        mock_proc.pid = 12345
        mock_popen.return_value = mock_proc

        result = cmd_start(
            base_dir="/tmp/test",
            port="auto",
            baud=115200,
            force=False,
            json_mode=False,
            log_compress=True,
        )

        assert result == 0
        args = mock_popen.call_args[0][0]
        assert "--no-log-compress" not in args


class TestCLIMainIntegration:
    """Test CLI main() passes rotation args through to cmd_start."""

    @patch('eab.cli.cmd_start')
    def test_cli_start_default_rotation_flags(self, mock_cmd_start):
        """Test CLI start command passes default rotation flags."""
        mock_cmd_start.return_value = 0

        result = cli_main(['start', '--port', 'auto', '--baud', '115200'])

        assert result == 0
        assert mock_cmd_start.called
        call_kwargs = mock_cmd_start.call_args[1]
        assert call_kwargs['log_max_size_mb'] == 100
        assert call_kwargs['log_max_files'] == 5
        assert call_kwargs['log_compress'] is True

    @patch('eab.cli.cmd_start')
    def test_cli_start_custom_rotation_flags(self, mock_cmd_start):
        """Test CLI start command with custom rotation flags."""
        mock_cmd_start.return_value = 0

        result = cli_main([
            'start',
            '--port', 'auto',
            '--log-max-size', '200',
            '--log-max-files', '8',
            '--no-log-compress',
        ])

        assert result == 0
        assert mock_cmd_start.called
        call_kwargs = mock_cmd_start.call_args[1]
        assert call_kwargs['log_max_size_mb'] == 200
        assert call_kwargs['log_max_files'] == 8
        assert call_kwargs['log_compress'] is False

    @patch('eab.cli.cmd_start')
    def test_cli_start_partial_override(self, mock_cmd_start):
        """Test CLI start command with partial override of rotation flags."""
        mock_cmd_start.return_value = 0

        result = cli_main([
            'start',
            '--port', 'auto',
            '--log-max-size', '50',
        ])

        assert result == 0
        call_kwargs = mock_cmd_start.call_args[1]
        assert call_kwargs['log_max_size_mb'] == 50
        assert call_kwargs['log_max_files'] == 5  # Default
        assert call_kwargs['log_compress'] is True  # Default


class TestDaemonMainIntegration:
    """Test daemon main() accepts rotation args from command line."""

    @patch('eab.daemon.SerialDaemon')
    @patch('eab.daemon.signal.signal')
    def test_daemon_main_default_rotation_args(self, mock_signal, mock_daemon_class):
        """Test daemon main() creates daemon with default rotation args."""
        mock_daemon = Mock()
        mock_daemon.start.return_value = False  # Prevent run() from being called
        mock_daemon_class.return_value = mock_daemon

        from eab.daemon import main as daemon_main
        result = daemon_main(['--port', 'auto'])

        assert result == 1  # start() returns False
        assert mock_daemon_class.called
        call_kwargs = mock_daemon_class.call_args[1]
        assert call_kwargs['log_max_size_mb'] == 100
        assert call_kwargs['log_max_files'] == 5
        assert call_kwargs['log_compress'] is True

    @patch('eab.daemon.SerialDaemon')
    @patch('eab.daemon.signal.signal')
    def test_daemon_main_custom_rotation_args(self, mock_signal, mock_daemon_class):
        """Test daemon main() creates daemon with custom rotation args."""
        mock_daemon = Mock()
        mock_daemon.start.return_value = False
        mock_daemon_class.return_value = mock_daemon

        from eab.daemon import main as daemon_main
        result = daemon_main([
            '--port', 'auto',
            '--log-max-size', '300',
            '--log-max-files', '12',
            '--no-log-compress',
        ])

        assert result == 1
        call_kwargs = mock_daemon_class.call_args[1]
        assert call_kwargs['log_max_size_mb'] == 300
        assert call_kwargs['log_max_files'] == 12
        assert call_kwargs['log_compress'] is False

    @patch('eab.daemon.SerialDaemon')
    @patch('eab.daemon.signal.signal')
    def test_daemon_main_no_log_compress_flag(self, mock_signal, mock_daemon_class):
        """Test --no-log-compress flag disables compression."""
        mock_daemon = Mock()
        mock_daemon.start.return_value = False
        mock_daemon_class.return_value = mock_daemon

        from eab.daemon import main as daemon_main
        result = daemon_main(['--port', 'auto', '--no-log-compress'])

        assert result == 1
        call_kwargs = mock_daemon_class.call_args[1]
        assert call_kwargs['log_compress'] is False


class TestEndToEndBehavior:
    """Test end-to-end behavior of rotation config flow."""

    def test_config_flows_through_full_stack(self):
        """Test rotation config flows from CLI -> daemon -> SessionLogger."""
        # This test simulates the full flow without actually starting the daemon
        with patch('eab.daemon.ReconnectionManager'):
            with patch('eab.daemon.PatternMatcher'):
                with patch('eab.daemon.AlertLogger'):
                    with patch('eab.daemon.StatusManager'):
                        with patch('eab.daemon.EventEmitter'):
                            with patch('eab.daemon.DataStreamWriter'):
                                with patch('eab.daemon.DeviceController'):
                                    with patch('eab.daemon.ChipRecovery'):
                                        # Create daemon with custom config
                                        daemon = SerialDaemon(
                                            port="/dev/ttyUSB0", auto_detect=False,
                                            baud=115200,
                                            base_dir="/tmp/test",
                                            log_max_size_mb=333,
                                            log_max_files=9,
                                            log_compress=False,
                                        )

                                        # Verify config made it through to SessionLogger
                                        logger = daemon._session_logger
                                        config = logger.rotation_config

                                        assert config.max_size_bytes == 333_000_000
                                        assert config.max_files == 9
                                        assert config.compress is False

    def test_backward_compatibility(self):
        """Test that existing code works without rotation config."""
        # Old code that doesn't specify rotation parameters should still work
        with patch('eab.daemon.ReconnectionManager'):
            with patch('eab.daemon.PatternMatcher'):
                with patch('eab.daemon.AlertLogger'):
                    with patch('eab.daemon.StatusManager'):
                        with patch('eab.daemon.EventEmitter'):
                            with patch('eab.daemon.DataStreamWriter'):
                                with patch('eab.daemon.DeviceController'):
                                    with patch('eab.daemon.ChipRecovery'):
                                        daemon = SerialDaemon(
                                            port="/dev/ttyUSB0", auto_detect=False,
                                            baud=115200,
                                        )

                                        # Should use defaults
                                        config = daemon._session_logger.rotation_config
                                        assert config.max_size_bytes == 100_000_000
                                        assert config.max_files == 5
                                        assert config.compress is True
