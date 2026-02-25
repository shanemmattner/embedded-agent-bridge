"""Unit tests for the C2000 FOC telemetry decoder (eab.analyzers.c2000_telemetry)."""

from __future__ import annotations

import math
import struct

import pytest

from eab.analyzers.c2000_telemetry import (
    PKT_SIZE,
    SYNC_WORD,
    SYS_STATES,
    TelemetryPacket,
    _to_f32,
    _to_u32,
    _xor_checksum,
    decode_packets,
    decode_packets_with_stats,
    decode_summary,
)


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def _make_words(
    *,
    pos_ref: float = 0.0,
    theta: float = 0.0,
    iq: float = 0.0,
    omega: float = 0.0,
    duty: float = 0.0,
    sys_state: int = 0,
    fault_code: int = 0,
    isr_count: int = 0,
    hil_mode: int = 0,
    hil_tick: int = 0,
) -> list[int]:
    """Build a 25-word list (no checksum yet) from field values."""

    def f32_words(v: float) -> tuple[int, int]:
        raw = struct.pack("<f", v)
        return struct.unpack("<HH", raw)  # type: ignore[return-value]

    def u32_words(v: int) -> tuple[int, int]:
        return v & 0xFFFF, (v >> 16) & 0xFFFF

    w1, w2 = f32_words(pos_ref)
    w3, w4 = f32_words(theta)
    w5, w6 = f32_words(iq)
    w7, w8 = f32_words(omega)
    w9, w10 = f32_words(duty)
    w13, w14 = u32_words(isr_count)
    w16, w17 = u32_words(hil_tick)

    return [
        SYNC_WORD,  # word 0
        w1, w2,     # words 1-2  pos_ref
        w3, w4,     # words 3-4  theta
        w5, w6,     # words 5-6  iq
        w7, w8,     # words 7-8  omega
        w9, w10,    # words 9-10 duty
        sys_state,  # word 11
        fault_code, # word 12
        w13, w14,   # words 13-14 isrCount
        hil_mode,   # word 15
        w16, w17,   # words 16-17 hilTickCount
        0, 0, 0, 0, 0, 0,  # words 18-23 reserved
        0,          # word 24 checksum (filled below)
    ]


def _make_packet(
    *,
    pos_ref: float = 0.0,
    theta: float = 0.0,
    iq: float = 0.0,
    omega: float = 0.0,
    duty: float = 0.0,
    sys_state: int = 0,
    fault_code: int = 0,
    isr_count: int = 0,
    hil_mode: int = 0,
    hil_tick: int = 0,
) -> bytes:
    """Build a fully-valid 50-byte telemetry packet."""
    words = _make_words(
        pos_ref=pos_ref,
        theta=theta,
        iq=iq,
        omega=omega,
        duty=duty,
        sys_state=sys_state,
        fault_code=fault_code,
        isr_count=isr_count,
        hil_mode=hil_mode,
        hil_tick=hil_tick,
    )
    # Compute XOR checksum over words[1..23].
    xor = 0
    for w in words[1:24]:
        xor ^= w
    words[24] = xor
    return struct.pack("<25H", *words)


def _corrupt_checksum(pkt: bytes) -> bytes:
    """Flip the checksum word so validation fails."""
    words = list(struct.unpack("<25H", pkt))
    words[24] ^= 0xFFFF  # guaranteed to mismatch
    return struct.pack("<25H", *words)


# ---------------------------------------------------------------------------
# Low-level helper tests
# ---------------------------------------------------------------------------


class TestHelpers:
    def test_to_f32_zero(self):
        assert _to_f32(0, 0) == 0.0

    def test_to_f32_pi_over_4(self):
        val = math.pi / 4
        w0, w1 = struct.unpack("<HH", struct.pack("<f", val))
        assert abs(_to_f32(w0, w1) - val) < 1e-6

    def test_to_u32_low_word_only(self):
        assert _to_u32(42, 0) == 42

    def test_to_u32_high_word(self):
        assert _to_u32(0, 1) == 0x10000

    def test_to_u32_combined(self):
        assert _to_u32(0xABCD, 0x1234) == 0x1234ABCD

    def test_xor_checksum_all_zeros(self):
        words = tuple([0] * 25)
        assert _xor_checksum(words) == 0

    def test_xor_checksum_single_nonzero(self):
        words = [0] * 25
        words[5] = 0xBEEF
        assert _xor_checksum(tuple(words)) == 0xBEEF

    def test_xor_checksum_cancels(self):
        words = [0] * 25
        words[3] = 0x1234
        words[4] = 0x1234
        assert _xor_checksum(tuple(words)) == 0


# ---------------------------------------------------------------------------
# Packet construction round-trip
# ---------------------------------------------------------------------------


