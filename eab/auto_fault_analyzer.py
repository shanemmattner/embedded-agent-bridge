"""Auto fault analysis triggered by crash detection in the serial daemon.

Invoked from SerialDaemon._on_crash_detected(). Runs analyze_fault() in a
background thread, debounces rapid-fire crash lines, and emits a fault_report
event to events.jsonl via EventEmitter.
"""

from __future__ import annotations

import logging
import threading
import time
from dataclasses import dataclass, field
from typing import Optional

from .debug_probes import get_debug_probe
from .fault_analyzer import analyze_fault
from .event_emitter import EventEmitter

logger = logging.getLogger(__name__)


@dataclass
class AutoFaultConfig:
    """Configuration for auto fault analysis."""

    enabled: bool = False
    chip: str = "nrf5340"
    device: str = "NRF5340_XXAA_APP"
    probe_type: str = "jlink"
    probe_selector: Optional[str] = None
    elf: Optional[str] = None
    restart_rtt: bool = False
    debounce_seconds: float = 5.0  # ignore further crash lines for N seconds after trigger
    base_dir: str = "/tmp/eab-devices/default"


class AutoFaultAnalyzer:
    """Manages auto-triggered fault analysis on crash detection.

    Thread-safe: on_crash_detected() can be called from any thread.
    Only one analysis runs at a time; subsequent crash signals within
    debounce_seconds are silently dropped.

    Usage:
        config = AutoFaultConfig(enabled=True, chip="nrf5340", ...)
        analyzer = AutoFaultAnalyzer(config=config, emitter=event_emitter)

        # Wire into SerialDaemon:
        chip_recovery.set_callbacks(on_crash_detected=analyzer.on_crash_detected)

    Args:
        config: AutoFaultConfig controlling behaviour.
        emitter: EventEmitter to write fault_report events.
        rtt_bridge: Optional JLinkBridge for J-Link RTT stop/restart (see §8).
    """

    def __init__(
        self,
        config: AutoFaultConfig,
        emitter: EventEmitter,
        rtt_bridge=None,
    ) -> None:
        self._config = config
        self._emitter = emitter
        self._rtt_bridge = rtt_bridge
        self._lock = threading.Lock()
        self._analysis_thread: Optional[threading.Thread] = None
        self._last_trigger_time: float = 0.0

    @property
    def config(self) -> AutoFaultConfig:
        return self._config

    def on_crash_detected(self, trigger_line: str) -> None:
        """Entry point wired to ChipRecovery.on_crash_detected callback.

        Called in the daemon main loop thread. Must return quickly.
        Dispatches analysis to a background thread.

        Args:
            trigger_line: The serial line that triggered crash detection.
        """
        if not self._config.enabled:
            return

        now = time.monotonic()
        with self._lock:
            # Debounce: ignore if within debounce window
            if now - self._last_trigger_time < self._config.debounce_seconds:
                logger.debug(
                    "Auto-fault: debouncing crash signal (last trigger %.1fs ago)",
                    now - self._last_trigger_time,
                )
                return

            # Check if previous analysis is still running
            if self._analysis_thread and self._analysis_thread.is_alive():
                logger.warning(
                    "Auto-fault: analysis already in progress, dropping crash signal"
                )
                return

            self._last_trigger_time = now

        logger.info("Auto-fault: scheduling fault analysis (trigger: %s)", trigger_line[:80])

        thread = threading.Thread(
            target=self._run_analysis,
            args=(trigger_line,),
            name="eab-auto-fault",
            daemon=True,  # won't block daemon shutdown
        )
        with self._lock:
            self._analysis_thread = thread
        thread.start()

    def _run_analysis(self, trigger_line: str) -> None:
        """Background thread: run analyze_fault() and emit fault_report event."""
        cfg = self._config
        start_time = time.monotonic()
        error: Optional[str] = None
        report = None

        logger.info(
            "Auto-fault: starting analysis — chip=%s device=%s probe=%s",
            cfg.chip,
            cfg.device,
            cfg.probe_type,
        )

        try:
            probe_kwargs: dict = {}

            if cfg.probe_type == "openocd":
                from .chips.zephyr import ZephyrProfile

                profile = ZephyrProfile(variant=cfg.chip)
                ocd_cfg = profile.get_openocd_config()
                probe_kwargs["interface_cfg"] = ocd_cfg.interface_cfg
                probe_kwargs["target_cfg"] = ocd_cfg.target_cfg
                if ocd_cfg.transport:
                    probe_kwargs["transport"] = ocd_cfg.transport
                probe_kwargs["extra_commands"] = ocd_cfg.extra_commands
                probe_kwargs["halt_command"] = ocd_cfg.halt_command
                if cfg.probe_selector:
                    probe_kwargs["adapter_serial"] = cfg.probe_selector
            else:
                # jlink, xds110: no extra kwargs needed beyond base_dir
                pass

            probe = get_debug_probe(
                cfg.probe_type,
                base_dir=cfg.base_dir,
                **probe_kwargs,
            )

            report = analyze_fault(
                probe=probe,
                device=cfg.device,
                elf=cfg.elf,
                chip=cfg.chip,
                restart_rtt=cfg.restart_rtt,
                rtt_bridge=self._rtt_bridge,
            )

        except Exception as exc:
            logger.exception("Auto-fault: analysis failed: %s", exc)
            error = str(exc)
            report = None

        duration_s = round(time.monotonic() - start_time, 2)

        # Build event data
        if report is not None and error is None:
            data: dict = {
                "trigger_line": trigger_line[:200],
                "chip": cfg.chip,
                "device": cfg.device,
                "probe_type": cfg.probe_type,
                "arch": report.arch,
                "fault_registers": {
                    k: f"0x{v:08X}" for k, v in report.fault_registers.items()
                },
                "stacked_pc": (
                    f"0x{report.stacked_pc:08X}"
                    if report.stacked_pc is not None
                    else None
                ),
                "faults": report.faults,
                "suggestions": report.suggestions,
                "core_regs": {k: f"0x{v:08X}" for k, v in report.core_regs.items()},
                "backtrace": report.backtrace,
                "rtt_context": report.rtt_context,
                "analysis_duration_s": duration_s,
                "error": None,
            }
        else:
            data = {
                "trigger_line": trigger_line[:200],
                "chip": cfg.chip,
                "device": cfg.device,
                "probe_type": cfg.probe_type,
                "analysis_duration_s": duration_s,
                "error": error or "unknown error",
            }

        try:
            self._emitter.emit("fault_report", data=data, level="error")
            logger.info(
                "Auto-fault: fault_report event emitted (duration=%.1fs error=%s)",
                duration_s,
                error,
            )
        except Exception as exc:
            logger.exception("Auto-fault: failed to emit fault_report event: %s", exc)

    def is_running(self) -> bool:
        """Return True if an analysis is currently in progress."""
        with self._lock:
            return bool(self._analysis_thread and self._analysis_thread.is_alive())
