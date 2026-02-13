"""
eabctl: Agent-friendly CLI for Embedded Agent Bridge (EAB).

This package provides a comprehensive command-line interface for managing
the EAB daemon and interacting with embedded devices through serial connections.

Design goals:
- Tiny, stable surface area for LLM agents
- Optional JSON output for reliable parsing
- Works with the existing file-based IPC used by the EAB daemon

Main commands:
- status: Check daemon and device status
- tail: View serial output logs
- send: Send commands to the device
- flash: Flash firmware to embedded devices
- openocd: Manage OpenOCD for JTAG debugging
- gdb: Run GDB commands through EAB

Entry points:
- eabctl: Main CLI entry point (installed via pip)
- Can also be imported and called programmatically via main(argv)
"""

from __future__ import annotations

import argparse
import sys
from typing import Optional

from eab.openocd_bridge import DEFAULT_TELNET_PORT, DEFAULT_GDB_PORT, DEFAULT_TCL_PORT

from eab.cli.helpers import (
    DEFAULT_BASE_DIR,
    _print,
    _resolve_base_dir,
)

# Import all command functions from submodules
from eab.cli.serial_cmds import (
    cmd_status,
    cmd_tail,
    cmd_alerts,
    cmd_events,
    cmd_send,
    cmd_wait,
    cmd_wait_event,
    cmd_capture_between,
)
from eab.cli.daemon_cmds import (
    cmd_start,
    cmd_stop,
    cmd_pause,
    cmd_resume,
    cmd_diagnose,
)
from eab.cli.flash_cmds import (
    cmd_flash,
    cmd_erase,
    cmd_reset,
    cmd_chip_info,
    cmd_preflight_hw,
)
from eab.cli.debug_cmds import (
    cmd_openocd_status,
    cmd_openocd_start,
    cmd_openocd_stop,
    cmd_openocd_cmd,
    cmd_gdb,
    cmd_gdb_script,
    cmd_inspect,
    cmd_threads,
    cmd_watch,
    cmd_memdump,
)
from eab.cli.fault_cmds import cmd_fault_analyze
from eab.cli.profile_cmds import (
    cmd_profile_function,
    cmd_profile_region,
    cmd_dwt_status,
)
from eab.cli.stream_cmds import (
    cmd_stream_start,
    cmd_stream_stop,
    cmd_recv,
    cmd_recv_latest,
)
from eab.cli.var_cmds import (
    cmd_vars,
    cmd_read_vars,
)


def _preprocess_argv(argv: list[str]) -> list[str]:
    """Reorder global flags (--json, --base-dir) before the subcommand.

    Agent ergonomics: allow global flags anywhere (before or after subcommand).
    argparse doesn't support this reliably with subparsers, so we reorder.

    Args:
        argv: Raw argument list (without ``sys.argv[0]``).

    Returns:
        Reordered argument list with global flags moved to the front.
    """
    global_args: list[str] = []
    rest: list[str] = []
    i = 0
    while i < len(argv):
        token = argv[i]
        if token == "--json":
            global_args.append(token)
            i += 1
            continue
        if token.startswith("--base-dir="):
            global_args.append(token)
            i += 1
            continue
        if token == "--base-dir":
            # Needs a value.
            if i + 1 >= len(argv):
                rest.append(token)
                i += 1
                continue
            global_args.extend([token, argv[i + 1]])
            i += 2
            continue

        rest.append(token)
        i += 1

    return global_args + rest


