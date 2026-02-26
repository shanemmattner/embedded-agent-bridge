"""Unit tests for DebugMonitor class and related utilities.

Tests:
- enable() writes correct DEMCR bits (MON_EN + TRCENA)
- disable() clears MON_EN
- status() correctly parses raw DEMCR register
- Priority is encoded correctly in SHPR3
- detect_ble_from_kconfig() parses .config file
- Missing file handled gracefully (returns False)
"""

from __future__ import annotations

import os
import tempfile
from pathlib import Path
from unittest.mock import MagicMock, call, patch

import pytest

from eab.debug_monitor import (
    DEMCR_ADDR,
    MON_EN,
    MON_PEND,
    MON_STEP,
    SHPR3_ADDR,
    TRCENA,
    DebugMonitor,
    DebugMonitorStatus,
)
from eab.chips.zephyr import ZephyrProfile


# =============================================================================
# Helpers
# =============================================================================

def _make_jlink(demcr_values=None, shpr3_values=None):
    """Return a mock JLink with configurable memory_read32 side_effects."""
    jl = MagicMock()
    reads = []
    if demcr_values is not None:
        reads.extend([[v] for v in demcr_values])
    if shpr3_values is not None:
        reads.extend([[v] for v in shpr3_values])
    if reads:
        jl.memory_read32.side_effect = reads
    return jl


# =============================================================================
# Register Constants Tests
# =============================================================================

class TestConstants:
    def test_demcr_addr(self):
        assert DEMCR_ADDR == 0xE000EDFC

    def test_shpr3_addr(self):
        assert SHPR3_ADDR == 0xE000ED20

    def test_mon_en_bit16(self):
        assert MON_EN == (1 << 16)

    def test_mon_pend_bit17(self):
        assert MON_PEND == (1 << 17)

    def test_mon_step_bit18(self):
        assert MON_STEP == (1 << 18)

    def test_trcena_bit24(self):
        assert TRCENA == (1 << 24)


# =============================================================================
# enable() Tests
# =============================================================================

class TestEnable:
    """Test DebugMonitor.enable() register write behaviour."""

    @patch("eab.debug_monitor.pylink", MagicMock())
    def test_enable_sets_mon_en_and_trcena(self):
        """enable() must set MON_EN (bit16) and TRCENA (bit24) in DEMCR."""
        jl = MagicMock()
        # Reads: DEMCR (empty), SHPR3 (empty)
        jl.memory_read32.side_effect = [
            [0x00000000],  # _read_demcr() in enable()
            [0x00000000],  # _read_demcr() in _set_priority() -> SHPR3 read
        ]

        dm = DebugMonitor(jl)
        dm.enable(priority=3)

        # First write should be DEMCR with MON_EN | TRCENA set
        demcr_write_call = jl.memory_write32.call_args_list[0]
        addr, data = demcr_write_call[0]
        assert addr == DEMCR_ADDR
        assert data[0] & MON_EN, "MON_EN must be set"
        assert data[0] & TRCENA, "TRCENA must be set"

    @patch("eab.debug_monitor.pylink", MagicMock())
    def test_enable_preserves_existing_bits(self):
        """enable() must preserve existing DEMCR bits (e.g., MON_STEP)."""
        jl = MagicMock()
        existing = MON_STEP  # some pre-existing bit
        jl.memory_read32.side_effect = [
            [existing],    # DEMCR read
            [0x00000000],  # SHPR3 read
        ]

        dm = DebugMonitor(jl)
        dm.enable(priority=0)

        demcr_write = jl.memory_write32.call_args_list[0][0][1][0]
        assert demcr_write & MON_STEP, "Existing MON_STEP bit should be preserved"
        assert demcr_write & MON_EN
        assert demcr_write & TRCENA

    @patch("eab.debug_monitor.pylink", MagicMock())
    def test_enable_writes_to_correct_demcr_address(self):
        """enable() must write to DEMCR_ADDR = 0xE000EDFC."""
        jl = MagicMock()
        jl.memory_read32.side_effect = [[0], [0]]

        dm = DebugMonitor(jl)
        dm.enable()

        demcr_call = jl.memory_write32.call_args_list[0]
        assert demcr_call[0][0] == DEMCR_ADDR


# =============================================================================
# disable() Tests
# =============================================================================

