"""Unit tests for eab.dwt_watchpoint — DwtWatchpointDaemon and ComparatorAllocator."""

from __future__ import annotations

import json
import threading
import time
from unittest.mock import MagicMock, call, patch

import pytest

from eab.dwt_watchpoint import (
    DWT_COMP_BASE,
    DWT_FUNCT_BASE,
    DWT_MASK_BASE,
    DWT_COMP_STRIDE,
    DWT_CTRL_ADDR,
    DWT_FUNC_DISABLED,
    DWT_FUNC_READ,
    DWT_FUNC_WRITE,
    DWT_FUNC_RW,
    DWT_FUNCT_MATCHED,
    Comparator,
    ComparatorAllocator,
    ComparatorExhaustedError,
    DwtWatchpointDaemon,
    _requires_write_to_clear_matched,
)


# =============================================================================
# Helpers
# =============================================================================

def _make_mock_jlink(numcomp: int = 4) -> MagicMock:
    """Return a mock JLink with DWT_CTRL returning the given NUMCOMP."""
    mock = MagicMock()
    # DWT_CTRL[31:28] = numcomp
    ctrl_val = numcomp << 28
    mock.memory_read32.return_value = [ctrl_val]
    return mock


def _make_comparator(
    index: int = 0,
    watch_addr: int = 0x20001234,
    label: str = "conn_interval",
    mode: str = "write",
    size_bytes: int = 2,
) -> Comparator:
    return Comparator(
        index=index,
        comp_addr=DWT_COMP_BASE + index * DWT_COMP_STRIDE,
        mask_addr=DWT_MASK_BASE + index * DWT_COMP_STRIDE,
        funct_addr=DWT_FUNCT_BASE + index * DWT_COMP_STRIDE,
        watch_addr=watch_addr,
        label=label,
        mode=mode,
        size_bytes=size_bytes,
    )


# =============================================================================
# ComparatorAllocator tests
# =============================================================================