def _build_parser() -> argparse.ArgumentParser:
    """Build the full argparse parser with all subcommands."""
    parser = argparse.ArgumentParser(prog="eabctl", description="EAB agent-friendly CLI")
    parser.add_argument(
        "--version",
        action="version",
        version="%(prog)s 1.0.0 (embedded-agent-bridge)",
    )
    parser.add_argument("--json", action="store_true", help="Output machine-parseable JSON")
    parser.add_argument(
        "--base-dir",
        default=None,
        help=f"Override session dir (default: daemon base_dir or {DEFAULT_BASE_DIR})",
    )

    sub = parser.add_subparsers(dest="cmd", required=True)

    sub.add_parser("status", help="Show daemon + device status")

    p_tail = sub.add_parser("tail", help="Show last N lines of latest.log")
    p_tail.add_argument("lines_pos", type=int, nargs="?", default=None, help="Number of lines (positional)")
    p_tail.add_argument("-n", "--lines", type=int, default=None, dest="lines_flag")

    p_alerts = sub.add_parser("alerts", help="Show last N lines of alerts.log")
    p_alerts.add_argument("lines_pos", type=int, nargs="?", default=None, help="Number of lines (positional)")
    p_alerts.add_argument("-n", "--lines", type=int, default=None, dest="lines_flag")

    p_send = sub.add_parser("send", help="Queue a command to the device")
    p_send.add_argument("text")
    p_send.add_argument("--await", dest="await_ack", action="store_true", help="Wait for daemon to log the command")
    p_send.add_argument(
        "--await-event",
        action="store_true",
        help="Wait for events.jsonl to confirm the command was sent",
    )
    p_send.add_argument("--timeout", type=float, default=10.0)

    p_wait = sub.add_parser("wait", help="Wait for a regex to appear in latest.log")
    p_wait.add_argument("pattern")
    p_wait.add_argument("--timeout", type=float, default=30.0)

    p_events = sub.add_parser("events", help="Show last N events from events.jsonl")
    p_events.add_argument("lines_pos", type=int, nargs="?", default=None, help="Number of lines (positional)")
    p_events.add_argument("-n", "--lines", type=int, default=None, dest="lines_flag")

    p_wait_event = sub.add_parser("wait-event", help="Wait for an event in events.jsonl")
    p_wait_event.add_argument("--type", dest="event_type", help="Event type to match")
    p_wait_event.add_argument("--contains", help="Substring to match in serialized event")
    p_wait_event.add_argument("--command", help="Match data.command exactly")
    p_wait_event.add_argument("--timeout", type=float, default=30.0)

    p_pause = sub.add_parser("pause", help="Pause daemon (release port) for N seconds")
    p_pause.add_argument("seconds", type=int, nargs="?", default=120)

    sub.add_parser("resume", help="Resume daemon early (remove pause file)")

    p_openocd = sub.add_parser("openocd", help="Manage OpenOCD (USB-JTAG) through EAB")
    p_openocd.add_argument("action", choices=["status", "start", "stop", "cmd"])
    p_openocd.add_argument("--chip", default="esp32s3")
    p_openocd.add_argument("--vid", default="0x303a")
    p_openocd.add_argument("--pid", default="0x1001")
    p_openocd.add_argument("--telnet-port", type=int, default=DEFAULT_TELNET_PORT)
    p_openocd.add_argument("--gdb-port", type=int, default=DEFAULT_GDB_PORT)
    p_openocd.add_argument("--tcl-port", type=int, default=DEFAULT_TCL_PORT)
    p_openocd.add_argument("--timeout", type=float, default=2.0)
    p_openocd.add_argument("--command", default="", help="Command for 'openocd cmd'")

    p_gdb = sub.add_parser("gdb", help="Run one-shot GDB commands through EAB (requires OpenOCD)")
    p_gdb.add_argument("--chip", default="esp32s3")
    p_gdb.add_argument("--target", default=f"localhost:{DEFAULT_GDB_PORT}")
    p_gdb.add_argument("--elf", default=None)
    p_gdb.add_argument("--gdb", dest="gdb_path", default=None)
    p_gdb.add_argument("--timeout", type=float, default=60.0)
    p_gdb.add_argument("--cmd", dest="commands", action="append", default=[], help="GDB command (repeatable)")

    p_fault = sub.add_parser("fault-analyze", help="Analyze Cortex-M fault registers via debug probe")
    p_fault.add_argument("--device", default="NRF5340_XXAA_APP", help="Device string (e.g., NRF5340_XXAA_APP, MCXN947)")
    p_fault.add_argument("--elf", default=None, help="ELF file for GDB symbols")
    p_fault.add_argument("--chip", default="nrf5340", help="Chip type for GDB selection")
    p_fault.add_argument("--probe", default="jlink", choices=["jlink", "openocd"],
                        help="Debug probe type (default: jlink)")

    p_profile_func = sub.add_parser("profile-function", help="Profile a function using DWT cycle counter")
    p_profile_func.add_argument("--device", default=None, help="J-Link device string (e.g., NRF5340_XXAA_APP)")
    p_profile_func.add_argument("--elf", required=True, help="Path to ELF file with debug symbols")
    p_profile_func.add_argument("--function", required=True, help="Function name to profile")
    p_profile_func.add_argument("--cpu-freq", type=int, default=None, help="CPU frequency in Hz (auto-detect if omitted)")
    p_profile_func.add_argument("--probe", default="jlink", choices=["jlink", "openocd"],
                        help="Debug probe type (default: jlink)")
    p_profile_func.add_argument("--chip", default=None, help="Chip type for OpenOCD config (e.g., stm32l4, mcxn947)")

    p_profile_region = sub.add_parser("profile-region", help="Profile an address region using DWT cycle counter")
    p_profile_region.add_argument("--device", default=None, help="J-Link device string (e.g., NRF5340_XXAA_APP)")
    p_profile_region.add_argument("--start", type=lambda x: int(x, 0), required=True, help="Start address (hex or decimal)")
    p_profile_region.add_argument("--end", type=lambda x: int(x, 0), required=True, help="End address (hex or decimal)")
    p_profile_region.add_argument("--cpu-freq", type=int, default=None, help="CPU frequency in Hz (auto-detect if omitted)")
    p_profile_region.add_argument("--probe", default="jlink", choices=["jlink", "openocd"],
                        help="Debug probe type (default: jlink)")
    p_profile_region.add_argument("--chip", default=None, help="Chip type for OpenOCD config (e.g., stm32l4, mcxn947)")

    p_dwt_status = sub.add_parser("dwt-status", help="Display DWT register state")
    p_dwt_status.add_argument("--device", default=None, help="J-Link device string (e.g., NRF5340_XXAA_APP)")
    p_dwt_status.add_argument("--probe", default="jlink", choices=["jlink", "openocd"],
                        help="Debug probe type (default: jlink)")
    p_dwt_status.add_argument("--chip", default=None, help="Chip type for OpenOCD config (e.g., stm32l4, mcxn947)")

    p_gdb_script = sub.add_parser("gdb-script", help="Execute custom GDB Python script via debug probe")
    p_gdb_script.add_argument("script_path", help="Path to GDB Python script")
    p_gdb_script.add_argument("--device", default=None, help="Device string for J-Link (e.g., NRF5340_XXAA_APP)")
    p_gdb_script.add_argument("--elf", default=None, help="ELF file for GDB symbols")
    p_gdb_script.add_argument("--chip", default="nrf5340", help="Chip type for GDB selection")
    p_gdb_script.add_argument("--probe", default="jlink", choices=["jlink", "openocd"],
                        help="Debug probe type (default: jlink)")
    p_gdb_script.add_argument("--port", type=int, default=None, help="GDB server port override")

    p_inspect = sub.add_parser("inspect", help="Inspect a struct variable via GDB")
    p_inspect.add_argument("variable", help="Variable name to inspect (e.g., _kernel)")
    p_inspect.add_argument("--device", default=None, help="Device string for J-Link")
    p_inspect.add_argument("--elf", default=None, help="ELF file for GDB symbols")
    p_inspect.add_argument("--chip", default="nrf5340", help="Chip type for GDB selection")
    p_inspect.add_argument("--probe", default="jlink", choices=["jlink", "openocd"],
                        help="Debug probe type (default: jlink)")
    p_inspect.add_argument("--port", type=int, default=None, help="GDB server port override")

    p_threads = sub.add_parser("threads", help="List RTOS threads via GDB")
    p_threads.add_argument("--device", default=None, help="Device string for J-Link")
    p_threads.add_argument("--elf", default=None, help="ELF file for GDB symbols")
    p_threads.add_argument("--chip", default="nrf5340", help="Chip type for GDB selection")
    p_threads.add_argument("--rtos", default="zephyr", help="RTOS type (default: zephyr)")
    p_threads.add_argument("--probe", default="jlink", choices=["jlink", "openocd"],
                        help="Debug probe type (default: jlink)")
    p_threads.add_argument("--port", type=int, default=None, help="GDB server port override")

    p_watch = sub.add_parser("watch", help="Set watchpoint on variable and log hits")
    p_watch.add_argument("variable", help="Variable name to watch (e.g., g_counter)")
    p_watch.add_argument("--device", default=None, help="Device string for J-Link")
    p_watch.add_argument("--elf", default=None, help="ELF file for GDB symbols")
    p_watch.add_argument("--chip", default="nrf5340", help="Chip type for GDB selection")
    p_watch.add_argument("--max-hits", type=int, default=100, help="Maximum hits to log (default: 100)")
    p_watch.add_argument("--probe", default="jlink", choices=["jlink", "openocd"],
                        help="Debug probe type (default: jlink)")
    p_watch.add_argument("--port", type=int, default=None, help="GDB server port override")

    p_memdump = sub.add_parser("memdump", help="Dump memory region to file via GDB")
    p_memdump.add_argument("start_addr", help="Starting address (hex like 0x20000000)")
    p_memdump.add_argument("size", type=int, help="Number of bytes to dump")
    p_memdump.add_argument("output_path", help="Output file path")
    p_memdump.add_argument("--device", default=None, help="Device string for J-Link")
    p_memdump.add_argument("--elf", default=None, help="ELF file for GDB symbols")
    p_memdump.add_argument("--chip", default="nrf5340", help="Chip type for GDB selection")
    p_memdump.add_argument("--probe", default="jlink", choices=["jlink", "openocd"],
                        help="Debug probe type (default: jlink)")
    p_memdump.add_argument("--port", type=int, default=None, help="GDB server port override")

    # Variable inspection commands
    p_vars = sub.add_parser("vars", help="List global/static variables from ELF symbol table")
    p_vars.add_argument("--elf", required=True, help="Path to ELF file with debug symbols")
    p_vars.add_argument("--map", dest="map_file", default=None, help="Optional GNU ld .map file for richer info")
    p_vars.add_argument("--filter", dest="filter_pattern", default=None, help="Glob pattern to filter names (e.g., 'g_*')")

    p_read_vars = sub.add_parser("read-vars", help="Read variable values from target via debug probe")
    p_read_vars.add_argument("--elf", required=True, help="Path to ELF file with debug symbols")
    p_read_vars.add_argument("--var", dest="var_names", action="append", default=[], help="Variable name (repeatable)")
    p_read_vars.add_argument("--all", dest="read_all", action="store_true", help="Read all variables from ELF")
    p_read_vars.add_argument("--filter", dest="filter_pattern", default=None, help="Glob pattern when using --all")
    p_read_vars.add_argument("--device", default=None, help="Device string for J-Link (e.g., NRF5340_XXAA_APP)")
    p_read_vars.add_argument("--chip", default="nrf5340", help="Chip type for GDB selection")
    p_read_vars.add_argument("--probe", default="jlink", choices=["jlink", "openocd"],
                        help="Debug probe type (default: jlink)")
    p_read_vars.add_argument("--port", type=int, default=None, help="GDB server port override")

    p_stream = sub.add_parser("stream", help="Configure high-speed data stream mode")
    p_stream.add_argument("action", choices=["start", "stop"])
    p_stream.add_argument("--mode", choices=["raw", "base64"], default="raw")
    p_stream.add_argument("--chunk", type=int, default=16384, help="Chunk size for raw reads")
    p_stream.add_argument("--marker", default=None, help="Marker line to start streaming")
    p_stream.add_argument(
        "--no-patterns",
        action="store_true",
        help="Disable pattern matching while streaming",
    )
    p_stream.add_argument(
        "--truncate",
        action="store_true",
        help="Truncate data.bin when enabling stream",
    )

    p_recv = sub.add_parser("recv", help="Read bytes from data.bin")
    p_recv.add_argument("--offset", type=int, required=True)
    p_recv.add_argument("--length", type=int, required=True)
    p_recv.add_argument("--out", dest="output_path", default=None)
    p_recv.add_argument("--base64", action="store_true")

    p_recv_latest = sub.add_parser("recv-latest", help="Read last N bytes from data.bin")
    p_recv_latest.add_argument("--bytes", dest="length", type=int, required=True)
    p_recv_latest.add_argument("--out", dest="output_path", default=None)
    p_recv_latest.add_argument("--base64", action="store_true")

    p_start = sub.add_parser("start", help="Start daemon in background (logs to /tmp)")
    p_start.add_argument("--port", default="auto")
    p_start.add_argument("--baud", type=int, default=115200)
    p_start.add_argument("--force", action="store_true")

    sub.add_parser("stop", help="Stop running daemon")

    p_capture = sub.add_parser(
        "capture-between",
        help="Capture payload lines between markers (defaults to base64-only) and write to a file",
    )
    p_capture.add_argument("start_marker")
    p_capture.add_argument("end_marker")
    p_capture.add_argument("output")
    p_capture.add_argument("--timeout", type=float, default=120.0)
    p_capture.add_argument(
        "--from-start",
        action="store_true",
        help="Scan from start of log instead of tailing new lines",
    )
    p_capture.add_argument(
        "--no-strip-timestamps",
        action="store_true",
        help="Do not remove [HH:MM:SS.mmm] prefixes before filtering",
    )
    p_capture.add_argument(
        "--filter",
        choices=["base64", "none"],
        default="base64",
        help="Payload filter mode (default: base64)",
    )
    p_capture.add_argument(
        "--decode-base64",
        action="store_true",
        help="Base64-decode captured payload and write bytes to output file",
    )

    sub.add_parser("diagnose", help="Run basic health checks and print recommendations")

    # Flash operations (chip-agnostic)
    p_flash = sub.add_parser("flash", help="Flash firmware to device")
    p_flash.add_argument("firmware", help="Path to firmware binary (.bin/.hex)")
    p_flash.add_argument("--chip", required=True, help="Chip type (esp32s3, stm32l4, etc.)")
    p_flash.add_argument("--address", default=None, help="Flash address (default: chip-specific)")
    p_flash.add_argument("--port", default=None, help="Serial port (ESP32) or ignored (STM32)")
    p_flash.add_argument("--tool", default=None, help="Flash tool override (st-flash, esptool.py, jlink)")
    p_flash.add_argument("--baud", type=int, default=921600, help="Baud rate (ESP32 only)")
    p_flash.add_argument("--connect-under-reset", action="store_true",
                        help="STM32: Connect while holding reset (for crashed chips)")
    p_flash.add_argument("--board", default=None, help="Zephyr board name (e.g., nrf5340dk/nrf5340/cpuapp)")
    p_flash.add_argument("--runner", default=None, help="Flash runner override (jlink, openocd, nrfjprog)")
    p_flash.add_argument("--device", default=None, help="J-Link device string (e.g., NRF5340_XXAA_APP, NRF5340_XXAA_NET)")
    p_flash.add_argument("--reset-after", action="store_true", default=None,
                        help="J-Link: Reset and run after flash (default: True, use --no-reset-after for NET core)")
    p_flash.add_argument("--no-reset-after", dest="reset_after", action="store_false",
                        help="J-Link: Skip reset after flash (for NET core)")
    p_flash.add_argument("--net-firmware", default=None, help="NET core firmware path (nRF5340 dual-core only)")

    p_erase = sub.add_parser("erase", help="Erase flash memory")
    p_erase.add_argument("--chip", required=True, help="Chip type (esp32s3, stm32l4, etc.)")
    p_erase.add_argument("--port", default=None, help="Serial port (ESP32) or ignored (STM32)")
    p_erase.add_argument("--tool", default=None, help="Erase tool override")
    p_erase.add_argument("--connect-under-reset", action="store_true",
                        help="STM32: Connect while holding reset (for crashed chips)")
    p_erase.add_argument("--runner", default=None, help="Flash runner override (jlink, openocd, nrfjprog)")
    p_erase.add_argument("--core", choices=["app", "net"], default="app",
                        help="Target core for multi-core chips (nRF5340: app or net, default: app)")

    p_chip_info = sub.add_parser("chip-info", help="Get chip information")
    p_chip_info.add_argument("--chip", required=True, help="Chip type (esp32s3, stm32l4, etc.)")
    p_chip_info.add_argument("--port", default=None, help="Serial port (ESP32) or ignored (STM32)")

    p_reset = sub.add_parser("reset", help="Hardware reset device")
    p_reset.add_argument("--chip", required=True, help="Chip type (esp32s3, stm32l4, etc.)")
    p_reset.add_argument("--method", choices=["hard", "soft", "bootloader"], default="hard")
    p_reset.add_argument("--connect-under-reset", action="store_true",
                        help="STM32: Connect while holding reset (for crashed chips)")
    p_reset.add_argument("--device", default=None, help="J-Link device string (e.g., NRF5340_XXAA_APP, MCXN947)")

    # Hardware verification (preflight check)
    p_preflight = sub.add_parser("preflight-hw", help="Verify hardware by flashing stock firmware")
    p_preflight.add_argument("stock_firmware", help="Path to known-good stock firmware binary")
    p_preflight.add_argument("--chip", required=True, help="Chip type (esp32s3, stm32l4, etc.)")
    p_preflight.add_argument("--address", default=None, help="Flash address (default: chip-specific)")
    p_preflight.add_argument("--timeout", type=int, default=10, help="Boot timeout in seconds")

    return parser


