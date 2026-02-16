"""Tests for C2000 fault decoder (Phase 2)."""

from __future__ import annotations

import json

import pytest

from eab.fault_decoders import get_fault_decoder, C2000Decoder
from eab.fault_decoders.base import FaultReport
from eab.fault_decoders.c2000 import C2000Decoder, _generate_c2000_suggestions


# =========================================================================
# Fake memory for testing
# =========================================================================

def _make_memory_reader(register_values: dict[int, int]) -> callable:
    """Create a mock memory reader from address -> value mapping.

    Values are stored as integers and returned as little-endian bytes.
    """
    def reader(address: int, size: int) -> bytes | None:
        if address in register_values:
            return register_values[address].to_bytes(size, "little")
        return None
    return reader


# Register addresses from f28003x.json
NMIFLG = 0x7060
NMISHDFLG = 0x7064
PIECTRL = 0x0CE0
RESC = 0x5D00C
WDCR = 0x7029
WDWCR = 0x7026
WDCNTR = 0x7023


# =========================================================================
# Registry
# =========================================================================


class TestRegistry:
    def test_get_c2000_decoder(self):
        decoder = get_fault_decoder("c2000")
        assert isinstance(decoder, C2000Decoder)

    def test_get_c2000_variant(self):
        decoder = get_fault_decoder("c2000_f280039c")
        assert isinstance(decoder, C2000Decoder)

    def test_name(self):
        decoder = C2000Decoder()
        assert decoder.name == "TI C2000"

    def test_gdb_commands_empty(self):
        decoder = C2000Decoder()
        assert decoder.gdb_commands() == []


# =========================================================================
# Analyze — healthy system
# =========================================================================


class TestAnalyzeHealthy:
    def test_no_faults(self):
        reader = _make_memory_reader({
            NMIFLG: 0x0000,
            NMISHDFLG: 0x0000,
            PIECTRL: 0x0001,  # ENPIE set, no errors
            RESC: 0x0001,     # POR only (normal)
            WDCR: 0x0068,     # WDDIS=1 (disabled), WDCHK=101
            WDWCR: 0x0000,
            WDCNTR: 0x0000,
        })
        decoder = C2000Decoder()
        report = decoder.analyze(reader)

        assert report.arch == "c2000"
        # POR is a "fault" in the report (reset cause) but not an error
        assert any("Reset cause: POR" in f for f in report.faults)
        # No NMI faults
        assert not any("NMI:" in f for f in report.faults)

    def test_watchdog_disabled_suggestion(self):
        reader = _make_memory_reader({
            NMIFLG: 0x0000,
            NMISHDFLG: 0x0000,
            PIECTRL: 0x0001,
            RESC: 0x0001,
            WDCR: 0x0068,  # WDDIS=1
            WDWCR: 0x0000,
            WDCNTR: 0x0000,
        })
        decoder = C2000Decoder()
        report = decoder.analyze(reader)

        assert any("disabled" in s.lower() for s in report.suggestions)


# =========================================================================
# Analyze — NMI faults
# =========================================================================


class TestAnalyzeNMI:
    def test_clock_fail(self):
        reader = _make_memory_reader({
            NMIFLG: 0x0003,    # NMIINT + CLOCKFAIL
            NMISHDFLG: 0x0003,
            PIECTRL: 0x0001,
            RESC: 0x0001,
            WDCR: 0x0068,
            WDWCR: 0x0000,
            WDCNTR: 0x0000,
        })
        decoder = C2000Decoder()
        report = decoder.analyze(reader)

        assert any("CLOCKFAIL" in f for f in report.faults)
        assert any("clock" in s.lower() for s in report.suggestions)

    def test_ram_error(self):
        reader = _make_memory_reader({
            NMIFLG: 0x0005,    # NMIINT + RAMUNCERR
            NMISHDFLG: 0x0005,
            PIECTRL: 0x0001,
            RESC: 0x0001,
            WDCR: 0x0068,
            WDWCR: 0x0000,
            WDCNTR: 0x0000,
        })
        decoder = C2000Decoder()
        report = decoder.analyze(reader)

        assert any("RAMUNCERR" in f for f in report.faults)
        assert any("ram" in s.lower() for s in report.suggestions)

    def test_flash_error(self):
        reader = _make_memory_reader({
            NMIFLG: 0x0009,    # NMIINT + FLUNCERR
            NMISHDFLG: 0x0009,
            PIECTRL: 0x0001,
            RESC: 0x0001,
            WDCR: 0x0068,
            WDWCR: 0x0000,
            WDCNTR: 0x0000,
        })
        decoder = C2000Decoder()
        report = decoder.analyze(reader)

        assert any("FLUNCERR" in f for f in report.faults)
        assert any("flash" in s.lower() for s in report.suggestions)

    def test_pie_vector_error(self):
        reader = _make_memory_reader({
            NMIFLG: 0x0011,    # NMIINT + PIEVECTERR
            NMISHDFLG: 0x0011,
            PIECTRL: 0x0001,
            RESC: 0x0001,
            WDCR: 0x0068,
            WDWCR: 0x0000,
            WDCNTR: 0x0000,
        })
        decoder = C2000Decoder()
        report = decoder.analyze(reader)

        assert any("PIEVECTERR" in f for f in report.faults)
        assert any("pie" in s.lower() for s in report.suggestions)

    def test_shadow_flags_latched(self):
        reader = _make_memory_reader({
            NMIFLG: 0x0000,      # Cleared
            NMISHDFLG: 0x0003,   # But shadow still shows CLOCKFAIL
            PIECTRL: 0x0001,
            RESC: 0x0001,
            WDCR: 0x0068,
            WDWCR: 0x0000,
            WDCNTR: 0x0000,
        })
        decoder = C2000Decoder()
        report = decoder.analyze(reader)

        assert any("shadow" in f.lower() for f in report.faults)


