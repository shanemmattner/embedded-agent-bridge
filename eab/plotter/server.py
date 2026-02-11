"""Minimal real-time plotter for EAB RTT/SWO data.

Single-file async server:
- Serves an HTML page with Plotly.js (CDN) on HTTP GET /
- Pushes parsed log data to all connected browsers via WebSocket
- Primary data source: pylink RTT via JLinkBridge
- Fallback: file-tailing mode via --log-path (reads clean rtt.log)

Only dependency beyond stdlib: `websockets`
"""

from __future__ import annotations

import asyncio
import json
import os
import sys
import webbrowser
from pathlib import Path
from typing import Optional

try:
    import websockets
    from websockets.http11 import Response
    from websockets.datastructures import Headers
except ImportError:
    websockets = None  # type: ignore[assignment]

# ---------------------------------------------------------------------------
# Constants
# ---------------------------------------------------------------------------

_BUFFER_CAP = 65536  # 64KB max for incomplete-line buffers
_HEARTBEAT_INTERVAL = 2.0  # seconds
_HEALTH_CHECK_INTERVAL = 5.0  # seconds
_CLIENT_SEND_TIMEOUT = 5.0  # seconds

# ---------------------------------------------------------------------------
# Data sources
# ---------------------------------------------------------------------------


async def rtt_processor_reader(
    bridge,
    device: str,
    queue: asyncio.Queue,
    block_address: int | None = None,
    interface: str = "SWD",
    speed: int = 4000,
):
    """Start RTT via pylink (through JLinkBridge) and feed parsed data to queue.

    The bridge's reader thread feeds RTTStreamProcessor which feeds the queue.
    This function monitors health and handles reconnection.
    """
    while True:
        st = bridge.start_rtt(
            device=device,
            interface=interface,
            speed=speed,
            block_address=block_address,
            queue=queue,
        )

        if not st.running:
            _enqueue_status(queue, f"RTT start failed: {st.last_error}")
            await asyncio.sleep(3.0)
            continue

        _enqueue_status(queue, f"RTT connected: {device} ({st.num_up_channels} up channels)")

        # Monitor RTT health
        while True:
            await asyncio.sleep(_HEALTH_CHECK_INTERVAL)
            st = bridge.rtt_status()
            if not st.running:
                _enqueue_status(queue, f"RTT disconnected: {st.last_error or 'unknown'}")
                break

        # Attempt reconnect
        bridge.stop_rtt()
        _enqueue_status(queue, "Reconnecting RTT...")
        await asyncio.sleep(2.0)


async def tail_log(path: str, queue: asyncio.Queue, poll_interval: float = 0.1):
    """Tail clean rtt.log and parse lines via RTTStreamProcessor.

    Fallback mode: reads the clean log produced by RTTStreamProcessor
    (no ANSI codes, bounded line length). Uses a processor instance
    without file outputs to parse and enqueue records.
    """
    from eab.rtt_stream import RTTStreamProcessor

    processor = RTTStreamProcessor(queue=queue)

    pos = 0
    # Start from end of file if it exists
    if os.path.exists(path):
        pos = os.path.getsize(path)

    while True:
        try:
            size = os.path.getsize(path) if os.path.exists(path) else 0
        except OSError:
            await asyncio.sleep(poll_interval)
            continue

        if size < pos:
            pos = 0  # File was truncated (new session / rotation)
            processor.reset()

        if size > pos:
            try:
                with open(path, "r", encoding="utf-8", errors="replace") as f:
                    f.seek(pos)
                    chunk = f.read()
                    pos = f.tell()
            except OSError:
                await asyncio.sleep(poll_interval)
                continue

            # Cap buffer to prevent unbounded growth from pathological files
            if len(chunk) > _BUFFER_CAP:
                chunk = chunk[-_BUFFER_CAP:]

            processor.feed(chunk.encode("utf-8"))
        else:
            await asyncio.sleep(poll_interval)


def _enqueue(queue: asyncio.Queue, item: dict):
    """Non-blocking enqueue with drop on overflow."""
    try:
        queue.put_nowait(item)
    except asyncio.QueueFull:
        # Drop oldest to make room
        try:
            queue.get_nowait()
        except asyncio.QueueEmpty:
            pass
        try:
            queue.put_nowait(item)
        except asyncio.QueueFull:
            pass


def _enqueue_status(queue: asyncio.Queue, message: str):
    """Push a status message into the queue."""
    _enqueue(queue, {"type": "status", "message": message})


# ---------------------------------------------------------------------------
# Health monitor
# ---------------------------------------------------------------------------


async def health_monitor(bridge, queue: asyncio.Queue):
    """Periodically check RTT health, push status on change."""
    was_healthy = True

    while True:
        await asyncio.sleep(_HEALTH_CHECK_INTERVAL)
        try:
            st = bridge.rtt_status()
            if st.running:
                if not was_healthy:
                    _enqueue_status(queue, "RTT recovered")
                    was_healthy = True
            else:
                if was_healthy:
                    _enqueue_status(queue, f"RTT stopped: {st.last_error or 'unknown'}")
                    was_healthy = False
        except Exception:
            pass  # Don't crash the monitor on transient errors


