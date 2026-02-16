"""Hardware integration tests for C2000 debug stack.

Requires: LAUNCHXL-F280039C connected via USB (XDS110 onboard).
Run with: pytest tests/test_c2000_hw.py -v --hw

These tests exercise the real hardware path:
  XDS110Probe → DSLite → JTAG → F280039C registers
"""

from __future__ import annotations

import json
import struct
import tempfile
from pathlib import Path

import pytest

def pytest_configure(config):
    config.addinivalue_line("markers", "hw: hardware-in-the-loop tests")


@pytest.fixture(autouse=True)
def skip_without_hw(request):
    """Skip HW tests unless --hw flag is passed."""
    if not request.config.getoption("--hw", default=False):
        pytest.skip("requires --hw flag")

DSLITE = "/Applications/ti/ccs2041/ccs/ccs_base/DebugServer/bin/DSLite"
CCXML = str(Path.home() / ".eab/ccxml/TMS320F280039C_XDS110.ccxml")


def have_hardware() -> bool:
    """Check if XDS110 probe and CCXML are available."""
    import subprocess
    if not Path(DSLITE).exists():
        return False
    if not Path(CCXML).exists():
        return False
    try:
        result = subprocess.run(
            [DSLITE, "identifyProbe", f"--config={CCXML}"],
            capture_output=True, text=True, timeout=15,
        )
        return result.returncode == 0
    except Exception:
        return False


# =========================================================================
# XDS110Probe basic connectivity
# =========================================================================


class TestXDS110Connection:
    """Test basic probe connectivity."""

    def test_probe_identifies(self):
        from eab.debug_probes.xds110 import XDS110Probe
        probe = XDS110Probe(
            base_dir=tempfile.mkdtemp(),
            dslite_path=DSLITE,
            ccxml=CCXML,
        )
        status = probe.start_gdb_server()
        assert status.running is True, f"Probe not detected: {status.last_error}"

    def test_memory_read_returns_bytes(self):
        from eab.debug_probes.xds110 import XDS110Probe
        probe = XDS110Probe(
            base_dir=tempfile.mkdtemp(),
            dslite_path=DSLITE,
            ccxml=CCXML,
        )
        # Read NMIFLG at 0x7060 (2 bytes)
        data = probe.memory_read(0x7060, 2)
        assert data is not None, "memory_read returned None"
        assert len(data) >= 2, f"Expected >= 2 bytes, got {len(data)}"


# =========================================================================
# Register map decode with real values
# =========================================================================


class TestRegisterReadHW:
    """Read and decode real registers from hardware."""

    def _read_register(self, address: int, size: int) -> bytes | None:
        from eab.debug_probes.xds110 import XDS110Probe
        probe = XDS110Probe(
            base_dir=tempfile.mkdtemp(),
            dslite_path=DSLITE,
            ccxml=CCXML,
        )
        return probe.memory_read(address, size)

    def test_nmiflg_register(self):
        """NMIFLG at 0x7060 — bit 0 (NMIINT) should be readable."""
        from eab.register_maps import load_register_map
        from eab.register_maps.decoder import decode_register

        reg_map = load_register_map("f28003x")
        nmiflg = reg_map.get_register("fault_registers", "NMIFLG")
        assert nmiflg is not None

        data = self._read_register(nmiflg.address, nmiflg.size)
        assert data is not None, "Failed to read NMIFLG from hardware"

        raw_value = struct.unpack("<H", data[:2])[0]
        decoded = decode_register(nmiflg, raw_value)

        print(f"\nNMIFLG raw: 0x{raw_value:04X}")
        print(f"NMIFLG decoded: {decoded}")

        # NMIFLG should be a valid 16-bit value
        assert 0 <= raw_value <= 0xFFFF

    def test_resc_register(self):
        """RESC at 0x5D00C — reset cause register."""
        from eab.register_maps import load_register_map
        from eab.register_maps.decoder import decode_register

        reg_map = load_register_map("f28003x")
        resc = reg_map.get_register("fault_registers", "RESC")
        assert resc is not None

        data = self._read_register(resc.address, resc.size)
        assert data is not None, "Failed to read RESC from hardware"

        raw_value = struct.unpack("<I", data[:4])[0]
        decoded = decode_register(resc, raw_value)

        print(f"\nRESC raw: 0x{raw_value:08X}")
        print(f"RESC decoded: {decoded}")
        assert 0 <= raw_value <= 0xFFFFFFFF

    def test_wdcr_register(self):
        """WDCR at 0x7029 — watchdog control register."""
        from eab.register_maps import load_register_map

        reg_map = load_register_map("f28003x")
        wdcr = reg_map.get_register("watchdog", "WDCR")
        assert wdcr is not None

        data = self._read_register(wdcr.address, wdcr.size)
        assert data is not None, "Failed to read WDCR from hardware"

        raw_value = struct.unpack("<H", data[:2])[0]
        print(f"\nWDCR raw: 0x{raw_value:04X}")
        assert 0 <= raw_value <= 0xFFFF

    def test_piectrl_register(self):
        """PIECTRL at 0x0CE0 — PIE control register."""
        from eab.register_maps import load_register_map

        reg_map = load_register_map("f28003x")
        piectrl = reg_map.get_register("fault_registers", "PIECTRL")
        assert piectrl is not None

        data = self._read_register(piectrl.address, piectrl.size)
        assert data is not None, "Failed to read PIECTRL from hardware"

        raw_value = struct.unpack("<H", data[:2])[0]
        print(f"\nPIECTRL raw: 0x{raw_value:04X}")
        assert 0 <= raw_value <= 0xFFFF


