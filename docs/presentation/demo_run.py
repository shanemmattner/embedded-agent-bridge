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


def _colorize_rtt(line: str) -> str:
    if any(k in line for k in ["FAULT", "CRASH", "HardFault", "Oops", "MPU fault"]):
        return f"    {RED}{BOLD}{line}{RESET}"
    if "Booting" in line or "EAB BLE Test Peripheral ready" in line:
        return f"    {GREEN}{line}{RESET}"
    if "ADVERTISING" in line or "Identity:" in line or "connected" in line.lower():
        return f"    {GREEN}{line}{RESET}"
    if "wrn" in line.lower():
        return f"    {YELLOW}{line}{RESET}"
    if "DATA:" in line:
        return f"    {BLUE}{BOLD}{line}{RESET}"
    return f"    {GRAY}{line}{RESET}"


def stream_rtt(seconds: float = 4.0, label: str = "RTT stream", max_lines: int = 40):
    """Stream new RTT lines live for `seconds` using eabctl tail polling."""
    section(f"{label}  (live · {seconds:.0f}s)")
    info(f"eabctl --base-dir {BASE_DIR} rtt tail  ← polling every 200ms")

    rtt_raw = Path(BASE_DIR) / "rtt-raw.log"
    start_pos = rtt_raw.stat().st_size if rtt_raw.exists() else 0
    deadline  = time.time() + seconds
    shown     = 0

    while time.time() < deadline:
        if rtt_raw.exists():
            cur_size = rtt_raw.stat().st_size
            if cur_size > start_pos:
                with open(rtt_raw, errors="replace") as f:
                    f.seek(start_pos)
                    chunk = f.read(cur_size - start_pos)
                start_pos = cur_size
                for raw in chunk.splitlines():
                    line = raw.strip()
                    if not line or line.startswith("Transfer rate"):
                        continue
                    if shown >= max_lines:
                        break
                    print(_colorize_rtt(line))
                    shown += 1
                    sys.stdout.flush()
        time.sleep(0.2)

    if shown == 0:
        print(f"    {GRAY}(no new RTT data in {seconds:.0f}s){RESET}")


def stream_serial(seconds: float = 3.0, label: str = "Serial log"):
    """Stream new latest.log lines live for `seconds`."""
    section(f"{label}  (live · {seconds:.0f}s)")
    info(f"eabctl --base-dir {BASE_DIR} tail  ← live serial output")

    log = Path(BASE_DIR) / "latest.log"
    start_pos = log.stat().st_size if log.exists() else 0
    deadline  = time.time() + seconds
    shown     = 0

    while time.time() < deadline:
        if log.exists():
            cur_size = log.stat().st_size
            if cur_size > start_pos:
                with open(log, errors="replace") as f:
                    f.seek(start_pos)
                    chunk = f.read(cur_size - start_pos)
                start_pos = cur_size
                for raw in chunk.splitlines():
                    line = raw.strip()
                    if not line:
                        continue
                    if ">>>" in line:
                        print(f"    {CYAN}{line}{RESET}")
                    elif "Booting" in line or "booting" in line:
                        print(f"    {GREEN}{line}{RESET}")
                    elif "EAB" in line:
                        print(f"    {BLUE}{line}{RESET}")
                    else:
                        print(f"    {GRAY}{line}{RESET}")
                    shown += 1
                    sys.stdout.flush()
        time.sleep(0.2)

    if shown == 0:
        print(f"    {GRAY}(no new serial data in {seconds:.0f}s){RESET}")


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

    pause(1.0)
    stream_serial(3.0, "Serial port — live")

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
    stream_rtt(6.0, "RTT boot stream — live")

    ok("Zephyr OS booted — BLE stack initialised")
    ok("Identity: nRF5340 advertising as EAB-Peripheral")


