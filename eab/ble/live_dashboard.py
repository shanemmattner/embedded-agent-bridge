"""BLE Test Lab Live Dashboard — real-time RTT + BLE log streaming with charts.

Async server using websockets (same pattern as eab/plotter/server.py):
- Tails RTT log file for firmware-side events
- Runs BleakCentral with event hooks for Python-side BLE operations
- Broadcasts both streams + parsed chart data to all connected browsers
- Accepts control commands (scan, connect, disconnect, write, etc.) via WebSocket
- Generates synthetic RTT log lines from BLE events when no real RTT source

Features:
  1. Rate Selector    — writes rate enum (0x00/0x01/0x02) to Config char (EAB10002)
  2. Notification Burst — writes CMD_BURST (0x02) to Command char (EAB10003)
  3. Status Decode    — reads Status char (EAB10004) and decodes bitfield flags
  4. RTT Simulation   — generates firmware-style log lines from BLE events
  5. Connection Stats — reports MTU, services, characteristics after connect
  6. Sine/Cosine Chart — derives waveforms from counter for live visualization

Usage:
    python3 -m eab.ble.live_dashboard --port 8860 --rtt-log /tmp/eab-devices/default/rtt-raw.log
"""

from __future__ import annotations

import argparse
import asyncio
import json
import math
import os
import re
import sys
import time
from pathlib import Path
from typing import Optional

try:
    import websockets
    from websockets.http11 import Response
    from websockets.datastructures import Headers
except ImportError:
    websockets = None  # type: ignore[assignment]

from eab.ble.bleak_central import BleakCentral, BleakCentralError

# ---------------------------------------------------------------------------
# Constants
# ---------------------------------------------------------------------------

_BUFFER_CAP = 65536
_HEARTBEAT_INTERVAL = 2.0
_CLIENT_SEND_TIMEOUT = 5.0
_DEFAULT_PORT = 8860
_DEFAULT_TARGET = "EAB-Test"
_DEFAULT_RTT_LOG = "/tmp/eab-devices/default/rtt-raw.log"

# ---------------------------------------------------------------------------
# GATT UUID map — matches firmware test_service.h / test_service.c
#
#   EAB10000  Service
#   EAB10001  Sensor Data  (READ + NOTIFY)  — uint32_t counter, LE
#   EAB10002  Config       (READ + WRITE)   — notification rate enum
#   EAB10003  Command      (WRITE)          — command endpoint
#   EAB10004  Status       (READ)           — device status bitfield
# ---------------------------------------------------------------------------

_UUID_BASE = "0001-1000-8000-00805f9b34fb"

UUID_SENSOR  = f"eab10001-{_UUID_BASE}"  # Notify + Read (counter value)
UUID_CONFIG  = f"eab10002-{_UUID_BASE}"  # Read + Write (rate: 0=100ms, 1=500ms, 2=1s)
UUID_COMMAND = f"eab10003-{_UUID_BASE}"  # Write-only (commands: 0x01=reset, 0x02=burst)
UUID_STATUS  = f"eab10004-{_UUID_BASE}"  # Read-only (status flags bitfield)

# Command values (from test_service.h: enum test_svc_cmd)
CMD_RESET_COUNTER = "01"  # TEST_SVC_CMD_RESET_COUNTER
CMD_NOTIFY_BURST  = "02"  # TEST_SVC_CMD_NOTIFY_BURST
CMD_CRASH         = "03"  # TEST_SVC_CMD_CRASH (intentional fault)

# Rate values (from test_service.h: enum test_svc_rate)
RATE_100MS  = "00"  # TEST_SVC_RATE_100MS
RATE_500MS  = "01"  # TEST_SVC_RATE_500MS
RATE_1000MS = "02"  # TEST_SVC_RATE_1000MS

RATE_LABELS = {
    "00": "100 ms",
    "01": "500 ms",
    "02": "1000 ms",
}

# Status flag bits (from test_service.h)
STATUS_ADVERTISING = 0x01  # BIT(0) — TEST_SVC_STATUS_ADVERTISING
STATUS_CONNECTED   = 0x02  # BIT(1) — TEST_SVC_STATUS_CONNECTED
STATUS_NOTIFYING   = 0x04  # BIT(2) — TEST_SVC_STATUS_NOTIFYING

# Regex to extract counter value from RTT NOTIFY lines like: [BLE] NOTIFY: counter=42
_COUNTER_RE = re.compile(r"counter[=:]\s*(\d+)", re.IGNORECASE)
# Regex to extract RSSI from RTT lines like: RSSI: -42 dBm
_RSSI_RE = re.compile(r"RSSI[=:]\s*(-?\d+)", re.IGNORECASE)

