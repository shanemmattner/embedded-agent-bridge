"""Tests for C2000 DSS flash support.

Covers:
- C2000Profile.get_dss_flash_command() — command construction, arch detection,
  temp JS content, and error handling.
- flash_cmd._build_flash_command() with --tool dss routing.
"""

from __future__ import annotations

import os
import platform
import tempfile
from pathlib import Path
from unittest.mock import MagicMock, patch

import pytest

from eab.chips.base import FlashCommand
from eab.chips.c2000 import (
    C2000Profile,
    _DSS_JS_TEMPLATE,
    _find_ccs_java,
    _find_ccs_root,
)


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def _fake_ccs_root(tmp_path: Path) -> Path:
    """Create a minimal fake CCS directory tree under tmp_path."""
    ccs = tmp_path / "ccs2041" / "ccs"
    # macOS JRE path
    java = ccs / "ccs-server.app" / "jre" / "Contents" / "Home" / "bin" / "java"
    java.parent.mkdir(parents=True)
    java.touch()
    # DebugServer jars
    dss_java = ccs / "ccs_base" / "DebugServer" / "packages" / "ti" / "dss" / "java"
    dss_java.mkdir(parents=True)
    (dss_java / "js.jar").touch()
    (dss_java / "dss.jar").touch()
    # dvt_scripting.jar
    dvt = ccs / "ccs_base" / "dvt" / "scripting"
    dvt.mkdir(parents=True)
    (dvt / "dvt_scripting.jar").touch()
    # DebugServer bin (lib_path)
    ds_bin = ccs / "ccs_base" / "DebugServer" / "bin"
    ds_bin.mkdir(parents=True)
    return ccs


# ---------------------------------------------------------------------------
# _find_ccs_root / _find_ccs_java
# ---------------------------------------------------------------------------


class TestFindCcsHelpers:
    def test_find_ccs_root_returns_none_when_nothing_exists(self, tmp_path):
        with patch("eab.chips.c2000._CCS_SEARCH_PATHS", [tmp_path / "nonexistent"]):
            assert _find_ccs_root() is None

    def test_find_ccs_root_returns_first_existing(self, tmp_path):
        real = tmp_path / "ccs"
        real.mkdir()
        with patch("eab.chips.c2000._CCS_SEARCH_PATHS", [tmp_path / "missing", real]):
            result = _find_ccs_root()
            assert result == real

    def test_find_ccs_java_macos_bundle(self, tmp_path):
        ccs = _fake_ccs_root(tmp_path)
        result = _find_ccs_java(ccs)
        expected = (
            ccs / "ccs-server.app" / "jre" / "Contents" / "Home" / "bin" / "java"
        )
        assert result == expected

    def test_find_ccs_java_linux_fallback(self, tmp_path):
        ccs = tmp_path / "ccs"
        linux_java = ccs / "jre" / "bin" / "java"
        linux_java.parent.mkdir(parents=True)
        linux_java.touch()
        result = _find_ccs_java(ccs)
        assert result == linux_java

    def test_find_ccs_java_returns_none_when_missing(self, tmp_path):
        ccs = tmp_path / "ccs"
        ccs.mkdir()
        assert _find_ccs_java(ccs) is None


# ---------------------------------------------------------------------------
# get_dss_flash_command — success path
# ---------------------------------------------------------------------------


