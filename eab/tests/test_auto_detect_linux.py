"""Unit tests for Feature 3 — Linux compat in ``eab.auto_detect``.

Mocks ``glob.glob`` entirely. Never touches ``/dev/*``.
"""

from __future__ import annotations

from unittest.mock import MagicMock, patch


def test_list_device_nodes_linux_patterns():
    """Linux-style device paths surface from glob."""
    import eab.auto_detect as ad

    fake_results = {
        "/dev/ttyUSB*": ["/dev/ttyUSB0", "/dev/ttyUSB1"],
        "/dev/ttyACM*": ["/dev/ttyACM0"],
        "/dev/tty.usbmodem*": [],
        "/dev/tty.usbserial*": [],
        "/dev/cu.usbmodem*": [],
        "/dev/cu.usbserial*": [],
    }
    with patch.object(ad, "glob") as mock_glob:
        mock_glob.glob.side_effect = lambda pat: fake_results.get(pat, [])
        nodes = ad.list_device_nodes()

    assert "/dev/ttyUSB0" in nodes
    assert "/dev/ttyUSB1" in nodes
    assert "/dev/ttyACM0" in nodes


def test_list_device_nodes_macos_patterns():
    """macOS-style device paths surface from glob."""
    import eab.auto_detect as ad

    fake_results = {
        "/dev/ttyUSB*": [],
        "/dev/ttyACM*": [],
        "/dev/tty.usbmodem*": ["/dev/tty.usbmodem14101"],
        "/dev/tty.usbserial*": [],
        "/dev/cu.usbmodem*": ["/dev/cu.usbmodem14101"],
        "/dev/cu.usbserial*": ["/dev/cu.usbserial-0001"],
    }
    with patch.object(ad, "glob") as mock_glob:
        mock_glob.glob.side_effect = lambda pat: fake_results.get(pat, [])
        nodes = ad.list_device_nodes()

    assert "/dev/tty.usbmodem14101" in nodes
    assert "/dev/cu.usbmodem14101" in nodes
    assert "/dev/cu.usbserial-0001" in nodes


def test_list_device_nodes_dedupes():
    """Same path returned by multiple patterns only appears once."""
    import eab.auto_detect as ad

    with patch.object(ad, "glob") as mock_glob:
        mock_glob.glob.side_effect = lambda pat: ["/dev/ttyUSB0"]
        nodes = ad.list_device_nodes()

    assert nodes.count("/dev/ttyUSB0") == 1


def test_detect_boards_pyserial_preserves_vid_pid_match():
    """Existing VID/PID logic still works when pyserial reports a known board."""
    import eab.auto_detect as ad

    fake_port = MagicMock()
    fake_port.vid = 0x1366  # J-Link
    fake_port.pid = 0x1015
    fake_port.device = "/dev/ttyACM0"
    fake_port.serial_number = "000261012345"

    import types
    fake_serial_tools = types.SimpleNamespace()
    fake_list_ports = types.SimpleNamespace(comports=lambda: [fake_port])
    fake_serial_tools.list_ports = fake_list_ports

    import sys

    with patch.dict(sys.modules, {
        "serial": types.SimpleNamespace(tools=fake_serial_tools),
        "serial.tools": fake_serial_tools,
        "serial.tools.list_ports": fake_list_ports,
    }), patch.object(ad, "list_device_nodes", return_value=[]):
        boards = ad.detect_boards_pyserial()

    assert boards is not None
    match = [b for b in boards if b.get("vid") == "1366"]
    assert match, "J-Link VID/PID should resolve to known board"
    assert match[0]["name"] == "J-Link"
    assert match[0]["port"] == "/dev/ttyACM0"


def test_detect_boards_pyserial_adds_linux_nodes_as_unknown():
    """Unclaimed Linux device nodes appear as unknown-serial entries."""
    import eab.auto_detect as ad
    import sys
    import types

    # pyserial reports nothing.
    fake_list_ports = types.SimpleNamespace(comports=lambda: [])
    fake_serial_tools = types.SimpleNamespace(list_ports=fake_list_ports)

    with patch.dict(sys.modules, {
        "serial": types.SimpleNamespace(tools=fake_serial_tools),
        "serial.tools": fake_serial_tools,
        "serial.tools.list_ports": fake_list_ports,
    }), patch.object(ad, "list_device_nodes", return_value=["/dev/ttyUSB0", "/dev/ttyACM1"]):
        boards = ad.detect_boards_pyserial()

    ports = [b["port"] for b in boards]
    assert "/dev/ttyUSB0" in ports
    assert "/dev/ttyACM1" in ports
    # Unknown entries should not claim vid/pid
    unknown = [b for b in boards if b["port"] == "/dev/ttyUSB0"]
    assert unknown[0]["vid"] == ""
    assert unknown[0]["pid"] == ""
