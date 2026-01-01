# EAB Binary Framing (Proposed Defaults)

This is a **proposed** single‑channel framing format for high‑speed UART streaming.
It is **not** required for normal EAB usage and is only applicable when you can
ship custom firmware. The current EAB log/command protocol remains the default.

## Goals

- High‑speed, best‑effort binary transport (≥ 1MB/s).
- Efficient parsing on MCU and host.
- Optional integrity check (CRC32) with no retransmit.
- Future‑proof for multi‑channel extension (but single‑channel only for now).

## Frame Format (v1 default)

```
SYNC   : 0xA5 0x5A                 (2 bytes)
VER    : 0x01                      (1 byte)
FLAGS  : bit0=CRC32_PRESENT        (1 byte)
TYPE   : 0x01=DATA, 0x02=LOG, 0x03=CTRL (1 byte)
LEN    : payload length, LE uint32 (4 bytes)
PAYLOAD: LEN bytes
CRC32  : optional, LE uint32       (4 bytes)
```

**CRC32 calculation (if enabled):** CRC32 over `VER | FLAGS | TYPE | LEN | PAYLOAD`
using standard IEEE 802.3 polynomial.

**Endianness:** Little‑endian for `LEN` and `CRC32`.

## Defaults

- **SYNC**: `0xA5 0x5A`
- **VER**: `1`
- **FLAGS**: `0x01` (CRC32 present)
- **TYPE**: `0x01` (DATA)
- **Baud**: `2,000,000` (fallback `921,600`)
- **Payload size**: 16–64 KB per frame

## Marker‑armed streaming

When using the daemon’s stream mode, it should be **armed** and start only after
the firmware prints a marker line (e.g., `===DATA_START===`). This avoids
accidental activation during normal logs.

## Non‑goals

- No compatibility with STM32 ASPEP/MCP tools.
- No retransmission / reliable delivery.
- No multi‑channel mux (can be added later by extending `TYPE` or adding `CHAN`).

## Compatibility

- **Stock firmware**: use standard log mode, no binary framing required.
- **Custom firmware**: can optionally enable framed binary streaming for maximum throughput.
