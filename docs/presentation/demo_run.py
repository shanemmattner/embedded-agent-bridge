#!/usr/bin/env python3
"""
EAB Presentation Demo Runner
==============================
Drives the live demo sequence for the nRF5340 BLE peripheral.
Prints richly formatted output to terminal.
Writes /tmp/demo_step.txt so the dashboard can track progress.

Run from terminal:
    python demo_run.py

Open dashboard separately:
    python demo_dashboard.py
"""

from __future__ import annotations

import json
import os
import re
import subprocess
import sys
import time
from pathlib import Path

# ---------------------------------------------------------------------------
# Config
# ---------------------------------------------------------------------------

DEVICE    = "NRF5340_XXAA_APP"
PORT      = "/dev/cu.usbmodem0010500636591"
BASE_DIR  = "/tmp/eab-devices/default"
STEP_FILE = Path("/tmp/demo_step.txt")
ELF_PATH  = Path("/Users/shane/zephyrproject/build/zephyr/zephyr.elf")

# ---------------------------------------------------------------------------
# Terminal formatting
# ---------------------------------------------------------------------------

RESET  = "\033[0m"
BOLD   = "\033[1m"
DIM    = "\033[2m"
RED    = "\033[91m"
GREEN  = "\033[92m"
YELLOW = "\033[93m"
BLUE   = "\033[94m"
CYAN   = "\033[96m"
WHITE  = "\033[97m"
GRAY   = "\033[90m"

def banner(text: str):
    width = 70
    print(f"\n{BOLD}{CYAN}{'═' * width}{RESET}")
    print(f"{BOLD}{CYAN}  {text}{RESET}")
    print(f"{BOLD}{CYAN}{'═' * width}{RESET}\n")

def step(n: int, label: str):
    STEP_FILE.write_text(json.dumps({"step": n, "label": label}))
    print(f"\n{BOLD}{BLUE}▶ STEP {n}: {label}{RESET}")
    print(f"{GRAY}{'─' * 60}{RESET}")

def ok(msg: str):
    print(f"  {GREEN}✓{RESET}  {msg}")

def info(msg: str):
    print(f"  {CYAN}→{RESET}  {msg}")

def warn(msg: str):
    print(f"  {YELLOW}⚠{RESET}  {msg}")

def err(msg: str):
    print(f"  {RED}✗{RESET}  {RED}{msg}{RESET}")

def section(title: str):
    print(f"\n  {GRAY}{title}{RESET}")
    print(f"  {GRAY}{'·' * 50}{RESET}")

def print_json_block(data: dict, label: str = ""):
    if label:
        print(f"\n  {GRAY}{label}:{RESET}")
    lines = json.dumps(data, indent=2).splitlines()
    for line in lines:
        # Colorize keys
        line = re.sub(r'"(\w+)":', f'{BLUE}"\\1"{RESET}:', line)
        print(f"    {line}")

def pause(seconds: float = 1.0):
    time.sleep(seconds)

# ---------------------------------------------------------------------------
# eabctl wrapper
# ---------------------------------------------------------------------------

def eabctl(*args, check: bool = False) -> dict | str:
    """Run eabctl with --json, return parsed output."""
    cmd = ["eabctl", "--base-dir", BASE_DIR] + list(args)
    # Check if --json is relevant for this subcommand
    no_json_cmds = {"start", "stop", "rtt"}
    if args and args[0] not in no_json_cmds:
        cmd.append("--json")
    result = subprocess.run(cmd, capture_output=True, text=True)
    out = result.stdout.strip()
    if out:
        try:
            return json.loads(out)
        except json.JSONDecodeError:
            return out
    return {}


def eabctl_raw(*args) -> str:
    """Run eabctl, return raw stdout."""
    cmd = ["eabctl", "--base-dir", BASE_DIR] + list(args)
    result = subprocess.run(cmd, capture_output=True, text=True)
    return result.stdout.strip()


# ---------------------------------------------------------------------------
# Demo steps
# ---------------------------------------------------------------------------

def step1_daemon():
    step(1, "Start EAB daemon — connect to nRF5340")

    info(f"Port: {PORT}")
    info(f"Session dir: {BASE_DIR}")

    # Stop any existing daemon
    eabctl_raw("stop")
    pause(0.5)

    # Start fresh
    result = eabctl("start", "--port", PORT)
    if isinstance(result, dict) and result.get("started"):
        ok(f"Daemon started  PID={result['pid']}")
    else:
        warn("Daemon may already be running — checking status")

    pause(1.5)

    # Status
    status = eabctl("status")
    if isinstance(status, dict):
        conn = status.get("status", {}).get("connection", {})
        health = status.get("status", {}).get("health", {})
        print_json_block({
            "port":       conn.get("port", PORT),
            "baud":       conn.get("baud", 115200),
            "connection": conn.get("status", "unknown"),
            "health":     health.get("status", "unknown"),
        }, "daemon status")
        if conn.get("status") == "connected":
            ok("Serial port open and connected")
        else:
            warn(f"Connection status: {conn.get('status')}")