class TestGetDssFlashCommand:
    """Tests for C2000Profile.get_dss_flash_command()."""

    def _make_profile_with_fake_ccs(self, tmp_path: Path, ccxml: str) -> C2000Profile:
        ccs = _fake_ccs_root(tmp_path)
        profile = C2000Profile(ccxml=ccxml)
        self._ccs = ccs
        return profile, ccs

    def test_returns_flash_command(self, tmp_path):
        ccs = _fake_ccs_root(tmp_path)
        profile = C2000Profile(ccxml="/some/target.ccxml")
        with patch("eab.chips.c2000._find_ccs_root", return_value=ccs):
            cmd = profile.get_dss_flash_command(firmware_path="/build/foc.out")
        assert isinstance(cmd, FlashCommand)

    def test_timeout_is_120(self, tmp_path):
        ccs = _fake_ccs_root(tmp_path)
        profile = C2000Profile(ccxml="/some/target.ccxml")
        with patch("eab.chips.c2000._find_ccs_root", return_value=ccs):
            cmd = profile.get_dss_flash_command(firmware_path="/build/foc.out")
        assert cmd.timeout == 120.0

    def test_temp_js_created_and_stored_in_env(self, tmp_path):
        ccs = _fake_ccs_root(tmp_path)
        profile = C2000Profile(ccxml="/some/target.ccxml")
        with patch("eab.chips.c2000._find_ccs_root", return_value=ccs):
            cmd = profile.get_dss_flash_command(firmware_path="/build/foc.out")
        js_path = cmd.env.get("_TEMP_JS")
        assert js_path is not None
        assert os.path.exists(js_path)
        # Cleanup
        os.unlink(js_path)

    def test_temp_js_contains_firmware_path(self, tmp_path):
        ccs = _fake_ccs_root(tmp_path)
        profile = C2000Profile(ccxml="/some/target.ccxml")
        with patch("eab.chips.c2000._find_ccs_root", return_value=ccs):
            cmd = profile.get_dss_flash_command(firmware_path="/build/foc_hil.out")
        js_path = cmd.env["_TEMP_JS"]
        js_content = Path(js_path).read_text()
        assert "/build/foc_hil.out" in js_content
        os.unlink(js_path)

    def test_temp_js_contains_ccxml_path(self, tmp_path):
        ccs = _fake_ccs_root(tmp_path)
        profile = C2000Profile(ccxml="/path/to/TMS320F280039C.ccxml")
        with patch("eab.chips.c2000._find_ccs_root", return_value=ccs):
            cmd = profile.get_dss_flash_command(firmware_path="/build/foc.out")
        js_content = Path(cmd.env["_TEMP_JS"]).read_text()
        assert "/path/to/TMS320F280039C.ccxml" in js_content
        os.unlink(cmd.env["_TEMP_JS"])

    def test_temp_js_has_expected_dss_calls(self, tmp_path):
        ccs = _fake_ccs_root(tmp_path)
        profile = C2000Profile(ccxml="/some/target.ccxml")
        with patch("eab.chips.c2000._find_ccs_root", return_value=ccs):
            cmd = profile.get_dss_flash_command(firmware_path="/build/foc.out")
        js_content = Path(cmd.env["_TEMP_JS"]).read_text()
        assert "session.target.connect()" in js_content
        assert "session.target.reset()" in js_content
        assert "session.memory.loadProgram" in js_content
        assert "session.target.runAsynch()" in js_content
        assert "session.target.disconnect()" in js_content
        assert "ds.stop()" in js_content
        os.unlink(cmd.env["_TEMP_JS"])

    def test_classpath_contains_required_jars(self, tmp_path):
        ccs = _fake_ccs_root(tmp_path)
        profile = C2000Profile(ccxml="/some/target.ccxml")
        with patch("eab.chips.c2000._find_ccs_root", return_value=ccs):
            cmd = profile.get_dss_flash_command(firmware_path="/build/foc.out")
        # -cp is one arg; value is the next
        cp_idx = cmd.args.index("-cp")
        classpath = cmd.args[cp_idx + 1]
        assert "js.jar" in classpath
        assert "dss.jar" in classpath
        assert "dvt_scripting.jar" in classpath
        os.unlink(cmd.env["_TEMP_JS"])

    def test_library_path_arg_present(self, tmp_path):
        ccs = _fake_ccs_root(tmp_path)
        profile = C2000Profile(ccxml="/some/target.ccxml")
        with patch("eab.chips.c2000._find_ccs_root", return_value=ccs):
            cmd = profile.get_dss_flash_command(firmware_path="/build/foc.out")
        lib_args = [a for a in cmd.args if a.startswith("-Djava.library.path=")]
        assert len(lib_args) == 1
        assert "DebugServer/bin" in lib_args[0]
        os.unlink(cmd.env["_TEMP_JS"])

    def test_main_class_present(self, tmp_path):
        ccs = _fake_ccs_root(tmp_path)
        profile = C2000Profile(ccxml="/some/target.ccxml")
        with patch("eab.chips.c2000._find_ccs_root", return_value=ccs):
            cmd = profile.get_dss_flash_command(firmware_path="/build/foc.out")
        assert "org.mozilla.javascript.tools.shell.Main" in cmd.args
        os.unlink(cmd.env["_TEMP_JS"])

    def test_temp_js_path_is_last_arg(self, tmp_path):
        ccs = _fake_ccs_root(tmp_path)
        profile = C2000Profile(ccxml="/some/target.ccxml")
        with patch("eab.chips.c2000._find_ccs_root", return_value=ccs):
            cmd = profile.get_dss_flash_command(firmware_path="/build/foc.out")
        js_path = cmd.env["_TEMP_JS"]
        assert cmd.args[-1] == js_path
        os.unlink(js_path)

    def test_ccxml_kwarg_override(self, tmp_path):
        """ccxml passed as kwarg takes priority over profile.ccxml."""
        ccs = _fake_ccs_root(tmp_path)
        profile = C2000Profile(ccxml="/original/target.ccxml")
        with patch("eab.chips.c2000._find_ccs_root", return_value=ccs):
            cmd = profile.get_dss_flash_command(
                firmware_path="/build/foc.out",
                ccxml="/override/custom.ccxml",
            )
        js_content = Path(cmd.env["_TEMP_JS"]).read_text()
        assert "/override/custom.ccxml" in js_content
        assert "/original/target.ccxml" not in js_content
        os.unlink(cmd.env["_TEMP_JS"])


