"""Tests for RTT transport ABC and backends (with mocks)."""

from unittest.mock import MagicMock, patch

import pytest

from eab.rtt_transport import RTTTransport, JLinkTransport, ProbeRSTransport, ProbeRsNativeTransport


class TestRTTTransportABC:
    def test_cannot_instantiate_abc(self):
        with pytest.raises(TypeError):
            RTTTransport()

    def test_context_manager_calls_cleanup(self):
        """Verify __exit__ calls stop_rtt and disconnect."""

        class DummyTransport(RTTTransport):
            def __init__(self):
                self.stopped = False
                self.disconnected = False

            def connect(self, device, interface="SWD", speed=4000):
                pass

            def start_rtt(self, block_address=None):
                return 1

            def read(self, channel, max_bytes=4096):
                return b""

            def write(self, channel, data):
                return 0

            def stop_rtt(self):
                self.stopped = True

            def disconnect(self):
                self.disconnected = True

            def reset(self, halt=False):
                pass

        t = DummyTransport()
        with t:
            pass
        assert t.stopped
        assert t.disconnected


class TestJLinkTransport:
    def test_connect_requires_pylink(self):
        transport = JLinkTransport()
        with patch.dict("sys.modules", {"pylink": None}):
            with pytest.raises(ImportError, match="pylink-square"):
                transport.connect("NRF5340_XXAA_APP")

    def test_connect_and_start(self):
        mock_pylink = MagicMock()
        mock_jlink = MagicMock()
        mock_pylink.JLink.return_value = mock_jlink
        mock_pylink.enums.JLinkInterfaces.SWD = 1
        mock_jlink.rtt_get_num_up_buffers.return_value = 3

        with patch.dict("sys.modules", {"pylink": mock_pylink}):
            transport = JLinkTransport()
            transport.connect("NRF5340_XXAA_APP", "SWD", 4000)

            mock_jlink.open.assert_called_once()
            mock_jlink.connect.assert_called_once_with("NRF5340_XXAA_APP", speed=4000)

            num_up = transport.start_rtt()
            assert num_up == 3
            mock_jlink.rtt_start.assert_called_once()

    def test_read_returns_bytes(self):
        mock_pylink = MagicMock()
        mock_jlink = MagicMock()
        mock_pylink.JLink.return_value = mock_jlink
        mock_pylink.enums.JLinkInterfaces.SWD = 1
        mock_jlink.rtt_read.return_value = [0x41, 0x42, 0x43]
        mock_jlink.rtt_get_num_up_buffers.return_value = 1

        with patch.dict("sys.modules", {"pylink": mock_pylink}):
            transport = JLinkTransport()
            transport.connect("NRF5340_XXAA_APP")
            transport.start_rtt()
            data = transport.read(0)
            assert data == b"ABC"

    def test_read_empty(self):
        transport = JLinkTransport()
        # Not connected → should return empty
        assert transport.read(0) == b""

    def test_write_returns_count(self):
        mock_pylink = MagicMock()
        mock_jlink = MagicMock()
        mock_pylink.JLink.return_value = mock_jlink
        mock_pylink.enums.JLinkInterfaces.SWD = 1
        mock_jlink.rtt_write.return_value = 3
        mock_jlink.rtt_get_num_up_buffers.return_value = 1

        with patch.dict("sys.modules", {"pylink": mock_pylink}):
            transport = JLinkTransport()
            transport.connect("TEST")
            transport.start_rtt()
            n = transport.write(0, b"ABC")
            assert n == 3
            mock_jlink.rtt_write.assert_called_once_with(0, [0x41, 0x42, 0x43])

    def test_disconnect(self):
        mock_pylink = MagicMock()
        mock_jlink = MagicMock()
        mock_pylink.JLink.return_value = mock_jlink
        mock_pylink.enums.JLinkInterfaces.SWD = 1
        mock_jlink.rtt_get_num_up_buffers.return_value = 1

        with patch.dict("sys.modules", {"pylink": mock_pylink}):
            transport = JLinkTransport()
            transport.connect("TEST")
            transport.disconnect()
            mock_jlink.close.assert_called_once()
            assert transport._jlink is None


class TestProbeRSTransport:
    def test_connect_requires_binary(self):
        transport = ProbeRSTransport()
        transport._bin = None
        with pytest.raises(FileNotFoundError, match="probe-rs not found"):
            transport.connect("nrf52840")

    def test_read_without_proc_returns_empty(self):
        transport = ProbeRSTransport()
        assert transport.read(0) == b""

    def test_write_returns_zero(self):
        transport = ProbeRSTransport()
        assert transport.write(0, b"test") == 0

    def test_stop_rtt_noop_when_not_running(self):
        transport = ProbeRSTransport()
        transport.stop_rtt()  # Should not raise


class TestProbeRsNativeTransport:
    """Tests for ProbeRsNativeTransport (native Rust extension).

    These tests require the eab-probe-rs extension to be built and installed.
    If not available, tests will be skipped with ImportError.
    """

    def test_connect_requires_extension(self):
        """Verify helpful error when Rust extension not installed."""
        with patch.dict("sys.modules", {"eab_probe_rs": None}):
            transport = ProbeRsNativeTransport()
            with pytest.raises(ImportError, match="eab-probe-rs Rust extension"):
                transport.connect("STM32L476RG")

    def test_read_without_session_returns_empty(self):
        """Verify read() returns empty bytes when not connected."""
        transport = ProbeRsNativeTransport()
        assert transport.read(0) == b""

    def test_write_without_session_returns_zero(self):
        """Verify write() returns 0 when not connected."""
        transport = ProbeRsNativeTransport()
        assert transport.write(0, b"test") == 0

    def test_disconnect_without_session(self):
        """Verify disconnect() is safe even when not connected."""
        transport = ProbeRsNativeTransport()
        transport.disconnect()  # Should not raise

    def test_reset_without_session_raises(self):
        """Verify reset() raises when not connected."""
        transport = ProbeRsNativeTransport()
        with pytest.raises(RuntimeError, match="Not connected"):
            transport.reset()

    @patch("eab.rtt_transport.logger")
    def test_read_logs_errors(self, mock_logger):
        """Verify read errors are logged gracefully."""
        transport = ProbeRsNativeTransport()
        mock_session = MagicMock()
        mock_session.rtt_read.side_effect = RuntimeError("RTT error")
        transport._session = mock_session

        data = transport.read(0)
        assert data == b""  # Returns empty on error
        mock_logger.error.assert_called_once()

    @patch("eab.rtt_transport.logger")
    def test_write_logs_errors(self, mock_logger):
        """Verify write errors are logged gracefully."""
        transport = ProbeRsNativeTransport()
        mock_session = MagicMock()
        mock_session.rtt_write.side_effect = RuntimeError("RTT error")
        transport._session = mock_session

        written = transport.write(0, b"test")
        assert written == 0  # Returns 0 on error
        mock_logger.error.assert_called_once()
