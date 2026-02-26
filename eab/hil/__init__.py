"""eab.hil — Hardware-in-the-loop test helpers for EAB.

Public API:
    HilDevice     — wraps a physical debug target for HIL pytest tests
    RttCapture    — per-test RTT log capture helper
    HilDeviceError — raised on operation failure
"""

from eab.hil.hil_device import HilDevice, HilDeviceError
from eab.hil.rtt_capture import RttCapture

__all__ = ["HilDevice", "HilDeviceError", "RttCapture"]
