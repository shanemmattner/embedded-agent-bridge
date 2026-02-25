"""C2000 FOC telemetry packet decoder.

Parses raw binary telemetry captured from a C2000 motor controller via the
FTDI UART daemon (written to data.bin in stream-raw mode).

Packet format — 50 bytes (25 × uint16, little-endian):

  Word  0:     0xBB66  (sync; bytes on wire: 0x66, 0xBB)
  Word  1- 2:  pos_ref   float32  position reference (rad)
  Word  3- 4:  theta     float32  mechanical angle (rad)
  Word  5- 6:  iq        float32  quadrature current (A)
  Word  7- 8:  omega     float32  angular velocity (rad/s)
  Word  9-10:  duty      float32  PWM duty cycle
  Word 11:     sysState  uint16   0=IDLE 1=STARTUP 2=RUN 3=FAULT 4=STOP
  Word 12:     faultCode uint16   bitmask
  Word 13-14:  isrCount  uint32   ISR tick counter @ 10 kHz
  Word 15:     hilMode   uint16
  Word 16-17:  hilTickCount uint32
  Word 18-23:  reserved / padding
  Word 24:     XOR checksum (XOR of words 1..23)

Synchronisation: scan for the byte pair 0x66, 0xBB; validate checksum; on
failure advance one byte and retry.
"""

from __future__ import annotations

import math
import struct
from dataclasses import dataclass
from typing import Iterator, Optional

SYNC_WORD: int = 0xBB66
PKT_WORDS: int = 25
PKT_SIZE: int = PKT_WORDS * 2  # 50 bytes

SYS_STATES: dict[int, str] = {
    0: "IDLE",
    1: "STARTUP",
    2: "RUN",
    3: "FAULT",
    4: "STOP",
}

_STRUCT_25H = struct.Struct("<25H")


# ---------------------------------------------------------------------------
# Public data model
# ---------------------------------------------------------------------------


@dataclass
class TelemetryPacket:
    offset: int    # byte offset in stream
    pos_ref: float  # position reference (rad)
    theta: float    # mechanical angle (rad)
    iq: float       # quadrature current (A)
    omega: float    # angular velocity (rad/s)
    duty: float     # PWM duty cycle
    sys_state: str  # IDLE / STARTUP / RUN / FAULT / STOP
    fault_code: int  # fault bitmask
    isr_count: int   # ISR tick count at 10 kHz
    hil_tick: int    # HIL tick count

    def to_dict(self) -> dict:
        """Return JSON-serialisable dict."""
        return {
            "offset": self.offset,
            "pos_ref": self.pos_ref,
            "theta": self.theta,
            "iq": self.iq,
            "omega": self.omega,
            "duty": self.duty,
            "sys_state": self.sys_state,
            "fault_code": self.fault_code,
            "isr_count": self.isr_count,
            "hil_tick": self.hil_tick,
        }


# ---------------------------------------------------------------------------
# Internal helpers
# ---------------------------------------------------------------------------


def _to_f32(w0: int, w1: int) -> float:
    """Reconstruct a float32 from two consecutive little-endian uint16 words."""
    return struct.unpack("<f", struct.pack("<HH", w0, w1))[0]


def _to_u32(w0: int, w1: int) -> int:
    """Reconstruct a uint32 from two consecutive little-endian uint16 words."""
    return w0 | (w1 << 16)


def _parse_words(words: tuple[int, ...], offset: int) -> TelemetryPacket:
    """Convert an already-validated 25-word tuple into a TelemetryPacket."""
    return TelemetryPacket(
        offset=offset,
        pos_ref=_to_f32(words[1], words[2]),
        theta=_to_f32(words[3], words[4]),
        iq=_to_f32(words[5], words[6]),
        omega=_to_f32(words[7], words[8]),
        duty=_to_f32(words[9], words[10]),
        sys_state=SYS_STATES.get(words[11], f"UNKNOWN({words[11]})"),
        fault_code=words[12],
        isr_count=_to_u32(words[13], words[14]),
        hil_tick=_to_u32(words[16], words[17]),
    )


def _xor_checksum(words: tuple[int, ...]) -> int:
    """XOR of words[1..23] (the specification checksum field)."""
    result = 0
    for w in words[1:24]:
        result ^= w
    return result


# ---------------------------------------------------------------------------
# Public decoder
# ---------------------------------------------------------------------------


def decode_packets(data: bytes) -> Iterator[TelemetryPacket]:
    """Decode all valid telemetry packets from raw binary data.

    Scans *data* for the sync marker (0x66, 0xBB), attempts to parse a
    50-byte packet and validates the XOR checksum.  On checksum failure the
    scanner advances one byte and re-tries (re-sync).

    Args:
        data: Raw bytes from data.bin (or any capture buffer).

    Yields:
        :class:`TelemetryPacket` for every packet that passes validation.
    """
    yield from _decode_impl(data, failures_out=None)


