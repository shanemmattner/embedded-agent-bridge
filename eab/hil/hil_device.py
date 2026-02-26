"""HilDevice — programmatic interface for a physical target under test."""

from __future__ import annotations

import os
import time
from typing import Optional

from eab.cli.regression.steps import (
    _run_eabctl,
    _run_flash,
    _run_reset,
    _run_wait,
    _run_send,
    _run_fault_check,
    _run_read_vars,
)
from eab.cli.regression.models import StepSpec


class HilDeviceError(RuntimeError):
    """Raised when a HilDevice operation fails."""


class HilDevice:
    """Wraps a physical debug target for HIL pytest tests.

    Parameters
    ----------
    device:
        EAB device identifier (e.g. ``"nrf5340"``).  Maps to
        ``/tmp/eab-devices/{device}/``.
    chip:
        Chip string forwarded to flash/reset/fault-analyze commands
        (e.g. ``"NRF5340_XXAA_APP"``).
    probe:
        Optional probe selector string (``"0483:3748"`` or J-Link serial).
    default_timeout:
        Seconds used when a method's ``timeout`` parameter is omitted.
    """

    def __init__(
        self,
        device: str,
        chip: str,
        probe: Optional[str] = None,
        default_timeout: int = 30,
    ) -> None:
        self.device = device
        self.chip = chip
        self.probe = probe
        self.default_timeout = default_timeout
        # Byte offset recorded at fixture setup — wait() scans from here
        self._log_offset: Optional[int] = None
        self._record_log_offset()

    # ------------------------------------------------------------------
    # Internal helpers
    # ------------------------------------------------------------------

    def _record_log_offset(self) -> None:
        """Snapshot the current log size so wait() ignores pre-test output."""
        base = os.path.join("/tmp/eab-devices", self.device)
        for candidate in [
            os.path.join(base, "latest.log"),
            os.path.join(base, "rtt-raw.log"),
            "/tmp/eab-devices/default/rtt-raw.log",
        ]:
            try:
                self._log_offset = os.path.getsize(candidate)
                return
            except OSError:
                continue
        self._log_offset = None

    def _make_step(self, step_type: str, **params) -> StepSpec:
        return StepSpec(step_type=step_type, params=params)

    # ------------------------------------------------------------------
    # Public API
    # ------------------------------------------------------------------

    def flash(
        self,
        firmware: str,
        *,
        runner: Optional[str] = None,
        address: Optional[str] = None,
        timeout: Optional[int] = None,
    ) -> None:
        """Flash firmware onto the device.

        Delegates to ``_run_flash`` (which shells out to ``eabctl flash``).

        Parameters
        ----------
        firmware:
            Path to firmware binary / ELF / ESP-IDF build dir.
        runner:
            Override flash runner (``"openocd"``, ``"jlink"``, ``"pyocd"``).
        address:
            Override load address (hex string, e.g. ``"0x08000000"``).
        timeout:
            Operation timeout in seconds.

        Raises
        ------
        HilDeviceError
            If flashing fails.
        """
        t = timeout or self.default_timeout
        step = self._make_step(
            "flash",
            firmware=firmware,
            chip=self.chip,
            runner=runner,
            address=address,
        )
        result = _run_flash(step, device=self.device, chip=self.chip, timeout=t)
        if not result.passed:
            raise HilDeviceError(f"flash failed: {result.error}")

    def reset(
        self,
        *,
        method: Optional[str] = None,
        timeout: Optional[int] = None,
    ) -> None:
        """Hardware-reset the device.

        Parameters
        ----------
        method:
            Reset method override (``"hw"``, ``"sw"``, ``"sysresetreq"``).
        timeout:
            Operation timeout in seconds.

        Raises
        ------
        HilDeviceError
            If reset fails.
        """
        t = timeout or self.default_timeout
        step = self._make_step("reset", chip=self.chip, method=method)
        result = _run_reset(step, device=self.device, chip=self.chip, timeout=t)
        if not result.passed:
            raise HilDeviceError(f"reset failed: {result.error}")
        # After reset, re-anchor the log offset so wait() ignores old output
        self._record_log_offset()

    def wait(
        self,
        pattern: str,
        *,
        timeout: int = 10,
    ) -> str:
        """Block until *pattern* appears in the device log.

        Parameters
        ----------
        pattern:
            Substring or regex to match in the device output.
        timeout:
            Maximum seconds to wait.

        Returns
        -------
        str
            The matched log line.

        Raises
        ------
        HilDeviceError
            If pattern is not seen before *timeout*.
        """
        step = self._make_step("wait", pattern=pattern, timeout=timeout)
        result = _run_wait(
            step,
            device=self.device,
            chip=self.chip,
            timeout=timeout,
            log_offset=self._log_offset,
        )
        if not result.passed:
            raise HilDeviceError(
                f"wait('{pattern}') timed out after {timeout}s: {result.error}"
            )
        return result.output.get("line", "")

    def send(
        self,
        text: str,
        *,
        await_ack: bool = False,
        timeout: Optional[int] = None,
    ) -> None:
        """Send a command string to the device over serial / RTT.

        Parameters
        ----------
        text:
            Command text to send.
        await_ack:
            If True, block until the daemon confirms the send via log.
        timeout:
            Operation timeout in seconds.

        Raises
        ------
        HilDeviceError
            If the send fails or ack times out.
        """
        t = timeout or self.default_timeout
        step = self._make_step("send", text=text, await_ack=await_ack, timeout=t)
        result = _run_send(step, device=self.device, chip=self.chip, timeout=t)
        if not result.passed:
            raise HilDeviceError(f"send('{text}') failed: {result.error}")

    def assert_no_fault(
        self,
        *,
        elf: Optional[str] = None,
        timeout: Optional[int] = None,
    ) -> None:
        """Assert the device has not crashed / hit a fault handler.

        Runs ``eabctl fault-analyze`` and raises if a fault is detected.

        Parameters
        ----------
        elf:
            Optional ELF path for symbolicated backtrace in the error message.
        timeout:
            Operation timeout in seconds.

        Raises
        ------
        HilDeviceError
            If a fault is detected.
        """
        t = timeout or self.default_timeout
        step = self._make_step(
            "fault_check",
            device=self.device,
            chip=self.chip,
            elf=elf,
            expect_clean=True,
        )
        result = _run_fault_check(
            step, device=self.device, chip=self.chip, timeout=t
        )
        if not result.passed:
            raise HilDeviceError(
                f"assert_no_fault: fault detected — {result.error}\n"
                f"output: {result.output}"
            )

    def sleep(self, seconds: float) -> None:
        """Sleep for *seconds* (convenience wrapper for readability in tests)."""
        time.sleep(seconds)

    def read_vars(
        self,
        elf: str,
        vars: list,
        *,
        timeout: Optional[int] = None,
    ) -> dict:
        """Read firmware variables via GDB.

        Parameters
        ----------
        elf:
            Path to ELF file with debug symbols.
        vars:
            List of ``{"name": "my_var", "expect_eq": 42}`` dicts (same
            schema as YAML ``read_vars`` step).
        timeout:
            Operation timeout in seconds.

        Returns
        -------
        dict
            ``{"variables": {"my_var": {"value": 42, ...}, ...}}``

        Raises
        ------
        HilDeviceError
            If read fails or an expectation is violated.
        """
        t = timeout or self.default_timeout
        step = self._make_step("read_vars", elf=elf, vars=vars)
        result = _run_read_vars(
            step, device=self.device, chip=self.chip, timeout=t
        )
        if not result.passed:
            raise HilDeviceError(f"read_vars failed: {result.error}")
        return result.output