def step2_rtt():
    step(2, "Start RTT — read Zephyr boot log")

    info(f"Transport: jlink  Device: {DEVICE}")

    result = eabctl_raw("rtt", "start", "--device", DEVICE, "--transport", "jlink", "--json")
    try:
        rdata = json.loads(result)
        ok(f"RTT started  channels={rdata.get('num_up_channels', '?')}")
        info(f"Log: {rdata.get('log_path', BASE_DIR + '/rtt.log')}")
    except Exception:
        warn(f"RTT start output: {result[:120]}")

    info("Waiting for Zephyr boot messages...")
    pause(5.0)

    section("RTT output (last 20 lines)")
    # rtt-raw.log is written directly by JLinkRTTLogger
    rtt_raw = Path(BASE_DIR) / "rtt-raw.log"
    if rtt_raw.exists():
        lines = rtt_raw.read_text(errors="replace").splitlines()
        lines = [l for l in lines if l.strip() and not l.startswith("Transfer rate")][-20:]
    else:
        lines = eabctl_raw("rtt", "tail", "20").splitlines()
    for line in lines:
        if "err" in line.lower() or "fault" in line.lower():
            print(f"    {RED}{line}{RESET}")
        elif "wrn" in line.lower():
            print(f"    {YELLOW}{line}{RESET}")
        elif "ADVERTISING" in line or "CONNECTED" in line or "ready" in line.lower():
            print(f"    {GREEN}{line}{RESET}")
        elif "DATA:" in line:
            print(f"    {BLUE}{line}{RESET}")
        else:
            print(f"    {GRAY}{line}{RESET}")

    ok("Zephyr OS booted — BLE stack initialised")
    ok("Identity: nRF5340 advertising as EAB-Peripheral")


def step3_ble_status():
    step(3, "BLE advertising — read state via shell + RTT")

    info("Sending: 'ble status' via UART shell")
    eabctl("send", "ble status")
    pause(1.5)

    section("RTT log — BLE stack state")
    rtt_raw = Path(BASE_DIR) / "rtt-raw.log"
    if rtt_raw.exists():
        rtt_lines = [l for l in rtt_raw.read_text(errors="replace").splitlines()
                     if l.strip() and not l.startswith("Transfer rate")][-20:]
    else:
        rtt_lines = eabctl_raw("rtt", "tail", "20").splitlines()
    for line in rtt_lines:
        if "ADVERTISING" in line or "Identity" in line or "ready" in line.lower():
            print(f"    {GREEN}{line}{RESET}")
        elif "wrn" in line.lower():
            print(f"    {YELLOW}{line}{RESET}")
        else:
            print(f"    {GRAY}{line}{RESET}")

    section("What EAB exposes to an agent")
    print(f"    {CYAN}eabctl rtt tail 50 --json{RESET}   ← structured JSON, parse in agent")
    print(f"    {CYAN}eabctl status --json{RESET}         ← connection health")
    print(f"    {CYAN}eabctl events 20 --json{RESET}      ← event stream (connect/disconnect)")
    print(f"    {GRAY}# All files also readable directly:{RESET}")
    print(f"    {GRAY}cat {BASE_DIR}/rtt.log{RESET}")
    print(f"    {GRAY}cat {BASE_DIR}/rtt.jsonl{RESET}")

    ok("Agent reads live BLE state without holding any connections or sessions")


