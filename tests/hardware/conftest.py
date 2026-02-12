"""HIL test fixtures for EAB hardware tests.

Provides pytest fixtures that wrap EAB's debug probe, GDB bridge,
and fault analysis APIs. Tests skip gracefully when boards aren't connected.
"""

from __future__ import annotations

import logging
import os
import shutil
import subprocess
import tempfile
import time
from dataclasses import dataclass
from pathlib import Path
from typing import Optional

import pytest
import yaml

from eab.debug_probes import get_debug_probe
from eab.debug_probes.base import DebugProbe
from eab.chips.zephyr import ZephyrProfile
from eab.fault_analyzer import analyze_fault
from eab.fault_decoders import FaultReport, get_fault_decoder
from eab.gdb_bridge import run_gdb_batch, GDBResult

logger = logging.getLogger(__name__)

# EAB repo root (two levels up from tests/hardware/)
_EAB_ROOT = Path(__file__).parent.parent.parent

# Build artifacts go here (persists across test runs for caching)
_BUILD_CACHE = Path("/tmp/eab-hil-builds")


# ---------------------------------------------------------------------------
# Board config loading
# ---------------------------------------------------------------------------

_BOARDS_YAML = Path(__file__).parent / "boards.yaml"


@dataclass
class FirmwareConfig:
    """Firmware build/flash metadata from boards.yaml."""

    framework: str              # "zephyr", "esp_idf", "bare_metal"
    source: Optional[str] = None       # Source dir (relative to EAB root)
    binary: Optional[str] = None       # Pre-built binary path (relative to EAB root)
    board_target: Optional[str] = None # Zephyr board target
    flash_runner: Optional[str] = None # Flash runner override
    flash_chip: Optional[str] = None   # Chip for st-flash / cmd_flash


@dataclass
class BoardConfig:
    """Parsed board definition from boards.yaml."""

    name: str
    chip: str
    probe: str
    arch: str
    has_dwt: bool
    sram_base: int
    device: Optional[str] = None
    elf: Optional[str] = None
    firmware: Optional[FirmwareConfig] = None


def _load_boards() -> list[BoardConfig]:
    """Load board definitions from boards.yaml."""
    data = yaml.safe_load(_BOARDS_YAML.read_text())
    boards = []
    for name, cfg in data["boards"].items():
        fw_data = cfg.get("firmware")
        fw = None
        if fw_data:
            fw = FirmwareConfig(
                framework=fw_data["framework"],
                source=fw_data.get("source"),
                binary=fw_data.get("binary"),
                board_target=fw_data.get("board_target"),
                flash_runner=fw_data.get("flash_runner"),
                flash_chip=fw_data.get("flash_chip"),
            )
        boards.append(
            BoardConfig(
                name=name,
                chip=cfg["chip"],
                probe=cfg["probe"],
                arch=cfg["arch"],
                has_dwt=cfg.get("has_dwt", False),
                sram_base=int(str(cfg["sram_base"]), 0),
                device=cfg.get("device"),
                elf=cfg.get("elf"),
                firmware=fw,
            )
        )
    return boards


_ALL_BOARDS = _load_boards()


# ---------------------------------------------------------------------------
# Firmware build / flash helpers
# ---------------------------------------------------------------------------

def _build_firmware(board: BoardConfig) -> Path:
    """Build firmware for a board. Returns path to build output.

    - bare_metal: returns the pre-built binary path (no build needed)
    - zephyr: runs ``west build``, returns build directory
    - esp_idf: runs ``idf.py build``, returns project directory

    Raises pytest.skip if required tools are not available.
    """
    fw = board.firmware
    if fw is None:
        pytest.skip(f"No firmware config for {board.name}")

    if fw.framework == "bare_metal":
        if fw.binary is None:
            pytest.skip(f"No binary path for bare_metal board {board.name}")
        binary = _EAB_ROOT / fw.binary
        if not binary.exists():
            pytest.skip(f"Pre-built binary not found: {binary}")
        return binary

    if fw.framework == "zephyr":
        return _build_zephyr(board)

    if fw.framework == "esp_idf":
        return _build_esp_idf(board)

    pytest.skip(f"Unknown firmware framework: {fw.framework}")


