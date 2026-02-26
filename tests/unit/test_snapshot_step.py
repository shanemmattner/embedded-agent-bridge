"""Unit tests for the snapshot regression step — no hardware required."""

from __future__ import annotations

from unittest.mock import MagicMock, patch

from eab.cli.regression.models import StepSpec
from eab.cli.regression.steps import _STEP_DISPATCH, _run_snapshot


def _make_snapshot_result(output_path: str = "results/state.core",
                          total_size: int = 1024) -> MagicMock:
    return MagicMock(output_path=output_path, total_size=total_size, regions=[MagicMock(), MagicMock()])


# ---------------------------------------------------------------------------
# Dispatch registration
# ---------------------------------------------------------------------------

class TestSnapshotDispatch:
    def test_snapshot_registered_in_step_dispatch(self):
        assert "snapshot" in _STEP_DISPATCH

    def test_snapshot_dispatch_points_to_run_snapshot(self):
        assert _STEP_DISPATCH["snapshot"] is _run_snapshot


# ---------------------------------------------------------------------------
# Parameter validation
# ---------------------------------------------------------------------------

class TestSnapshotValidation:
    def test_missing_output_returns_failed(self):
        step = StepSpec("snapshot", {"elf": "build/zephyr/zephyr.elf"})
        result = _run_snapshot(step, device=None, chip=None, timeout=60)
        assert not result.passed
        assert "output" in result.error

    def test_missing_elf_returns_failed(self):
        step = StepSpec("snapshot", {"output": "results/state.core"})
        result = _run_snapshot(step, device=None, chip=None, timeout=60)
        assert not result.passed
        assert "elf" in result.error

    def test_on_anomaly_missing_baseline_returns_failed(self):
        step = StepSpec("snapshot", {
            "output": "results/state.core",
            "elf": "build/zephyr/zephyr.elf",
            "trigger": "on_anomaly",
        })
        result = _run_snapshot(step, device=None, chip=None, timeout=60)
        assert not result.passed
        assert "baseline" in result.error


# ---------------------------------------------------------------------------
# Manual trigger
# ---------------------------------------------------------------------------

class TestSnapshotManualTrigger:
    def _step(self, extra: dict | None = None) -> StepSpec:
        params: dict = {
            "output": "results/state.core",
            "elf": "build/zephyr/zephyr.elf",
            "trigger": "manual",
        }
        if extra:
            params.update(extra)
        return StepSpec("snapshot", params)

    def test_manual_always_captures(self):
        snap_result = _make_snapshot_result()
        with patch("eab.cli.regression.steps.capture_snapshot",
                   return_value=snap_result) as mock_capture:
            result = _run_snapshot(
                self._step(), device="nrf5340", chip="NRF5340_XXAA_APP", timeout=60
            )
        mock_capture.assert_called_once()
        assert result.passed
        assert result.output["captured"] is True
        assert result.output["trigger"] == "manual"

    def test_default_trigger_is_manual(self):
        """Absent trigger param should behave the same as manual."""
        step = StepSpec("snapshot", {
            "output": "results/state.core",
            "elf": "build/zephyr/zephyr.elf",
        })
        snap_result = _make_snapshot_result()
        with patch("eab.cli.regression.steps.capture_snapshot",
                   return_value=snap_result) as mock_capture:
            result = _run_snapshot(step, device="dev", chip=None, timeout=60)
        mock_capture.assert_called_once()
        assert result.passed

    def test_output_and_elf_forwarded_to_capture_snapshot(self):
        snap_result = _make_snapshot_result(output_path="results/state.core")
        with patch("eab.cli.regression.steps.capture_snapshot",
                   return_value=snap_result) as mock_capture:
            _run_snapshot(self._step(), device="dev", chip="NRF5340_XXAA_APP", timeout=60)
        call_kwargs = mock_capture.call_args
        assert call_kwargs.kwargs["elf_path"] == "build/zephyr/zephyr.elf"
        assert call_kwargs.kwargs["output_path"] == "results/state.core"

    def test_capture_exception_returns_failed(self):
        with patch("eab.cli.regression.steps.capture_snapshot",
                   side_effect=ValueError("ELF file not found: build/zephyr/zephyr.elf")):
            result = _run_snapshot(
                self._step(), device="dev", chip=None, timeout=60
            )
        assert not result.passed
        assert "capture_snapshot failed" in result.error

    def test_unrecognised_trigger_also_captures(self):
        """Unrecognised trigger value falls through to manual behaviour."""
        step = StepSpec("snapshot", {
            "output": "results/state.core",
            "elf": "build/zephyr/zephyr.elf",
            "trigger": "unknown_mode",
        })
        snap_result = _make_snapshot_result()
        with patch("eab.cli.regression.steps.capture_snapshot",
                   return_value=snap_result) as mock_capture:
            result = _run_snapshot(step, device="dev", chip=None, timeout=60)
        mock_capture.assert_called_once()
        assert result.passed