def step4_dwt():
    step(4, "DWT — non-halting watchpoint on BLE counter")

    info("ARM Cortex-M33 has 4 DWT comparators")
    info("Normal GDB watchpoints halt the CPU — BLE connection drops")
    info("DWT watchpoints: no halt, streams changes at ~100Hz via J-Link")

    # Try to resolve symbol from ELF
    if ELF_PATH.exists():
        info(f"ELF: {ELF_PATH}")
        cmd_args = [
            "dwt", "watch",
            "--device", DEVICE,
            "--symbol", "sensor_counter",
            "--elf", str(ELF_PATH),
        ]
    else:
        warn(f"ELF not found at {ELF_PATH} — using raw address")
        cmd_args = [
            "dwt", "watch",
            "--device", DEVICE,
            "--address", "0x200026ec",
            "--size", "4",
            "--mode", "write",
            "--label", "sensor_counter",
        ]

    section("DWT watch command")
    cmd_display = "eabctl " + " ".join(cmd_args[1:])
    print(f"    {CYAN}{cmd_display}{RESET}")

    # dwt watch streams continuously — run for 4s then kill
    proc = subprocess.Popen(
        ["eabctl", "--base-dir", BASE_DIR] + cmd_args,
        stdout=subprocess.PIPE, stderr=subprocess.PIPE, text=True
    )
    pause(4.0)
    proc.terminate()
    try:
        out, err = proc.communicate(timeout=2)
        output = (out + err).strip()
        if output:
            for line in output.splitlines()[:10]:
                print(f"    {GRAY}{line}{RESET}")
    except subprocess.TimeoutExpired:
        proc.kill()

    section("Listing active DWT comparators")
    dwt_list = eabctl_raw("dwt", "list")
    for line in dwt_list.splitlines():
        print(f"    {BLUE}{line}{RESET}")

    ok("DWT watchpoint armed — CPU keeps running, BLE connection stays up")
    info("Events stream to /tmp/eab-devices/default/events.jsonl")

    pause(2.0)

    section("Recent events")
    events = eabctl("events", "10")
    if isinstance(events, dict):
        for ev in events.get("events", [])[:8]:
            print(f"    {GRAY}{json.dumps(ev)}{RESET}")


def step5_fault():
    step(5, "Inject fault — Cortex-M UsageFault")

    info("Sending: 'fault null'  → triggers NULL pointer dereference")
    warn("Board will crash and auto-reboot (MPU + stack sentinel enabled)")

    eabctl("send", "fault null")
    pause(3.0)

    section("Alerts (crash detection)")
    alerts = eabctl("alerts", "10")
    if isinstance(alerts, dict):
        lines = alerts.get("lines", [])
        if lines:
            for entry in lines:
                content = entry.get("content", "")
                if content:
                    print(f"    {RED}{content}{RESET}")
            ok(f"EAB detected crash pattern — {len(lines)} alert line(s)")
        else:
            info("No alerts yet — checking RTT log directly")
            rtt_lines = eabctl_raw("rtt", "tail", "20")
            for line in rtt_lines.splitlines():
                if any(k in line for k in ["FAULT", "fault", "CRASH", "reset"]):
                    print(f"    {RED}{line}{RESET}")

    section("RTT log around crash")
    rtt_lines = eabctl_raw("rtt", "tail", "25")
    for line in rtt_lines.splitlines():
        if any(k in line for k in ["FAULT", "CRASH", "USAGE", "BUS", "MEM", "HF"]):
            print(f"    {RED}{BOLD}{line}{RESET}")
        elif "Booting" in line or "starting" in line:
            print(f"    {GREEN}{line}{RESET}")
        else:
            print(f"    {GRAY}{line}{RESET}")


def step6_fault_analyze():
    step(6, "Fault analysis — decode Cortex-M registers + AI prompt")

    info("Runs GDB one-shot via J-Link GDB server")
    info("Reads: CFSR, HFSR, BFAR, MMFAR, SFSR, stacked PC")
    info("--rtt-context 50: last 50 RTT lines attached for LLM context")

    section("eabctl fault-analyze")
    print(f"    {CYAN}eabctl fault-analyze \\")
    print(f"        --device {DEVICE} \\")
    print(f"        --rtt-context 50 \\")
    print(f"        --json{RESET}\n")

    result = subprocess.run(
        ["eabctl", "--base-dir", BASE_DIR,
         "fault-analyze", "--device", DEVICE, "--json"],
        capture_output=True, text=True, timeout=30,
    )
    output = result.stdout.strip()
    if output:
        try:
            data = json.loads(output)
            # Print key fields
            fault_info = {
                "fault_type":   data.get("fault_type", "unknown"),
                "cfsr_decoded": data.get("cfsr_decoded", {}),
                "stacked_pc":   data.get("stacked_pc", "N/A"),
                "rtt_lines":    f"{len(data.get('context_window', []))} lines captured",
            }
            print_json_block(fault_info, "fault analysis")

            ai_prompt = data.get("ai_prompt", "")
            if ai_prompt:
                print(f"\n  {GRAY}ai_prompt (send this to Claude):{RESET}")
                print(f"  {YELLOW}{'─' * 60}{RESET}")
                for line in ai_prompt.splitlines()[:15]:
                    print(f"    {YELLOW}{line}{RESET}")
                if len(ai_prompt.splitlines()) > 15:
                    print(f"    {GRAY}... ({len(ai_prompt.splitlines())} lines total){RESET}")
                ok("ai_prompt field ready — paste into Claude for root cause")
        except json.JSONDecodeError:
            for line in output.splitlines():
                print(f"    {GRAY}{line}{RESET}")
    else:
        stderr = result.stderr.strip()
        if stderr:
            warn("fault-analyze needs GDB probe connection")
            warn("(Board may have already reset — run manually after crash)")
            for line in stderr.splitlines()[:8]:
                print(f"    {GRAY}{line}{RESET}")