def _build_zephyr(board: BoardConfig) -> Path:
    """Build Zephyr firmware with ``west build``. Returns build directory."""
    fw = board.firmware
    assert fw is not None

    if not shutil.which("west"):
        pytest.skip("west not found in PATH — cannot build Zephyr firmware")

    zephyr_base = Path.home() / "zephyrproject" / "zephyr"
    if not zephyr_base.is_dir():
        pytest.skip(f"ZEPHYR_BASE not found: {zephyr_base}")

    source_dir = _EAB_ROOT / fw.source
    if not source_dir.is_dir():
        pytest.skip(f"Firmware source not found: {source_dir}")

    build_dir = _BUILD_CACHE / board.name
    build_dir.mkdir(parents=True, exist_ok=True)

    env = {**os.environ, "ZEPHYR_BASE": str(zephyr_base)}
    cmd = [
        "west", "build",
        "-b", fw.board_target,
        str(source_dir),
        "--build-dir", str(build_dir),
        "--pristine", "auto",
    ]
    logger.info("Building Zephyr firmware: %s", " ".join(cmd))

    result = subprocess.run(
        cmd, capture_output=True, text=True, timeout=300, env=env,
    )
    if result.returncode != 0:
        logger.error("Zephyr build failed:\n%s\n%s", result.stdout, result.stderr)
        pytest.fail(f"Zephyr build failed for {board.name}: {result.stderr[-500:]}")

    return build_dir


def _build_esp_idf(board: BoardConfig) -> Path:
    """Build ESP-IDF firmware with ``idf.py build``. Returns project directory."""
    fw = board.firmware
    assert fw is not None

    esp_idf = Path.home() / "esp" / "esp-idf" / "export.sh"
    if not esp_idf.exists():
        pytest.skip(f"ESP-IDF not found: {esp_idf}")

    source_dir = _EAB_ROOT / fw.source
    if not source_dir.is_dir():
        pytest.skip(f"Firmware source not found: {source_dir}")

    # Source export.sh then build — must run in a shell
    cmd = f"source {esp_idf} && cd {source_dir} && idf.py build"
    logger.info("Building ESP-IDF firmware: %s", cmd)

    result = subprocess.run(
        ["bash", "-c", cmd],
        capture_output=True, text=True, timeout=300,
    )
    if result.returncode != 0:
        logger.error("ESP-IDF build failed:\n%s\n%s", result.stdout, result.stderr)
        pytest.fail(f"ESP-IDF build failed for {board.name}: {result.stderr[-500:]}")

    return source_dir


def _flash_firmware(board: BoardConfig, build_output: Path) -> bool:
    """Flash firmware to a board. Returns True on success.

    - bare_metal (STM32): uses ``st-flash write``
    - zephyr: uses ``west flash --build-dir <dir> [--runner <runner>]``
    - esp_idf: uses eab's OpenOCD JTAG flash path via ``cmd_flash``
    """
    fw = board.firmware
    assert fw is not None

    if fw.framework == "bare_metal":
        return _flash_stm32(board, build_output)

    if fw.framework == "zephyr":
        return _flash_zephyr(board, build_output)

    if fw.framework == "esp_idf":
        return _flash_esp_idf(board, build_output)

    return False


def _flash_stm32(board: BoardConfig, binary: Path) -> bool:
    """Flash STM32 via st-flash."""
    if not shutil.which("st-flash"):
        pytest.skip("st-flash not found in PATH")

    # Convert ELF to bin if needed, or flash bin directly
    bin_path = binary
    if binary.suffix == ".elf":
        # Look for .bin sibling
        bin_sibling = binary.with_suffix(".bin")
        if bin_sibling.exists():
            bin_path = bin_sibling
        else:
            pytest.skip(f"No .bin file found for {binary}")

    cmd = ["st-flash", "write", str(bin_path), "0x08000000"]
    logger.info("Flashing STM32: %s", " ".join(cmd))

    result = subprocess.run(cmd, capture_output=True, text=True, timeout=60)
    if result.returncode != 0:
        logger.error("st-flash failed: %s", result.stderr)
    return result.returncode == 0


def _flash_zephyr(board: BoardConfig, build_dir: Path) -> bool:
    """Flash Zephyr firmware via ``west flash``."""
    fw = board.firmware
    assert fw is not None

    if not shutil.which("west"):
        pytest.skip("west not found in PATH")

    zephyr_base = Path.home() / "zephyrproject" / "zephyr"
    env = {**os.environ, "ZEPHYR_BASE": str(zephyr_base)}

    cmd = [
        "west", "flash",
        "--no-rebuild",
        "--build-dir", str(build_dir),
    ]
    if fw.flash_runner:
        cmd.extend(["--runner", fw.flash_runner])

    logger.info("Flashing Zephyr: %s", " ".join(cmd))

    result = subprocess.run(
        cmd, capture_output=True, text=True, timeout=120, env=env,
    )
    if result.returncode != 0:
        logger.error("west flash failed: %s", result.stderr)
    return result.returncode == 0