# ---------------------------------------------------------------------------
# HTML path
# ---------------------------------------------------------------------------

_HTML_PATH = Path(__file__).parent / "dashboard.html"

# ---------------------------------------------------------------------------
# Queue helpers
# ---------------------------------------------------------------------------


def _enqueue(queue: asyncio.Queue, item: dict):
    """Non-blocking enqueue with overflow protection (drop oldest on full)."""
    try:
        queue.put_nowait(item)
    except asyncio.QueueFull:
        try:
            queue.get_nowait()
        except asyncio.QueueEmpty:
            pass
        try:
            queue.put_nowait(item)
        except asyncio.QueueFull:
            pass


# ---------------------------------------------------------------------------
# RTT log tailer
# ---------------------------------------------------------------------------


async def tail_rtt_log(path: str, queue: asyncio.Queue, poll_interval: float = 0.1):
    """Tail the RTT raw log file and push lines + chart data to the queue.

    Handles file truncation (log rotation) and missing files gracefully.
    Extracts counter values, RSSI, and connection events for chart plotting.
    """
    pos = 0
    if os.path.exists(path):
        pos = os.path.getsize(path)

    while True:
        try:
            size = os.path.getsize(path) if os.path.exists(path) else 0
        except OSError:
            await asyncio.sleep(poll_interval)
            continue

        if size < pos:
            pos = 0  # File truncated — start from beginning

        if size > pos:
            try:
                with open(path, "r", encoding="utf-8", errors="replace") as f:
                    f.seek(pos)
                    chunk = f.read()
                    pos = f.tell()
            except OSError:
                await asyncio.sleep(poll_interval)
                continue

            if len(chunk) > _BUFFER_CAP:
                chunk = chunk[-_BUFFER_CAP:]

            for line in chunk.splitlines():
                line = line.strip()
                if not line:
                    continue

                # Push RTT log line to all browsers
                _enqueue(queue, {"type": "rtt_log", "line": line, "ts": time.time()})

                # Detect connection events for timeline chart
                ll = line.lower()
                if "connected" in ll and "disconnect" not in ll:
                    _enqueue(queue, {
                        "type": "data",
                        "series": "conn_event",
                        "value": 1,
                        "ts": time.time(),
                    })
                elif "disconnect" in ll:
                    _enqueue(queue, {
                        "type": "data",
                        "series": "conn_event",
                        "value": 0,
                        "ts": time.time(),
                    })
        else:
            await asyncio.sleep(poll_interval)


# ---------------------------------------------------------------------------
# RTT Simulator — generates synthetic firmware-side logs from BLE events
# ---------------------------------------------------------------------------


