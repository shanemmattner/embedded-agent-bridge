"""Unit tests for Feature 2 — ``eabctl build`` dockerized wrapper.

All ``subprocess.run`` calls are mocked. No ``docker run`` is ever executed.
No network access. No hardware.
"""

from __future__ import annotations

from unittest.mock import MagicMock, patch

import pytest


# ---------------------------------------------------------------------------
# Pure-function tests: docker-run argv construction.
# ---------------------------------------------------------------------------

def test_build_docker_command_defaults():
    from eab.cli.build_cmd import build_docker_command

    argv = build_docker_command(
        project_dir="/home/user/esp-proj",
        target="esp32c6",
        idf_version="v5.4.1",
        no_pull=False,
    )
    assert argv[0] == "docker"
    assert argv[1] == "run"
    assert "--rm" in argv
    # volume mount
    assert "-v" in argv
    assert "/home/user/esp-proj:/project" in argv
    # workdir
    wi = argv.index("-w")
    assert argv[wi + 1] == "/project"
    # env
    ei = argv.index("-e")
    assert argv[ei + 1] == "IDF_TARGET=esp32c6"
    # image
    assert "espressif/idf:v5.4.1" in argv
    # final command
    assert argv[-2:] == ["idf.py", "build"]
    # no --pull when no_pull is False
    assert "--pull=never" not in argv


def test_build_docker_command_no_pull_flag():
    from eab.cli.build_cmd import build_docker_command

    argv = build_docker_command(
        project_dir="/tmp/proj",
        target="esp32c6",
        idf_version="v5.4.1",
        no_pull=True,
    )
    assert "--pull=never" in argv
    # --pull=never must appear before the image tag
    idx_pull = argv.index("--pull=never")
    idx_image = argv.index("espressif/idf:v5.4.1")
    assert idx_pull < idx_image


@pytest.mark.parametrize("target", ["esp32c6", "esp32s3", "esp32h2"])
def test_build_docker_command_target_parametrized(target):
    from eab.cli.build_cmd import build_docker_command

    argv = build_docker_command(
        project_dir="/tmp/proj",
        target=target,
        idf_version="v5.4.1",
        no_pull=False,
    )
    ei = argv.index("-e")
    assert argv[ei + 1] == f"IDF_TARGET={target}"


# ---------------------------------------------------------------------------
# cmd_build: preflight + exit-code pass-through, all subprocess.run mocked.
# ---------------------------------------------------------------------------

def _make_completed(returncode: int):
    res = MagicMock()
    res.returncode = returncode
    res.stdout = ""
    res.stderr = ""
    return res


def test_cmd_build_preflight_success_runs_build(capsys):
    from eab.cli.build_cmd import cmd_build

    # First call: docker info (preflight). Second: docker run (actual build).
    call_log = []

    def fake_run(argv, *args, **kwargs):
        call_log.append(list(argv))
        if argv[:2] == ["docker", "info"]:
            return _make_completed(0)
        # simulate build success
        return _make_completed(0)

    with patch("eab.cli.build_cmd.subprocess.run", side_effect=fake_run):
        rc = cmd_build(
            target="esp32c6",
            idf_version="v5.4.1",
            project_dir="/tmp/proj",
            no_pull=False,
            json_mode=False,
        )

    assert rc == 0
    # Two subprocess calls expected
    assert len(call_log) == 2
    assert call_log[0][:2] == ["docker", "info"]
    # Second call is the assembled build command
    build_argv = call_log[1]
    assert build_argv[0] == "docker"
    assert build_argv[1] == "run"
    assert "espressif/idf:v5.4.1" in build_argv
    assert "IDF_TARGET=esp32c6" in build_argv


def test_cmd_build_preflight_failure_actionable_error(capsys):
    from eab.cli.build_cmd import cmd_build
    from eab.cli.build_cmd import DOCKER_UNREACHABLE_HINT

    def fake_run(argv, *args, **kwargs):
        if argv[:2] == ["docker", "info"]:
            return _make_completed(1)
        pytest.fail("build should not run when preflight fails")

    with patch("eab.cli.build_cmd.subprocess.run", side_effect=fake_run):
        rc = cmd_build(
            target="esp32c6",
            idf_version="v5.4.1",
            project_dir="/tmp/proj",
            no_pull=False,
            json_mode=True,
        )

    assert rc != 0
    captured = capsys.readouterr()
    combined = captured.out + captured.err
    assert "Docker daemon unreachable" in combined
    assert DOCKER_UNREACHABLE_HINT in combined
    assert "colima start" in combined
    assert "systemctl start docker" in combined


def test_cmd_build_preflight_file_not_found(capsys):
    from eab.cli.build_cmd import cmd_build

    with patch(
        "eab.cli.build_cmd.subprocess.run",
        side_effect=FileNotFoundError("docker"),
    ):
        rc = cmd_build(
            target="esp32c6",
            idf_version="v5.4.1",
            project_dir="/tmp/proj",
            no_pull=False,
            json_mode=True,
        )

    assert rc == 1
    captured = capsys.readouterr()
    assert "command not found" in (captured.out + captured.err).lower()


def test_cmd_build_no_pull_flag_propagates():
    from eab.cli.build_cmd import cmd_build

    captured_argv = []

    def fake_run(argv, *args, **kwargs):
        captured_argv.append(list(argv))
        if argv[:2] == ["docker", "info"]:
            return _make_completed(0)
        return _make_completed(0)

    with patch("eab.cli.build_cmd.subprocess.run", side_effect=fake_run):
        rc = cmd_build(
            target="esp32s3",
            idf_version="v5.4.1",
            project_dir="/tmp/proj",
            no_pull=True,
            json_mode=False,
        )

    assert rc == 0
    build_argv = captured_argv[1]
    assert "--pull=never" in build_argv
    assert "IDF_TARGET=esp32s3" in build_argv


def test_cmd_build_exit_code_passthrough():
    from eab.cli.build_cmd import cmd_build

    def fake_run(argv, *args, **kwargs):
        if argv[:2] == ["docker", "info"]:
            return _make_completed(0)
        return _make_completed(2)

    with patch("eab.cli.build_cmd.subprocess.run", side_effect=fake_run):
        rc = cmd_build(
            target="esp32c6",
            idf_version="v5.4.1",
            project_dir="/tmp/proj",
            no_pull=False,
            json_mode=False,
        )

    assert rc == 2
