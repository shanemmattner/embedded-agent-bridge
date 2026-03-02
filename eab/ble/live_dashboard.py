"""BLE Test Lab Live Dashboard — real-time RTT + BLE log streaming with charts.

Async server using websockets (same pattern as eab/plotter/server.py):
- Tails RTT log file for firmware-side events
- Runs BleakCentral with event hooks for Python-side BLE operations
- Broadcasts both streams + parsed chart data to all connected browsers
- Accepts control commands (scan, connect, disconnect, write, etc.) via WebSocket

Usage:
    python3 -m eab.ble.live_dashboard --port 8860 --rtt-log /tmp/eab-devices/default/rtt-raw.log
"""

from __future__ import annotations

import argparse
import asyncio
import json
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

# BLE UUIDs (EAB custom service on nRF5340 firmware)
_DEFAULT_NOTIFY_UUID = "eab10001-0001-1000-8000-00805f9b34fb"  # notify + read (counter)
_DEFAULT_WRITE_UUID = "eab10002-0001-1000-8000-00805f9b34fb"   # read + write (reset counter)

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
    """Tail the RTT raw log file and push lines to the queue."""
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
            pos = 0  # File truncated

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

                # Push RTT log line
                _enqueue(queue, {"type": "rtt_log", "line": line, "ts": time.time()})

                # Try to extract chart data
                m = _COUNTER_RE.search(line)
                if m:
                    _enqueue(queue, {
                        "type": "data",
                        "series": "counter",
                        "value": int(m.group(1)),
                        "ts": time.time(),
                    })

                m = _RSSI_RE.search(line)
                if m:
                    _enqueue(queue, {
                        "type": "data",
                        "series": "rssi",
                        "value": int(m.group(1)),
                        "ts": time.time(),
                    })

                # Detect connection events for timeline
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
# BLE controller
# ---------------------------------------------------------------------------


class BleController:
    """Wraps BleakCentral and pushes events to the broadcast queue."""

    def __init__(self, queue: asyncio.Queue, target_name: str, notify_uuid: str, write_uuid: str):
        self._queue = queue
        self._target_name = target_name
        self._notify_uuid = notify_uuid
        self._write_uuid = write_uuid
        self._central = BleakCentral(event_callback=self._on_event)

    def _on_event(self, event: dict):
        _enqueue(self._queue, {
            "type": "ble_log",
            "line": f"[{event['type']}] {event['detail']}",
            "ts": event["ts"],
        })

        # Parse notification hex payload → chart data (little-endian uint32 counter)
        if event["type"] == "notification":
            try:
                # detail format: "uuid: hex_payload"
                hex_part = event["detail"].split(": ", 1)[1].strip()
                value = int.from_bytes(bytes.fromhex(hex_part), byteorder="little")
                _enqueue(self._queue, {
                    "type": "data",
                    "series": "counter",
                    "value": value,
                    "ts": event["ts"],
                })
            except (IndexError, ValueError):
                pass

        # Connection events → chart
        if event["type"] == "connected":
            _enqueue(self._queue, {"type": "data", "series": "conn_event", "value": 1, "ts": event["ts"]})
        elif event["type"] == "disconnected":
            _enqueue(self._queue, {"type": "data", "series": "conn_event", "value": 0, "ts": event["ts"]})

    def _log(self, msg: str):
        _enqueue(self._queue, {"type": "ble_log", "line": msg, "ts": time.time()})

    def _status(self, msg: str):
        _enqueue(self._queue, {"type": "status", "message": msg})

    async def handle_command(self, cmd: dict) -> dict:
        """Handle a command from the browser. Returns {ok, message}."""
        action = cmd.get("action", "")
        try:
            if action == "scan":
                self._log(f"Scanning for '{self._target_name}'...")
                self._status("Scanning...")
                addr = await self._central.scan(self._target_name, timeout=15)
                self._status(f"Found: {addr}")
                return {"ok": True, "message": f"Found at {addr}"}

            elif action == "connect":
                self._log("Connecting...")
                self._status("Connecting...")
                await self._central.connect()
                self._status("Connected")
                return {"ok": True, "message": "Connected"}

            elif action == "disconnect":
                self._log("Disconnecting...")
                await self._central.disconnect()
                self._status("Disconnected")
                return {"ok": True, "message": "Disconnected"}

            elif action == "subscribe":
                uuid = cmd.get("uuid", self._notify_uuid)
                self._log(f"Subscribing to {uuid}...")
                await self._central.subscribe(uuid)
                return {"ok": True, "message": f"Subscribed to {uuid}"}

            elif action == "unsubscribe":
                uuid = cmd.get("uuid", self._notify_uuid)
                self._log(f"Unsubscribing from {uuid}...")
                if self._central._client:
                    await self._central._client.stop_notify(uuid)
                    self._central._notifications.pop(uuid.lower(), None)
                    self._central._notify_events.pop(uuid.lower(), None)
                self._log(f"Unsubscribed from {uuid}")
                return {"ok": True, "message": f"Unsubscribed from {uuid}"}

            elif action == "write_cmd":
                uuid = cmd.get("uuid", self._write_uuid)
                value = cmd.get("value", "00")
                self._log(f"Writing {value} to {uuid}...")
                await self._central.write(uuid, value)
                return {"ok": True, "message": f"Wrote {value}"}

            elif action == "read":
                uuid = cmd.get("uuid", self._notify_uuid)
                val = await self._central.read(uuid)
                self._log(f"Read from {uuid}: {val}")
                return {"ok": True, "message": f"Value: {val}"}

            elif action == "run_tests":
                return await self._run_test_suite()

            else:
                return {"ok": False, "message": f"Unknown action: {action}"}

        except BleakCentralError as e:
            self._log(f"ERROR: {e}")
            self._status(f"Error: {e}")
            return {"ok": False, "message": str(e)}
        except Exception as e:
            self._log(f"ERROR: {e}")
            return {"ok": False, "message": str(e)}

    async def _run_test_suite(self) -> dict:
        """Run the standard BLE test sequence."""
        self._log("=== Running BLE Test Suite ===")

        # Disconnect first if already connected (clean slate)
        if self._central.is_connected:
            self._log("  (disconnecting existing session for clean test)")
            await self._central.disconnect()
            import asyncio as _aio
            await _aio.sleep(1.0)

        steps = [
            ("Scan", lambda: self._central.scan(self._target_name, timeout=15)),
            ("Connect", lambda: self._central.connect()),
            ("Subscribe", lambda: self._central.subscribe(self._notify_uuid)),
            ("Wait for notifications", lambda: self._central.assert_notify(self._notify_uuid, count=3, timeout=15)),
            ("Read", lambda: self._central.read(self._notify_uuid)),
            ("Write reset", lambda: self._central.write(self._write_uuid, "00")),
            ("Wait after reset", lambda: self._central.assert_notify(self._notify_uuid, count=2, timeout=10)),
            ("Disconnect", lambda: self._central.disconnect()),
        ]

        passed = 0
        failed = 0
        for name, coro_fn in steps:
            self._log(f"  [{passed + failed + 1}/{len(steps)}] {name}...")
            try:
                result = await coro_fn()
                self._log(f"  PASS: {name}" + (f" → {result}" if result else ""))
                passed += 1
            except Exception as e:
                self._log(f"  FAIL: {name} — {e}")
                failed += 1
                break  # Stop on first failure

        summary = f"=== Results: {passed} passed, {failed} failed ==="
        self._log(summary)
        self._status(summary)
        return {"ok": failed == 0, "message": summary}

    @property
    def is_connected(self) -> bool:
        return self._central.is_connected


