"""
EAB Presentation Dashboard
===========================
Live Plotly Dash dashboard for the nRF5340 BLE peripheral demo.
Tails rtt.jsonl and latest.log from the EAB session directory.

Run:
    python demo_dashboard.py

Then open http://<host>:8050  (accessible over SSH / LAN)

Displays:
  - Temperature over time (from DATA: temp=XX.XX)
  - Notify counter (rate indicator)
  - BLE connection status + event log
  - Real-time RTT log feed
  - Demo step progress (synced with demo_run.py via /tmp/demo_step.txt)
"""

from __future__ import annotations

import json
import os
import re
import time
from collections import deque
from pathlib import Path

import dash
from dash import dcc, html, Input, Output, State
import plotly.graph_objs as go

# ---------------------------------------------------------------------------
# Config
# ---------------------------------------------------------------------------

BASE_DIR      = Path("/tmp/eab-devices/default")
RTT_JSONL     = BASE_DIR / "rtt.jsonl"
RTT_LOG       = BASE_DIR / "rtt-raw.log"   # jlink writes raw RTT here
LATEST_LOG    = BASE_DIR / "latest.log"
ALERTS_LOG    = BASE_DIR / "alerts.log"
STEP_FILE     = Path("/tmp/demo_step.txt")

MAX_POINTS    = 300   # points to keep on graphs
POLL_INTERVAL = 500   # ms

# ---------------------------------------------------------------------------
# State (module-level, single process)
# ---------------------------------------------------------------------------

_rtt_pos      = 0     # byte offset into rtt.jsonl
_log_pos      = 0     # byte offset into rtt.log (for the log panel)
_alert_pos    = 0

temps:    deque = deque(maxlen=MAX_POINTS)
times:    deque = deque(maxlen=MAX_POINTS)
counters: deque = deque(maxlen=MAX_POINTS)
log_lines: deque = deque(maxlen=200)
alert_lines: deque = deque(maxlen=50)

# BLE state derived from RTT events
ble_state = {"connected": False, "peer": "", "mtu": 23, "notify_count": 0, "conn_count": 0}

# Demo step
current_step = {"n": 0, "label": "Waiting..."}

# ---------------------------------------------------------------------------
# Parsers
# ---------------------------------------------------------------------------

_DATA_RE   = re.compile(r"DATA:\s+counter=(-?\d+)\s+temp=([0-9\-\.]+)\s+notify_count=(\d+)")
_CONN_RE   = re.compile(r"=== CONNECTED ===")
_DISC_RE   = re.compile(r"=== DISCONNECTED ===")
_PEER_RE   = re.compile(r"Peer:\s+([0-9A-Fa-f:]+)")
_MTU_RE    = re.compile(r"MTU:\s+(\d+)")
_CONNCNT_RE = re.compile(r"Total connections:\s+(\d+)")


def _poll_rtt_jsonl():
    """Read new lines from rtt.jsonl, update graphs + BLE state."""
    global _rtt_pos
    if not RTT_JSONL.exists():
        return
    size = RTT_JSONL.stat().st_size
    if size < _rtt_pos:
        _rtt_pos = 0  # rotated
    if size == _rtt_pos:
        return
    with open(RTT_JSONL, "r", errors="replace") as f:
        f.seek(_rtt_pos)
        chunk = f.read()
        _rtt_pos = f.tell()
    for line in chunk.splitlines():
        line = line.strip()
        if not line:
            continue
        try:
            rec = json.loads(line)
        except json.JSONDecodeError:
            continue
        msg = rec.get("message", "") or rec.get("raw", "")
        _process_message(msg, rec.get("ts") or rec.get("timestamp") or time.time())


def _poll_rtt_log():
    """Fallback: tail rtt.log for display in the log panel."""
    global _log_pos
    if not RTT_LOG.exists():
        return
    size = RTT_LOG.stat().st_size
    if size < _log_pos:
        _log_pos = 0
    if size == _log_pos:
        return
    with open(RTT_LOG, "r", errors="replace") as f:
        f.seek(_log_pos)
        chunk = f.read()
        _log_pos = f.tell()
    for line in chunk.splitlines():
        line = line.strip()
        if line:
            log_lines.append(line)
            _process_message(line, time.time())