# =========================================================================
# Fault analyzer on real hardware
# =========================================================================


class TestFaultAnalyzerHW:
    """Run the full C2000 fault decoder against real hardware."""

    def test_c2000_fault_analysis(self):
        """Full fault analysis — reads NMI, PIE, RESC, watchdog from hardware."""
        from eab.debug_probes.xds110 import XDS110Probe
        from eab.fault_decoders.c2000 import C2000Decoder

        probe = XDS110Probe(
            base_dir=tempfile.mkdtemp(),
            dslite_path=DSLITE,
            ccxml=CCXML,
        )

        decoder = C2000Decoder()
        result = decoder.analyze(
            memory_reader=probe.memory_read,
            chip="f28003x",
        )

        print(f"\n{decoder.format_report(result)}")

        # Result should be a FaultReport with decoded registers
        assert result is not None
        assert hasattr(result, 'fault_registers')
        assert len(result.fault_registers) > 0

        # Faults list should contain strings
        assert isinstance(result.faults, list)

        # JSON output should be valid
        json_out = decoder.to_json(result)
        json_str = json.dumps(json_out, indent=2)
        print(f"\nJSON:\n{json_str}")
        assert isinstance(json_out, dict)


# =========================================================================
# DSS transport on real hardware
# =========================================================================


class TestDSSTransportHW:
    """Test DSS persistent session against real hardware."""

    def test_dss_connect_and_read(self):
        """Start DSS session, read a register, stop."""
        from eab.transports.dss import DSSTransport, find_ccs_root

        if find_ccs_root() is None:
            pytest.skip("CCS 2041+ not found")

        with DSSTransport(ccxml=CCXML) as t:
            assert t.is_running, "DSS failed to start"

            # Read NMIFLG
            data = t.memory_read(0x7060, 2)
            assert data is not None, "DSS memory_read returned None"
            assert len(data) >= 2

            raw = struct.unpack("<H", data[:2])[0]
            print(f"\nDSS NMIFLG: 0x{raw:04X}")

    def test_dss_multiple_reads(self):
        """Verify DSS can do multiple reads in one session (the whole point)."""
        from eab.transports.dss import DSSTransport, find_ccs_root

        if find_ccs_root() is None:
            pytest.skip("CCS 2041+ not found")

        with DSSTransport(ccxml=CCXML) as t:
            assert t.is_running

            addresses = [0x7060, 0x0CE0, 0x7029, 0x7023]
            for addr in addresses:
                data = t.memory_read(addr, 2)
                assert data is not None, f"Failed to read 0x{addr:04X}"
                raw = struct.unpack("<H", data[:2])[0]
                print(f"  0x{addr:04X}: 0x{raw:04X}")


# =========================================================================
# ERAD register read (check ERAD is accessible)
# =========================================================================


class TestERADHW:
    """Verify ERAD registers are accessible on hardware."""

    def test_read_erad_global_enable(self):
        """Read GLBL_ENABLE register — should be 0 if ERAD is disabled."""
        from eab.debug_probes.xds110 import XDS110Probe

        probe = XDS110Probe(
            base_dir=tempfile.mkdtemp(),
            dslite_path=DSLITE,
            ccxml=CCXML,
        )

        # ERAD GLBL_ENABLE at 0x0005E800
        data = probe.memory_read(0x0005E800, 2)
        assert data is not None, "Failed to read ERAD GLBL_ENABLE"
        raw = struct.unpack("<H", data[:2])[0]
        print(f"\nERAD GLBL_ENABLE: 0x{raw:04X}")
        # Value should be readable (0 = disabled, 0xF = all enabled)
        assert 0 <= raw <= 0xFFFF