# ---------------------------------------------------------------------------
# Heartbeat
# ---------------------------------------------------------------------------


async def heartbeat(queue: asyncio.Queue):
    while True:
        await asyncio.sleep(_HEARTBEAT_INTERVAL)
        _enqueue(queue, {"type": "heartbeat", "ts": time.time()})


# ---------------------------------------------------------------------------
# WebSocket + HTTP server
# ---------------------------------------------------------------------------

_clients: set = set()


def _make_response(status: int, content_type: str, body: bytes) -> Response:
    return Response(
        status,
        "OK" if status == 200 else "Not Found",
        Headers({"Content-Type": content_type}),
        body,
    )


def _process_request(connection, request):
    if request.headers.get("Upgrade", "").lower() == "websocket":
        return None
    if request.path in ("/", "/index.html"):
        html = _HTML_PATH.read_bytes()
        return _make_response(200, "text/html; charset=utf-8", html)
    if request.path == "/health":
        return _make_response(200, "application/json", b'{"ok":true}')
    return _make_response(404, "text/plain", b"Not Found")


# Global ref for command routing
_ble_controller: Optional[BleController] = None


async def _ws_handler(websocket):
    _clients.add(websocket)
    try:
        async for raw in websocket:
            # Handle commands from browser
            try:
                cmd = json.loads(raw)
                if _ble_controller and cmd.get("action"):
                    result = await _ble_controller.handle_command(cmd)
                    await websocket.send(json.dumps({"type": "cmd_result", **result}))
            except json.JSONDecodeError:
                pass
    finally:
        _clients.discard(websocket)


async def _broadcast(data: dict):
    msg = json.dumps(data)
    dead = set()
    for ws in _clients:
        try:
            await asyncio.wait_for(ws.send(msg), timeout=_CLIENT_SEND_TIMEOUT)
        except Exception:
            dead.add(ws)
    _clients.difference_update(dead)


async def _broadcaster(queue: asyncio.Queue):
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
    notify_uuid: str = _DEFAULT_NOTIFY_UUID,
    write_uuid: str = _DEFAULT_WRITE_UUID,
) -> None:
    """Start the BLE live dashboard server (blocking)."""
    global _ble_controller

    if websockets is None:
        print("ERROR: 'websockets' package required. Install with: pip install websockets")
        raise SystemExit(1)

    async def _main():
        global _ble_controller
        queue: asyncio.Queue = asyncio.Queue(maxsize=2000)

        _ble_controller = BleController(queue, target_name, notify_uuid, write_uuid)

        async with websockets.serve(
            _ws_handler,
            host,
            port,
            process_request=_process_request,
        ):
            print(f"BLE Live Dashboard running at http://{host}:{port}")
            if rtt_log:
                print(f"RTT source: {rtt_log}")
            print(f"BLE target: {target_name}")
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
    parser.add_argument("--rtt-log", default=_DEFAULT_RTT_LOG, help="RTT log file to tail")
    parser.add_argument("--target", default=_DEFAULT_TARGET, help="BLE device name to scan for")
    parser.add_argument("--notify-uuid", default=_DEFAULT_NOTIFY_UUID, help="Notification characteristic UUID")
    parser.add_argument("--write-uuid", default=_DEFAULT_WRITE_UUID, help="Write characteristic UUID")
    args = parser.parse_args()

    run_dashboard(
        host=args.host,
        port=args.port,
        rtt_log=args.rtt_log,
        target_name=args.target,
        notify_uuid=args.notify_uuid,
        write_uuid=args.write_uuid,
    )


if __name__ == "__main__":
    main()