class TestDisable:
    """Test DebugMonitor.disable() clears MON_EN."""

    @patch("eab.debug_monitor.pylink", MagicMock())
    def test_disable_clears_mon_en(self):
        """disable() must clear MON_EN in DEMCR."""
        jl = MagicMock()
        # DEMCR currently has MON_EN and TRCENA set
        initial_demcr = MON_EN | TRCENA
        jl.memory_read32.side_effect = [[initial_demcr]]

        dm = DebugMonitor(jl)
        dm.disable()

        written_val = jl.memory_write32.call_args[0][1][0]
        assert not (written_val & MON_EN), "MON_EN must be cleared after disable()"

    @patch("eab.debug_monitor.pylink", MagicMock())
    def test_disable_preserves_trcena(self):
        """disable() only clears MON_EN; TRCENA and other bits stay."""
        jl = MagicMock()
        initial_demcr = MON_EN | TRCENA | MON_STEP
        jl.memory_read32.side_effect = [[initial_demcr]]

        dm = DebugMonitor(jl)
        dm.disable()

        written_val = jl.memory_write32.call_args[0][1][0]
        assert written_val & TRCENA, "TRCENA should remain set"
        assert written_val & MON_STEP, "MON_STEP should remain set"

    @patch("eab.debug_monitor.pylink", MagicMock())
    def test_disable_writes_to_demcr_addr(self):
        """disable() must target DEMCR_ADDR."""
        jl = MagicMock()
        jl.memory_read32.side_effect = [[MON_EN]]

        dm = DebugMonitor(jl)
        dm.disable()

        assert jl.memory_write32.call_args[0][0] == DEMCR_ADDR


# =============================================================================
# status() Tests
# =============================================================================

class TestStatus:
    """Test DebugMonitor.status() parses DEMCR correctly."""

    @patch("eab.debug_monitor.pylink", MagicMock())
    def test_status_enabled_when_mon_en_set(self):
        """status().enabled is True when MON_EN bit is set."""
        jl = MagicMock()
        jl.memory_read32.side_effect = [
            [MON_EN | TRCENA],  # DEMCR
            [0x00000000],        # SHPR3
        ]

        dm = DebugMonitor(jl)
        st = dm.status()

        assert st.enabled is True

    @patch("eab.debug_monitor.pylink", MagicMock())
    def test_status_disabled_when_mon_en_clear(self):
        """status().enabled is False when MON_EN bit is clear."""
        jl = MagicMock()
        jl.memory_read32.side_effect = [
            [TRCENA],     # DEMCR (no MON_EN)
            [0x00000000], # SHPR3
        ]

        dm = DebugMonitor(jl)
        st = dm.status()

        assert st.enabled is False

    @patch("eab.debug_monitor.pylink", MagicMock())
    def test_status_mon_step_parsed(self):
        """status().mon_step reflects MON_STEP bit."""
        jl = MagicMock()
        jl.memory_read32.side_effect = [
            [MON_EN | MON_STEP],
            [0],
        ]
        dm = DebugMonitor(jl)
        st = dm.status()
        assert st.mon_step is True

    @patch("eab.debug_monitor.pylink", MagicMock())
    def test_status_mon_pend_parsed(self):
        """status().mon_pend reflects MON_PEND bit."""
        jl = MagicMock()
        jl.memory_read32.side_effect = [
            [MON_EN | MON_PEND],
            [0],
        ]
        dm = DebugMonitor(jl)
        st = dm.status()
        assert st.mon_pend is True

    @patch("eab.debug_monitor.pylink", MagicMock())
    def test_status_raw_demcr_returned(self):
        """status().raw_demcr is the unmodified DEMCR value."""
        raw = MON_EN | TRCENA | 0xABC00000
        jl = MagicMock()
        jl.memory_read32.side_effect = [[raw], [0]]
        dm = DebugMonitor(jl)
        st = dm.status()
        assert st.raw_demcr == raw

    @patch("eab.debug_monitor.pylink", MagicMock())
    def test_status_all_false_on_zero_demcr(self):
        """status() with DEMCR=0 returns all flags False."""
        jl = MagicMock()
        jl.memory_read32.side_effect = [[0x00000000], [0x00000000]]
        dm = DebugMonitor(jl)
        st = dm.status()
        assert st.enabled is False
        assert st.mon_step is False
        assert st.mon_pend is False