class RttSimulator:
    """Generates synthetic RTT-style log lines that mirror what the nRF5340
    firmware would output over J-Link RTT.

    This provides a realistic firmware-side view in the RTT log pane even
    when no real RTT source is connected.  Each method matches a firmware
    log pattern from ``test_service.c`` and ``main.c``.
    """

    def __init__(self, queue: asyncio.Queue):
        self._queue = queue
        self._counter = 0
        self._rate_ms = 100
        self._t0 = time.time()

    def _ts(self) -> str:
        """Firmware-style uptime timestamp [HH:MM:SS]."""
        elapsed = int(time.time() - self._t0)
        h, r = divmod(elapsed, 3600)
        m, s = divmod(r, 60)
        return f"[{h:02d}:{m:02d}:{s:02d}]"

    def _emit(self, line: str):
        """Push a synthetic RTT log line to the broadcast queue."""
        _enqueue(self._queue, {"type": "rtt_log", "line": line, "ts": time.time()})

    # --- Simulated firmware events ---

    def advertising_started(self):
        """Simulate: [BLE] ADVERTISING started"""
        self._emit(f"{self._ts()} [BLE] ADVERTISING started")

    def connected(self, peer: str = "AA:BB:CC:DD:EE:FF"):
        """Simulate: [BLE] CONNECTED peer=..."""
        self._emit(f"{self._ts()} [BLE] CONNECTED peer={peer}")

    def disconnected(self, reason: int = 0x13):
        """Simulate: [BLE] DISCONNECTED reason=0x13"""
        self._emit(f"{self._ts()} [BLE] DISCONNECTED reason=0x{reason:02x}")
        # Firmware re-starts advertising after disconnect
        self.advertising_started()

    def ccc_enabled(self):
        """Simulate: [BLE] CCC notifications enabled"""
        self._emit(f"{self._ts()} [BLE] CCC notifications enabled")

    def ccc_disabled(self):
        """Simulate: [BLE] CCC notifications disabled"""
        self._emit(f"{self._ts()} [BLE] CCC notifications disabled")

    def notify(self, counter: int):
        """Simulate: [BLE] NOTIFY char=EAB10001 len=4"""
        self._counter = counter
        self._emit(f"{self._ts()} [BLE] NOTIFY char=EAB10001 len=4")

    def write_config(self, rate_byte: str):
        """Simulate: [BLE] WRITE char=EAB10002 len=1 value=XX"""
        self._emit(f"{self._ts()} [BLE] WRITE char=EAB10002 len=1 value={rate_byte}")
        rate_ms = {0: 100, 1: 500, 2: 1000}.get(int(rate_byte, 16), 100)
        self._rate_ms = rate_ms

    def write_command(self, cmd_byte: str):
        """Simulate: [BLE] WRITE char=EAB10003 len=1 value=XX"""
        self._emit(f"{self._ts()} [BLE] WRITE char=EAB10003 len=1 value={cmd_byte}")
        cmd = int(cmd_byte, 16)
        if cmd == 0x01:
            self._emit(f"{self._ts()} [BLE] Counter reset to 0")
            self._counter = 0
        elif cmd == 0x02:
            self._emit(f"{self._ts()} [BLE] Triggering notification burst (10x)")
            # Simulate the 10 rapid notifications the firmware sends
            for _ in range(10):
                self._counter += 1
                self._emit(f"{self._ts()} [BLE] NOTIFY char=EAB10001 len=4")
        elif cmd == 0x03:
            self._emit(f"{self._ts()} [BLE] Intentional crash triggered!")

    def status_read(self, flags: int):
        """Simulate: [BLE] READ char=EAB10004 status=0xXX"""
        self._emit(f"{self._ts()} [BLE] READ char=EAB10004 status=0x{flags:02x}")


# ---------------------------------------------------------------------------
# Status decoder — interprets the Status characteristic bitfield
# ---------------------------------------------------------------------------


def decode_status_flags(hex_val: str) -> dict:
    """Decode the Status characteristic (EAB10004) bitfield.

    The firmware's test_service.h defines:
      BIT(0) = advertising
      BIT(1) = connected
      BIT(2) = notifying

    Parameters
    ----------
    hex_val:
        Hex string from a read of the Status characteristic.

    Returns
    -------
    dict
        ``{"raw": "0x07", "flags": ["advertising", "connected", "notifying"]}``
    """
    try:
        val = int(hex_val, 16)
    except (ValueError, TypeError):
        return {"raw": hex_val, "flags": [], "error": "invalid hex"}

    flags = []
    if val & STATUS_ADVERTISING:
        flags.append("advertising")
    if val & STATUS_CONNECTED:
        flags.append("connected")
    if val & STATUS_NOTIFYING:
        flags.append("notifying")

    return {"raw": f"0x{val:02X}", "flags": flags}


# ---------------------------------------------------------------------------
# Connection stats — extract MTU, services, characteristics after connect
# ---------------------------------------------------------------------------


def get_connection_stats(central: BleakCentral) -> dict:
    """Gather connection statistics from a connected BleakCentral.

    Returns
    -------
    dict
        ``{"mtu": 247, "services": 3, "characteristics": 10, "details": [...]}``
    """
    stats = {"mtu": None, "services": 0, "characteristics": 0, "details": []}

    if not central.is_connected or central._client is None:
        return stats

    # MTU (bleak exposes this on the client)
    try:
        stats["mtu"] = central._client.mtu_size
    except (AttributeError, Exception):
        stats["mtu"] = None

    # Service / characteristic counts
    svc_map = central.services
    stats["services"] = len(svc_map)
    total_chars = sum(len(chars) for chars in svc_map.values())
    stats["characteristics"] = total_chars

    # Detailed service list for the stats bar
    for svc_uuid, chars in svc_map.items():
        stats["details"].append({
            "service": svc_uuid,
            "chars": len(chars),
        })

    return stats


# ---------------------------------------------------------------------------
# BLE controller — routes browser commands to BleakCentral
# ---------------------------------------------------------------------------