def _poll_alerts():
    global _alert_pos
    if not ALERTS_LOG.exists():
        return
    size = ALERTS_LOG.stat().st_size
    if size < _alert_pos:
        _alert_pos = 0
    if size == _alert_pos:
        return
    with open(ALERTS_LOG, "r", errors="replace") as f:
        f.seek(_alert_pos)
        chunk = f.read()
        _alert_pos = f.tell()
    for line in chunk.splitlines():
        line = line.strip()
        if line:
            alert_lines.append(line)


def _process_message(msg: str, ts: float):
    """Extract metrics and BLE state from a log message."""
    # DATA record → temperature + counter
    m = _DATA_RE.search(msg)
    if m:
        counter  = int(m.group(1))
        temp     = float(m.group(2))
        ncount   = int(m.group(3))
        t_now    = time.strftime("%H:%M:%S", time.localtime(ts if isinstance(ts, float) else time.time()))
        temps.append(temp)
        times.append(t_now)
        counters.append(counter)
        ble_state["notify_count"] = ncount
        return

    # BLE events
    if _CONN_RE.search(msg):
        ble_state["connected"] = True
    if _DISC_RE.search(msg):
        ble_state["connected"] = False
        ble_state["peer"] = ""
    pm = _PEER_RE.search(msg)
    if pm:
        ble_state["peer"] = pm.group(1)
    mm = _MTU_RE.search(msg)
    if mm:
        ble_state["mtu"] = int(mm.group(1))
    cm = _CONNCNT_RE.search(msg)
    if cm:
        ble_state["conn_count"] = int(cm.group(1))


def _poll_step():
    """Read current demo step from file written by demo_run.py.
    When step resets to 1, clear all log/graph state so the dashboard starts fresh."""
    global _rtt_pos, _log_pos, _alert_pos
    if STEP_FILE.exists():
        try:
            data  = json.loads(STEP_FILE.read_text())
            new_n = data.get("step", 0)
            # Demo restarted — clear everything
            if new_n == 1 and current_step["n"] > 1:
                log_lines.clear()
                alert_lines.clear()
                temps.clear()
                times.clear()
                counters.clear()
                ble_state.update({"connected": False, "peer": "", "mtu": 23,
                                  "notify_count": 0, "conn_count": 0})
                _rtt_pos = 0
                _log_pos = 0
                _alert_pos = 0
            current_step["n"]     = new_n
            current_step["label"] = data.get("label", "")
        except Exception:
            pass


# ---------------------------------------------------------------------------
# Dash app
# ---------------------------------------------------------------------------

app = dash.Dash(__name__, title="EAB Live Demo — nRF5340")

# Suppress callback exceptions for dynamic IDs
app.config.suppress_callback_exceptions = True

DEMO_STEPS = [
    "0: Standby",
    "1: Daemon started — board connected",
    "2: RTT streaming — Zephyr boot",
    "3: BLE advertising",
    "4: BLE connected — notifications flowing",
    "5: DWT watchpoint armed",
    "6: Fault injected",
    "7: Fault analyzed — ai_prompt generated",
    "8: Board reset — clean boot",
    "9: Demo complete",
]