class TestMakePacket:
    def test_length(self):
        pkt = _make_packet()
        assert len(pkt) == PKT_SIZE

    def test_sync_bytes_on_wire(self):
        pkt = _make_packet()
        assert pkt[0] == 0x66
        assert pkt[1] == 0xBB

    def test_checksum_valid(self):
        pkt = _make_packet(pos_ref=1.0, theta=0.5, isr_count=100_000)
        words = struct.unpack("<25H", pkt)
        xor = 0
        for w in words[1:24]:
            xor ^= w
        assert xor == words[24]


# ---------------------------------------------------------------------------
# decode_packets — basic cases
# ---------------------------------------------------------------------------


class TestDecodePackets:
    def test_empty_bytes(self):
        assert list(decode_packets(b"")) == []

    def test_short_bytes(self):
        # Less than PKT_SIZE — nothing to decode.
        assert list(decode_packets(b"\x66\xBB" + b"\x00" * 10)) == []

    def test_single_valid_packet(self):
        pkt = _make_packet(pos_ref=math.pi / 4, theta=0.1, sys_state=2)
        packets = list(decode_packets(pkt))
        assert len(packets) == 1
        p = packets[0]
        assert p.offset == 0
        assert abs(p.pos_ref - math.pi / 4) < 1e-5
        assert abs(p.theta - 0.1) < 1e-5
        assert p.sys_state == "RUN"

    def test_two_consecutive_packets(self):
        p1 = _make_packet(isr_count=0, sys_state=1)
        p2 = _make_packet(isr_count=1000, sys_state=2)
        packets = list(decode_packets(p1 + p2))
        assert len(packets) == 2
        assert packets[0].isr_count == 0
        assert packets[1].isr_count == 1000
        assert packets[1].offset == PKT_SIZE

    def test_leading_garbage_resync(self):
        garbage = b"\xFF\xAA\x12\x34\x00\x00"
        pkt = _make_packet(sys_state=3)
        data = garbage + pkt
        packets = list(decode_packets(data))
        assert len(packets) == 1
        assert packets[0].sys_state == "FAULT"
        assert packets[0].offset == len(garbage)

    def test_interleaved_garbage(self):
        p1 = _make_packet(isr_count=100)
        p2 = _make_packet(isr_count=200)
        noise = b"\xDE\xAD\xBE\xEF"
        data = p1 + noise + p2
        packets = list(decode_packets(data))
        assert len(packets) == 2
        assert packets[0].isr_count == 100
        assert packets[1].isr_count == 200

    def test_checksum_failure_skips_and_resyncs(self):
        valid = _make_packet(isr_count=999)
        bad = _corrupt_checksum(_make_packet(isr_count=0))
        # bad packet first, then valid — decoder should skip the bad one.
        data = bad + valid
        packets = list(decode_packets(data))
        assert len(packets) == 1
        assert packets[0].isr_count == 999

    def test_false_sync_in_payload(self):
        # Craft a packet whose payload naturally contains 0x66 0xBB bytes
        # to ensure the decoder doesn't get confused by them.
        # Force the sync bytes into the reserved area by raw manipulation.
        pkt = bytearray(_make_packet())
        # Plant a fake sync at word 20 (bytes 40-41) — inside reserved area.
        pkt[40] = 0x66
        pkt[41] = 0xBB
        # Recompute checksum.
        words = list(struct.unpack("<25H", bytes(pkt)))
        xor = 0
        for w in words[1:24]:
            xor ^= w
        words[24] = xor
        pkt = struct.pack("<25H", *words)
        packets = list(decode_packets(pkt))
        assert len(packets) == 1


# ---------------------------------------------------------------------------
# decode_packets — field extraction
# ---------------------------------------------------------------------------


class TestFieldExtraction:
    def test_sys_state_values(self):
        for code, name in SYS_STATES.items():
            pkt = _make_packet(sys_state=code)
            packets = list(decode_packets(pkt))
            assert packets[0].sys_state == name

    def test_unknown_sys_state(self):
        pkt = _make_packet(sys_state=99)
        packets = list(decode_packets(pkt))
        assert "UNKNOWN" in packets[0].sys_state

    def test_fault_code(self):
        pkt = _make_packet(fault_code=0x0005)
        packets = list(decode_packets(pkt))
        assert packets[0].fault_code == 0x0005

    def test_isr_count(self):
        pkt = _make_packet(isr_count=0x0001_ABCD)
        packets = list(decode_packets(pkt))
        assert packets[0].isr_count == 0x0001_ABCD

    def test_hil_tick(self):
        pkt = _make_packet(hil_tick=0xDEAD_BEEF)
        packets = list(decode_packets(pkt))
        assert packets[0].hil_tick == 0xDEAD_BEEF

    def test_negative_omega(self):
        pkt = _make_packet(omega=-123.45)
        packets = list(decode_packets(pkt))
        assert abs(packets[0].omega - (-123.45)) < 1e-3

    def test_duty_value(self):
        pkt = _make_packet(duty=0.75)
        packets = list(decode_packets(pkt))
        assert abs(packets[0].duty - 0.75) < 1e-6