class BleController:
    """Wraps BleakCentral and pushes events to the broadcast queue.

    Uses a simple state machine to control which actions are valid:

        idle ──scan──▸ scanned ──connect──▸ connected ──subscribe──▸ subscribed
          ▲                                     │    ◂──unsubscribe──┘
          └──────────disconnect──────────────────┘

    Each state defines which buttons the browser should enable.
    Invalid actions for the current state are rejected with a clear message.
    The test suite bypasses the state machine (manages its own lifecycle).
    """

    # States and their allowed actions
    STATES = {
        "idle":       {"scan", "run_tests"},
        "scanned":    {"scan", "connect", "run_tests"},
        "connected":  {"disconnect", "subscribe", "read", "read_status",
                       "set_rate", "burst", "get_conn_stats",
                       "run_tests"},
        "subscribed": {"disconnect", "unsubscribe", "read", "read_status",
                       "set_rate", "burst", "get_conn_stats",
                       "run_tests"},
    }

    # Friendly names for known characteristic UUIDs
    _CHAR_NAMES = {
        "eab10001": "Counter",
        "eab10002": "Config",
        "eab10003": "Command",
        "eab10004": "Status",
    }

    def __init__(self, queue: asyncio.Queue, target_name: str, rtt_sim: RttSimulator):
        self._queue = queue
        self._target_name = target_name
        self._central = BleakCentral(event_callback=self._on_event)
        self._rtt_sim = rtt_sim
        self._notify_count = 0
        self._current_rate = "00"  # Track current rate setting
        self._state = "idle"
        # UUIDs whose write/read events are suppressed in _on_event because
        # the high-level command handler already logs a more descriptive line
        # (e.g. "CMD Reset Counter" instead of raw "WRITE Command <- 1").
        self._suppress_event_uuids: set[str] = set()

    def _char_name(self, uuid: str) -> str:
        """Map UUID to friendly name (e.g. 'eab10001-...' → 'Counter')."""
        prefix = uuid[:8].lower()
        return self._CHAR_NAMES.get(prefix, uuid[:13] + "...")

    def _ts(self) -> str:
        """Short timestamp for log lines (HH:MM:SS.mmm)."""
        from datetime import datetime
        return datetime.now().strftime("%H:%M:%S.%f")[:-3]

    def _decode_counter(self, hex_payload: str) -> int | None:
        """Decode little-endian uint32 counter from hex string."""
        try:
            return int.from_bytes(bytes.fromhex(hex_payload), byteorder="little")
        except (ValueError, TypeError):
            return None

    def _on_event(self, event: dict):
        """Event callback from BleakCentral — formats and logs each BLE event.

        Also drives the RTT simulator to generate matching firmware-side logs.
        """
        etype = event["type"]
        detail = event["detail"]
        ts = self._ts()

        if etype == "notification":
            self._notify_count += 1
            # Parse "uuid: hex_payload" format from BleakCentral._emit
            parts = detail.split(": ", 1)
            uuid_part = parts[0] if len(parts) > 1 else ""
            hex_part = parts[1].strip() if len(parts) > 1 else detail
            name = self._char_name(uuid_part)
            value = self._decode_counter(hex_part)
            if value is not None:
                # Derive sine/cosine waveforms from counter for a compelling chart
                # Period of 50 samples → visible oscillation at any notification rate
                phase = value * 2.0 * math.pi / 50.0
                sin_val = round(math.sin(phase) * 100, 1)
                cos_val = round(math.cos(phase) * 100, 1)
                self._log(f"{ts}  NOTIFY  {name} = {value}  "
                          f"sin={sin_val:+.0f} cos={cos_val:+.0f}")
                _enqueue(self._queue, {
                    "type": "data", "series": "sin",
                    "value": sin_val, "ts": event["ts"],
                })
                _enqueue(self._queue, {
                    "type": "data", "series": "cos",
                    "value": cos_val, "ts": event["ts"],
                })
                # Mirror to RTT simulator
                self._rtt_sim.notify(value)
            else:
                self._log(f"{ts}  NOTIFY  {name}: {hex_part}")

        elif etype == "scan_found":
            self._log(f"{ts}  FOUND   {detail}")

        elif etype == "connected":
            addr_short = detail[:8] + "..." if len(detail) > 12 else detail
            self._log(f"{ts}  CONN    {self._target_name} ({addr_short})")
            _enqueue(self._queue, {"type": "data", "series": "conn_event", "value": 1, "ts": event["ts"]})
            # Mirror to RTT simulator
            self._rtt_sim.connected()

        elif etype == "disconnected":
            self._log(f"{ts}  DISCON  link terminated")
            _enqueue(self._queue, {"type": "data", "series": "conn_event", "value": 0, "ts": event["ts"]})
            # Mirror to RTT simulator
            self._rtt_sim.disconnected()

        elif etype == "subscribed":
            name = self._char_name(detail)
            self._log(f"{ts}  SUB     notifications enabled on {name}")
            self._rtt_sim.ccc_enabled()

        elif etype == "write":
            parts = detail.split(": ", 1)
            uuid_part = parts[0] if len(parts) > 1 else ""
            val = parts[1].strip() if len(parts) > 1 else detail
            # Skip logging if the command handler already logged a higher-level line
            if uuid_part.lower() in self._suppress_event_uuids:
                self._suppress_event_uuids.discard(uuid_part.lower())
                return
            name = self._char_name(uuid_part)
            decoded = self._decode_counter(val)
            if decoded is not None:
                self._log(f"{ts}  WRITE   {name} <- {decoded}  (0x{decoded:04X})")
            else:
                self._log(f"{ts}  WRITE   {name} <- 0x{val}")

        elif etype == "read":
            parts = detail.split(": ", 1)
            uuid_part = parts[0] if len(parts) > 1 else ""
            val = parts[1].strip() if len(parts) > 1 else detail
            # Skip logging if the command handler already logged a higher-level line
            if uuid_part.lower() in self._suppress_event_uuids:
                self._suppress_event_uuids.discard(uuid_part.lower())
                return
            name = self._char_name(uuid_part)
            decoded = self._decode_counter(val)
            if decoded is not None:
                self._log(f"{ts}  READ    {name} = {decoded}  (0x{decoded:04X})")
            else:
                self._log(f"{ts}  READ    {name} = 0x{val}")

        else:
            self._log(f"{ts}  {etype.upper():7s} {detail}")

    def _log(self, msg: str):
        """Push a BLE log line to all connected browsers."""
        _enqueue(self._queue, {"type": "ble_log", "line": msg, "ts": time.time()})

    def _status(self, msg: str):
        """Push a status update to all connected browsers."""
        _enqueue(self._queue, {"type": "status", "message": msg})

    def _set_state(self, new_state: str):
        """Transition to a new state and notify all browsers."""
        self._state = new_state
        allowed = sorted(self.STATES.get(new_state, set()))
        _enqueue(self._queue, {
            "type": "state_change",
            "state": new_state,
            "allowed": allowed,
        })

    async def handle_command(self, cmd: dict) -> dict:
        """Handle a command from the browser. Returns {ok, message, ...}.

        Validates action against current state machine before executing.
        """
        action = cmd.get("action", "")
        ts = self._ts()

        # State gate — reject actions not allowed in current state
        allowed = self.STATES.get(self._state, set())
        if action not in allowed:
            msg = f"Cannot '{action}' in state '{self._state}'"
            self._log(f"{ts}  BLOCKED {msg}")
            return {"ok": False, "message": msg, "state": self._state}

        try:
            if action == "scan":
                self._log(f"{ts}  SCAN    searching for '{self._target_name}'...")
                self._status("Scanning...")
                self._rtt_sim.advertising_started()
                addr = await self._central.scan(self._target_name, timeout=15)
                self._set_state("scanned")
                return {"ok": True, "message": f"Found {self._target_name}"}

            elif action == "connect":
                self._log(f"{ts}  CONN    initiating BLE connection...")
                self._status("Connecting...")
                await self._central.connect()
                stats = get_connection_stats(self._central)
                ts2 = self._ts()
                mtu_str = f"MTU={stats['mtu']}" if stats["mtu"] else "MTU=unknown"
                self._log(f"{ts2}  STATS   {mtu_str}, "
                          f"{stats['services']} services, "
                          f"{stats['characteristics']} characteristics")
                self._set_state("connected")
                self._status("Connected")
                return {"ok": True, "message": "Connected", "conn_stats": stats}

            elif action == "disconnect":
                self._log(f"{ts}  DISCON  requesting disconnect...")
                await self._central.disconnect()
                self._notify_count = 0
                self._set_state("idle")
                self._status("Disconnected")
                return {"ok": True, "message": "Disconnected"}

            elif action == "subscribe":
                name = self._char_name(UUID_SENSOR)
                self._log(f"{ts}  SUB     enabling notifications on {name}...")
                self._notify_count = 0
                await self._central.subscribe(UUID_SENSOR)
                self._set_state("subscribed")
                return {"ok": True, "message": f"Subscribed to {name}"}

            elif action == "unsubscribe":
                name = self._char_name(UUID_SENSOR)
                self._log(f"{ts}  UNSUB   disabling notifications on {name}...")
                if self._central._client:
                    await self._central._client.stop_notify(UUID_SENSOR)
                    self._central._notifications.pop(UUID_SENSOR.lower(), None)
                    self._central._notify_events.pop(UUID_SENSOR.lower(), None)
                self._log(f"{ts}  UNSUB   {name} stopped ({self._notify_count} received)")
                self._rtt_sim.ccc_disabled()
                self._notify_count = 0
                self._set_state("connected")
                return {"ok": True, "message": f"Unsubscribed from {name}"}

            elif action == "read":
                uuid = cmd.get("uuid", UUID_SENSOR)
                val = await self._central.read(uuid)
                decoded = self._decode_counter(val)
                name = self._char_name(uuid)
                display = f"{decoded} (0x{decoded:04X})" if decoded is not None else f"0x{val}"
                return {"ok": True, "message": f"{name}: {display}"}

            elif action == "set_rate":
                rate = cmd.get("rate", RATE_100MS)
                label = RATE_LABELS.get(rate, f"unknown({rate})")
                self._log(f"{ts}  CONFIG  Set rate → {label} (0x{rate})")
                self._suppress_event_uuids.add(UUID_CONFIG.lower())
                await self._central.write(UUID_CONFIG, rate, without_response=False)
                self._rtt_sim.write_config(rate)
                self._current_rate = rate
                return {"ok": True, "message": f"Rate: {label}"}

            elif action == "burst":
                self._log(f"{ts}  CMD     Burst → Command (0x{CMD_NOTIFY_BURST})")
                self._suppress_event_uuids.add(UUID_COMMAND.lower())
                await self._central.write(UUID_COMMAND, CMD_NOTIFY_BURST)
                self._rtt_sim.write_command(CMD_NOTIFY_BURST)
                return {"ok": True, "message": "Burst triggered"}

            elif action == "read_status":
                self._log(f"{ts}  STATUS  reading device status flags...")
                self._suppress_event_uuids.add(UUID_STATUS.lower())
                val = await self._central.read(UUID_STATUS)
                decoded = decode_status_flags(val)
                flags_str = ", ".join(decoded["flags"]) if decoded["flags"] else "none"
                self._log(f"{ts}  STATUS  {decoded['raw']} → [{flags_str}]")
                self._rtt_sim.status_read(int(val, 16))
                _enqueue(self._queue, {
                    "type": "device_status",
                    "flags": decoded["flags"],
                    "raw": decoded["raw"],
                })
                return {
                    "ok": True,
                    "message": f"Status: [{flags_str}]",
                    "status_flags": decoded,
                }

            elif action == "get_conn_stats":
                stats = get_connection_stats(self._central)
                mtu_str = f"MTU={stats['mtu']}" if stats["mtu"] else "MTU=unknown"
                self._log(f"{ts}  STATS   {mtu_str}, "
                          f"{stats['services']} services, "
                          f"{stats['characteristics']} characteristics")
                return {"ok": True, "message": mtu_str, "conn_stats": stats}

            elif action == "run_tests":
                result = await self._run_test_suite()
                # Test suite ends disconnected
                self._set_state("idle")
                return result

            else:
                return {"ok": False, "message": f"Unknown action: {action}"}

        except BleakCentralError as e:
            self._log(f"{ts}  ERROR   {e}")
            self._status(f"Error: {e}")
            # If we lost connection, reset state
            if not self._central.is_connected and self._state in ("connected", "subscribed"):
                self._set_state("idle")
            return {"ok": False, "message": str(e)}
        except Exception as e:
            self._log(f"{ts}  ERROR   {e}")
            if not self._central.is_connected and self._state in ("connected", "subscribed"):
                self._set_state("idle")
            return {"ok": False, "message": str(e)}

    async def _run_test_suite(self) -> dict:
        """Run the standard BLE test sequence.

        Exercises all firmware features:
          1. Scan for device
          2. Connect
          3. Subscribe to notifications
          4. Receive notifications (verify counter increments)
          5. Read counter characteristic
          6. Change rate to 500ms via Config char
          7. Trigger notification burst via Command char (0x02 → EAB10003)
          8. Read device status flags
          9. Disconnect
        """
        ts = self._ts()
        self._log("")
        self._log(f"{'='*56}")
        self._log(f"  BLE Integration Test Suite — {self._target_name}")
        self._log(f"  nRF5340 DK  ←BLE→  Mac (bleak)")
        self._log(f"{'='*56}")

        # Disconnect first if already connected (clean slate)
        if self._central.is_connected:
            self._log(f"{ts}  SETUP   teardown existing connection")
            await self._central.disconnect()
            await asyncio.sleep(1.0)

        steps = [
            ("BLE scan", f"find '{self._target_name}' in advertisements",
             lambda: self._central.scan(self._target_name, timeout=15)),
            ("Connect", "establish GATT connection",
             lambda: self._central.connect()),
            ("Subscribe", "enable Counter notifications",
             lambda: self._central.subscribe(UUID_SENSOR)),
            ("Rx notifications", "receive 3 Counter values",
             lambda: self._central.assert_notify(UUID_SENSOR, count=3, timeout=15)),
            ("GATT read", "read Counter characteristic",
             lambda: self._central.read(UUID_SENSOR)),
            ("Set rate 500ms", "write RATE_500MS (0x01) to Config",
             lambda: self._central.write(UUID_CONFIG, RATE_500MS, without_response=False)),
            ("Burst trigger", "write CMD_BURST (0x02) to Command",
             lambda: self._central.write(UUID_COMMAND, CMD_NOTIFY_BURST)),
            ("Read status", "read Status flags bitfield",
             lambda: self._central.read(UUID_STATUS)),
            ("Disconnect", "clean BLE disconnect",
             lambda: self._central.disconnect()),
        ]

        passed = 0
        failed = 0
        t0 = time.time()
        for name, desc, coro_fn in steps:
            step_num = passed + failed + 1
            self._log("")
            self._log(f"  [{step_num}/{len(steps)}] {name} — {desc}")
            step_t0 = time.time()
            try:
                result = await coro_fn()
                elapsed_ms = (time.time() - step_t0) * 1000
                result_str = ""
                if isinstance(result, str) and len(result) <= 40:
                    # Try to decode as counter or status flags
                    if name == "Read status":
                        decoded = decode_status_flags(result)
                        flags_str = ", ".join(decoded["flags"]) if decoded["flags"] else "none"
                        result_str = f" → [{flags_str}]"
                    else:
                        decoded_val = self._decode_counter(result)
                        result_str = f" = {decoded_val}" if decoded_val is not None else f" = {result}"
                elif isinstance(result, list):
                    vals = [self._decode_counter(v) for v in result[:3]]
                    result_str = f" values: {vals}"
                self._log(f"  PASS  {name}{result_str}  ({elapsed_ms:.0f} ms)")
                passed += 1
            except Exception as e:
                elapsed_ms = (time.time() - step_t0) * 1000
                self._log(f"  FAIL  {name} — {e}  ({elapsed_ms:.0f} ms)")
                failed += 1
                break

        total_ms = (time.time() - t0) * 1000
        self._log("")
        self._log(f"{'─'*56}")
        summary = f"{passed}/{passed + failed} passed" if failed == 0 else f"{passed}/{passed + failed} passed, {failed} FAILED"
        self._log(f"  {summary}  ({total_ms:.0f} ms total)")
        self._log(f"{'─'*56}")
        self._status(summary)
        return {"ok": failed == 0, "message": summary}

    @property
    def is_connected(self) -> bool:
        return self._central.is_connected