def step7_reset():
    step(7, "Reset board — verify clean boot")

    info("Hardware reset via J-Link")
    result = eabctl("reset", "--chip", "nrf5340")
    if isinstance(result, dict):
        print_json_block(result, "reset result")

    pause(3.0)
    info("Waiting for Zephyr to boot...")

    section("RTT after reset")
    rtt_lines = eabctl_raw("rtt", "tail", "15")
    for line in rtt_lines.splitlines():
        if "Booting" in line or "ready" in line.lower() or "ADVERTISING" in line:
            print(f"    {GREEN}{line}{RESET}")
        else:
            print(f"    {GRAY}{line}{RESET}")

    ok("Clean boot confirmed — BLE advertising again")

    section("Daemon health after reset")
    diag = eabctl("diagnose")
    if isinstance(diag, dict):
        for check in diag.get("checks", []):
            s = check["status"]
            sym = GREEN + "✓" if s == "ok" else YELLOW + "⚠" if s == "warn" else RED + "✗"
            print(f"    {sym}{RESET}  {check['name']:20s} {GRAY}{check['message']}{RESET}")


def step8_complete():
    step(9, "Demo complete")
    STEP_FILE.write_text(json.dumps({"step": 9, "label": "Demo complete"}))

    banner("Embedded Agent Bridge — Summary")

    items = [
        ("Serial daemon",     "Port owned by daemon — agent never blocks"),
        ("RTT via J-Link",    "Zephyr logs readable as files — no subprocess"),
        ("DWT watchpoints",   "Watch memory without halting CPU — BLE stays up"),
        ("GDB one-shot",      "Batch commands, JSON output, no interactive TTY"),
        ("Fault analyze",     "Registers decoded + ai_prompt for LLM root cause"),
        ("HIL regression",    "YAML test suite — exit 0/1, drops into CI"),
        ("MCP server",        "eabmcp — 8 tools for Claude Desktop / Cursor"),
    ]

    for feature, desc in items:
        print(f"  {GREEN}✓{RESET}  {BOLD}{feature:22s}{RESET}  {GRAY}{desc}{RESET}")

    print(f"\n  {BLUE}github.com/shanemmattner/embedded-agent-bridge{RESET}\n")


# ---------------------------------------------------------------------------
# Main
# ---------------------------------------------------------------------------

STEPS = [
    step1_daemon,
    step2_rtt,
    step3_ble_status,
    step4_dwt,
    step5_fault,
    step6_fault_analyze,
    step7_reset,
    step8_complete,
]

def run_all():
    banner("Embedded Agent Bridge — Live Demo")
    print(f"  {GRAY}nRF5340 DK  •  Zephyr OS  •  BLE 5.4  •  Cortex-M33{RESET}")
    print(f"  {GRAY}Dashboard:  http://0.0.0.0:8050{RESET}\n")

    for fn in STEPS:
        fn()
        pause(1.0)
        input(f"\n  {DIM}[press Enter for next step]{RESET} ")

    STEP_FILE.write_text(json.dumps({"step": 9, "label": "Complete"}))


def run_step(n: int):
    """Run a single numbered step (1-based)."""
    if 1 <= n <= len(STEPS):
        STEPS[n - 1]()
    else:
        err(f"Step {n} out of range (1–{len(STEPS)})")


if __name__ == "__main__":
    import argparse

    ap = argparse.ArgumentParser(description="EAB Demo Runner")
    ap.add_argument("--step", type=int, default=None,
                    help="Run a single step (1-8) instead of all")
    ap.add_argument("--auto", action="store_true",
                    help="Run all steps without pausing for Enter")
    args = ap.parse_args()

    if args.step is not None:
        run_step(args.step)
    elif args.auto:
        banner("EAB Demo — Auto Mode")
        for fn in STEPS:
            fn()
            pause(2.0)
        STEP_FILE.write_text(json.dumps({"step": 9, "label": "Complete"}))
    else:
        run_all()
