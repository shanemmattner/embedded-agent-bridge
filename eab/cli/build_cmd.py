"""`eabctl build` — wrap ESP-IDF builds in the official Espressif Docker image.

This subcommand produces a reproducible, host-OS-independent ESP-IDF build by
invoking ``espressif/idf:<idf-version>`` with the project directory
bind-mounted at ``/project``. It is a thin wrapper:

  docker run --rm \
      -v <project-dir>:/project \
      -w /project \
      -e IDF_TARGET=<target> \
      [--pull=never]          # when --no-pull
      espressif/idf:<version> \
      idf.py build

It is intentionally decoupled from the running EAB daemon — builds do not
touch serial, RTT, or any probe. Flashing remains the exclusive job of
``eabctl flash`` (which handles daemon pause, port release, chip detection,
and runner selection).

Defaults:
    --target       esp32c6
    --idf-version  v5.4.1
    --project-dir  $PWD

Preflight: we require ``docker info`` to succeed before attempting the build.
If it fails we return an actionable error pointing at Colima (macOS / Mac
Studio) or ``systemctl start docker`` (Linux). Windows users are directed to
Docker Desktop.
"""

from __future__ import annotations

import json
import os
import subprocess
from typing import List, Optional

from eab.cli.helpers import _print


DEFAULT_TARGET = "esp32c6"
DEFAULT_IDF_VERSION = "v5.4.1"

DOCKER_UNREACHABLE_HINT = (
    "Docker daemon unreachable. On Mac Studio: 'colima start' (Colima is "
    "opt-in; see docs/mac-studio-setup.md). On Linux: 'sudo systemctl start "
    "docker'."
)


def build_docker_command(
    *,
    project_dir: str,
    target: str,
    idf_version: str,
    no_pull: bool,
) -> List[str]:
    """Assemble the ``docker run`` argv for an ESP-IDF build.

    Pure function — makes unit testing trivial (no subprocess, no env).

    Args:
        project_dir: Absolute path to ESP-IDF project on host.
        target: Espressif chip target (``esp32c6``, ``esp32s3`` …).
        idf_version: ESP-IDF docker tag (``v5.4.1``).
        no_pull: Pass ``--pull=never`` to skip registry lookup.

    Returns:
        The argv list for ``subprocess.run``.
    """
    cmd: List[str] = [
        "docker",
        "run",
        "--rm",
        "-v",
        f"{project_dir}:/project",
        "-w",
        "/project",
        "-e",
        f"IDF_TARGET={target}",
    ]
    if no_pull:
        cmd.append("--pull=never")
    cmd.append(f"espressif/idf:{idf_version}")
    cmd.extend(["idf.py", "build"])
    return cmd


def _docker_preflight() -> Optional[str]:
    """Return None if docker is reachable, else an error string."""
    try:
        result = subprocess.run(
            ["docker", "info"],
            capture_output=True,
            text=True,
            timeout=10,
        )
    except FileNotFoundError:
        return "docker: command not found. Install Docker or Colima."
    except subprocess.TimeoutExpired:
        return DOCKER_UNREACHABLE_HINT
    except Exception as exc:  # pragma: no cover - defensive
        return f"docker info failed: {exc}"

    if result.returncode != 0:
        return DOCKER_UNREACHABLE_HINT
    return None


def cmd_build(
    *,
    target: str = DEFAULT_TARGET,
    idf_version: str = DEFAULT_IDF_VERSION,
    project_dir: Optional[str] = None,
    no_pull: bool = False,
    json_mode: bool = False,
) -> int:
    """Dockerized ``idf.py build`` runner.

    Returns:
        Exit code from ``docker run`` (passes through), or non-zero on preflight.
    """
    resolved_project_dir = os.path.abspath(project_dir or os.getcwd())

    preflight_err = _docker_preflight()
    if preflight_err is not None:
        _print(
            {"ok": False, "error": preflight_err, "hint": DOCKER_UNREACHABLE_HINT},
            json_mode=json_mode,
        )
        return 1

    argv = build_docker_command(
        project_dir=resolved_project_dir,
        target=target,
        idf_version=idf_version,
        no_pull=no_pull,
    )

    if json_mode:
        # Emit plan before execution for agent traceability.
        print(
            json.dumps(
                {
                    "ok": True,
                    "phase": "plan",
                    "command": argv,
                    "target": target,
                    "idf_version": idf_version,
                    "project_dir": resolved_project_dir,
                    "no_pull": no_pull,
                },
                indent=2,
            ),
            flush=True,
        )

    # Stream stdout/stderr through to the caller — no capture. This matches
    # the ergonomics of ``idf.py build`` when run directly.
    try:
        result = subprocess.run(argv, check=False)
    except FileNotFoundError:
        _print({"ok": False, "error": "docker binary vanished between preflight and run"},
               json_mode=json_mode)
        return 1

    return result.returncode
