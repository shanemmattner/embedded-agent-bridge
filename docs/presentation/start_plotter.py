#!/usr/bin/env python3
"""Launch the EAB real-time uPlot WebSocket plotter (file-tail mode)."""
import argparse
from eab.plotter.server import run_plotter

ap = argparse.ArgumentParser(description="EAB RTT Plotter")
ap.add_argument("--log-path", default="/tmp/eab-devices/default/rtt-raw.log")
ap.add_argument("--host",     default="0.0.0.0")
ap.add_argument("--port",     type=int, default=8080)
args = ap.parse_args()

print(f"\n  EAB RTT Plotter")
print(f"  Log:  {args.log_path}")
print(f"  URL:  http://192.168.0.19:{args.port}\n")

run_plotter(host=args.host, port=args.port, log_path=args.log_path, open_browser=False)