app.layout = html.Div(
    style={"backgroundColor": "#0d1117", "color": "#c9d1d9", "fontFamily": "monospace", "minHeight": "100vh", "padding": "20px"},
    children=[

        # Header
        html.Div([
            html.H2("Embedded Agent Bridge", style={"color": "#58a6ff", "margin": 0}),
            html.Span("nRF5340 DK — Live Demo", style={"color": "#8b949e", "fontSize": "14px"}),
            html.Span(" | ", style={"color": "#30363d"}),
            html.Span("github.com/shanemmattner/embedded-agent-bridge",
                      style={"color": "#3fb950", "fontSize": "13px"}),
        ], style={"borderBottom": "1px solid #30363d", "paddingBottom": "10px", "marginBottom": "16px",
                  "display": "flex", "alignItems": "baseline", "gap": "12px"}),

        # Status bar
        html.Div(id="status-bar", style={"marginBottom": "16px"}),

        # Demo step progress
        html.Div([
            html.Div("DEMO STEPS", style={"color": "#8b949e", "fontSize": "11px", "marginBottom": "6px"}),
            html.Div(id="step-display"),
        ], style={"background": "#161b22", "border": "1px solid #30363d", "borderRadius": "6px",
                  "padding": "12px", "marginBottom": "16px"}),

        # Charts row
        html.Div([
            html.Div([
                dcc.Graph(id="temp-graph", config={"displayModeBar": False},
                          style={"height": "280px"}),
            ], style={"flex": "1", "background": "#161b22", "border": "1px solid #30363d",
                      "borderRadius": "6px", "padding": "8px", "marginRight": "12px"}),

            html.Div([
                dcc.Graph(id="counter-graph", config={"displayModeBar": False},
                          style={"height": "280px"}),
            ], style={"flex": "1", "background": "#161b22", "border": "1px solid #30363d",
                      "borderRadius": "6px", "padding": "8px"}),
        ], style={"display": "flex", "marginBottom": "16px"}),

        # Log + alerts row
        html.Div([
            html.Div([
                html.Div("RTT LOG", style={"color": "#8b949e", "fontSize": "11px", "marginBottom": "6px"}),
                html.Div(id="rtt-log",
                         style={"height": "260px", "overflowY": "auto", "fontSize": "12px",
                                "lineHeight": "1.5", "whiteSpace": "pre-wrap", "wordBreak": "break-all"}),
            ], style={"flex": "2", "background": "#161b22", "border": "1px solid #30363d",
                      "borderRadius": "6px", "padding": "12px", "marginRight": "12px"}),

            html.Div([
                html.Div("ALERTS", style={"color": "#f85149", "fontSize": "11px", "marginBottom": "6px"}),
                html.Div(id="alerts-panel",
                         style={"height": "260px", "overflowY": "auto", "fontSize": "12px",
                                "lineHeight": "1.5", "whiteSpace": "pre-wrap"}),
            ], style={"flex": "1", "background": "#161b22", "border": "1px solid #30363d",
                      "borderRadius": "6px", "padding": "12px"}),
        ], style={"display": "flex"}),

        # Interval driver
        dcc.Interval(id="interval", interval=POLL_INTERVAL, n_intervals=0),
    ]
)


# ---------------------------------------------------------------------------
# Callbacks
# ---------------------------------------------------------------------------