# ---------------------------------------------------------------------------
# Heartbeat
# ---------------------------------------------------------------------------


async def heartbeat(queue: asyncio.Queue):
    """Send periodic heartbeat to detect stale WebSocket connections."""
    while True:
        await asyncio.sleep(_HEARTBEAT_INTERVAL)
        _enqueue(queue, {"type": "heartbeat", "ts": time.time()})


# ---------------------------------------------------------------------------
# WebSocket + HTTP server
# ---------------------------------------------------------------------------

_clients: set = set()


def _make_response(status: int, content_type: str, body: bytes) -> Response:
    """Build an HTTP response for non-WebSocket requests."""
    return Response(
        status,
        "OK" if status == 200 else "Not Found",
        Headers({"Content-Type": content_type}),
        body,
    )


def _process_request(connection, request):
    """HTTP request handler — serves dashboard HTML and health endpoint."""
    if request.headers.get("Upgrade", "").lower() == "websocket":
        return None  # Let websockets handle the upgrade
    if request.path in ("/", "/index.html"):
        html = _HTML_PATH.read_bytes()
        return _make_response(200, "text/html; charset=utf-8", html)
    if request.path == "/health":
        return _make_response(200, "application/json", b'{"ok":true}')
    return _make_response(404, "text/plain", b"Not Found")


