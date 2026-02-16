"""Tests for register map infrastructure (Phase 1)."""

from __future__ import annotations

import pytest

from eab.register_maps import load_register_map, available_maps
from eab.register_maps.base import BitField, Register, RegisterGroup, RegisterMap
from eab.register_maps.decoder import (
    bytes_to_int,
    decode_register,
    decode_register_bytes,
    decode_group,
)


# =========================================================================
# BitField
# =========================================================================


class TestBitField:
    def test_single_bit_mask(self):
        bf = BitField(name="NMIINT", bit=0)
        assert bf.mask == 0x01
        assert bf.shift == 0

    def test_single_bit_high(self):
        bf = BitField(name="SYSDBGNMI", bit=8)
        assert bf.mask == 0x100
        assert bf.shift == 8

    def test_bit_range_mask(self):
        bf = BitField(name="PIEVECT", bits=(1, 15))
        assert bf.mask == 0xFFFE
        assert bf.shift == 1

    def test_bit_range_small(self):
        bf = BitField(name="BUS_SEL", bits=(0, 3))
        assert bf.mask == 0x0F
        assert bf.shift == 0

    def test_extract_single_bit(self):
        bf = BitField(name="CLOCKFAIL", bit=1)
        assert bf.extract(0b10) == 1
        assert bf.extract(0b01) == 0
        assert bf.extract(0b11) == 1

    def test_extract_bit_range(self):
        bf = BitField(name="BUS_SEL", bits=(0, 3))
        assert bf.extract(0x04) == 4  # VPC
        assert bf.extract(0x05) == 5  # PAB

    def test_decode_with_values(self):
        bf = BitField(name="BUS_SEL", bits=(0, 3), values={"4": "VPC", "5": "PAB"})
        assert bf.decode(0x04) == "VPC"
        assert bf.decode(0x05) == "PAB"
        assert bf.decode(0x0F) == "unknown(15)"

    def test_decode_no_values(self):
        bf = BitField(name="NMIINT", bit=0)
        assert bf.decode(0x01) == 1
        assert bf.decode(0x00) == 0


# =========================================================================
# Register
# =========================================================================


class TestRegister:
    def test_decode_nmiflg(self):
        reg = Register(
            name="NMIFLG",
            address=0x7060,
            size=2,
            bit_fields=[
                BitField(name="NMIINT", bit=0),
                BitField(name="CLOCKFAIL", bit=1),
                BitField(name="RAMUNCERR", bit=2),
            ],
        )
        result = reg.decode(0b101)
        assert result["NMIINT"] == 1
        assert result["CLOCKFAIL"] == 0
        assert result["RAMUNCERR"] == 1

    def test_active_flags(self):
        reg = Register(
            name="NMIFLG",
            address=0x7060,
            size=2,
            bit_fields=[
                BitField(name="NMIINT", bit=0),
                BitField(name="CLOCKFAIL", bit=1),
                BitField(name="RAMUNCERR", bit=2),
            ],
        )
        assert reg.active_flags(0b101) == ["NMIINT", "RAMUNCERR"]
        assert reg.active_flags(0b000) == []

    def test_active_flags_skips_ranges(self):
        """Bit range fields should not appear in active_flags."""
        reg = Register(
            name="PIECTRL",
            address=0x0CE0,
            size=2,
            bit_fields=[
                BitField(name="ENPIE", bit=0),
                BitField(name="PIEVECT", bits=(1, 15)),
            ],
        )
        # PIEVECT has a non-zero value but it's a range, not a flag
        assert reg.active_flags(0xFFFF) == ["ENPIE"]


# =========================================================================
# RegisterMap loading from JSON
# =========================================================================


class TestRegisterMapLoading:
    def test_load_f28003x(self):
        regmap = load_register_map("f28003x")
        assert regmap.chip == "f28003x"
        assert regmap.family == "c2000"
        assert regmap.cpu_freq_hz == 120_000_000

    def test_groups_loaded(self):
        regmap = load_register_map("f28003x")
        assert "fault_registers" in regmap.groups
        assert "watchdog" in regmap.groups
        assert "clock" in regmap.groups
        assert "erad" in regmap.groups

    def test_nmiflg_register(self):
        regmap = load_register_map("f28003x")
        nmiflg = regmap.get_register("fault_registers", "NMIFLG")
        assert nmiflg is not None
        assert nmiflg.address == 0x7060
        assert nmiflg.size == 2
        assert len(nmiflg.bit_fields) == 9

    def test_nmiflg_bit_fields(self):
        regmap = load_register_map("f28003x")
        nmiflg = regmap.get_register("fault_registers", "NMIFLG")
        field_names = {bf.name for bf in nmiflg.bit_fields}
        assert "NMIINT" in field_names
        assert "CLOCKFAIL" in field_names
        assert "RAMUNCERR" in field_names
        assert "PIEVECTERR" in field_names

    def test_resc_register(self):
        regmap = load_register_map("f28003x")
        resc = regmap.get_register("fault_registers", "RESC")
        assert resc is not None
        assert resc.address == 0x5D00C
        assert resc.size == 4

    def test_erad_registers(self):
        regmap = load_register_map("f28003x")
        ebc1 = regmap.get_register("erad", "EBC1_CNTL")
        assert ebc1 is not None
        assert ebc1.address == 0x5E820
        field_names = {bf.name for bf in ebc1.bit_fields}
        assert "BUS_SEL" in field_names
        assert "ENABLE" in field_names

    def test_erad_sec1_cntl(self):
        regmap = load_register_map("f28003x")
        sec1 = regmap.get_register("erad", "SEC1_CNTL")
        assert sec1 is not None
        field_names = {bf.name for bf in sec1.bit_fields}
        assert "MODE" in field_names
        assert "EDGE_LEVEL" in field_names

    def test_watchdog_registers(self):
        regmap = load_register_map("f28003x")
        wdcr = regmap.get_register("watchdog", "WDCR")
        assert wdcr is not None
        assert wdcr.address == 0x7029
        field_names = {bf.name for bf in wdcr.bit_fields}
        assert "WDDIS" in field_names
        assert "WDFLG" in field_names

    def test_clock_registers(self):
        regmap = load_register_map("f28003x")
        clksrc = regmap.get_register("clock", "CLKSRCCTL1")
        assert clksrc is not None
        assert clksrc.address == 0x5D208

    def test_all_registers(self):
        regmap = load_register_map("f28003x")
        all_regs = regmap.all_registers()
        assert len(all_regs) > 20  # We defined 30+ registers

    def test_get_nonexistent_register(self):
        regmap = load_register_map("f28003x")
        assert regmap.get_register("fault_registers", "NONEXISTENT") is None
        assert regmap.get_register("nonexistent_group", "NMIFLG") is None

    def test_file_not_found(self):
        with pytest.raises(FileNotFoundError, match="No register map"):
            load_register_map("nonexistent_chip")

    def test_available_maps(self):
        maps = available_maps()
        assert "f28003x" in maps