# ---------------------------------------------------------------------------
# decode_packets_with_stats
# ---------------------------------------------------------------------------


class TestDecodeWithStats:
    def test_no_failures(self):
        pkt = _make_packet()
        packets, failures = decode_packets_with_stats(pkt)
        assert len(packets) == 1
        assert failures == 0

    def test_counts_checksum_failures(self):
        bad = _corrupt_checksum(_make_packet(isr_count=0))
        good = _make_packet(isr_count=500)
        # The bad packet starts with 0x66 0xBB so it will be counted.
        _, failures = decode_packets_with_stats(bad + good)
        assert failures >= 1

    def test_empty_input(self):
        packets, failures = decode_packets_with_stats(b"")
        assert packets == []
        assert failures == 0


# ---------------------------------------------------------------------------
# decode_summary
# ---------------------------------------------------------------------------


class TestDecodeSummary:
    def test_empty_packets(self):
        s = decode_summary([])
        assert s["total_packets"] == 0
        assert s["duration_s"] == 0.0
        assert s["final_state"] == "N/A"
        assert s["faults"] == []

    def test_single_packet_duration_zero(self):
        pkt = _make_packet(isr_count=10_000)
        packets = list(decode_packets(pkt))
        s = decode_summary(packets)
        assert s["total_packets"] == 1
        assert s["duration_s"] == 0.0

    def test_duration_calculation(self):
        p1 = _make_packet(isr_count=0)
        p2 = _make_packet(isr_count=10_000)  # 1 second at 10 kHz
        packets = list(decode_packets(p1 + p2))
        s = decode_summary(packets)
        assert abs(s["duration_s"] - 1.0) < 1e-6

    def test_final_state(self):
        p1 = _make_packet(sys_state=1)
        p2 = _make_packet(sys_state=2)
        packets = list(decode_packets(p1 + p2))
        assert decode_summary(packets)["final_state"] == "RUN"

    def test_faults_empty_when_no_faults(self):
        pkt = _make_packet(fault_code=0)
        packets = list(decode_packets(pkt))
        assert decode_summary(packets)["faults"] == []

    def test_faults_collected(self):
        p1 = _make_packet(fault_code=0x0001)
        p2 = _make_packet(fault_code=0x0002)
        packets = list(decode_packets(p1 + p2))
        s = decode_summary(packets)
        assert "0x0001" in s["faults"]
        assert "0x0002" in s["faults"]

    def test_faults_deduped(self):
        p1 = _make_packet(fault_code=0x000F)
        p2 = _make_packet(fault_code=0x000F)
        packets = list(decode_packets(p1 + p2))
        s = decode_summary(packets)
        assert s["faults"].count("0x000F") == 1

    def test_position_error_degrees(self):
        # pos_ref = π/2, theta = 0  →  error = 90 °
        pkt = _make_packet(pos_ref=math.pi / 2, theta=0.0)
        packets = list(decode_packets(pkt))
        s = decode_summary(packets)
        assert abs(s["position_error_deg"] - 90.0) < 1e-3

    def test_min_max_theta(self):
        p1 = _make_packet(theta=math.radians(10.0))
        p2 = _make_packet(theta=math.radians(80.0))
        packets = list(decode_packets(p1 + p2))
        s = decode_summary(packets)
        assert abs(s["min_theta_deg"] - 10.0) < 1e-3
        assert abs(s["max_theta_deg"] - 80.0) < 1e-3

    def test_checksum_failures_forwarded(self):
        packets: list[TelemetryPacket] = []
        s = decode_summary(packets, checksum_failures=7)
        assert s["checksum_failures"] == 7


# ---------------------------------------------------------------------------
# TelemetryPacket.to_dict
# ---------------------------------------------------------------------------


class TestTelemetryPacketToDict:
    def test_all_keys_present(self):
        pkt = _make_packet(pos_ref=1.0, theta=0.5, sys_state=2, fault_code=3)
        p = list(decode_packets(pkt))[0]
        d = p.to_dict()
        expected_keys = {
            "offset", "pos_ref", "theta", "iq", "omega",
            "duty", "sys_state", "fault_code", "isr_count", "hil_tick",
        }
        assert expected_keys == set(d.keys())

    def test_values_match(self):
        pkt = _make_packet(pos_ref=2.5, sys_state=4, isr_count=12345)
        p = list(decode_packets(pkt))[0]
        d = p.to_dict()
        assert abs(d["pos_ref"] - 2.5) < 1e-5
        assert d["sys_state"] == "STOP"
        assert d["isr_count"] == 12345