def main(argv: Optional[list[str]] = None) -> int:
    """Entry point for the ``eabctl`` CLI.

    Parses arguments, resolves the session base directory, and dispatches
    to the appropriate command handler.

    Args:
        argv: Argument list to parse.  Defaults to ``sys.argv[1:]``.

    Returns:
        Exit code: 0 on success, non-zero on error.
    """
    if argv is None:
        argv = sys.argv[1:]

    argv = _preprocess_argv(argv)

    parser = _build_parser()
    args = parser.parse_args(argv)
    base_dir = _resolve_base_dir(args.base_dir)

    if args.cmd == "status":
        return cmd_status(base_dir=base_dir, json_mode=args.json)
    if args.cmd == "tail":
        lines = args.lines_flag if args.lines_flag is not None else (args.lines_pos if args.lines_pos is not None else 50)
        return cmd_tail(base_dir=base_dir, lines=lines, json_mode=args.json)
    if args.cmd == "alerts":
        lines = args.lines_flag if args.lines_flag is not None else (args.lines_pos if args.lines_pos is not None else 20)
        return cmd_alerts(base_dir=base_dir, lines=lines, json_mode=args.json)
    if args.cmd == "events":
        lines = args.lines_flag if args.lines_flag is not None else (args.lines_pos if args.lines_pos is not None else 50)
        return cmd_events(base_dir=base_dir, lines=lines, json_mode=args.json)
    if args.cmd == "send":
        return cmd_send(
            base_dir=base_dir,
            text=args.text,
            await_ack=args.await_ack,
            await_event=args.await_event,
            timeout_s=args.timeout,
            json_mode=args.json,
        )
    if args.cmd == "wait":
        return cmd_wait(base_dir=base_dir, pattern=args.pattern, timeout_s=args.timeout, json_mode=args.json)
    if args.cmd == "wait-event":
        return cmd_wait_event(
            base_dir=base_dir,
            event_type=args.event_type,
            contains=args.contains,
            command=args.command,
            timeout_s=args.timeout,
            json_mode=args.json,
        )
    if args.cmd == "pause":
        return cmd_pause(base_dir=base_dir, seconds=args.seconds, json_mode=args.json)
    if args.cmd == "resume":
        return cmd_resume(base_dir=base_dir, json_mode=args.json)
    if args.cmd == "openocd":
        if args.action == "status":
            return cmd_openocd_status(base_dir=base_dir, json_mode=args.json)
        if args.action == "start":
            return cmd_openocd_start(
                base_dir=base_dir,
                chip=args.chip,
                vid=args.vid,
                pid=args.pid,
                telnet_port=args.telnet_port,
                gdb_port=args.gdb_port,
                tcl_port=args.tcl_port,
                json_mode=args.json,
            )
        if args.action == "stop":
            return cmd_openocd_stop(base_dir=base_dir, json_mode=args.json)
        if args.action == "cmd":
            if not args.command:
                _print({"error": "missing --command"}, json_mode=args.json)
                return 2
            return cmd_openocd_cmd(
                base_dir=base_dir,
                command=args.command,
                telnet_port=args.telnet_port,
                timeout_s=args.timeout,
                json_mode=args.json,
            )
    if args.cmd == "gdb":
        if not args.commands:
            _print({"error": "missing --cmd (repeatable)"}, json_mode=args.json)
            return 2
        return cmd_gdb(
            base_dir=base_dir,
            chip=args.chip,
            target=args.target,
            elf=args.elf,
            gdb_path=args.gdb_path,
            commands=args.commands,
            timeout_s=args.timeout,
            json_mode=args.json,
        )
    if args.cmd == "fault-analyze":
        return cmd_fault_analyze(
            base_dir=base_dir,
            device=args.device,
            elf=args.elf,
            chip=args.chip,
            probe_type=args.probe,
            json_mode=args.json,
        )
    if args.cmd == "profile-function":
        return cmd_profile_function(
            base_dir=base_dir,
            device=args.device,
            elf=args.elf,
            function=args.function,
            cpu_freq=args.cpu_freq,
            probe_type=args.probe,
            chip=args.chip,
            json_mode=args.json,
        )
    if args.cmd == "profile-region":
        return cmd_profile_region(
            base_dir=base_dir,
            start_addr=args.start,
            end_addr=args.end,
            device=args.device,
            cpu_freq=args.cpu_freq,
            probe_type=args.probe,
            chip=args.chip,
            json_mode=args.json,
        )
    if args.cmd == "dwt-status":
        return cmd_dwt_status(
            base_dir=base_dir,
            device=args.device,
            probe_type=args.probe,
            chip=args.chip,
            json_mode=args.json,
        )
    if args.cmd == "gdb-script":
        return cmd_gdb_script(
            base_dir=base_dir,
            script_path=args.script_path,
            device=args.device,
            elf=args.elf,
            chip=args.chip,
            probe_type=args.probe,
            port=args.port,
            json_mode=args.json,
        )
    if args.cmd == "inspect":
        return cmd_inspect(
            base_dir=base_dir,
            variable=args.variable,
            device=args.device,
            elf=args.elf,
            chip=args.chip,
            probe_type=args.probe,
            port=args.port,
            json_mode=args.json,
        )
    if args.cmd == "threads":
        return cmd_threads(
            base_dir=base_dir,
            device=args.device,
            elf=args.elf,
            chip=args.chip,
            rtos=args.rtos,
            probe_type=args.probe,
            port=args.port,
            json_mode=args.json,
        )
    if args.cmd == "watch":
        return cmd_watch(
            base_dir=base_dir,
            variable=args.variable,
            device=args.device,
            elf=args.elf,
            chip=args.chip,
            max_hits=args.max_hits,
            probe_type=args.probe,
            port=args.port,
            json_mode=args.json,
        )
    if args.cmd == "memdump":
        return cmd_memdump(
            base_dir=base_dir,
            start_addr=args.start_addr,
            size=args.size,
            device=args.device,
            elf=args.elf,
            chip=args.chip,
            output_path=args.output_path,
            probe_type=args.probe,
            port=args.port,
            json_mode=args.json,
        )
    if args.cmd == "vars":
        return cmd_vars(
            elf=args.elf,
            map_file=args.map_file,
            filter_pattern=args.filter_pattern,
            json_mode=args.json,
        )
    if args.cmd == "read-vars":
        if not args.var_names and not args.read_all:
            _print({"error": "Specify --var <name> or --all"}, json_mode=args.json)
            return 2
        return cmd_read_vars(
            base_dir=base_dir,
            elf=args.elf,
            var_names=args.var_names,
            read_all=args.read_all,
            filter_pattern=args.filter_pattern,
            device=args.device,
            chip=args.chip,
            probe_type=args.probe,
            port=args.port,
            json_mode=args.json,
        )
    if args.cmd == "stream":
        if args.action == "start":
            return cmd_stream_start(
                base_dir=base_dir,
                mode=args.mode,
                chunk_size=args.chunk,
                marker=args.marker,
                pattern_matching=not args.no_patterns,
                truncate=args.truncate,
                json_mode=args.json,
            )
        return cmd_stream_stop(base_dir=base_dir, json_mode=args.json)
    if args.cmd == "recv":
        return cmd_recv(
            base_dir=base_dir,
            offset=args.offset,
            length=args.length,
            output_path=args.output_path,
            base64_output=args.base64,
            json_mode=args.json,
        )
    if args.cmd == "recv-latest":
        return cmd_recv_latest(
            base_dir=base_dir,
            length=args.length,
            output_path=args.output_path,
            base64_output=args.base64,
            json_mode=args.json,
        )
    if args.cmd == "start":
        return cmd_start(
            base_dir=base_dir,
            port=args.port,
            baud=args.baud,
            force=args.force,
            json_mode=args.json,
        )
    if args.cmd == "stop":
        return cmd_stop(json_mode=args.json)
    if args.cmd == "capture-between":
        return cmd_capture_between(
            base_dir=base_dir,
            start_marker=args.start_marker,
            end_marker=args.end_marker,
            output_path=args.output,
            timeout_s=args.timeout,
            from_start=args.from_start,
            strip_timestamps=not args.no_strip_timestamps,
            filter_mode=args.filter,
            decode_base64=args.decode_base64,
            json_mode=args.json,
        )
    if args.cmd == "diagnose":
        return cmd_diagnose(base_dir=base_dir, json_mode=args.json)
    if args.cmd == "flash":
        return cmd_flash(
            firmware=args.firmware,
            chip=args.chip,
            address=args.address,
            port=args.port,
            tool=args.tool,
            baud=args.baud,
            connect_under_reset=getattr(args, "connect_under_reset", False),
            board=args.board,
            runner=args.runner,
            device=getattr(args, "device", None),
            reset_after=getattr(args, "reset_after", True),
            net_firmware=getattr(args, "net_firmware", None),
            json_mode=args.json,
        )
    if args.cmd == "erase":
        return cmd_erase(
            chip=args.chip,
            port=args.port,
            tool=args.tool,
            connect_under_reset=getattr(args, "connect_under_reset", False),
            runner=args.runner,
            core=getattr(args, "core", "app"),
            json_mode=args.json,
        )
    if args.cmd == "chip-info":
        return cmd_chip_info(
            chip=args.chip,
            port=args.port,
            json_mode=args.json,
        )
    if args.cmd == "reset":
        return cmd_reset(
            chip=args.chip,
            method=args.method,
            connect_under_reset=getattr(args, "connect_under_reset", False),
            device=getattr(args, "device", None),
            json_mode=args.json,
        )
    if args.cmd == "preflight-hw":
        return cmd_preflight_hw(
            base_dir=base_dir,
            chip=args.chip,
            stock_firmware=args.stock_firmware,
            address=args.address,
            timeout=args.timeout,
            json_mode=args.json,
        )

    parser.error(f"Unknown command: {args.cmd}")
    return 2