# ---------------------------------------------------------------------------
# Heartbeat
# ---------------------------------------------------------------------------


async def heartbeat(queue: asyncio.Queue):
    """Push heartbeat messages so the browser can detect server liveness."""
    import time
    while True:
        await asyncio.sleep(_HEARTBEAT_INTERVAL)
        _enqueue(queue, {"type": "heartbeat", "ts": time.time()})


# ---------------------------------------------------------------------------
# WebSocket + HTTP server (websockets v16 API)
# ---------------------------------------------------------------------------

_HTML_PATH = Path(__file__).parent / "page.html"
_clients: set = set()


def _make_response(status: int, content_type: str, body: bytes) -> Response:
    return Response(
        status,
        "OK" if status == 200 else "Not Found",
        Headers({"Content-Type": content_type}),
        body,
    )


def _process_request(connection, request):
    """Serve HTML page on GET /, health on /health. Return None for WS upgrade."""
    # If it's a WebSocket upgrade request, let websockets handle it
    if request.headers.get("Upgrade", "").lower() == "websocket":
        return None
    if request.path == "/" or request.path == "/index.html":
        html = _HTML_PATH.read_bytes()
        return _make_response(200, "text/html; charset=utf-8", html)
    if request.path == "/health":
        return _make_response(200, "application/json", b'{"ok":true}')
    return _make_response(404, "text/plain", b"Not Found")


async def _ws_handler(websocket):
    _clients.add(websocket)
    try:
        async for _ in websocket:
            pass  # We don't expect messages from the client
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
    """Read from queue and broadcast to all WebSocket clients."""
    while True:
        data = await queue.get()
        if _clients:
            await _broadcast(data)


def run_plotter(
    host: str = "127.0.0.1",
    port: int = 8080,
    device: str | None = None,
    block_address: int | None = None,
    log_path: Optional[str] = None,
    base_dir: Optional[str] = None,
    open_browser: bool = True,
    interface: str = "SWD",
    speed: int = 4000,
):
    """Start the real-time plotter server (blocking).

    Args:
        host: Bind address for HTTP/WS server.
        port: HTTP + WebSocket port.
        device: J-Link device string for direct RTT mode.
        block_address: RTT control block address (from .map file).
        log_path: If set, use file-tailing fallback instead of direct RTT.
        base_dir: EAB session dir.
        open_browser: Auto-open browser on start.
        interface: Debug interface (SWD or JTAG).
        speed: Interface speed in kHz.
    """
    if websockets is None:
        print("ERROR: 'websockets' package required. Install with: pip install 'embedded-agent-bridge[plotter]'")
        raise SystemExit(1)

    use_direct_rtt = log_path is None and device is not None

    if use_direct_rtt and base_dir is None:
        base_dir = "/tmp/eab-session"

    async def _main():
        queue: asyncio.Queue = asyncio.Queue(maxsize=1000)

        # Create shared bridge instance for direct RTT mode
        bridge = None
        if use_direct_rtt:
            from eab.jlink_bridge import JLinkBridge
            bridge = JLinkBridge(base_dir)

        async with websockets.serve(
            _ws_handler,
            host,
            port,
            process_request=_process_request,
        ):
            if use_direct_rtt:
                print(f"EAB Plotter running at http://{host}:{port}")
                print(f"Data source: RTT via pylink ({device})")
            else:
                print(f"EAB Plotter running at http://{host}:{port}")
                print(f"Data source: file tail {log_path}")
            print("Press Ctrl+C to stop.")

            if open_browser:
                webbrowser.open(f"http://{host}:{port}")

            # Build task list
            tasks = []
            if use_direct_rtt:
                tasks.append(asyncio.create_task(
                    rtt_processor_reader(bridge, device, queue, block_address, interface, speed),
                    name="rtt_processor_reader",
                ))
            elif log_path:
                tasks.append(asyncio.create_task(
                    tail_log(log_path, queue),
                    name="tail_log",
                ))

            tasks.append(asyncio.create_task(_broadcaster(queue), name="broadcaster"))
            tasks.append(asyncio.create_task(heartbeat(queue), name="heartbeat"))

            if bridge:
                tasks.append(asyncio.create_task(
                    health_monitor(bridge, queue),
                    name="health_monitor",
                ))

            try:
                # Wait for first task to complete (shouldn't happen in normal operation)
                done, pending = await asyncio.wait(tasks, return_when=asyncio.FIRST_COMPLETED)
                for t in done:
                    if t.exception():
                        print(f"Task {t.get_name()} failed: {t.exception()}", file=sys.stderr)
            finally:
                # Cancel all tasks on shutdown
                for t in tasks:
                    t.cancel()
                await asyncio.gather(*tasks, return_exceptions=True)

                # Clean up RTT on exit
                if bridge:
                    bridge.stop_rtt()

    try:
        asyncio.run(_main())
    except KeyboardInterrupt:
        print("\nPlotter stopped.")