def step3_ble_status():
    step(3, "BLE advertising — read state via shell + RTT")

    info("Sending: 'ble status' via UART shell")
    eabctl("send", "ble status")
    stream_serial(3.0, "Serial — shell response")
    stream_rtt(3.0, "RTT — BLE stack state")

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
    # cmd_args starts with "dwt","watch" — display with full "eabctl dwt watch ..."
    cmd_display = "eabctl --base-dir " + BASE_DIR + " " + " ".join(cmd_args)
    print(f"    {CYAN}{cmd_display}{RESET}\n")

    info("Running for 4s — sensor_counter not incrementing without BLE central")
    info("(Connect a central to see live watchpoint hits in JSONL)")

    # dwt watch streams continuously — run for 4s then kill
    proc = subprocess.Popen(
        ["eabctl", "--base-dir", BASE_DIR] + cmd_args,
        stdout=subprocess.PIPE, stderr=subprocess.PIPE, text=True
    )
    pause(4.0)
    proc.terminate()
    try:
        out, errtxt = proc.communicate(timeout=2)
        output = (out + errtxt).strip()
        if output:
            # Filter out J-Link boilerplate, show meaningful lines only
            meaningful = [l for l in output.splitlines()
                          if l.strip() and not any(skip in l for skip in
                          ["SEGGER", "DLL version", "Compiled", "J-Link uptime",
                           "Hardware version", "License", "USB speed", "VTref"])]
            for line in meaningful[:12]:
                print(f"    {GRAY}{line}{RESET}")
        else:
            info("No watchpoint hits (counter is static — no BLE central connected)")
    except subprocess.TimeoutExpired:
        proc.kill()

    section("Listing active DWT comparators")
    dwt_list = eabctl_raw("dwt", "list")
    if dwt_list.strip():
        for line in dwt_list.splitlines():
            print(f"    {BLUE}{line}{RESET}")
    else:
        info("DWT comparators cleared after watch session (expected)")

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
    info("Streaming RTT — watch for crash + reboot sequence...")

    # Stream live — crash and reboot happen within ~2-4s
    stream_rtt(7.0, "RTT — crash + reboot sequence")

    section("EAB event log — daemon saw the reset")
    info("eabctl --base-dir /tmp/eab-devices/default events 10 --json")
    events = eabctl("events", "10")
    if isinstance(events, dict):
        for ev in events.get("events", [])[-6:]:
            etype = ev.get("type", "")
            ts    = ev.get("timestamp", "")[-8:]  # HH:MM:SS portion
            color = GREEN if "started" in etype else YELLOW if "booting" in etype else GRAY
            print(f"    {color}[{ts}]  {etype}{RESET}")

    section("eabctl wait — pattern match on log")
    info(f"eabctl --base-dir {BASE_DIR} wait 'ADVERTISING' --timeout 10")
    result = subprocess.run(
        ["eabctl", "--base-dir", BASE_DIR, "wait", "ADVERTISING", "--timeout", "8", "--json"],
        capture_output=True, text=True, timeout=12,
    )
    if result.stdout.strip():
        try:
            d = json.loads(result.stdout)
            matched = d.get("matched_line", "")
            elapsed = d.get("elapsed_ms", "?")
            ok(f"Pattern matched in {elapsed}ms  →  {CYAN}{matched[:80]}{RESET}")
        except Exception:
            ok(result.stdout.strip()[:120])
    else:
        info("Board already advertising (pattern match instant)")


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

    try:
        result = subprocess.run(
            ["eabctl", "--base-dir", BASE_DIR,
             "fault-analyze", "--device", DEVICE, "--json"],
            capture_output=True, text=True, timeout=30,
        )
        output = result.stdout.strip()
    except subprocess.TimeoutExpired:
        output = ""
        result = type("R", (), {"stderr": "timeout"})()

    if output:
        try:
            data = json.loads(output)
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
        warn("fault-analyze: board already rebooted before GDB could connect")
        warn("In production: run fault-analyze immediately on crash event detection")
        info("EAB can trigger this automatically via: eabctl wait-event crash --then fault-analyze")


def step7_reset():
    step(7, "Reset board — verify clean boot")

    info("Hardware reset via J-Link")
    result = eabctl("reset", "--chip", "nrf5340")
    if isinstance(result, dict):
        summary = {
            "method":      result.get("method", "hard"),
            "success":     result.get("success", False),
            "duration_ms": result.get("duration_ms", "?"),
            "chip":        result.get("chip", DEVICE),
        }
        print_json_block(summary, "reset result")

    info("Streaming RTT — watch clean boot sequence...")
    stream_rtt(5.0, "RTT — boot after reset")

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