class TestComparatorAllocator:

    def test_detect_numcomp_reads_dwt_ctrl(self):
        """detect_numcomp() should return DWT_CTRL[31:28]."""
        mock_jlink = MagicMock()
        mock_jlink.memory_read32.return_value = [0x40000000]   # NUMCOMP=4
        alloc = ComparatorAllocator(mock_jlink)
        assert alloc.detect_numcomp() == 4

    def test_detect_numcomp_two(self):
        """detect_numcomp() should return 2 for nRF5340 NET core."""
        mock_jlink = MagicMock()
        mock_jlink.memory_read32.return_value = [0x20000000]   # NUMCOMP=2
        alloc = ComparatorAllocator(mock_jlink)
        assert alloc.detect_numcomp() == 2

    def test_allocate_uses_highest_free_slot(self):
        """allocate() should use slot 3 (highest) when all comparators are free."""
        mock_jlink = _make_mock_jlink(numcomp=4)
        alloc = ComparatorAllocator(mock_jlink)
        comp = alloc.allocate(watch_addr=0x20001234, label="x", mode="write", size_bytes=4)
        # Highest free slot with 4 comparators = slot 3
        assert comp.index == 3
        assert comp.watch_addr == 0x20001234
        assert comp.label == "x"
        assert comp.mode == "write"
        assert comp.size_bytes == 4

    def test_allocate_writes_dwt_comp_register(self):
        """allocate() should write target address to DWT_COMPn."""
        mock_jlink = _make_mock_jlink(numcomp=4)
        alloc = ComparatorAllocator(mock_jlink)
        alloc.allocate(watch_addr=0x20001234, label="x", mode="write", size_bytes=4)
        # DWT_COMP3 = 0xE0001020 + 3*16 = 0xE0001050
        dwt_comp3 = DWT_COMP_BASE + 3 * DWT_COMP_STRIDE
        mock_jlink.memory_write32.assert_any_call(dwt_comp3, [0x20001234])

    def test_allocate_second_uses_next_lower_slot(self):
        """Second allocate() should use slot 2 after slot 3 is taken."""
        mock_jlink = _make_mock_jlink(numcomp=4)
        alloc = ComparatorAllocator(mock_jlink)
        comp1 = alloc.allocate(watch_addr=0x20001234, label="x", mode="write")
        comp2 = alloc.allocate(watch_addr=0x20001238, label="y", mode="write")
        assert comp1.index == 3
        assert comp2.index == 2

    def test_allocate_raises_when_exhausted(self):
        """allocate() should raise ComparatorExhaustedError when all 4 slots are taken."""
        mock_jlink = _make_mock_jlink(numcomp=4)
        alloc = ComparatorAllocator(mock_jlink)
        for i in range(4):
            alloc.allocate(watch_addr=0x20000000 + i * 4, label=f"v{i}", mode="write")
        with pytest.raises(ComparatorExhaustedError):
            alloc.allocate(watch_addr=0x20000010, label="overflow", mode="write")

    def test_numcomp_2_limits_allocation(self):
        """On a chip with NUMCOMP=2, allocating a third slot should fail."""
        mock_jlink = _make_mock_jlink(numcomp=2)
        alloc = ComparatorAllocator(mock_jlink)
        alloc.allocate(watch_addr=0x20000000, label="a", mode="write")
        alloc.allocate(watch_addr=0x20000004, label="b", mode="write")
        with pytest.raises(ComparatorExhaustedError):
            alloc.allocate(watch_addr=0x20000008, label="c", mode="write")

    def test_release_clears_funct_register(self):
        """release(index) should write 0 to DWT_FUNCTn."""
        mock_jlink = _make_mock_jlink(numcomp=4)
        alloc = ComparatorAllocator(mock_jlink)
        comp = alloc.allocate(watch_addr=0x20001234, label="x", mode="write")
        alloc.release(comp.index)
        funct_addr = DWT_FUNCT_BASE + comp.index * DWT_COMP_STRIDE
        mock_jlink.memory_write32.assert_any_call(funct_addr, [0])

    def test_release_frees_slot_for_reuse(self):
        """After release, the slot can be reallocated."""
        mock_jlink = _make_mock_jlink(numcomp=4)
        alloc = ComparatorAllocator(mock_jlink)
        comp = alloc.allocate(watch_addr=0x20001234, label="x", mode="write")
        alloc.release(comp.index)
        # Should not raise
        comp2 = alloc.allocate(watch_addr=0x20001234, label="x2", mode="write")
        assert comp2.index == comp.index

    def test_release_all_clears_all_slots(self):
        """release_all() should write 0 to all DWT_FUNCTn registers."""
        mock_jlink = _make_mock_jlink(numcomp=4)
        alloc = ComparatorAllocator(mock_jlink)
        for i in range(4):
            alloc.allocate(watch_addr=0x20000000 + i * 4, label=f"v{i}", mode="write")
        alloc.release_all()
        assert alloc.active() == []
        # Verify all 4 FUNCT registers were written to 0
        for idx in range(4):
            funct_addr = DWT_FUNCT_BASE + idx * DWT_COMP_STRIDE
            mock_jlink.memory_write32.assert_any_call(funct_addr, [0])

    def test_active_returns_allocated_comparators(self):
        """active() should return all currently allocated comparators."""
        mock_jlink = _make_mock_jlink(numcomp=4)
        alloc = ComparatorAllocator(mock_jlink)
        assert alloc.active() == []
        alloc.allocate(watch_addr=0x20001234, label="x", mode="write")
        assert len(alloc.active()) == 1

    def test_invalid_mode_raises_value_error(self):
        """allocate() should raise ValueError for unknown mode."""
        mock_jlink = _make_mock_jlink(numcomp=4)
        alloc = ComparatorAllocator(mock_jlink)
        with pytest.raises(ValueError, match="Invalid mode"):
            alloc.allocate(watch_addr=0x20001234, label="x", mode="invalid_mode")

    def test_state_file_written_on_allocate(self, tmp_path):
        """State file should be written when a comparator is allocated."""
        state_file = str(tmp_path / "state.json")
        mock_jlink = _make_mock_jlink(numcomp=4)
        alloc = ComparatorAllocator(mock_jlink, state_file=state_file)
        alloc.allocate(watch_addr=0x20001234, label="x", mode="write")
        with open(state_file) as f:
            data = json.load(f)
        assert len(data) == 1
        assert data[0]["watch_addr"] == 0x20001234

    def test_state_file_cleared_on_release_all(self, tmp_path):
        """State file should be empty after release_all()."""
        state_file = str(tmp_path / "state.json")
        mock_jlink = _make_mock_jlink(numcomp=4)
        alloc = ComparatorAllocator(mock_jlink, state_file=state_file)
        alloc.allocate(watch_addr=0x20001234, label="x", mode="write")
        alloc.release_all()
        with open(state_file) as f:
            data = json.load(f)
        assert data == []