# Global ref for command routing
_ble_controller: Optional[BleController] = None


async def _ws_handler(websocket):
    """WebSocket handler — receives commands, routes to BleController."""
    _clients.add(websocket)
    # Send current state so browser enables the right buttons immediately
    if _ble_controller:
        state = _ble_controller._state
        allowed = sorted(BleController.STATES.get(state, set()))
        await websocket.send(json.dumps({
            "type": "state_change", "state": state, "allowed": allowed,
        }))
    try:
        async for raw in websocket:
            try:
                cmd = json.loads(raw)
                if _ble_controller and cmd.get("action"):
                    result = await _ble_controller.handle_command(cmd)
                    result["state"] = _ble_controller._state
                    await websocket.send(json.dumps({"type": "cmd_result", **result}))
            except json.JSONDecodeError:
                pass
    finally:
        _clients.discard(websocket)


async def _broadcast(data: dict):
    """Send a message to all connected WebSocket clients."""
    msg = json.dumps(data)
    dead = set()
    for ws in _clients:
        try:
            await asyncio.wait_for(ws.send(msg), timeout=_CLIENT_SEND_TIMEOUT)
        except Exception:
            dead.add(ws)
    _clients.difference_update(dead)


async def _broadcaster(queue: asyncio.Queue):
    """Main broadcast loop — drains the queue and fans out to all clients."""
    while True:
        data = await queue.get()
        if _clients:
            await _broadcast(data)