@app.callback(
    Output("status-bar",    "children"),
    Output("step-display",  "children"),
    Output("temp-graph",    "figure"),
    Output("counter-graph", "figure"),
    Output("rtt-log",       "children"),
    Output("alerts-panel",  "children"),
    Input("interval",       "n_intervals"),
)
def update(_n):
    # Pull new data
    _poll_rtt_jsonl()
    _poll_rtt_log()
    _poll_alerts()
    _poll_step()

    # --- Status bar ---
    conn_color  = "#3fb950" if ble_state["connected"] else "#f85149"
    conn_label  = "CONNECTED" if ble_state["connected"] else "ADVERTISING"
    peer_text   = f"  peer: {ble_state['peer']}" if ble_state["peer"] else ""
    mtu_text    = f"  MTU: {ble_state['mtu']}" if ble_state["connected"] else ""
    ncount_text = f"  notifies: {ble_state['notify_count']}"
    conns_text  = f"  total conns: {ble_state['conn_count']}"
    daemon_ok   = BASE_DIR.exists()
    daemon_color = "#3fb950" if daemon_ok else "#f85149"

    status = html.Div([
        html.Span("● DAEMON ", style={"color": daemon_color, "fontWeight": "bold"}),
        html.Span("nRF5340  ", style={"color": "#c9d1d9"}),
        html.Span(f"● BLE {conn_label}", style={"color": conn_color, "fontWeight": "bold"}),
        html.Span(f"{peer_text}{mtu_text}{ncount_text}{conns_text}",
                  style={"color": "#8b949e", "fontSize": "13px"}),
    ], style={"display": "flex", "gap": "16px", "alignItems": "center",
              "background": "#161b22", "border": "1px solid #30363d",
              "borderRadius": "6px", "padding": "8px 14px"})

    # --- Step display ---
    step_n = current_step["n"]
    steps_ui = []
    for i, s in enumerate(DEMO_STEPS):
        if i < step_n:
            color, prefix = "#3fb950", "✓ "
        elif i == step_n:
            color, prefix = "#f0883e", "▶ "
        else:
            color, prefix = "#484f58", "  "
        steps_ui.append(
            html.Span(f"{prefix}{s}",
                      style={"color": color, "marginRight": "20px", "fontSize": "13px"})
        )
    step_display = html.Div(steps_ui, style={"display": "flex", "flexWrap": "wrap", "gap": "4px"})

    # --- Temp graph ---
    xs = list(times)
    ys = list(temps)
    temp_fig = go.Figure(
        data=[go.Scatter(
            x=xs, y=ys, mode="lines+markers",
            line={"color": "#58a6ff", "width": 2},
            marker={"size": 3},
            name="temp °C",
        )],
        layout=go.Layout(
            title={"text": "Temperature (°C)", "font": {"color": "#c9d1d9", "size": 13}},
            paper_bgcolor="#161b22", plot_bgcolor="#0d1117",
            font={"color": "#8b949e"},
            margin={"l": 40, "r": 10, "t": 30, "b": 30},
            xaxis={"showgrid": False, "color": "#484f58"},
            yaxis={"gridcolor": "#21262d", "color": "#8b949e"},
            showlegend=False,
        )
    )

    # --- Counter / notify rate graph ---
    counter_fig = go.Figure(
        data=[go.Scatter(
            x=xs, y=list(counters), mode="lines",
            line={"color": "#3fb950", "width": 2},
            name="counter",
        )],
        layout=go.Layout(
            title={"text": "BLE Notify Counter", "font": {"color": "#c9d1d9", "size": 13}},
            paper_bgcolor="#161b22", plot_bgcolor="#0d1117",
            font={"color": "#8b949e"},
            margin={"l": 40, "r": 10, "t": 30, "b": 30},
            xaxis={"showgrid": False, "color": "#484f58"},
            yaxis={"gridcolor": "#21262d", "color": "#8b949e"},
            showlegend=False,
        )
    )

    # --- RTT log ---
    def _color_line(line: str) -> html.Span:
        if "<err>" in line or "FAULT" in line or "=== CRASH" in line:
            c = "#f85149"
        elif "<wrn>" in line or "WRN" in line:
            c = "#f0883e"
        elif "CONNECTED" in line:
            c = "#3fb950"
        elif "DATA:" in line:
            c = "#58a6ff"
        else:
            c = "#8b949e"
        return html.Div(line, style={"color": c, "marginBottom": "1px"})

    log_ui = [_color_line(l) for l in list(log_lines)[-80:]]

    # --- Alerts ---
    alert_ui = [
        html.Div(l, style={"color": "#f85149", "marginBottom": "2px"})
        for l in list(alert_lines)
    ] or [html.Div("No alerts", style={"color": "#484f58", "fontStyle": "italic"})]

    return status, step_display, temp_fig, counter_fig, html.Div(log_ui), html.Div(alert_ui)


# ---------------------------------------------------------------------------
# Main
# ---------------------------------------------------------------------------

if __name__ == "__main__":
    import argparse

    parser = argparse.ArgumentParser(description="EAB Presentation Dashboard")
    parser.add_argument("--port", type=int, default=8050)
    parser.add_argument("--host", default="0.0.0.0",
                        help="Bind address. 0.0.0.0 = accessible over SSH/LAN")
    args = parser.parse_args()

    print(f"\n  EAB Dashboard  →  http://0.0.0.0:{args.port}")
    print(f"  From SSH host  →  http://<mac-ip>:{args.port}")
    print(f"  Data source    →  {BASE_DIR}")
    print("  Press Ctrl+C to stop.\n")

    app.run(host=args.host, port=args.port, debug=False)