# =============================================================================
# DwtWatchpointDaemon tests
# =============================================================================

class TestDwtWatchpointDaemon:

    def _make_daemon(
        self,
        mock_jlink: MagicMock,
        index: int = 0,
        size_bytes: int = 2,
        events_file: str = None,
        poll_hz: int = 1000,
    ) -> DwtWatchpointDaemon:
        comp = _make_comparator(index=index, size_bytes=size_bytes)
        return DwtWatchpointDaemon(
            mock_jlink,
            comp,
            poll_hz=poll_hz,
            events_file=events_file,
        )

    def test_emits_jsonl_event_on_matched_bit(self, capsys):
        """Daemon should emit JSONL event when DWT_FUNCT MATCHED bit is set."""
        mock_jlink = MagicMock()
        mock_jlink.memory_read32.side_effect = [
            [DWT_FUNCT_MATCHED | DWT_FUNC_WRITE],  # poll — matched
            [DWT_FUNC_WRITE],                       # re-read to clear MATCHED
        ]
        mock_jlink.memory_read8.return_value = [0x18, 0x00]  # value = 0x0018

        daemon = self._make_daemon(mock_jlink)
        daemon._stop_event.set()  # stop after one iteration
        daemon._poll_loop()

        captured = capsys.readouterr()
        event = json.loads(captured.out.strip())
        assert event["label"] == "conn_interval"
        assert event["addr"] == "0x20001234"
        assert event["value"] == "0x0018"
        assert isinstance(event["ts"], int)

    def test_no_event_when_matched_not_set(self, capsys):
        """Daemon should not emit events when MATCHED bit is 0."""
        mock_jlink = MagicMock()
        mock_jlink.memory_read32.return_value = [DWT_FUNC_WRITE]  # MATCHED=0
        daemon = self._make_daemon(mock_jlink)
        daemon._stop_event.set()
        daemon._poll_loop()
        assert capsys.readouterr().out.strip() == ""

    def test_poll_error_does_not_crash(self, capsys):
        """Poll loop should survive transient JLink read errors."""
        mock_jlink = MagicMock()
        mock_jlink.memory_read32.side_effect = RuntimeError("SWD timeout")
        daemon = self._make_daemon(mock_jlink)
        daemon._stop_event.set()
        daemon._poll_loop()   # should not raise
        assert capsys.readouterr().out == ""

    def test_start_stop_lifecycle(self):
        """start() spawns a thread; stop() joins it cleanly."""
        mock_jlink = MagicMock()
        mock_jlink.memory_read32.return_value = [DWT_FUNC_WRITE]  # no match
        daemon = self._make_daemon(mock_jlink, poll_hz=10)
        daemon.start()
        assert daemon._thread is not None
        assert daemon._thread.is_alive()
        daemon.stop()
        assert daemon._thread is None or not daemon._thread.is_alive()

    def test_events_file_written(self, tmp_path, capsys):
        """When events_file is set, each hit is appended to the file."""
        events_path = tmp_path / "events.jsonl"
        mock_jlink = MagicMock()
        mock_jlink.memory_read32.side_effect = [
            [DWT_FUNCT_MATCHED | DWT_FUNC_WRITE],
            [DWT_FUNC_WRITE],  # clear read
        ]
        mock_jlink.memory_read8.return_value = [0x18, 0x00]

        daemon = self._make_daemon(mock_jlink, events_file=str(events_path))
        daemon._stop_event.set()
        daemon._poll_loop()

        lines = events_path.read_text().strip().splitlines()
        assert len(lines) == 1
        event = json.loads(lines[0])
        assert event["value"] == "0x0018"
        assert event["label"] == "conn_interval"

    def test_read_value_4_bytes(self):
        """_read_value() reads 4 bytes via memory_read32 for size_bytes=4."""
        mock_jlink = MagicMock()
        mock_jlink.memory_read32.return_value = [0xDEADBEEF]
        comp = _make_comparator(size_bytes=4)
        daemon = DwtWatchpointDaemon(mock_jlink, comp)
        val = daemon._read_value()
        assert val == 0xDEADBEEF

    def test_read_value_2_bytes(self):
        """_read_value() reads 2 bytes via memory_read8 for size_bytes=2."""
        mock_jlink = MagicMock()
        mock_jlink.memory_read8.return_value = [0xAD, 0xDE]  # little-endian 0xDEAD
        comp = _make_comparator(size_bytes=2)
        daemon = DwtWatchpointDaemon(mock_jlink, comp)
        val = daemon._read_value()
        assert val == 0xDEAD

    def test_read_value_1_byte(self):
        """_read_value() reads 1 byte via memory_read8 for size_bytes=1."""
        mock_jlink = MagicMock()
        mock_jlink.memory_read8.return_value = [0x42]
        comp = _make_comparator(size_bytes=1)
        daemon = DwtWatchpointDaemon(mock_jlink, comp)
        val = daemon._read_value()
        assert val == 0x42

    def test_write_to_clear_m4_mode(self, capsys):
        """For M4 (write_to_clear=True), daemon writes 0 + func code to clear MATCHED."""
        mock_jlink = MagicMock()
        mock_jlink.memory_read32.side_effect = [
            [DWT_FUNCT_MATCHED | DWT_FUNC_WRITE],  # poll — matched
        ]
        mock_jlink.memory_read8.return_value = [0x18, 0x00]

        comp = _make_comparator(index=0, mode="write", size_bytes=2)
        daemon = DwtWatchpointDaemon(
            mock_jlink, comp, poll_hz=1000, write_to_clear=True
        )
        daemon._stop_event.set()
        daemon._poll_loop()

        # Should have written 0 then func code to funct_addr
        funct_addr = DWT_FUNCT_BASE
        mock_jlink.memory_write32.assert_any_call(funct_addr, [0])
        mock_jlink.memory_write32.assert_any_call(funct_addr, [DWT_FUNC_WRITE])

    def test_value_format_4byte(self, capsys):
        """4-byte value should format as 8 hex digits."""
        mock_jlink = MagicMock()
        comp = _make_comparator(size_bytes=4)
        daemon = DwtWatchpointDaemon(mock_jlink, comp, poll_hz=1000)

        # Directly call _emit_event with a known 4-byte value
        daemon._emit_event(0xCAFEBABE)
        captured = capsys.readouterr()
        event = json.loads(captured.out.strip())
        assert event["value"] == "0xCAFEBABE"


# =============================================================================
# _requires_write_to_clear_matched tests
# =============================================================================

class TestRequiresWriteToClearMatched:

    def test_nrf52_needs_write_to_clear(self):
        assert _requires_write_to_clear_matched("NRF52840_XXAA") is True

    def test_stm32f4_needs_write_to_clear(self):
        assert _requires_write_to_clear_matched("STM32F407VG") is True

    def test_nrf5340_does_not_need_write_to_clear(self):
        assert _requires_write_to_clear_matched("NRF5340_XXAA_APP") is False

    def test_mcxn947_does_not_need_write_to_clear(self):
        assert _requires_write_to_clear_matched("MCXN947") is False