def decode_packets_with_stats(
    data: bytes,
) -> tuple[list[TelemetryPacket], int]:
    """Decode all valid packets and also return the checksum failure count.

    This is the internal workhorse used by the CLI command so that the
    summary can report ``checksum_failures``.

    Args:
        data: Raw bytes from data.bin.

    Returns:
        ``(packets, checksum_failures)`` where *checksum_failures* is the
        number of candidate sync positions that were rejected due to a bad
        XOR checksum.
    """
    failures: list[int] = []
    packets = list(_decode_impl(data, failures_out=failures))
    return packets, len(failures)


def _decode_impl(
    data: bytes,
    *,
    failures_out: Optional[list[int]],
) -> Iterator[TelemetryPacket]:
    """Core scanning loop shared by :func:`decode_packets` and
    :func:`decode_packets_with_stats`.
    """
    n = len(data)
    pos = 0

    while pos <= n - PKT_SIZE:
        # Fast path: look for the first sync byte (0x66).
        if data[pos] != 0x66:
            pos += 1
            continue

        # Second sync byte must follow immediately.
        if data[pos + 1] != 0xBB:
            pos += 1
            continue

        # Unpack the candidate packet.
        words: tuple[int, ...] = _STRUCT_25H.unpack_from(data, pos)

        # Redundant guard (should always be true given the byte checks above,
        # but keeps the logic self-contained).
        if words[0] != SYNC_WORD:  # pragma: no cover
            pos += 1
            continue

        # Validate XOR checksum.
        expected = _xor_checksum(words)
        if expected != words[24]:
            if failures_out is not None:
                failures_out.append(pos)
            pos += 1
            continue

        yield _parse_words(words, pos)
        pos += PKT_SIZE


# ---------------------------------------------------------------------------
# Segment splitting (reboot boundaries)
# ---------------------------------------------------------------------------


def split_at_reboots(
    packets: list[TelemetryPacket],
    threshold: int = 100_000,
) -> list[list[TelemetryPacket]]:
    """Split a packet list at reboot boundaries.

    A reboot is detected when the ISR counter goes backwards by more than
    *threshold* ticks between consecutive packets.

    Args:
        packets: Decoded packet list.
        threshold: Minimum backwards ISR jump to trigger a split.

    Returns:
        List of segments, each a list of :class:`TelemetryPacket`.
    """
    if not packets:
        return []
    segments: list[list[TelemetryPacket]] = []
    seg_start = 0
    for j in range(1, len(packets)):
        if packets[j].isr_count < packets[j - 1].isr_count - threshold:
            segments.append(packets[seg_start:j])
            seg_start = j
    segments.append(packets[seg_start:])
    return segments


# ---------------------------------------------------------------------------
# Summary statistics
# ---------------------------------------------------------------------------


def decode_summary(
    packets: list[TelemetryPacket],
    checksum_failures: int = 0,
) -> dict:
    """Generate summary statistics from a decoded packet list.

    Args:
        packets: List of :class:`TelemetryPacket` instances.
        checksum_failures: Number of sync candidates rejected (from
            :func:`decode_packets_with_stats`).

    Returns:
        Dict suitable for JSON serialisation with keys:

        * ``total_packets`` — number of valid packets decoded
        * ``duration_s`` — elapsed time derived from ISR counter
        * ``final_state`` — ``sys_state`` of the last packet
        * ``faults`` — sorted list of unique non-zero fault codes (as hex strings)
        * ``position_error_deg`` — peak |pos_ref − theta| in degrees
        * ``min_theta_deg`` — minimum theta in degrees
        * ``max_theta_deg`` — maximum theta in degrees
        * ``checksum_failures`` — number of packets rejected by checksum
    """
    if not packets:
        return {
            "total_packets": 0,
            "duration_s": 0.0,
            "final_state": "N/A",
            "faults": [],
            "position_error_deg": 0.0,
            "min_theta_deg": 0.0,
            "max_theta_deg": 0.0,
            "checksum_failures": checksum_failures,
        }

    # Use hil_tick for timing if available (more reliable across reboots),
    # otherwise fall back to ISR count.
    first_tick = packets[0].hil_tick or packets[0].isr_count
    last_tick = packets[-1].hil_tick or packets[-1].isr_count
    duration_s = (last_tick - first_tick) / 10_000.0
    # Guard against reboot boundary giving negative duration
    if duration_s < 0:
        duration_s = abs(duration_s)

    rad_to_deg = 180.0 / math.pi

    fault_set: set[str] = set()
    max_pos_err_deg = 0.0
    thetas_deg: list[float] = []

    for pkt in packets:
        if pkt.fault_code != 0:
            fault_set.add(f"0x{pkt.fault_code:04X}")
        err_deg = abs(pkt.pos_ref - pkt.theta) * rad_to_deg
        if err_deg > max_pos_err_deg:
            max_pos_err_deg = err_deg
        thetas_deg.append(pkt.theta * rad_to_deg)

    return {
        "total_packets": len(packets),
        "duration_s": round(duration_s, 4),
        "final_state": packets[-1].sys_state,
        "faults": sorted(fault_set),
        "position_error_deg": round(max_pos_err_deg, 4),
        "min_theta_deg": round(min(thetas_deg), 4),
        "max_theta_deg": round(max(thetas_deg), 4),
        "checksum_failures": checksum_failures,
    }
