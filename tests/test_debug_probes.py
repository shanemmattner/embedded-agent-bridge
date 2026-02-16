"""Tests for debug probe abstraction layer.

Tests the probe registry, JLinkProbe wrapper, and OpenOCDProbe config.
"""

from __future__ import annotations

from unittest.mock import MagicMock, patch

import pytest

from eab.debug_probes import get_debug_probe, GDBServerStatus
from eab.debug_probes.base import DebugProbe as DebugProbeABC
from eab.debug_probes.jlink import JLinkProbe
from eab.debug_probes.openocd import OpenOCDProbe


# =============================================================================
# Registry Tests
# =============================================================================

class TestProbeRegistry:
    def test_get_jlink_probe(self, tmp_path):
        """get_debug_probe('jlink') should return JLinkProbe."""
        probe = get_debug_probe("jlink", base_dir=str(tmp_path))
        assert isinstance(probe, JLinkProbe)
        assert probe.name == "J-Link"
        assert probe.gdb_port == 2331

    def test_get_openocd_probe(self, tmp_path):
        """get_debug_probe('openocd') should return OpenOCDProbe."""
        probe = get_debug_probe("openocd", base_dir=str(tmp_path))
        assert isinstance(probe, OpenOCDProbe)
        assert probe.name == "OpenOCD"
        assert probe.gdb_port == 3333

    def test_get_openocd_with_config(self, tmp_path):
        """get_debug_probe('openocd') should accept interface/target kwargs."""
        probe = get_debug_probe(
            "openocd",
            base_dir=str(tmp_path),
            interface_cfg="interface/cmsis-dap.cfg",
            transport="swd",
            gdb_port=4444,
        )
        assert isinstance(probe, OpenOCDProbe)
        assert probe.gdb_port == 4444

    def test_unknown_probe_raises(self, tmp_path):
        """get_debug_probe() should raise ValueError for unknown types."""
        with pytest.raises(ValueError, match="Unknown probe type"):
            get_debug_probe("pyocd", base_dir=str(tmp_path))

    def test_case_insensitive(self, tmp_path):
        """Probe type lookup should be case-insensitive."""
        probe = get_debug_probe("JLink", base_dir=str(tmp_path))
        assert isinstance(probe, JLinkProbe)

    def test_jlink_with_explicit_bridge(self, tmp_path):
        """get_debug_probe('jlink') should use provided bridge."""
        bridge = MagicMock()
        probe = get_debug_probe("jlink", base_dir=str(tmp_path), bridge=bridge)
        assert isinstance(probe, JLinkProbe)
        assert probe.bridge is bridge


# =============================================================================
# JLinkProbe Tests
# =============================================================================

class TestJLinkProbe:
    def test_delegates_start(self):
        """JLinkProbe.start_gdb_server() should delegate to JLinkBridge."""
        bridge = MagicMock()
        bridge_status = MagicMock()
        bridge_status.running = True
        bridge_status.pid = 12345
        bridge_status.port = 2331
        bridge_status.last_error = None
        bridge.start_gdb_server.return_value = bridge_status

        probe = JLinkProbe(bridge)
        status = probe.start_gdb_server(device="NRF5340_XXAA_APP")

        bridge.start_gdb_server.assert_called_once_with(device="NRF5340_XXAA_APP", port=2331)
        assert isinstance(status, GDBServerStatus)
        assert status.running is True
        assert status.port == 2331

    def test_delegates_stop(self):
        """JLinkProbe.stop_gdb_server() should delegate to JLinkBridge."""
        bridge = MagicMock()
        probe = JLinkProbe(bridge)
        probe.stop_gdb_server()
        bridge.stop_gdb_server.assert_called_once()

    def test_custom_port(self):
        """JLinkProbe should respect custom port."""
        bridge = MagicMock()
        probe = JLinkProbe(bridge, port=9999)
        assert probe.gdb_port == 9999

    def test_name(self):
        bridge = MagicMock()
        probe = JLinkProbe(bridge)
        assert probe.name == "J-Link"

    def test_bridge_property(self):
        """Should expose underlying bridge for RTT access."""
        bridge = MagicMock()
        probe = JLinkProbe(bridge)
        assert probe.bridge is bridge


# =============================================================================
# OpenOCDProbe Tests
# =============================================================================