# =============================================================================
# Priority Encoding Tests
# =============================================================================

class TestPriorityEncoding:
    """Test that priority is correctly encoded in SHPR3 bits [23:16]."""

    @patch("eab.debug_monitor.pylink", MagicMock())
    def test_priority_3_encoded_in_shpr3(self):
        """Priority 3 should appear as (3 << 5) in bits [23:16] of SHPR3."""
        jl = MagicMock()
        jl.memory_read32.side_effect = [
            [0x00000000],  # DEMCR read in enable()
            [0x00000000],  # SHPR3 read in _set_priority()
        ]

        dm = DebugMonitor(jl)
        dm.enable(priority=3)

        # Second write is SHPR3
        shpr3_call = jl.memory_write32.call_args_list[1]
        shpr3_val = shpr3_call[0][1][0]
        byte2 = (shpr3_val >> 16) & 0xFF
        # priority 3 in top 3 bits of byte2 = 3 << 5 = 0x60
        assert byte2 == (3 << 5), f"Expected 0x{3<<5:02X} in byte2, got 0x{byte2:02X}"

    @patch("eab.debug_monitor.pylink", MagicMock())
    def test_priority_0_encoded_in_shpr3(self):
        """Priority 0 should set byte2 of SHPR3 to 0x00."""
        jl = MagicMock()
        jl.memory_read32.side_effect = [[0], [0]]
        dm = DebugMonitor(jl)
        dm.enable(priority=0)

        shpr3_val = jl.memory_write32.call_args_list[1][0][1][0]
        byte2 = (shpr3_val >> 16) & 0xFF
        assert byte2 == 0

    @patch("eab.debug_monitor.pylink", MagicMock())
    def test_priority_7_encoded_in_shpr3(self):
        """Priority 7 should set byte2 of SHPR3 to 0xE0."""
        jl = MagicMock()
        jl.memory_read32.side_effect = [[0], [0]]
        dm = DebugMonitor(jl)
        dm.enable(priority=7)

        shpr3_val = jl.memory_write32.call_args_list[1][0][1][0]
        byte2 = (shpr3_val >> 16) & 0xFF
        assert byte2 == (7 << 5)  # 0xE0

    @patch("eab.debug_monitor.pylink", MagicMock())
    def test_priority_read_back_from_shpr3(self):
        """_read_priority() should decode priority from SHPR3 bytes [23:16]."""
        jl = MagicMock()
        # SHPR3 with priority=5 encoded in byte2: (5 << 5) << 16
        shpr3_val = (5 << 5) << 16
        jl.memory_read32.side_effect = [
            [MON_EN],      # DEMCR in status()
            [shpr3_val],   # SHPR3 in _read_priority()
        ]
        dm = DebugMonitor(jl)
        st = dm.status()
        assert st.priority == 5

    @patch("eab.debug_monitor.pylink", MagicMock())
    def test_priority_written_to_shpr3_addr(self):
        """_set_priority() must target SHPR3_ADDR = 0xE000ED20."""
        jl = MagicMock()
        jl.memory_read32.side_effect = [[0], [0]]
        dm = DebugMonitor(jl)
        dm.enable(priority=3)

        shpr3_write_call = jl.memory_write32.call_args_list[1]
        assert shpr3_write_call[0][0] == SHPR3_ADDR


# =============================================================================
# ImportError Tests
# =============================================================================

class TestImportError:
    """Test helpful error when pylink is not installed."""

    @patch("eab.debug_monitor.pylink", None)
    def test_enable_raises_import_error(self):
        jl = MagicMock()
        with pytest.raises(ImportError) as exc:
            dm = DebugMonitor(jl)
            dm.enable()
        assert "pylink" in str(exc.value).lower()
        assert "pip install pylink-square" in str(exc.value)

    @patch("eab.debug_monitor.pylink", None)
    def test_status_raises_import_error(self):
        jl = MagicMock()
        with pytest.raises(ImportError):
            dm = DebugMonitor(jl)
            dm.status()


# =============================================================================
# detect_ble_from_kconfig() Tests
# =============================================================================

