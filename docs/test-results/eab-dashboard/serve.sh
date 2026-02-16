#!/bin/bash
cd /tmp/eab-dashboard

PORT=${1:-8888}

echo "========================================"
echo "EAB Dashboard Server Starting"
echo "========================================"
echo "Dashboard: http://localhost:$PORT"
echo "Press Ctrl+C to stop"
echo "========================================"

python3 -m http.server $PORT