# =========================================================================
# Decoder
# =========================================================================


class TestDecoder:
    def test_bytes_to_int_16bit_le(self):
        assert bytes_to_int(b"\x05\x00", 2) == 5
        assert bytes_to_int(b"\xFF\x7F", 2) == 0x7FFF

    def test_bytes_to_int_32bit_le(self):
        assert bytes_to_int(b"\x0C\xD0\x05\x00", 4) == 0x5D00C

    def test_bytes_to_int_short_data(self):
        # Pads with zeros
        assert bytes_to_int(b"\x05", 2) == 5

    def test_decode_register_nmiflg(self):
        regmap = load_register_map("f28003x")
        nmiflg = regmap.get_register("fault_registers", "NMIFLG")
        # NMIINT=1, CLOCKFAIL=1 → bits 0 and 1 set
        decoded = decode_register(nmiflg, 0x0003)
        assert decoded.name == "NMIFLG"
        assert decoded.raw_value == 0x0003
        assert decoded.hex_value == "0x0003"
        assert "NMIINT" in decoded.active_flags
        assert "CLOCKFAIL" in decoded.active_flags

    def test_decode_register_resc(self):
        regmap = load_register_map("f28003x")
        resc = regmap.get_register("fault_registers", "RESC")
        # Watchdog reset: bit 2
        decoded = decode_register(resc, 0x04)
        assert "WDRSN" in decoded.active_flags
        assert "POR" not in decoded.active_flags

    def test_decode_register_bytes(self):
        regmap = load_register_map("f28003x")
        nmiflg = regmap.get_register("fault_registers", "NMIFLG")
        decoded = decode_register_bytes(nmiflg, b"\x03\x00")
        assert decoded.raw_value == 0x0003
        assert "NMIINT" in decoded.active_flags

    def test_decode_erad_bus_sel(self):
        regmap = load_register_map("f28003x")
        ebc1 = regmap.get_register("erad", "EBC1_CNTL")
        # BUS_SEL=4 (VPC) + ENABLE=1 (bit 15)
        decoded = decode_register(ebc1, 0x8004)
        bus_sel_field = next(f for f in decoded.fields if f.name == "BUS_SEL")
        assert bus_sel_field.decoded == "VPC"
        enable_field = next(f for f in decoded.fields if f.name == "ENABLE")
        assert enable_field.is_set is True

    def test_decode_group(self):
        regmap = load_register_map("f28003x")
        wd_group = regmap.get_group("watchdog")

        # Mock memory reader
        fake_memory = {
            0x7029: b"\x68\x00",  # WDCR: WDDIS=1 (bit 6), WDCHK=101 (bits 3-5)
            0x7026: b"\x00\x00",  # WDWCR: all zeros
            0x7023: b"\x42\x00",  # WDCNTR: counter = 0x42
        }

        def mock_reader(addr, size):
            return fake_memory.get(addr)

        results = decode_group(wd_group, mock_reader)
        assert len(results) == 3  # All three watchdog registers
        wdcr = next(r for r in results if r.name == "WDCR")
        assert "WDDIS" in wdcr.active_flags

    def test_decode_group_partial_read(self):
        """If memory_reader returns None for some registers, skip them."""
        regmap = load_register_map("f28003x")
        wd_group = regmap.get_group("watchdog")

        def failing_reader(addr, size):
            if addr == 0x7029:
                return b"\x00\x00"
            return None  # Simulate read failure

        results = decode_group(wd_group, failing_reader)
        assert len(results) == 1  # Only WDCR succeeded

    def test_hex_value_format(self):
        reg = Register(name="TEST16", address=0, size=2)
        decoded = decode_register(reg, 0x0A)
        assert decoded.hex_value == "0x000A"

        reg32 = Register(name="TEST32", address=0, size=4)
        decoded32 = decode_register(reg32, 0x0A)
        assert decoded32.hex_value == "0x0000000A"