class TestDetectBleFromKconfig:
    """Test ZephyrProfile.detect_ble_from_kconfig()."""

    def test_returns_true_when_config_bt_y(self, tmp_path):
        """Returns True when CONFIG_BT=y is present in .config."""
        zephyr_dir = tmp_path / "zephyr"
        zephyr_dir.mkdir()
        config_file = zephyr_dir / ".config"
        config_file.write_text(
            "# Zephyr config\n"
            "CONFIG_ARM=y\n"
            "CONFIG_BT=y\n"
            "CONFIG_BT_PERIPHERAL=y\n"
        )

        result = ZephyrProfile.detect_ble_from_kconfig(str(tmp_path))
        assert result is True

    def test_returns_false_when_config_bt_not_y(self, tmp_path):
        """Returns False when CONFIG_BT is not y (disabled or absent)."""
        zephyr_dir = tmp_path / "zephyr"
        zephyr_dir.mkdir()
        config_file = zephyr_dir / ".config"
        config_file.write_text(
            "CONFIG_ARM=y\n"
            "# CONFIG_BT is not set\n"
        )

        result = ZephyrProfile.detect_ble_from_kconfig(str(tmp_path))
        assert result is False

    def test_returns_false_when_file_missing(self, tmp_path):
        """Returns False gracefully when .config file does not exist."""
        result = ZephyrProfile.detect_ble_from_kconfig(str(tmp_path))
        assert result is False

    def test_returns_false_when_directory_missing(self, tmp_path):
        """Returns False when build directory doesn't exist at all."""
        nonexistent = tmp_path / "no_such_build"
        result = ZephyrProfile.detect_ble_from_kconfig(str(nonexistent))
        assert result is False

    def test_returns_false_when_config_bt_n(self, tmp_path):
        """Returns False when CONFIG_BT=n (explicitly disabled)."""
        zephyr_dir = tmp_path / "zephyr"
        zephyr_dir.mkdir()
        config_file = zephyr_dir / ".config"
        config_file.write_text("CONFIG_BT=n\n")

        result = ZephyrProfile.detect_ble_from_kconfig(str(tmp_path))
        assert result is False

    def test_returns_false_when_config_bt_missing_but_others_present(self, tmp_path):
        """Returns False when CONFIG_BT is not in the file at all."""
        zephyr_dir = tmp_path / "zephyr"
        zephyr_dir.mkdir()
        config_file = zephyr_dir / ".config"
        config_file.write_text(
            "CONFIG_ARM=y\n"
            "CONFIG_NETWORKING=y\n"
            "CONFIG_ENTROPY_GENERATOR=y\n"
        )

        result = ZephyrProfile.detect_ble_from_kconfig(str(tmp_path))
        assert result is False

    def test_accepts_path_object(self, tmp_path):
        """detect_ble_from_kconfig() accepts a pathlib.Path object."""
        zephyr_dir = tmp_path / "zephyr"
        zephyr_dir.mkdir()
        config_file = zephyr_dir / ".config"
        config_file.write_text("CONFIG_BT=y\n")

        result = ZephyrProfile.detect_ble_from_kconfig(tmp_path)
        assert result is True

    def test_config_bt_partial_match_not_counted(self, tmp_path):
        """CONFIG_BT_LE=y should NOT trigger BLE detection (must be exact CONFIG_BT=y)."""
        zephyr_dir = tmp_path / "zephyr"
        zephyr_dir.mkdir()
        config_file = zephyr_dir / ".config"
        # Only CONFIG_BT_LE, not CONFIG_BT
        config_file.write_text("CONFIG_BT_LE=y\nCONFIG_BT_GAP=y\n")

        result = ZephyrProfile.detect_ble_from_kconfig(str(tmp_path))
        assert result is False


# =============================================================================
# DebugMonitorStatus Dataclass Tests
# =============================================================================

class TestDebugMonitorStatus:
    """Test the DebugMonitorStatus dataclass."""

    def test_fields_accessible(self):
        st = DebugMonitorStatus(
            enabled=True,
            mon_step=False,
            mon_pend=True,
            priority=3,
            raw_demcr=0x01030000,
        )
        assert st.enabled is True
        assert st.mon_step is False
        assert st.mon_pend is True
        assert st.priority == 3
        assert st.raw_demcr == 0x01030000

    def test_is_dataclass(self):
        from dataclasses import fields
        field_names = {f.name for f in fields(DebugMonitorStatus)}
        assert "enabled" in field_names
        assert "mon_step" in field_names
        assert "mon_pend" in field_names
        assert "priority" in field_names
        assert "raw_demcr" in field_names