class TestOpenOCDProbe:
    def test_default_ports(self, tmp_path):
        """OpenOCDProbe should use default ports."""
        probe = OpenOCDProbe(str(tmp_path))
        assert probe.gdb_port == 3333
        assert probe.name == "OpenOCD"

    def test_custom_gdb_port(self, tmp_path):
        """OpenOCDProbe should accept custom GDB port."""
        probe = OpenOCDProbe(str(tmp_path), gdb_port=5555)
        assert probe.gdb_port == 5555

    def test_stop_when_not_running(self, tmp_path):
        """stop_gdb_server() should handle no running process gracefully."""
        probe = OpenOCDProbe(str(tmp_path))
        probe.stop_gdb_server()  # Should not raise

    def test_is_debug_probe(self, tmp_path):
        """OpenOCDProbe should be a DebugProbe."""
        probe = OpenOCDProbe(str(tmp_path))
        assert isinstance(probe, DebugProbeABC)

    @patch("eab.debug_probes.openocd.subprocess.Popen")
    @patch("eab.debug_probes.openocd.pid_alive", return_value=True)
    def test_start_builds_cmd(self, mock_alive, mock_popen, tmp_path):
        """start_gdb_server() should build OpenOCD command with config."""
        mock_proc = MagicMock()
        mock_proc.pid = 99999
        mock_proc.poll.return_value = None
        mock_popen.return_value = mock_proc

        probe = OpenOCDProbe(
            str(tmp_path),
            interface_cfg="interface/cmsis-dap.cfg",
            transport="swd",
            extra_commands=["adapter speed 1000"],
        )

        with patch("eab.debug_probes.openocd.time.sleep"):
            status = probe.start_gdb_server(device="MCXN947")

        assert status.running is True
        assert status.port == 3333

        # Verify command includes our config
        call_args = mock_popen.call_args[0][0]
        assert "openocd" in call_args[0]
        assert "interface/cmsis-dap.cfg" in call_args

    @patch("eab.debug_probes.openocd.subprocess.Popen")
    @patch("eab.debug_probes.openocd.pid_alive", return_value=True)
    def test_adapter_serial_injected(self, mock_alive, mock_popen, tmp_path):
        """adapter_serial should inject 'adapter serial' command before interface config."""
        mock_proc = MagicMock()
        mock_proc.pid = 99999
        mock_proc.poll.return_value = None
        mock_popen.return_value = mock_proc

        probe = OpenOCDProbe(
            str(tmp_path),
            interface_cfg="interface/cmsis-dap.cfg",
            adapter_serial="MYSERIAL123",
        )

        with patch("eab.debug_probes.openocd.time.sleep"):
            status = probe.start_gdb_server()

        assert status.running is True
        call_args = mock_popen.call_args[0][0]
        # adapter serial must appear before interface config
        serial_idx = call_args.index("adapter serial MYSERIAL123")
        iface_idx = call_args.index("interface/cmsis-dap.cfg")
        assert serial_idx < iface_idx

    def test_no_adapter_serial_by_default(self, tmp_path):
        """OpenOCDProbe without adapter_serial should not inject adapter serial command."""
        probe = OpenOCDProbe(str(tmp_path))
        assert probe._adapter_serial is None


# =============================================================================
# MCXN947 Decoder Registration
# =============================================================================

class TestMCXN947Registration:
    def test_fault_decoder_registered(self):
        """mcxn947 should resolve to CortexMDecoder."""
        from eab.fault_decoders import get_fault_decoder
        decoder = get_fault_decoder("mcxn947")
        assert decoder.name == "ARM Cortex-M"

    def test_chip_profile_registered(self):
        """zephyr_mcxn947 should resolve to ZephyrProfile."""
        from eab.chips import get_chip_profile
        profile = get_chip_profile("zephyr_mcxn947")
        assert profile.variant == "mcxn947"
        assert profile.board == "frdm_mcxn947/mcxn947/cpu0"
        assert profile.runner == "linkserver"

    def test_openocd_config(self):
        """MCXN947 OpenOCD config should use CMSIS-DAP with inline SWD config."""
        from eab.chips.zephyr import ZephyrProfile
        profile = ZephyrProfile(variant="mcxn947")
        cfg = profile.get_openocd_config()
        assert cfg.interface_cfg == "interface/cmsis-dap.cfg"
        assert cfg.target_cfg is None  # Inline config, no stock target cfg
        assert cfg.transport == "swd"
        assert len(cfg.extra_commands) > 0
        assert any("mcxn947" in cmd for cmd in cfg.extra_commands)
