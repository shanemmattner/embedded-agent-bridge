"""SWO trace commands for eabctl."""

from __future__ import annotations

from pathlib import Path
from typing import Optional

from eab.swo import SWOCapture, ITMDecoder, ExceptionTracer
from eab.cli.helpers import _print


# Default CPU frequencies for common chips (used for SWO frequency calculation)
DEFAULT_CPU_FREQ = {
    "nrf5340": 128_000_000,   # 128 MHz
    "nrf52840": 64_000_000,   # 64 MHz
    "mcxn947": 150_000_000,   # 150 MHz
    "stm32f4": 168_000_000,   # 168 MHz
    "stm32h7": 480_000_000,   # 480 MHz
}


def _get_cpu_freq(device: str, cpu_freq: Optional[int]) -> int:
    """Get CPU frequency from explicit value or device lookup."""
    if cpu_freq is not None:
        return cpu_freq

    # Try to match device string to known chip
    device_lower = device.lower()
    for chip, freq in DEFAULT_CPU_FREQ.items():
        if chip in device_lower:
            return freq

    # Default to 128 MHz (nRF5340 reference)
    return 128_000_000


def cmd_swo_start(
    *,
    base_dir: str,
    device: str,
    speed: int,
    cpu_freq: Optional[int],
    itm_port: int,
    json_mode: bool,
) -> int:
    """Start SWO capture via J-Link.

    Args:
        base_dir: Session directory for SWO state files
        device: J-Link device string (e.g., NRF5340_XXAA_APP)
        speed: SWO frequency in Hz (default 4000000)
        cpu_freq: CPU frequency in Hz (auto-detected if not provided)
        itm_port: ITM port number (default 0)
        json_mode: Emit machine-parseable JSON output

    Returns:
        Exit code: 0 if started, 1 on failure
    """
    cpu_freq_hz = _get_cpu_freq(device, cpu_freq)

    decoder = ITMDecoder()
    exception_tracer = ExceptionTracer(Path(base_dir) / "swo_exceptions.log")
    capture = SWOCapture(base_dir, decoder=decoder, exception_tracer=exception_tracer)

    status = capture.start_jlink(
        device=device,
        swo_freq=speed,
        cpu_freq=cpu_freq_hz,
        itm_port=itm_port,
    )

    _print(
        {
            "running": status.running,
            "pid": status.pid,
            "device": status.device,
            "swo_freq": status.swo_freq,
            "cpu_freq": status.cpu_freq,
            "log_path": status.log_path,
            "bin_path": status.bin_path,
            "last_error": status.last_error,
        },
        json_mode=json_mode,
    )

    return 0 if status.running else 1


def cmd_swo_stop(*, base_dir: str, json_mode: bool) -> int:
    """Stop SWO capture.

    Args:
        base_dir: Session directory for SWO state files
        json_mode: Emit machine-parseable JSON output

    Returns:
        Exit code: always 0
    """
    capture = SWOCapture(base_dir)
    status = capture.stop()

    _print(
        {
            "running": status.running,
            "pid": status.pid,
        },
        json_mode=json_mode,
    )

    return 0


def cmd_swo_status(*, base_dir: str, json_mode: bool) -> int:
    """Get SWO capture status.

    Args:
        base_dir: Session directory for SWO state files
        json_mode: Emit machine-parseable JSON output

    Returns:
        Exit code: always 0
    """
    capture = SWOCapture(base_dir)
    status = capture.status()

    _print(
        {
            "running": status.running,
            "pid": status.pid,
            "device": status.device,
            "swo_freq": status.swo_freq,
            "cpu_freq": status.cpu_freq,
            "log_path": status.log_path,
            "bin_path": status.bin_path,
            "last_error": status.last_error,
        },
        json_mode=json_mode,
    )

    return 0


def cmd_swo_tail(*, base_dir: str, lines: int, json_mode: bool) -> int:
    """Show last N lines of SWO decoded output.

    Args:
        base_dir: Session directory for SWO state files
        lines: Number of lines to show (default 50)
        json_mode: Emit machine-parseable JSON output

    Returns:
        Exit code: always 0
    """
    capture = SWOCapture(base_dir)
    log_lines = capture.tail(n=lines)

    if json_mode:
        _print({"lines": log_lines}, json_mode=True)
    else:
        for line in log_lines:
            print(line)

    return 0


def cmd_swo_exceptions(*, base_dir: str, lines: int, json_mode: bool) -> int:
    """Show exception trace log.

    Args:
        base_dir: Session directory for SWO state files
        lines: Number of lines to show (default 50)
        json_mode: Emit machine-parseable JSON output

    Returns:
        Exit code: always 0
    """
    exceptions_path = Path(base_dir) / "swo_exceptions.log"

    if not exceptions_path.exists():
        if json_mode:
            _print({"lines": []}, json_mode=True)
        else:
            print("No exception trace log found")
        return 0

    try:
        with open(exceptions_path, "r", encoding="utf-8", errors="replace") as f:
            log_lines = f.readlines()
        log_lines = [line.rstrip() for line in log_lines[-lines:]]
    except OSError:
        log_lines = []

    if json_mode:
        _print({"lines": log_lines}, json_mode=True)
    else:
        for line in log_lines:
            print(line)

    return 0