# ---------------------------------------------------------------------------
# Main
# ---------------------------------------------------------------------------


def run_dashboard(
    host: str = "0.0.0.0",
    port: int = _DEFAULT_PORT,
    rtt_log: Optional[str] = None,
    target_name: str = _DEFAULT_TARGET,
) -> None:
    """Start the BLE live dashboard server (blocking).

    Parameters
    ----------
    host:
        Bind address (default: 0.0.0.0 for all interfaces).
    port:
        HTTP/WebSocket port (default: 8860).
    rtt_log:
        Path to RTT raw log file to tail.  If the file doesn't exist yet,
        the tailer waits for it.  If None, only synthetic RTT logs are shown.
    target_name:
        BLE device name to scan for (default: "EAB-Test").
    """
    global _ble_controller

    if websockets is None:
        print("ERROR: 'websockets' package required. Install with: pip install websockets")
        raise SystemExit(1)

    async def _main():
        global _ble_controller
        queue: asyncio.Queue = asyncio.Queue(maxsize=2000)

        # RTT simulator generates synthetic firmware-side logs from BLE events
        rtt_sim = RttSimulator(queue)

        _ble_controller = BleController(queue, target_name, rtt_sim)

        async with websockets.serve(
            _ws_handler,
            host,
            port,
            process_request=_process_request,
        ):
            print(f"BLE Live Dashboard running at http://{host}:{port}")
            print(f"BLE target: {target_name}")
            print(f"GATT UUIDs:")
            print(f"  Sensor  (notify): {UUID_SENSOR}")
            print(f"  Config  (rate):   {UUID_CONFIG}")
            print(f"  Command (cmds):   {UUID_COMMAND}")
            print(f"  Status  (flags):  {UUID_STATUS}")
            if rtt_log:
                print(f"RTT source: {rtt_log}")
            else:
                print("RTT source: synthetic (no --rtt-log specified)")
            print("Press Ctrl+C to stop.")

            tasks = [
                asyncio.create_task(_broadcaster(queue), name="broadcaster"),
                asyncio.create_task(heartbeat(queue), name="heartbeat"),
            ]

            if rtt_log:
                tasks.append(asyncio.create_task(
                    tail_rtt_log(rtt_log, queue),
                    name="rtt_tailer",
                ))

            try:
                done, pending = await asyncio.wait(tasks, return_when=asyncio.FIRST_COMPLETED)
                for t in done:
                    if t.exception():
                        print(f"Task {t.get_name()} failed: {t.exception()}", file=sys.stderr)
            finally:
                for t in tasks:
                    t.cancel()
                await asyncio.gather(*tasks, return_exceptions=True)

    try:
        asyncio.run(_main())
    except KeyboardInterrupt:
        print("\nDashboard stopped.")


# ---------------------------------------------------------------------------
# CLI entry point
# ---------------------------------------------------------------------------

def main():
    parser = argparse.ArgumentParser(description="BLE Test Lab Live Dashboard")
    parser.add_argument("--host", default="0.0.0.0", help="Bind address (default: 0.0.0.0)")
    parser.add_argument("--port", type=int, default=_DEFAULT_PORT, help=f"Port (default: {_DEFAULT_PORT})")
    parser.add_argument("--rtt-log", default=None,
                        help=f"RTT log file to tail (default: synthetic only). "
                             f"Use '{_DEFAULT_RTT_LOG}' for real RTT.")
    parser.add_argument("--target", default=_DEFAULT_TARGET, help="BLE device name to scan for")
    args = parser.parse_args()

    run_dashboard(
        host=args.host,
        port=args.port,
        rtt_log=args.rtt_log,
        target_name=args.target,
    )


if __name__ == "__main__":
    main()