# ---------------------------------------------------------------------------
# on_fault trigger
# ---------------------------------------------------------------------------

class TestSnapshotOnFaultTrigger:
    def _step(self) -> StepSpec:
        return StepSpec("snapshot", {
            "output": "results/state.core",
            "elf": "build/zephyr/zephyr.elf",
            "trigger": "on_fault",
        })

    def test_fault_detected_true_captures(self):
        snap_result = _make_snapshot_result()
        with patch("eab.cli.regression.steps._run_eabctl",
                   return_value=(0, {"fault_detected": True})), \
             patch("eab.cli.regression.steps.capture_snapshot",
                   return_value=snap_result) as mock_capture:
            result = _run_snapshot(self._step(), device="dev", chip=None, timeout=60)
        mock_capture.assert_called_once()
        assert result.passed
        assert result.output["captured"] is True

    def test_faulted_key_also_triggers_capture(self):
        snap_result = _make_snapshot_result()
        with patch("eab.cli.regression.steps._run_eabctl",
                   return_value=(0, {"faulted": True})), \
             patch("eab.cli.regression.steps.capture_snapshot",
                   return_value=snap_result) as mock_capture:
            result = _run_snapshot(self._step(), device="dev", chip=None, timeout=60)
        mock_capture.assert_called_once()
        assert result.passed

    def test_no_fault_skips_capture_and_passes(self):
        with patch("eab.cli.regression.steps._run_eabctl",
                   return_value=(0, {"fault_detected": False})), \
             patch("eab.cli.regression.steps.capture_snapshot") as mock_capture:
            result = _run_snapshot(self._step(), device="dev", chip=None, timeout=60)
        mock_capture.assert_not_called()
        assert result.passed
        assert result.output["captured"] is False

    def test_no_fault_fields_skips_capture(self):
        with patch("eab.cli.regression.steps._run_eabctl",
                   return_value=(0, {})), \
             patch("eab.cli.regression.steps.capture_snapshot") as mock_capture:
            result = _run_snapshot(self._step(), device="dev", chip=None, timeout=60)
        mock_capture.assert_not_called()
        assert result.passed


# ---------------------------------------------------------------------------
# on_anomaly trigger
# ---------------------------------------------------------------------------

class TestSnapshotOnAnomalyTrigger:
    def _step(self, extra: dict | None = None) -> StepSpec:
        params: dict = {
            "output": "results/state.core",
            "elf": "build/zephyr/zephyr.elf",
            "trigger": "on_anomaly",
            "baseline": "baselines/nominal.json",
        }
        if extra:
            params.update(extra)
        return StepSpec("snapshot", params)

    def test_anomaly_count_gte_1_captures(self):
        snap_result = _make_snapshot_result()
        with patch("eab.cli.regression.steps._run_eabctl",
                   return_value=(0, {"anomaly_count": 2})), \
             patch("eab.cli.regression.steps.capture_snapshot",
                   return_value=snap_result) as mock_capture:
            result = _run_snapshot(self._step(), device="dev", chip=None, timeout=60)
        mock_capture.assert_called_once()
        assert result.passed
        assert result.output["captured"] is True

    def test_anomaly_count_zero_skips_capture(self):
        with patch("eab.cli.regression.steps._run_eabctl",
                   return_value=(0, {"anomaly_count": 0})), \
             patch("eab.cli.regression.steps.capture_snapshot") as mock_capture:
            result = _run_snapshot(self._step(), device="dev", chip=None, timeout=60)
        mock_capture.assert_not_called()
        assert result.passed
        assert result.output["captured"] is False

    def test_missing_anomaly_count_key_skips_capture(self):
        with patch("eab.cli.regression.steps._run_eabctl",
                   return_value=(0, {})), \
             patch("eab.cli.regression.steps.capture_snapshot") as mock_capture:
            result = _run_snapshot(self._step(), device="dev", chip=None, timeout=60)
        mock_capture.assert_not_called()
        assert result.passed

    def test_baseline_forwarded_to_eabctl(self):
        snap_result = _make_snapshot_result()
        with patch("eab.cli.regression.steps._run_eabctl",
                   return_value=(0, {"anomaly_count": 1})) as mock_eabctl, \
             patch("eab.cli.regression.steps.capture_snapshot",
                   return_value=snap_result):
            _run_snapshot(self._step(), device="dev", chip=None, timeout=60)
        call_args = mock_eabctl.call_args[0][0]
        assert "baselines/nominal.json" in call_args
