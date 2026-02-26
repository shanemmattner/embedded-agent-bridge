"""eab.hil — Hardware-in-the-loop test helpers for EAB.

Public API:
    HilDevice      — wraps a physical debug target for HIL pytest tests
    HilDeviceError — raised on HilDevice operation failure
    RttCapture     — per-test RTT log capture helper
    BleCentral     — BLE central simulator backed by a second nRF5340 DK
    BleCentralError — raised on BleCentral operation failure
"""

from eab.hil.hil_device import HilDevice, HilDeviceError
from eab.hil.rtt_capture import RttCapture
from eab.hil.ble_central import BleCentral, BleCentralError

__all__ = ["HilDevice", "HilDeviceError", "RttCapture", "BleCentral", "BleCentralError"]
