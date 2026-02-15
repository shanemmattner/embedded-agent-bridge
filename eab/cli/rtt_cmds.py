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
    transport: str,
    interface: str,
    speed: int,
    channel: int,
    block_address: Optional[int],
    probe_selector: Optional[str],
    json_mode: bool,
) -> int:
    """Start RTT streaming using the specified transport backend.

    Args:
        base_dir: EAB session directory
        device: Device/chip identifier (e.g., NRF5340_XXAA_APP, STM32L476RG)
        transport: Transport backend ("jlink" or "probe-rs")
        interface: Debug interface (SWD or JTAG)
        speed: Interface speed in kHz
        channel: RTT channel number
        block_address: Optional RTT control block address
        probe_selector: Optional probe selector for probe-rs (serial or VID:PID)
        json_mode: Output JSON

    Returns:
        Exit code (0 = success, 1 = failure)
    """
    if transport == "jlink":
        # Use existing JLinkBridge (subprocess-based JLinkRTTLogger)
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

    elif transport == "probe-rs":
        # probe-rs transport not yet integrated with daemon (unlike JLinkBridge).
        # TODO: add background logging support via daemon for continuous RTT capture.
        # For now, this is for testing connectivity and firmware RTT setup verification.
        from eab.rtt_transport import ProbeRsNativeTransport

        try:
            # Create transport and connect
            rtt = ProbeRsNativeTransport()
            rtt.connect(device=device, probe_selector=probe_selector)

            # Start RTT
            num_up = rtt.start_rtt(block_address=block_address)

            # TODO: For now, just report success. Future work: integrate with daemon
            # for continuous logging like JLinkBridge does.
            _print(
                {
                    "running": True,
                    "device": device,
                    "channel": channel,
                    "num_up_channels": num_up,
                    "transport": "probe-rs",
                    "note": "probe-rs transport does not yet support background logging. Use Python API for streaming.",
                },
                json_mode=json_mode,
            )

            # Disconnect (cleanup)
            rtt.disconnect()
            return 0

        except Exception as e:
            _print(
                {
                    "running": False,
                    "device": device,
                    "channel": channel,
                    "transport": "probe-rs",
                    "last_error": str(e),
                },
                json_mode=json_mode,
            )
            return 1

    else:
        _print({"error": f"Unknown transport: {transport}"}, json_mode=json_mode)
        return 1


def cmd_rtt_stop(*, base_dir: str, json_mode: bool) -> int:
    """Stop RTT streaming and terminate the background JLinkRTTLogger process.

    Args:
        base_dir: EAB session directory
        json_mode: Output JSON

    Returns:
        Exit code (0 = success)
    """
    bridge = JLinkBridge(base_dir)
    status = bridge.stop_rtt()
    _print(
        {"running": status.running},
        json_mode=json_mode,
    )
    return 0


def cmd_rtt_status(*, base_dir: str, json_mode: bool) -> int:
    """Query current RTT streaming status.

    Args:
        base_dir: EAB session directory
        json_mode: Output JSON

    Returns:
        Exit code (0 = success)
    """
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
    """Reset the target device and restart RTT streaming.

    Args:
        base_dir: EAB session directory
        wait: Seconds to wait after reset before reconnecting
        json_mode: Output JSON

    Returns:
        Exit code (0 = success, 1 = RTT not running after reset)
    """
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
    """Display the last N lines of RTT output.

    Args:
        base_dir: EAB session directory
        lines: Number of lines to display
        json_mode: Output JSON

    Returns:
        Exit code (0 = success)
    """
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