# ---------------------------------------------------------------------------
# Apple Silicon (arm64 macOS) path
# ---------------------------------------------------------------------------


class TestDssFlashArm64:
    def test_arm64_mac_uses_arch_tool(self, tmp_path):
        ccs = _fake_ccs_root(tmp_path)
        profile = C2000Profile(ccxml="/some/target.ccxml")
        with (
            patch("eab.chips.c2000._find_ccs_root", return_value=ccs),
            patch("platform.machine", return_value="arm64"),
            patch("platform.system", return_value="Darwin"),
        ):
            cmd = profile.get_dss_flash_command(firmware_path="/build/foc.out")
        assert cmd.tool == "arch"
        assert cmd.args[0] == "-x86_64"
        os.unlink(cmd.env["_TEMP_JS"])

    def test_arm64_mac_java_path_is_second_arg(self, tmp_path):
        ccs = _fake_ccs_root(tmp_path)
        profile = C2000Profile(ccxml="/some/target.ccxml")
        expected_java = str(
            ccs / "ccs-server.app" / "jre" / "Contents" / "Home" / "bin" / "java"
        )
        with (
            patch("eab.chips.c2000._find_ccs_root", return_value=ccs),
            patch("platform.machine", return_value="arm64"),
            patch("platform.system", return_value="Darwin"),
        ):
            cmd = profile.get_dss_flash_command(firmware_path="/build/foc.out")
        assert cmd.args[1] == expected_java
        os.unlink(cmd.env["_TEMP_JS"])

    def test_non_arm64_uses_java_directly_as_tool(self, tmp_path):
        ccs = _fake_ccs_root(tmp_path)
        profile = C2000Profile(ccxml="/some/target.ccxml")
        with (
            patch("eab.chips.c2000._find_ccs_root", return_value=ccs),
            patch("platform.machine", return_value="x86_64"),
            patch("platform.system", return_value="Darwin"),
        ):
            cmd = profile.get_dss_flash_command(firmware_path="/build/foc.out")
        assert cmd.tool != "arch"
        assert "java" in cmd.tool
        os.unlink(cmd.env["_TEMP_JS"])

    def test_linux_x86_64_uses_java_directly_as_tool(self, tmp_path):
        ccs_linux = tmp_path / "ccs"
        java = ccs_linux / "jre" / "bin" / "java"
        java.parent.mkdir(parents=True)
        java.touch()
        # Create required jars
        dss_java = ccs_linux / "ccs_base" / "DebugServer" / "packages" / "ti" / "dss" / "java"
        dss_java.mkdir(parents=True)
        (dss_java / "js.jar").touch()
        (dss_java / "dss.jar").touch()
        dvt = ccs_linux / "ccs_base" / "dvt" / "scripting"
        dvt.mkdir(parents=True)
        (dvt / "dvt_scripting.jar").touch()
        (ccs_linux / "ccs_base" / "DebugServer" / "bin").mkdir(parents=True)

        profile = C2000Profile(ccxml="/some/target.ccxml")
        with (
            patch("eab.chips.c2000._find_ccs_root", return_value=ccs_linux),
            patch("platform.machine", return_value="x86_64"),
            patch("platform.system", return_value="Linux"),
        ):
            cmd = profile.get_dss_flash_command(firmware_path="/build/foc.out")
        assert cmd.tool == str(java)
        os.unlink(cmd.env["_TEMP_JS"])


# ---------------------------------------------------------------------------
# Error cases
# ---------------------------------------------------------------------------