# =========================================================================
# Analyze — reset causes
# =========================================================================


class TestAnalyzeReset:
    def test_watchdog_reset(self):
        reader = _make_memory_reader({
            NMIFLG: 0x0000,
            NMISHDFLG: 0x0000,
            PIECTRL: 0x0001,
            RESC: 0x0004,     # WDRSN
            WDCR: 0x0028,     # WDDIS=0 (enabled), WDCHK=101
            WDWCR: 0x0000,
            WDCNTR: 0x00FF,
        })
        decoder = C2000Decoder()
        report = decoder.analyze(reader)

        assert any("WDRSN" in f for f in report.faults)
        assert any("watchdog" in s.lower() for s in report.suggestions)

    def test_nmi_watchdog_reset(self):
        reader = _make_memory_reader({
            NMIFLG: 0x0000,
            NMISHDFLG: 0x0000,
            PIECTRL: 0x0001,
            RESC: 0x0008,     # NMIWDRSN
            WDCR: 0x0028,
            WDWCR: 0x0000,
            WDCNTR: 0x0000,
        })
        decoder = C2000Decoder()
        report = decoder.analyze(reader)

        assert any("NMIWDRSN" in f for f in report.faults)

    def test_external_reset(self):
        reader = _make_memory_reader({
            NMIFLG: 0x0000,
            NMISHDFLG: 0x0000,
            PIECTRL: 0x0001,
            RESC: 0x0002,     # XRSN
            WDCR: 0x0068,
            WDWCR: 0x0000,
            WDCNTR: 0x0000,
        })
        decoder = C2000Decoder()
        report = decoder.analyze(reader)

        assert any("XRSN" in f for f in report.faults)


# =========================================================================
# Analyze — partial memory reads
# =========================================================================


class TestAnalyzePartialReads:
    def test_some_registers_unreadable(self):
        """Decoder should still work if some registers fail to read."""
        reader = _make_memory_reader({
            NMIFLG: 0x0003,
            # Everything else missing
        })
        decoder = C2000Decoder()
        report = decoder.analyze(reader)

        # Should still decode what it got
        assert "NMIFLG" in report.fault_registers
        assert any("CLOCKFAIL" in f for f in report.faults)

    def test_all_reads_fail(self):
        """Decoder should return empty report if all reads fail."""
        def failing_reader(addr, size):
            return None

        decoder = C2000Decoder()
        report = decoder.analyze(failing_reader)

        assert report.arch == "c2000"
        assert len(report.fault_registers) == 0


# =========================================================================
# Output formatting
# =========================================================================


class TestFormatting:
    def test_format_report(self):
        reader = _make_memory_reader({
            NMIFLG: 0x0003,
            NMISHDFLG: 0x0003,
            PIECTRL: 0x0001,
            RESC: 0x0001,
            WDCR: 0x0068,
            WDWCR: 0x0000,
            WDCNTR: 0x0000,
        })
        decoder = C2000Decoder()
        report = decoder.analyze(reader)
        text = decoder.format_report(report)

        assert "TI C2000" in text
        assert "CLOCKFAIL" in text
        assert "NMIFLG" in text

    def test_to_json(self):
        reader = _make_memory_reader({
            NMIFLG: 0x0003,
            NMISHDFLG: 0x0003,
            PIECTRL: 0x0001,
            RESC: 0x0001,
            WDCR: 0x0068,
            WDWCR: 0x0000,
            WDCNTR: 0x0000,
        })
        decoder = C2000Decoder()
        report = decoder.analyze(reader)
        j = decoder.to_json(report)

        assert j["arch"] == "c2000"
        assert j["has_faults"] is True
        assert isinstance(j["registers"], dict)
        assert isinstance(j["faults"], list)
        # Verify it's JSON-serializable
        json.dumps(j)

    def test_to_json_no_faults(self):
        reader = _make_memory_reader({
            NMIFLG: 0x0000,
            NMISHDFLG: 0x0000,
            PIECTRL: 0x0001,
            RESC: 0x0000,
            WDCR: 0x0068,
            WDWCR: 0x0000,
            WDCNTR: 0x0000,
        })
        decoder = C2000Decoder()
        report = decoder.analyze(reader)
        j = decoder.to_json(report)

        # No NMI or reset faults (RESC=0 means no reset cause bits)
        assert not any("NMI:" in f for f in j["faults"])


# =========================================================================
# Suggestions
# =========================================================================


class TestSuggestions:
    def test_clock_fail_suggestion(self):
        suggestions = _generate_c2000_suggestions(
            nmi_flags=["CLOCKFAIL"],
            reset_flags=[],
            wd_disabled=True,
            wd_flag=False,
        )
        assert any("clock" in s.lower() for s in suggestions)

    def test_watchdog_reset_suggestion(self):
        suggestions = _generate_c2000_suggestions(
            nmi_flags=[],
            reset_flags=["WDRSN"],
            wd_disabled=False,
            wd_flag=True,
        )
        assert any("watchdog" in s.lower() for s in suggestions)

    def test_no_faults_suggestion(self):
        suggestions = _generate_c2000_suggestions(
            nmi_flags=[],
            reset_flags=[],
            wd_disabled=True,
            wd_flag=False,
        )
        # Should still have watchdog status
        assert len(suggestions) > 0