def _flash_esp_idf(board: BoardConfig, project_dir: Path) -> bool:
    """Flash ESP32 via eab's OpenOCD JTAG path (cmd_flash)."""
    from eab.cli.flash_cmds import cmd_flash

    rc = cmd_flash(
        firmware=str(project_dir),
        chip=board.chip,
        address=None,
        port="",
        tool=None,
        baud=460800,
        connect_under_reset=False,
        json_mode=True,
    )
    return rc == 0


# ---------------------------------------------------------------------------
# GDB helper
# ---------------------------------------------------------------------------

@dataclass
class GDBHelper:
    """Convenience wrapper around run_gdb_batch for a specific board."""

    chip: str
    port: int
    elf: Optional[str] = None

    @property
    def target(self) -> str:
        return f"localhost:{self.port}"

    def cmd(self, *commands: str, timeout_s: float = 30.0) -> GDBResult:
        """Run GDB commands against the connected board."""
        return run_gdb_batch(
            chip=self.chip,
            target=self.target,
            elf=self.elf,
            commands=list(commands),
            timeout_s=timeout_s,
        )

    def read_memory(self, address: int, count: int = 16) -> GDBResult:
        """Read memory bytes via GDB 'x' command."""
        return self.cmd(f"x/{count}xb 0x{address:08x}")

    def read_register(self, reg: str) -> GDBResult:
        """Read a single register via GDB 'info registers'."""
        return self.cmd(f"info registers {reg}")


# ---------------------------------------------------------------------------
# Probe builder
# ---------------------------------------------------------------------------

def _build_probe(board: BoardConfig, base_dir: str) -> DebugProbe:
    """Build a DebugProbe from a BoardConfig, using ZephyrProfile for OpenOCD boards."""
    probe_type = board.probe

    if probe_type == "openocd_esp":
        # ESP32 boards use Espressif OpenOCD with board-level configs
        from eab.debug_probes.openocd import OpenOCDProbe

        esp_ocd = _find_espressif_openocd()
        if not esp_ocd:
            raise RuntimeError("Espressif OpenOCD not found")

        board_cfg = f"board/{board.chip}-builtin.cfg"
        return OpenOCDProbe(
            base_dir=base_dir,
            interface_cfg=board_cfg,
            target_cfg=None,
            transport=None,
            gdb_port=3333,
            openocd_path=str(esp_ocd),
        )

    if probe_type == "openocd":
        profile = ZephyrProfile(variant=board.chip)
        ocd_cfg = profile.get_openocd_config()
        return get_debug_probe(
            "openocd",
            base_dir=base_dir,
            interface_cfg=ocd_cfg.interface_cfg,
            target_cfg=ocd_cfg.target_cfg,
            transport=ocd_cfg.transport or "swd",
            extra_commands=ocd_cfg.extra_commands,
        )

    if probe_type == "jlink":
        return get_debug_probe("jlink", base_dir=base_dir)

    raise ValueError(f"Unknown probe type: {probe_type}")


def _find_espressif_openocd() -> Optional[Path]:
    """Find Espressif OpenOCD installation."""
    esp_tools = Path.home() / ".espressif" / "tools" / "openocd-esp32"
    if not esp_tools.exists():
        return None
    # Find the latest version directory
    versions = sorted(esp_tools.iterdir(), reverse=True)
    for v in versions:
        ocd_bin = v / "openocd-esp32" / "bin" / "openocd"
        if ocd_bin.exists():
            return ocd_bin
    return None


# ---------------------------------------------------------------------------
# Fixtures
# ---------------------------------------------------------------------------

def pytest_configure(config):
    config.addinivalue_line("markers", "hardware: requires physical boards")


@pytest.fixture(params=[b.name for b in _ALL_BOARDS], scope="module")
def board_config(request) -> BoardConfig:
    """Parametrized board config — each test runs once per board in boards.yaml."""
    name = request.param
    for b in _ALL_BOARDS:
        if b.name == name:
            return b
    pytest.fail(f"Board {name!r} not found in boards.yaml")


@pytest.fixture(scope="module")
def firmware(board_config: BoardConfig) -> Path:
    """Build and flash firmware for the board. Skips if tools unavailable."""
    build_output = _build_firmware(board_config)
    success = _flash_firmware(board_config, build_output)
    if not success:
        pytest.skip(f"Flash failed for {board_config.name}")
    return build_output


@pytest.fixture(scope="module")
def probe(board_config: BoardConfig, tmp_path_factory) -> DebugProbe:
    """Start a debug probe for the board. Skips if board not connected."""
    base_dir = str(tmp_path_factory.mktemp(f"probe-{board_config.name}"))

    try:
        p = _build_probe(board_config, base_dir)
    except Exception as exc:
        pytest.skip(f"Cannot build probe for {board_config.name}: {exc}")

    # Try to start GDB server to verify board is connected
    device = board_config.device or ""
    try:
        status = p.start_gdb_server(device=device)
    except Exception as exc:
        pytest.skip(f"Board {board_config.name} not connected: {exc}")

    if not status.running:
        pytest.skip(
            f"Board {board_config.name} not connected: "
            f"{status.last_error or 'GDB server failed to start'}"
        )

    yield p

    # Teardown: stop GDB server
    try:
        p.stop_gdb_server()
    except Exception:
        pass


