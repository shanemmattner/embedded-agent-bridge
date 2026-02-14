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
    log_path = str(bridge.rtt_log_path)
    log_lines = _tail_lines(log_path, lines)

    if json_mode:
        _print({"lines": log_lines}, json_mode=True)
    else:
        for line in log_lines:
            print(line)

    return 0
