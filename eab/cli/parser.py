"""Argument parser for eabctl CLI."""

from __future__ import annotations

import argparse

from eab.openocd_bridge import DEFAULT_GDB_PORT, DEFAULT_TCL_PORT, DEFAULT_TELNET_PORT


def _preprocess_argv(argv: list[str]) -> list[str]:
    """Reorder global flags (--json, --base-dir, --device) before the subcommand.

    Agent ergonomics: allow global flags anywhere (before or after subcommand).
    argparse doesn't support this reliably with subparsers, so we reorder.

    Note: ``--device`` is ONLY treated as a global flag when it appears
    **before** the subcommand.  Many subcommands (fault-analyze, rtt start,
    etc.) have their own ``--device`` argument with a different meaning
    (J-Link device string).  Once we encounter the first positional token
    (the subcommand), we stop extracting ``--device`` as a global flag.

    Args:
        argv: Raw argument list (without ``sys.argv[0]``).

    Returns:
        Reordered argument list with global flags moved to the front.
    """
    global_args: list[str] = []
    rest: list[str] = []
    i = 0
    found_subcommand = False
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
        # Only extract --device as a global flag before the subcommand token.
        # After the subcommand, --device belongs to the subcommand (e.g.,
        # fault-analyze --device NRF5340_XXAA_APP is a J-Link device string,
        # NOT the global EAB device selector).
        if not found_subcommand and token.startswith("--device="):
            global_args.append(token)
            i += 1
            continue
        if not found_subcommand and token == "--device" and i + 1 < len(argv):
            next_token = argv[i + 1]
            if not next_token.startswith("-"):
                global_args.extend([token, next_token])
                i += 2
                continue
            rest.append(token)
            i += 1
            continue

        # First non-flag token is the subcommand
        if not token.startswith("-") and not found_subcommand:
            found_subcommand = True
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
        help="Override session dir (default: /tmp/eab-devices/<device>/)",
    )
    parser.add_argument(
        "--device",
        default=None,
        dest="target_device",
        help="Target device name (e.g., nrf5340, esp32). Routes to /tmp/eab-devices/<name>/",
    )

    sub = parser.add_subparsers(dest="cmd", required=True)

    sub.add_parser("status", help="Show daemon + device status")

    p_tail = sub.add_parser("tail", help="Show last N lines of latest.log")
    p_tail.add_argument("lines_pos", type=int, nargs="?", default=None, help="Number of lines (positional)")
    p_tail.add_argument("-n", "--lines", type=int, default=None, dest="lines_flag")

    p_alerts = sub.add_parser("alerts", help="Show last N lines of alerts.log")
    p_alerts.add_argument("lines_pos", type=int, nargs="?", default=None, help="Number of lines (positional)")
    p_alerts.add_argument("-n", "--lines", type=int, default=None, dest="lines_flag")

    p_resets = sub.add_parser("resets", help="Show reset history and statistics")
    p_resets.add_argument(
        "lines_pos", type=int, nargs="?", default=10, help="Number of recent resets to show (positional)"
    )
    p_resets.add_argument("-n", "--lines", type=int, default=None, dest="lines_flag")

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
    p_wait.add_argument(
        "--scan-all", action="store_true", default=False, help="Scan from beginning of log instead of end"
    )
    p_wait.add_argument("--scan-from", type=int, default=None, help="Scan from byte offset in log file")

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
    p_fault.add_argument(
        "--probe", default="jlink", choices=["jlink", "openocd", "xds110"], help="Debug probe type (default: jlink)"
    )
    p_fault.add_argument(
        "--probe-selector",
        default=None,
        help="Probe serial number or identifier (OpenOCD: adapter serial, J-Link: serial number)",
    )

    p_profile_func = sub.add_parser("profile-function", help="Profile a function using DWT cycle counter")
    p_profile_func.add_argument("--device", default=None, help="J-Link device string (e.g., NRF5340_XXAA_APP)")
    p_profile_func.add_argument("--elf", required=True, help="Path to ELF file with debug symbols")
    p_profile_func.add_argument("--function", required=True, help="Function name to profile")
    p_profile_func.add_argument(
        "--cpu-freq", type=int, default=None, help="CPU frequency in Hz (auto-detect if omitted)"
    )
    p_profile_func.add_argument(
        "--probe", default="jlink", choices=["jlink", "openocd", "xds110"], help="Debug probe type (default: jlink)"
    )
    p_profile_func.add_argument("--chip", default=None, help="Chip type for OpenOCD config (e.g., stm32l4, mcxn947)")
    p_profile_func.add_argument(
        "--probe-selector",
        default=None,
        help="Probe serial number or identifier (OpenOCD: adapter serial, J-Link: serial number)",
    )

    p_profile_region = sub.add_parser("profile-region", help="Profile an address region using DWT cycle counter")
    p_profile_region.add_argument("--device", default=None, help="J-Link device string (e.g., NRF5340_XXAA_APP)")
    p_profile_region.add_argument(
        "--start", type=lambda x: int(x, 0), required=True, help="Start address (hex or decimal)"
    )
    p_profile_region.add_argument("--end", type=lambda x: int(x, 0), required=True, help="End address (hex or decimal)")
    p_profile_region.add_argument(
        "--cpu-freq", type=int, default=None, help="CPU frequency in Hz (auto-detect if omitted)"
    )
    p_profile_region.add_argument(
        "--probe", default="jlink", choices=["jlink", "openocd", "xds110"], help="Debug probe type (default: jlink)"
    )
    p_profile_region.add_argument("--chip", default=None, help="Chip type for OpenOCD config (e.g., stm32l4, mcxn947)")
    p_profile_region.add_argument(
        "--probe-selector",
        default=None,
        help="Probe serial number or identifier (OpenOCD: adapter serial, J-Link: serial number)",
    )

    p_dwt_status = sub.add_parser("dwt-status", help="Display DWT register state")
    p_dwt_status.add_argument("--device", default=None, help="J-Link device string (e.g., NRF5340_XXAA_APP)")
    p_dwt_status.add_argument(
        "--probe", default="jlink", choices=["jlink", "openocd", "xds110"], help="Debug probe type (default: jlink)"
    )
    p_dwt_status.add_argument("--chip", default=None, help="Chip type for OpenOCD config (e.g., stm32l4, mcxn947)")
    p_dwt_status.add_argument(
        "--probe-selector",
        default=None,
        help="Probe serial number or identifier (OpenOCD: adapter serial, J-Link: serial number)",
    )

    p_gdb_script = sub.add_parser("gdb-script", help="Execute custom GDB Python script via debug probe")
    p_gdb_script.add_argument("script_path", help="Path to GDB Python script")
    p_gdb_script.add_argument("--device", default=None, help="Device string for J-Link (e.g., NRF5340_XXAA_APP)")
    p_gdb_script.add_argument("--elf", default=None, help="ELF file for GDB symbols")
    p_gdb_script.add_argument("--chip", default="nrf5340", help="Chip type for GDB selection")
    p_gdb_script.add_argument(
        "--probe", default="jlink", choices=["jlink", "openocd", "xds110"], help="Debug probe type (default: jlink)"
    )
    p_gdb_script.add_argument("--port", type=int, default=None, help="GDB server port override")

    p_inspect = sub.add_parser("inspect", help="Inspect a struct variable via GDB")
    p_inspect.add_argument("variable", help="Variable name to inspect (e.g., _kernel)")
    p_inspect.add_argument("--device", default=None, help="Device string for J-Link")
    p_inspect.add_argument("--elf", default=None, help="ELF file for GDB symbols")
    p_inspect.add_argument("--chip", default="nrf5340", help="Chip type for GDB selection")
    p_inspect.add_argument(
        "--probe", default="jlink", choices=["jlink", "openocd", "xds110"], help="Debug probe type (default: jlink)"
    )
    p_inspect.add_argument("--port", type=int, default=None, help="GDB server port override")

    p_threads = sub.add_parser("threads", help="List RTOS threads via GDB")
    p_threads.add_argument("--device", default=None, help="Device string for J-Link")
    p_threads.add_argument("--elf", default=None, help="ELF file for GDB symbols")
    p_threads.add_argument("--chip", default="nrf5340", help="Chip type for GDB selection")
    p_threads.add_argument("--rtos", default="zephyr", help="RTOS type (default: zephyr)")
    p_threads.add_argument(
        "--probe", default="jlink", choices=["jlink", "openocd", "xds110"], help="Debug probe type (default: jlink)"
    )
    p_threads.add_argument("--port", type=int, default=None, help="GDB server port override")

    p_watch = sub.add_parser("watch", help="Set watchpoint on variable and log hits")
    p_watch.add_argument("variable", help="Variable name to watch (e.g., g_counter)")
    p_watch.add_argument("--device", default=None, help="Device string for J-Link")
    p_watch.add_argument("--elf", default=None, help="ELF file for GDB symbols")
    p_watch.add_argument("--chip", default="nrf5340", help="Chip type for GDB selection")
    p_watch.add_argument("--max-hits", type=int, default=100, help="Maximum hits to log (default: 100)")
    p_watch.add_argument(
        "--probe", default="jlink", choices=["jlink", "openocd", "xds110"], help="Debug probe type (default: jlink)"
    )
    p_watch.add_argument("--port", type=int, default=None, help="GDB server port override")

    p_memdump = sub.add_parser("memdump", help="Dump memory region to file via GDB")
    p_memdump.add_argument("start_addr", help="Starting address (hex like 0x20000000)")
    p_memdump.add_argument("size", type=int, help="Number of bytes to dump")
    p_memdump.add_argument("output_path", help="Output file path")
    p_memdump.add_argument("--device", default=None, help="Device string for J-Link")
    p_memdump.add_argument("--elf", default=None, help="ELF file for GDB symbols")
    p_memdump.add_argument("--chip", default="nrf5340", help="Chip type for GDB selection")
    p_memdump.add_argument(
        "--probe", default="jlink", choices=["jlink", "openocd", "xds110"], help="Debug probe type (default: jlink)"
    )
    p_memdump.add_argument("--port", type=int, default=None, help="GDB server port override")

    # Variable inspection commands
    p_vars = sub.add_parser("vars", help="List global/static variables from ELF symbol table")
    p_vars.add_argument("--elf", required=True, help="Path to ELF file with debug symbols")
    p_vars.add_argument("--map", dest="map_file", default=None, help="Optional GNU ld .map file for richer info")
    p_vars.add_argument(
        "--filter", dest="filter_pattern", default=None, help="Glob pattern to filter names (e.g., 'g_*')"
    )

    p_read_vars = sub.add_parser("read-vars", help="Read variable values from target via debug probe")
    p_read_vars.add_argument("--elf", required=True, help="Path to ELF file with debug symbols")
    p_read_vars.add_argument("--var", dest="var_names", action="append", default=[], help="Variable name (repeatable)")
    p_read_vars.add_argument("--all", dest="read_all", action="store_true", help="Read all variables from ELF")
    p_read_vars.add_argument("--filter", dest="filter_pattern", default=None, help="Glob pattern when using --all")
    p_read_vars.add_argument("--device", default=None, help="Device string for J-Link (e.g., NRF5340_XXAA_APP)")
    p_read_vars.add_argument("--chip", default="nrf5340", help="Chip type for GDB selection")
    p_read_vars.add_argument(
        "--probe", default="jlink", choices=["jlink", "openocd", "xds110"], help="Debug probe type (default: jlink)"
    )
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
    p_start.add_argument(
        "--log-max-size", type=int, default=100, help="Max log size in MB before rotation (default: 100)"
    )
    p_start.add_argument("--log-max-files", type=int, default=5, help="Max rotated log files to keep (default: 5)")
    p_start.add_argument("--no-log-compress", action="store_true", help="Disable compression of rotated logs")

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
    p_flash.add_argument("firmware", help="Path to firmware binary (.bin/.hex/.elf) or ESP-IDF project directory")
    p_flash.add_argument("--chip", required=False, default=None, help="Chip type (esp32s3, stm32l4, etc.)")
    p_flash.add_argument("--address", default=None, help="Flash address (default: chip-specific)")
    p_flash.add_argument("--port", default=None, help="Serial port (ESP32) or ignored (STM32)")
    p_flash.add_argument("--tool", default=None, help="Flash tool override (st-flash, esptool, jlink)")
    p_flash.add_argument("--baud", type=int, default=921600, help="Baud rate (ESP32 only)")
    p_flash.add_argument(
        "--connect-under-reset", action="store_true", help="STM32: Connect while holding reset (for crashed chips)"
    )
    p_flash.add_argument("--board", default=None, help="Zephyr board name (e.g., nrf5340dk/nrf5340/cpuapp)")
    p_flash.add_argument("--runner", default=None, help="Flash runner override (jlink, openocd, nrfjprog)")
    p_flash.add_argument(
        "--device", default=None, help="J-Link device string (e.g., NRF5340_XXAA_APP, NRF5340_XXAA_NET)"
    )
    p_flash.add_argument(
        "--reset-after",
        action="store_true",
        default=None,
        help="J-Link: Reset and run after flash (default: True, use --no-reset-after for NET core)",
    )
    p_flash.add_argument(
        "--no-reset-after",
        dest="reset_after",
        action="store_false",
        help="J-Link: Skip reset after flash (for NET core)",
    )
    p_flash.add_argument("--net-firmware", default=None, help="NET core firmware path (nRF5340 dual-core only)")
    p_flash.add_argument(
        "--no-stub",
        action="store_true",
        help="ESP32: Use ROM bootloader directly (slower but more reliable for USB-JTAG)",
    )
    p_flash.add_argument(
        "--extra-esptool-args",
        nargs="*",
        default=[],
        help="ESP32: Extra arguments to pass through to esptool (e.g., --no-compress --verify)",
    )

    p_erase = sub.add_parser("erase", help="Erase flash memory")
    p_erase.add_argument("--chip", required=True, help="Chip type (esp32s3, stm32l4, etc.)")
    p_erase.add_argument("--port", default=None, help="Serial port (ESP32) or ignored (STM32)")
    p_erase.add_argument("--tool", default=None, help="Erase tool override")
    p_erase.add_argument(
        "--connect-under-reset", action="store_true", help="STM32: Connect while holding reset (for crashed chips)"
    )
    p_erase.add_argument("--runner", default=None, help="Flash runner override (jlink, openocd, nrfjprog)")
    p_erase.add_argument(
        "--core",
        choices=["app", "net"],
        default="app",
        help="Target core for multi-core chips (nRF5340: app or net, default: app)",
    )

    p_chip_info = sub.add_parser("chip-info", help="Get chip information")
    p_chip_info.add_argument("--chip", required=True, help="Chip type (esp32s3, stm32l4, etc.)")
    p_chip_info.add_argument("--port", default=None, help="Serial port (ESP32) or ignored (STM32)")

    p_reset = sub.add_parser("reset", help="Hardware reset device")
    p_reset.add_argument("--chip", required=True, help="Chip type (esp32s3, stm32l4, etc.)")
    p_reset.add_argument("--method", choices=["hard", "soft", "bootloader"], default="hard")
    p_reset.add_argument(
        "--connect-under-reset", action="store_true", help="STM32: Connect while holding reset (for crashed chips)"
    )
    p_reset.add_argument("--device", default=None, help="J-Link device string (e.g., NRF5340_XXAA_APP, MCXN947)")

    # Hardware verification (preflight check)
    p_preflight = sub.add_parser("preflight-hw", help="Verify hardware by flashing stock firmware")
    p_preflight.add_argument("stock_firmware", help="Path to known-good stock firmware binary")
    p_preflight.add_argument("--chip", required=True, help="Chip type (esp32s3, stm32l4, etc.)")
    p_preflight.add_argument("--address", default=None, help="Flash address (default: chip-specific)")
    p_preflight.add_argument("--timeout", type=int, default=10, help="Boot timeout in seconds")

    # Backtrace decoding
    p_decode_bt = sub.add_parser("decode-backtrace", help="Decode backtrace addresses to source locations")
    p_decode_bt.add_argument("--elf", required=True, help="Path to ELF file with debug symbols")
    p_decode_bt.add_argument("--text", default=None, help="Backtrace text to decode (reads from stdin if omitted)")
    p_decode_bt.add_argument(
        "--arch", default="arm", help="Architecture hint (arm, xtensa, riscv, esp32, nrf, stm32, etc.)"
    )
    p_decode_bt.add_argument("--toolchain", default=None, help="Explicit path to addr2line binary")
    p_decode_bt.add_argument("--show-raw", action="store_true", help="Include raw backtrace lines in output")

    # RTT commands (J-Link RTT via JLinkRTTLogger)
    p_rtt = sub.add_parser("rtt", help="J-Link RTT streaming (start/stop/reset/tail)")
    rtt_sub = p_rtt.add_subparsers(dest="rtt_action", required=True)

    p_rtt_start = rtt_sub.add_parser("start", help="Start RTT streaming via JLinkRTTLogger or probe-rs")
    p_rtt_start.add_argument("--device", required=True, help="Device/chip string (e.g., NRF5340_XXAA_APP, STM32L476RG)")
    p_rtt_start.add_argument(
        "--transport", default="jlink", choices=["jlink", "probe-rs"], help="RTT transport backend (default: jlink)"
    )
    p_rtt_start.add_argument(
        "--interface", default="SWD", choices=["SWD", "JTAG"], help="Debug interface (default: SWD)"
    )
    p_rtt_start.add_argument("--speed", type=int, default=4000, help="Interface speed in kHz (default: 4000)")
    p_rtt_start.add_argument("--channel", type=int, default=0, help="RTT channel number (default: 0)")
    p_rtt_start.add_argument(
        "--block-address",
        type=lambda x: int(x, 0),
        default=None,
        help="RTT control block address (hex, e.g., 0x20000410)",
    )
    p_rtt_start.add_argument(
        "--probe-selector", default=None, help="Probe selector for probe-rs (serial number or VID:PID, e.g., 0483:374b)"
    )

    rtt_sub.add_parser("stop", help="Stop RTT streaming")
    rtt_sub.add_parser("status", help="Get RTT streaming status")

    p_rtt_reset = rtt_sub.add_parser("reset", help="Stop RTT, reset target, restart RTT")
    p_rtt_reset.add_argument(
        "--wait", type=float, default=1.0, help="Seconds to wait after reset before restarting RTT (default: 1.0)"
    )

    p_rtt_tail = rtt_sub.add_parser("tail", help="Show last N lines of rtt.log")
    p_rtt_tail.add_argument("lines", type=int, nargs="?", default=50, help="Number of lines (default: 50)")

    # Binary RTT capture commands
    p_rtt_cap = sub.add_parser("rtt-capture", help="Binary RTT capture (start/convert/info)")
    rtt_cap_sub = p_rtt_cap.add_subparsers(dest="rtt_capture_action", required=True)

    p_cap_start = rtt_cap_sub.add_parser("start", help="Start binary RTT capture to .rttbin file")
    p_cap_start.add_argument("--device", required=True, help="Device string (e.g., NRF5340_XXAA_APP)")
    p_cap_start.add_argument(
        "--channel",
        type=int,
        action="append",
        default=[],
        dest="channels",
        help="RTT channel to capture (repeatable, default: [1])",
    )
    p_cap_start.add_argument("--output", "-o", required=True, help="Output .rttbin file path")
    p_cap_start.add_argument(
        "--sample-width", type=int, default=2, choices=[1, 2, 4], help="Bytes per sample (default: 2)"
    )
    p_cap_start.add_argument("--sample-rate", type=int, default=0, help="Sample rate in Hz (0 = unknown)")
    p_cap_start.add_argument("--timestamp-hz", type=int, default=0, help="Timestamp resolution in Hz (0 = none)")
    p_cap_start.add_argument("--interface", default="SWD", choices=["SWD", "JTAG"])
    p_cap_start.add_argument("--speed", type=int, default=4000, help="Interface speed in kHz")
    p_cap_start.add_argument(
        "--block-address", type=lambda x: int(x, 0), default=None, help="RTT control block address (hex)"
    )
    p_cap_start.add_argument(
        "--transport", default="jlink", choices=["jlink", "probe-rs"], help="Debug probe transport (default: jlink)"
    )

    p_cap_convert = rtt_cap_sub.add_parser("convert", help="Convert .rttbin to CSV/WAV/numpy")
    p_cap_convert.add_argument("input", help="Input .rttbin file")
    p_cap_convert.add_argument(
        "--format", "-f", dest="fmt", required=True, choices=["csv", "wav", "numpy"], help="Output format"
    )
    p_cap_convert.add_argument("--output", "-o", default=None, help="Output file path")
    p_cap_convert.add_argument("--channel", type=int, default=0, help="Channel for WAV export (default: 0)")
    p_cap_convert.add_argument(
        "--sample-rate", type=int, default=None, help="Override sample rate (required for WAV if not in header)"
    )

    p_cap_info = rtt_cap_sub.add_parser("info", help="Show .rttbin file header and stats")
    p_cap_info.add_argument("input", help="Input .rttbin file")

    # Multi-device management
    sub.add_parser("devices", help="List all registered devices and their status")

    p_device = sub.add_parser("device", help="Manage device registration (add/remove)")
    device_sub = p_device.add_subparsers(dest="device_action", required=True)

    p_dev_add = device_sub.add_parser("add", help="Register a device")
    p_dev_add.add_argument("name", help="Device name (e.g., nrf5340, esp32)")
    p_dev_add.add_argument(
        "--type", dest="device_type", default="debug", choices=["serial", "debug"], help="Device type (default: debug)"
    )
    p_dev_add.add_argument("--chip", default="", help="Chip identifier (e.g., nrf5340, stm32l476rg)")

    p_dev_rm = device_sub.add_parser("remove", help="Unregister a device")
    p_dev_rm.add_argument("name", help="Device name to remove")

    # Trace capture (Tonbandgerät/Perfetto integration)
    p_trace = sub.add_parser("trace", help="Trace capture (RTT/serial/logfile) and export to Perfetto")
    trace_sub = p_trace.add_subparsers(dest="trace_action", required=True)

    p_trace_start = trace_sub.add_parser("start", help="Start trace capture to binary file")
    p_trace_start.add_argument("--output", "-o", required=True, help="Output .rttbin file")
    p_trace_start.add_argument(
        "--source",
        default="rtt",
        choices=["rtt", "apptrace", "serial", "logfile"],
        help="Capture source (default: rtt)",
    )
    p_trace_start.add_argument(
        "--device", default="NRF5340_XXAA_APP", help="Device (rtt: J-Link device, apptrace: ESP32 variant like esp32c6)"
    )
    p_trace_start.add_argument("--channel", type=int, default=0, help="RTT channel (default: 0)")
    p_trace_start.add_argument(
        "--trace-dir",
        dest="trace_dir",
        default=None,
        help="Device base dir for serial mode (default: /tmp/eab-devices/{device})",
    )
    p_trace_start.add_argument("--logfile", default=None, help="Log file path for logfile mode")

    trace_sub.add_parser("stop", help="Stop active trace capture")

    p_trace_export = trace_sub.add_parser("export", help="Export trace to Perfetto JSON")
    p_trace_export.add_argument("--input", "-i", required=True, help="Input trace file (.rttbin, .svdat, CTF dir)")
    p_trace_export.add_argument("--output", "-o", required=True, help="Output .json file")
    p_trace_export.add_argument(
        "--format",
        default="auto",
        choices=["auto", "perfetto", "tband", "systemview", "ctf"],
        help="Input format (default: auto)",
    )

    # USB device reset
    p_usb_reset = sub.add_parser("usb-reset", help="Reset USB debug probe (recover from corruption)")
    p_usb_reset.add_argument(
        "--probe", default=None, help="Known probe name (stlink-v3, stlink-v2, jlink, cmsis-dap, esp-usb-jtag)"
    )
    p_usb_reset.add_argument("--vid", default=None, help="USB Vendor ID (hex, e.g., 0483)")
    p_usb_reset.add_argument("--pid", default=None, help="USB Product ID (hex, e.g., 3754)")
    p_usb_reset.add_argument(
        "--wait", type=float, default=5.0, help="Seconds to wait for re-enumeration (default: 5.0)"
    )

    # --- C2000-specific commands ---
    p_reg_read = sub.add_parser("reg-read", help="Read and decode a C2000 register or register group")
    p_reg_read.add_argument("--chip", default="f28003x", help="Chip name for register map (default: f28003x)")
    p_reg_read.add_argument("--register", default=None, help="Register name (e.g., NMIFLG)")
    p_reg_read.add_argument("--group", default=None, help="Register group name (e.g., fault_registers)")
    p_reg_read.add_argument("--ccxml", default=None, help="CCXML path for XDS110 probe")

    p_erad_status = sub.add_parser("erad-status", help="Show ERAD profiler register info")
    p_erad_status.add_argument("--chip", default="f28003x", help="Chip name (default: f28003x)")

    p_stream_vars = sub.add_parser("stream-vars", help="Stream variable values from C2000 target")
    p_stream_vars.add_argument("--map", dest="map_file", required=True, help="Path to MAP file")
    p_stream_vars.add_argument(
        "--var", dest="var_specs", action="append", default=[], help="Variable spec: name:address:type (repeatable)"
    )
    p_stream_vars.add_argument("--interval", type=int, default=100, help="Polling interval in ms (default: 100)")
    p_stream_vars.add_argument("--count", type=int, default=0, help="Number of samples (0 = infinite)")
    p_stream_vars.add_argument("--output", "-o", default=None, help="Output file path")

    p_dlog = sub.add_parser("dlog-capture", help="Capture DLOG_4CH buffers from C2000")
    p_dlog.add_argument(
        "--buffer", dest="buffer_specs", action="append", default=[], help="Buffer spec: name:address (repeatable)"
    )
    p_dlog.add_argument("--status-addr", default=None, help="DLOG status register address")
    p_dlog.add_argument("--size-addr", default=None, help="DLOG size register address")
    p_dlog.add_argument("--buffer-size", type=int, default=200, help="Samples per buffer (default: 200)")
    p_dlog.add_argument("--output", "-o", default=None, help="Output file path")
    p_dlog.add_argument(
        "--format",
        dest="output_format",
        default="json",
        choices=["json", "csv", "jsonl"],
        help="Output format (default: json)",
    )

    p_c2000_trace = sub.add_parser("c2000-trace-export", help="Export C2000 debug data to Perfetto JSON")
    p_c2000_trace.add_argument("--output", "-o", required=True, help="Output .json file")
    p_c2000_trace.add_argument("--erad-data", default=None, help="ERAD profiling results JSON file")
    p_c2000_trace.add_argument("--dlog-data", default=None, help="DLOG capture results JSON file")
    p_c2000_trace.add_argument("--log-file", default=None, help="Serial log file")
    p_c2000_trace.add_argument("--process-name", default="C2000 Debug", help="Process name in trace")

    # --- multi-device command ---
    p_multi = sub.add_parser("multi", help="Run a command across all registered devices")
    p_multi.add_argument("multi_cmd", nargs=argparse.REMAINDER, help="Command and args to run on each device")
    p_multi.add_argument("--timeout", type=float, default=30.0, help="Per-device timeout in seconds (default: 30)")

    # --- ELF size analysis ---
    p_size = sub.add_parser("size", help="Show ELF section sizes (Flash/RAM usage)")
    p_size.add_argument("elf", help="Path to ELF file")
    p_size.add_argument("--compare", default=None, help="Compare against another ELF file (show deltas)")

    # --- defmt decode ---
    p_defmt = sub.add_parser("defmt", help="Decode defmt wire format")
    defmt_sub = p_defmt.add_subparsers(dest="defmt_action", required=True)
    p_defmt_decode = defmt_sub.add_parser("decode", help="Decode defmt-encoded RTT stream")
    p_defmt_decode.add_argument("--elf", required=True, help="ELF file with defmt symbols")
    p_defmt_decode.add_argument("--input", dest="input_file", default=None, help="Input file (raw RTT binary)")
    p_defmt_decode.add_argument(
        "--from-rtt", action="store_true", help="Read from device RTT log (uses base_dir/rtt.log)"
    )

    # --- DWT hardware watchpoints ---
    p_dwt = sub.add_parser("dwt", help="DWT hardware watchpoints (non-halting stream)")
    dwt_sub = p_dwt.add_subparsers(dest="dwt_action", required=True)

    # dwt watch
    p_dwt_watch = dwt_sub.add_parser("watch", help="Non-halting watchpoint — stream JSONL hits")
    p_dwt_watch.add_argument(
        "--symbol", required=False, default=None, help="Symbol name from ELF (e.g., conn_interval)"
    )
    p_dwt_watch.add_argument(
        "--addr",
        type=lambda x: int(x, 0),
        default=None,
        help="Raw address override (hex, e.g., 0x20001234). Skips ELF lookup.",
    )
    p_dwt_watch.add_argument("--elf", default=None, help="ELF file for symbol resolution")
    p_dwt_watch.add_argument("--device", required=True, help="J-Link device string (e.g., NRF5340_XXAA_APP)")
    p_dwt_watch.add_argument(
        "--mode", default="write", choices=["read", "write", "rw"], help="Watchpoint mode (default: write)"
    )
    p_dwt_watch.add_argument(
        "--size", type=int, default=None, choices=[1, 2, 4], help="Variable size in bytes (auto from ELF if omitted)"
    )
    p_dwt_watch.add_argument("--poll-hz", type=int, default=100, help="Poll rate in Hz (default: 100)")
    p_dwt_watch.add_argument("--output", default=None, help="Append JSONL events to this file")
    p_dwt_watch.add_argument(
        "--duration", type=float, default=None, help="Stop after N seconds (default: run until Ctrl-C)"
    )
    p_dwt_watch.add_argument("--probe-selector", default=None, help="J-Link serial number for multi-probe setups")

    # dwt halt
    p_dwt_halt = dwt_sub.add_parser("halt", help="Halting watchpoint via GDB with optional condition")
    p_dwt_halt.add_argument("--symbol", required=True, help="Variable name to watch (must be in ELF symbols)")
    p_dwt_halt.add_argument("--elf", required=True, help="ELF file for debug symbols")
    p_dwt_halt.add_argument("--device", default=None, help="J-Link device string")
    p_dwt_halt.add_argument("--chip", default="nrf5340", help="Chip type for GDB selection (default: nrf5340)")
    p_dwt_halt.add_argument(
        "--mode",
        default="write",
        choices=["read", "write", "rw"],
        help="Watchpoint mode: write=watch, read=rwatch, rw=awatch",
    )
    p_dwt_halt.add_argument(
        "--condition", default=None, help="Python expression evaluated at each hit (e.g., 'value > 100')"
    )
    p_dwt_halt.add_argument("--max-hits", type=int, default=100)
    p_dwt_halt.add_argument("--backtrace", action="store_true", default=True)
    p_dwt_halt.add_argument("--probe", default="jlink", choices=["jlink", "openocd"])
    p_dwt_halt.add_argument("--probe-selector", default=None)
    p_dwt_halt.add_argument("--port", type=int, default=None)

    # dwt list
    p_dwt_list = dwt_sub.add_parser("list", help="Show active DWT comparators")
    p_dwt_list.add_argument("--device", default=None, help="J-Link device (reads live DWT_FUNCTn registers)")
    p_dwt_list.add_argument("--probe-selector", default=None)

    # dwt clear
    p_dwt_clear = dwt_sub.add_parser("clear", help="Release all DWT comparators")
    p_dwt_clear.add_argument("--device", required=True, help="J-Link device string")
    p_dwt_clear.add_argument("--probe-selector", default=None)

    # dwt explain
    p_dwt_explain = dwt_sub.add_parser("explain", help="Capture DWT data and produce an AI narrative")
    p_dwt_explain.add_argument("--device", default=None,
                               help="Device identifier, e.g. NRF5340_XXAA_APP")
    p_dwt_explain.add_argument("--symbols", required=True,
                               help="Comma-separated list of symbol names, e.g. conn_interval,mtu_size")
    p_dwt_explain.add_argument("--elf", required=True,
                               help="Path to the ELF file")
    p_dwt_explain.add_argument("--duration", type=int, default=5,
                               help="Capture duration in seconds (default: 5)")

    # --- MCP server ---
    sub.add_parser(
        "mcp-server",
        help="Start the EAB MCP server (stdio transport) for Claude Desktop / MCP clients",
    )

    # --- debug-monitor (ARM Debug Monitor exception control) ---
    p_dm = sub.add_parser("debug-monitor", help="Control ARM Debug Monitor exception mode")
    dm_sub = p_dm.add_subparsers(dest="dm_action", required=True)

    p_dm_enable = dm_sub.add_parser("enable", help="Enable debug monitor mode on target")
    p_dm_enable.add_argument("--device", required=True, help="J-Link device string (e.g., NRF5340_XXAA_APP)")
    p_dm_enable.add_argument(
        "--priority",
        type=int,
        default=3,
        help="Debug monitor exception priority (0-7, lower = higher priority, default: 3)",
    )

    p_dm_disable = dm_sub.add_parser("disable", help="Disable debug monitor mode on target")
    p_dm_disable.add_argument("--device", required=True, help="J-Link device string")

    p_dm_status = dm_sub.add_parser("status", help="Show current debug monitor status")
    p_dm_status.add_argument("--device", required=True, help="J-Link device string")

    # --- preflight (BLE-safe check) ---
    p_preflight_ble = sub.add_parser("preflight", help="Pre-debug preflight checks (BLE-safe mode etc.)")
    p_preflight_ble.add_argument("--device", required=True, help="J-Link device string")
    p_preflight_ble.add_argument(
        "--build-dir", dest="build_dir", default="build", help="Zephyr build directory (default: build)"
    )
    p_preflight_ble.add_argument(
        "--ble-safe", action="store_true", help="Check if BLE build conflicts with halt-mode debugging"
    )

    # --- regression (hardware-in-the-loop test runner) ---
    p_regression = sub.add_parser("regression", help="Run hardware-in-the-loop regression tests")
    p_regression.add_argument("--suite", default=None, help="Directory containing *.yaml test files")
    p_regression.add_argument("--test", default=None, help="Single test YAML file to run")
    p_regression.add_argument(
        "--filter", default=None, dest="filter_pattern", help="Glob pattern to filter test files (e.g. '*nrf*')"
    )
    p_regression.add_argument(
        "--timeout", type=int, default=None, help="Global timeout per test in seconds (overrides per-test)"
    )

    # --- anomaly detection ---
    p_anomaly = sub.add_parser("anomaly", help="Anomaly detection (record/compare/watch)")
    anomaly_sub = p_anomaly.add_subparsers(dest="anomaly_action", required=True)

    # anomaly record
    p_anom_rec = anomaly_sub.add_parser("record", help="Record a golden baseline from device log")
    p_anom_rec.add_argument("--duration", type=float, default=60.0, help="Recording window in seconds (default: 60)")
    p_anom_rec.add_argument("--output", "-o", required=True, help="Output baseline JSON file path")
    p_anom_rec.add_argument(
        "--log-source", default=None, help="Override log file path (default: <base_dir>/latest.log)"
    )
    p_anom_rec.add_argument(
        "--metric",
        dest="metrics",
        action="append",
        default=[],
        help="Metric name(s) to record (repeatable; default: all)",
    )

    # anomaly compare
    p_anom_cmp = anomaly_sub.add_parser("compare", help="Compare live window against a baseline")
    p_anom_cmp.add_argument("--baseline", required=True, help="Path to baseline JSON file")
    p_anom_cmp.add_argument("--duration", type=float, default=30.0, help="Comparison window in seconds (default: 30)")
    p_anom_cmp.add_argument("--sigma", type=float, default=3.0, help="Z-score alert threshold (default: 3.0)")
    p_anom_cmp.add_argument("--log-source", default=None, help="Override log file path")

    # anomaly watch
    p_anom_wat = anomaly_sub.add_parser("watch", help="Streaming EWMA anomaly watch")
    p_anom_wat.add_argument("--metric", required=True, help="Metric name to watch (e.g. bt_notification_interval_ms)")
    p_anom_wat.add_argument(
        "--threshold", default="2.5sigma", help="Alert threshold, e.g. '2.5sigma' (default: 2.5sigma)"
    )
    p_anom_wat.add_argument("--ewma-window", type=int, default=20, help="EWMA window size (default: 20)")
    p_anom_wat.add_argument(
        "--min-samples", type=int, default=30, help="Cold-start samples before alerting (default: 30)"
    )
    p_anom_wat.add_argument(
        "--duration", type=float, default=None, help="Stop after N seconds (default: run until Ctrl-C)"
    )
    p_anom_wat.add_argument("--log-source", default=None, help="Override log file path")

    # --- snapshot ---
    p_snapshot = sub.add_parser("snapshot", help="Capture a core snapshot from a running device")
    p_snapshot.add_argument("--device", required=True, help="Target device name (e.g. NRF5340_XXAA_APP)")
    p_snapshot.add_argument("--elf", required=True, help="Path to the firmware ELF file")
    p_snapshot.add_argument("--output", required=True, help="Output path for the .core file")

    return parser