class TestDssFlashErrors:
    def test_raises_when_ccs_not_found(self):
        profile = C2000Profile(ccxml="/some/target.ccxml")
        with patch("eab.chips.c2000._find_ccs_root", return_value=None):
            with pytest.raises(RuntimeError, match="CCS installation not found"):
                profile.get_dss_flash_command(firmware_path="/build/foc.out")

    def test_raises_when_java_not_found(self, tmp_path):
        # CCS root exists but has no JRE
        ccs = tmp_path / "ccs"
        ccs.mkdir()
        profile = C2000Profile(ccxml="/some/target.ccxml")
        with patch("eab.chips.c2000._find_ccs_root", return_value=ccs):
            with pytest.raises(RuntimeError, match="CCS JRE not found"):
                profile.get_dss_flash_command(firmware_path="/build/foc.out")

    def test_raises_when_no_ccxml(self, tmp_path):
        ccs = _fake_ccs_root(tmp_path)
        profile = C2000Profile()  # no ccxml set
        with (
            patch("eab.chips.c2000._find_ccs_root", return_value=ccs),
            patch("eab.chips.c2000._find_ccxml", return_value=None),
        ):
            with pytest.raises(RuntimeError, match="No CCXML configuration file found"):
                profile.get_dss_flash_command(firmware_path="/build/foc.out")


# ---------------------------------------------------------------------------
# flash_cmd._build_flash_command routing for --tool dss
# ---------------------------------------------------------------------------


class TestBuildFlashCommandDssRouting:
    """Unit tests for the --tool dss branch in _build_flash_command."""

    def _make_mock_dss_cmd(self, tmp_path: Path) -> FlashCommand:
        """Return a fake FlashCommand with a real temp JS file."""
        js = tempfile.NamedTemporaryFile(suffix=".js", delete=False)
        js.write(b"// fake\n")
        js.close()
        return FlashCommand(
            tool="arch",
            args=["-x86_64", "/usr/bin/java", "-cp", "x.jar", "Main", js.name],
            env={"_TEMP_JS": js.name},
            timeout=120.0,
        )

    def test_dss_tool_returns_flash_command(self, tmp_path):
        from eab.cli.flash.flash_cmd import _build_flash_command
        from eab.chips.c2000 import C2000Profile

        fake_cmd = self._make_mock_dss_cmd(tmp_path)
        profile = C2000Profile(ccxml="/some/target.ccxml")
        with patch.object(profile, "get_dss_flash_command", return_value=fake_cmd):
            result = _build_flash_command(
                profile=profile,
                chip="c2000",
                firmware="/build/foc.out",
                port=None,
                address=None,
                tool="dss",
                device=None,
                reset_after=True,
                use_multi_core=False,
                kwargs={},
                json_mode=False,
            )
        flash_cmd, use_jlink, use_openocd, jlink_script_path, esptool_cfg_path, err = result
        assert err is None
        assert flash_cmd is fake_cmd
        assert use_jlink is False
        assert use_openocd is False
        assert esptool_cfg_path is None
        # Temp JS path should be threaded through the jlink_script_path slot for cleanup
        assert jlink_script_path == fake_cmd.env["_TEMP_JS"]
        os.unlink(fake_cmd.env["_TEMP_JS"])

    def test_dss_tool_wrong_chip_returns_error(self):
        from eab.cli.flash.flash_cmd import _build_flash_command
        from eab.chips.esp32 import ESP32Profile

        profile = ESP32Profile()
        flash_cmd, use_jlink, use_openocd, jlink_script_path, esptool_cfg_path, err = (
            _build_flash_command(
                profile=profile,
                chip="esp32",
                firmware="/build/app.bin",
                port="/dev/tty.usbserial",
                address="0x10000",
                tool="dss",
                device=None,
                reset_after=True,
                use_multi_core=False,
                kwargs={},
                json_mode=False,
            )
        )
        assert err == 2
        assert flash_cmd is None

    def test_dss_tool_propagates_runtime_error(self, tmp_path):
        from eab.cli.flash.flash_cmd import _build_flash_command
        from eab.chips.c2000 import C2000Profile

        profile = C2000Profile(ccxml="/some/target.ccxml")
        with patch.object(
            profile,
            "get_dss_flash_command",
            side_effect=RuntimeError("CCS installation not found"),
        ):
            flash_cmd, _, _, _, _, err = _build_flash_command(
                profile=profile,
                chip="c2000",
                firmware="/build/foc.out",
                port=None,
                address=None,
                tool="dss",
                device=None,
                reset_after=True,
                use_multi_core=False,
                kwargs={},
                json_mode=False,
            )
        assert err == 1
        assert flash_cmd is None