@pytest.fixture(scope="module")
def gdb(board_config: BoardConfig, probe: DebugProbe) -> GDBHelper:
    """GDB helper wired to the probe's port."""
    return GDBHelper(
        chip=board_config.chip,
        port=probe.gdb_port,
        elf=board_config.elf,
    )


@pytest.fixture(scope="module")
def fault_analyzer_fn(board_config: BoardConfig, probe: DebugProbe):
    """Returns a callable that runs fault analysis on the current board.

    The probe's GDB server is already running (managed by the probe fixture),
    so we stop it first, let analyze_fault manage its own lifecycle, then
    restart it for subsequent tests.
    """

    def _analyze(**kwargs) -> FaultReport:
        # analyze_fault manages its own GDB server start/stop
        # We need to stop the fixture's server first
        try:
            probe.stop_gdb_server()
        except Exception:
            pass

        report = analyze_fault(
            probe,
            device=board_config.device or "",
            chip=board_config.chip,
            elf=board_config.elf,
            **kwargs,
        )

        # Restart GDB server for other tests
        try:
            probe.start_gdb_server(device=board_config.device or "")
        except Exception:
            pass

        return report

    return _analyze


@pytest.fixture(scope="module")
def dwt(board_config: BoardConfig, gdb: GDBHelper):
    """DWT cycle counter helper. Skips on boards without DWT (e.g. RISC-V)."""
    if not board_config.has_dwt:
        pytest.skip(f"{board_config.name} has no DWT (arch={board_config.arch})")
    return _DWTHelper(gdb, probe_type=board_config.probe)


class _DWTHelper:
    """Thin wrapper for DWT register operations via GDB."""

    # ARM Cortex-M DWT register addresses
    DWT_CTRL = 0xE0001000
    DWT_CYCCNT = 0xE0001004
    DEMCR = 0xE000EDFC

    def __init__(self, gdb: GDBHelper, probe_type: str = "openocd"):
        self._gdb = gdb
        self._probe_type = probe_type

    @property
    def _resume_cmd(self) -> str:
        """J-Link uses 'monitor go', OpenOCD uses 'monitor resume'."""
        return "monitor go" if self._probe_type == "jlink" else "monitor resume"

    def enable(self) -> GDBResult:
        """Enable DWT cycle counter (set TRCENA in DEMCR, CYCCNTENA in DWT_CTRL)."""
        return self._gdb.cmd(
            f"set *(unsigned int *)0x{self.DEMCR:08X} = "
            f"(*(unsigned int *)0x{self.DEMCR:08X}) | (1 << 24)",
            f"set *(unsigned int *)0x{self.DWT_CTRL:08X} = "
            f"(*(unsigned int *)0x{self.DWT_CTRL:08X}) | 1",
        )

    def disable(self) -> GDBResult:
        """Disable DWT cycle counter (clear CYCCNTENA in DWT_CTRL)."""
        return self._gdb.cmd(
            f"set *(unsigned int *)0x{self.DWT_CTRL:08X} = "
            f"(*(unsigned int *)0x{self.DWT_CTRL:08X}) & ~1",
        )

    def resume(self) -> GDBResult:
        """Resume CPU execution so CYCCNT counts."""
        return self._gdb.cmd(self._resume_cmd)

    def halt(self) -> GDBResult:
        """Halt CPU for register reads."""
        return self._gdb.cmd("monitor halt")

    def read_cyccnt(self) -> Optional[int]:
        """Read DWT_CYCCNT register value."""
        result = self._gdb.cmd(f"x/1xw 0x{self.DWT_CYCCNT:08X}")
        if not result.success:
            return None
        return self._parse_memory_word(result.stdout)

    def read_ctrl(self) -> Optional[int]:
        """Read DWT_CTRL register value."""
        result = self._gdb.cmd(f"x/1xw 0x{self.DWT_CTRL:08X}")
        if not result.success:
            return None
        return self._parse_memory_word(result.stdout)

    @staticmethod
    def _parse_memory_word(gdb_output: str) -> Optional[int]:
        """Parse a single word from GDB 'x/1xw' output.

        Expected format: '0xE0001004:\t0x00000001'
        """
        import re

        match = re.search(r":\s+(0x[0-9a-fA-F]+)", gdb_output)
        if match:
            return int(match.group(1), 16)
        return None
