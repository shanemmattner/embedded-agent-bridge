"""RTT commands for eabctl."""

from __future__ import annotations

from pathlib import Path
from typing import Optional

from eab.jlink_bridge import JLinkBridge
from eab.cli.helpers import _print, _tail_lines


def cmd_rtt_start(
    *,
    base_dir: str,
    device: str,
    interface: str,
    speed: int,
    channel: int,
    block_address: Optional[int],
    json_mode: bool,
) -> int:
    bridge = JLinkBridge(base_dir)
    status = bridge.start_rtt(
        device=device,
        interface=interface,
        speed=speed,
        rtt_channel=channel,
        block_address=block_address,
    )
    _print(
        {
            "running": status.running,
            "device": status.device,
            "channel": status.channel,
            "num_up_channels": status.num_up_channels,
            "log_path": status.log_path,
            "last_error": status.last_error,
        },
        json_mode=json_mode,
    )
    return 0 if status.running else 1


def cmd_rtt_stop(*, base_dir: str, json_mode: bool) -> int:
    bridge = JLinkBridge(base_dir)
    status = bridge.stop_rtt()
    _print(
        {"running": status.running},
        json_mode=json_mode,
    )
    return 0


def cmd_rtt_status(*, base_dir: str, json_mode: bool) -> int:
    bridge = JLinkBridge(base_dir)
    status = bridge.rtt_status()
    _print(
        {
            "running": status.running,
            "device": status.device,
            "channel": status.channel,
            "num_up_channels": status.num_up_channels,
            "bytes_read": status.bytes_read,
            "log_path": status.log_path,
            "last_error": status.last_error,
        },
        json_mode=json_mode,
    )
    return 0


def cmd_rtt_reset(
    *,
    base_dir: str,
    wait: float,
    json_mode: bool,
) -> int:
    bridge = JLinkBridge(base_dir)
    status = bridge.reset_rtt_target(wait_after_reset_s=wait)
    _print(
        {
            "running": status.running,
            "device": status.device,
            "channel": status.channel,
            "num_up_channels": status.num_up_channels,
            "log_path": status.log_path,
            "last_error": status.last_error,
        },
        json_mode=json_mode,
    )
    return 0 if status.running else 1


def cmd_rtt_tail(*, base_dir: str, lines: int, json_mode: bool) -> int:
    bridge = JLinkBridge(base_dir)

    # JLinkRTTLogger writes raw data to rtt-raw.log. The tailer thread
    # processes it into rtt.log, but the tailer only runs in-process.
    # For cross-process CLI use, prefer whichever file was modified most
    # recently (raw log is always written by JLinkRTTLogger directly).
    processed_path = Path(base_dir) / "rtt.log"
    raw_path = Path(base_dir) / "rtt-raw.log"

    # Use the most recently modified file
    use_raw = False
    if raw_path.exists():
        if not processed_path.exists():
            use_raw = True
        elif raw_path.stat().st_mtime > processed_path.stat().st_mtime:
            use_raw = True

    log_path = str(raw_path if use_raw else processed_path)
    log_lines = _tail_lines(log_path, lines)

    if json_mode:
        _print({"lines": log_lines}, json_mode=True)
    else:
        for line in log_lines:
            print(line)

    return 0
