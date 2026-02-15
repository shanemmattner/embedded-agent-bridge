"""OpenOCD Apptrace transport for ESP32 chips.

Provides binary trace streaming from ESP32 via OpenOCD's apptrace feature.
Uses TCP socket streaming for high-throughput trace data capture.

This transport:
- Starts OpenOCD subprocess with ESP32 board config
- Connects via telnet to port 4444
- Sends commands to start apptrace with TCP streaming
- Reads binary trace data from TCP socket
- Supports clean shutdown

Typical usage:
    >>> from eab.apptrace_transport import OpenOCDApptrace
    >>> transport = OpenOCDApptrace()
    >>> transport.connect('esp32c6')
    >>> transport.start_apptrace()
    >>> data = transport.read(4096)
    >>> transport.stop_apptrace()
    >>> transport.disconnect()
"""

from __future__ import annotations

import logging
import os
import select
import shutil
import signal
import socket
import subprocess
import time
from pathlib import Path
from typing import Optional

logger = logging.getLogger(__name__)

# Import RTTTransport base class
from eab.rtt_transport import RTTTransport


# Board config mapping for ESP32 variants
BOARD_CONFIGS = {
    "esp32c6": "board/esp32c6-builtin.cfg",
    "esp32c3": "board/esp32c3-builtin.cfg",
    "esp32s3": "board/esp32s3-builtin.cfg",
    "esp32s2": "board/esp32s2-builtin.cfg",
    "esp32": "board/esp32-wrover-kit-3.3v.cfg",
}


def find_espressif_openocd() -> str | None:
    """Find the Espressif OpenOCD binary (has ESP32 board configs).

    The standard Homebrew OpenOCD does NOT include esp32c6-builtin.cfg
    or the esp_usb_jtag interface driver. Only the Espressif fork works.

    Returns:
        Path to openocd binary, or None if not found.
    """
    # Check ESP-IDF tools directory (installed by install.sh)
    home = Path.home()
    espressif_dir = home / ".espressif" / "tools" / "openocd-esp32"
    if espressif_dir.exists():
        # Find newest version
        versions = sorted(espressif_dir.iterdir(), reverse=True)
        for ver_dir in versions:
            ocd_bin = ver_dir / "openocd-esp32" / "bin" / "openocd"
            if ocd_bin.exists():
                logger.info("Found Espressif OpenOCD: %s", ocd_bin)
                return str(ocd_bin)

    # Check if openocd in PATH has esp32 support
    ocd_path = shutil.which("openocd")
    if ocd_path:
        # Quick check: does it have esp32c6-builtin.cfg?
        ocd_dir = Path(ocd_path).parent.parent / "share" / "openocd" / "scripts" / "board"
        if (ocd_dir / "esp32c6-builtin.cfg").exists():
            return ocd_path

    return None


def _pid_alive(pid: int) -> bool:
    """Check if a process is still running."""
    try:
        os.kill(pid, 0)
        return True
    except OSError:
        return False


class OpenOCDApptrace(RTTTransport):
    """OpenOCD Apptrace transport for ESP32 chips.

    Implements binary trace streaming via OpenOCD's apptrace feature.
    Starts OpenOCD, connects via telnet, and reads trace data from TCP socket.

    This class inherits from RTTTransport for compatibility with RTTBinaryCapture.
    Apptrace is conceptually similar to RTT (high-speed trace streaming), just
    implemented via OpenOCD instead of J-Link.
    """

    def __init__(self, telnet_port: int = 4444, tcp_port: int = 53535):
        """Initialize OpenOCD Apptrace transport.

        Args:
            telnet_port: OpenOCD telnet command port (default: 4444).
            tcp_port: TCP port for apptrace streaming (default: 53535).
        """
        self._openocd_proc: Optional[subprocess.Popen] = None
        self._telnet_port = telnet_port
        self._tcp_port = tcp_port
        self._tcp_server_sock: Optional[socket.socket] = None
        self._tcp_client_sock: Optional[socket.socket] = None
        self._board_cfg: Optional[str] = None
        self._device: Optional[str] = None
        self._apptrace_running = False

    def connect(self, device: str, interface: str = "SWD", speed: int = 4000, board_cfg: str | None = None) -> None:
        """Connect to target device by starting OpenOCD.

        Args:
            device: Device/chip identifier (e.g., "esp32c6", "esp32s3").
            interface: Debug interface (ignored for OpenOCD, kept for RTTTransport compatibility).
            speed: Interface speed in kHz (ignored for OpenOCD, kept for RTTTransport compatibility).
            board_cfg: Optional board config file. If None, auto-detected from device.

        Raises:
            FileNotFoundError: If Espressif OpenOCD not found.
            RuntimeError: If OpenOCD fails to start.
        """
        # Find OpenOCD binary
        openocd_bin = find_espressif_openocd()
        if not openocd_bin:
            raise FileNotFoundError(
                "Espressif OpenOCD not found. Install ESP-IDF and run install.sh, "
                "or install openocd-esp32 manually."
            )

        # Determine board config
        if board_cfg is None:
            device_lower = device.lower()
            board_cfg = BOARD_CONFIGS.get(device_lower)
            if board_cfg is None:
                raise ValueError(
                    f"Unknown device '{device}'. Supported: {list(BOARD_CONFIGS.keys())}"
                )

        self._device = device
        self._board_cfg = board_cfg

        # Build OpenOCD command
        # Note: port configuration must come BEFORE -f config files
        cmd = [
            openocd_bin,
            "-c", f"gdb port disabled",
            "-c", f"tcl port disabled",
            "-f", board_cfg,
        ]

        logger.info("Starting OpenOCD: %s", " ".join(cmd))

        # Start OpenOCD subprocess
        self._openocd_proc = subprocess.Popen(
            cmd,
            stdout=subprocess.PIPE,
            stderr=subprocess.PIPE,
            stdin=subprocess.DEVNULL,
        )

        # Wait for OpenOCD to start and bind telnet port
        deadline = time.time() + 5.0
        while time.time() < deadline:
            # Check if process died
            if self._openocd_proc.poll() is not None:
                stderr = self._openocd_proc.stderr.read().decode("utf-8", errors="replace") if self._openocd_proc.stderr else ""
                raise RuntimeError(f"OpenOCD exited immediately. stderr:\n{stderr}")

            # Try to connect to telnet port
            try:
                with socket.create_connection(("127.0.0.1", self._telnet_port), timeout=0.5):
                    logger.info("OpenOCD started successfully (PID %d)", self._openocd_proc.pid)
                    time.sleep(0.2)  # Give it a moment to stabilize
                    return
            except (socket.timeout, ConnectionRefusedError, OSError):
                time.sleep(0.1)

        # Timeout waiting for OpenOCD
        self._openocd_proc.terminate()
        raise RuntimeError("OpenOCD failed to start within 5 seconds")

    def start_tcp_listener(self, port: int | None = None) -> None:
        """Start TCP socket listener for apptrace data.

        Args:
            port: TCP port to listen on. If None, uses port from __init__.

        Raises:
            RuntimeError: If listener already running or socket bind fails.
        """
        if self._tcp_server_sock is not None:
            raise RuntimeError("TCP listener already running")

        if port is not None:
            self._tcp_port = port

        # Create TCP server socket
        self._tcp_server_sock = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
        self._tcp_server_sock.setsockopt(socket.SOL_SOCKET, socket.SO_REUSEADDR, 1)
        self._tcp_server_sock.bind(("127.0.0.1", self._tcp_port))
        self._tcp_server_sock.listen(1)
        self._tcp_server_sock.setblocking(False)

        logger.info("TCP listener started on port %d", self._tcp_port)

    def start_apptrace(
        self,
        timeout_bytes: int = 0,
        size_bytes: int = -1,
        poll_period_ms: int = 10,
    ) -> None:
        """Start apptrace on the target via telnet commands.

        This sends:
        1. "init" - Initialize OpenOCD target
        2. "reset run" - Reset and run the target
        3. Wait for target to stabilize
        4. "esp apptrace start tcp://localhost:<port> <timeout> <size> <poll>"

        Args:
            timeout_bytes: Trace timeout in bytes (0 = infinite).
            size_bytes: Max trace size in bytes (-1 = infinite).
            poll_period_ms: Polling period in milliseconds (default: 10).

        Raises:
            RuntimeError: If not connected or apptrace command fails.
        """
        if self._openocd_proc is None or self._openocd_proc.poll() is not None:
            raise RuntimeError("OpenOCD not running. Call connect() first.")

        if self._tcp_server_sock is None:
            self.start_tcp_listener()

        # Send telnet commands
        logger.info("Initializing target and starting apptrace...")

        # Initialize target (required before any target commands)
        try:
            self._send_telnet_cmd("init")
        except Exception as e:
            logger.warning("Init command failed (may already be initialized): %s", e)
        
        # Small delay to let init complete
        time.sleep(0.2)

        # Reset target
        self._send_telnet_cmd("reset run")
        
        # Wait for target to start running and apptrace to initialize
        time.sleep(0.5)

        # Start apptrace with TCP streaming
        apptrace_cmd = (
            f"esp apptrace start tcp://localhost:{self._tcp_port} "
            f"{timeout_bytes} {size_bytes} {poll_period_ms}"
        )
        response = self._send_telnet_cmd(apptrace_cmd, timeout=5.0)

        if "error" in response.lower() and "failed to init" in response.lower():
            raise RuntimeError(f"Failed to start apptrace: {response}")

        self._apptrace_running = True
        logger.info("Apptrace started on %s via TCP port %d", self._device, self._tcp_port)

        # Wait for OpenOCD to connect to our TCP socket (non-blocking check)
        deadline = time.time() + 2.0
        while time.time() < deadline:
            try:
                ready, _, _ = select.select([self._tcp_server_sock], [], [], 0.1)
                if ready:
                    self._tcp_client_sock, addr = self._tcp_server_sock.accept()
                    self._tcp_client_sock.setblocking(False)
                    logger.info("OpenOCD connected to TCP socket from %s", addr)
                    return
            except socket.error:
                pass

        logger.warning("OpenOCD did not connect to TCP socket within 2 seconds")

    def start_rtt(self, block_address: int | None = None) -> int:
        """Start RTT (apptrace) on the target.

        This is an alias for start_apptrace() to satisfy the RTTTransport interface.

        Args:
            block_address: Ignored (not used by apptrace).

        Returns:
            Number of channels (always 1 for apptrace).
        """
        self.start_apptrace()
        return 1  # Apptrace has one stream (no multi-channel support)

    def read(self, channel: int = 0, max_bytes: int = 4096) -> bytes:
        """Read raw bytes from apptrace TCP socket.

        Non-blocking: returns empty bytes if no data available.

        Args:
            channel: Channel index (ignored, apptrace has single stream).
            max_bytes: Maximum bytes to read per call.

        Returns:
            Raw bytes from the trace (may be empty).
        """
        if self._tcp_client_sock is None:
            # Try to accept connection if we haven't yet
            if self._tcp_server_sock is not None:
                try:
                    ready, _, _ = select.select([self._tcp_server_sock], [], [], 0.0)
                    if ready:
                        self._tcp_client_sock, addr = self._tcp_server_sock.accept()
                        self._tcp_client_sock.setblocking(False)
                        logger.info("OpenOCD connected to TCP socket from %s", addr)
                except socket.error:
                    pass

            if self._tcp_client_sock is None:
                return b""

        try:
            # Non-blocking read
            ready, _, _ = select.select([self._tcp_client_sock], [], [], 0.0)
            if ready:
                data = self._tcp_client_sock.recv(max_bytes)
                if not data:
                    # Connection closed
                    logger.warning("TCP connection closed by OpenOCD")
                    self._tcp_client_sock.close()
                    self._tcp_client_sock = None
                    return b""
                return data
            return b""
        except socket.error as e:
            logger.debug("TCP read error: %s", e)
            return b""

    def write(self, channel: int, data: bytes) -> int:
        """Write to apptrace down channel (not supported).

        Apptrace is primarily for target→host streaming.  Bidirectional
        communication is technically possible but not implemented here.

        Args:
            channel: Channel index (ignored).
            data: Data to write.

        Returns:
            0 (write not supported).
        """
        logger.warning("Apptrace write not implemented")
        return 0

    def stop_rtt(self) -> None:
        """Stop RTT (apptrace).

        Alias for stop_apptrace() to satisfy RTTTransport interface.
        """
        self.stop_apptrace()

    def stop_apptrace(self) -> None:
        """Stop apptrace on the target."""
        if not self._apptrace_running:
            return

        try:
            self._send_telnet_cmd("esp apptrace stop")
            logger.info("Apptrace stopped")
        except Exception as e:
            logger.warning("Failed to stop apptrace: %s", e)
        finally:
            self._apptrace_running = False

    def reset(self, halt: bool = False) -> None:
        """Reset the target via OpenOCD.

        Args:
            halt: If True, halt CPU after reset (default: False).

        Raises:
            RuntimeError: If OpenOCD not running.
        """
        if self._openocd_proc is None or self._openocd_proc.poll() is not None:
            raise RuntimeError("OpenOCD not running")

        try:
            if halt:
                self._send_telnet_cmd("reset halt")
            else:
                self._send_telnet_cmd("reset run")
            logger.info("Target reset (%s)", "halt" if halt else "run")
        except Exception as e:
            logger.warning("Reset command failed: %s", e)
            raise

    def disconnect(self) -> None:
        """Disconnect from target and shutdown OpenOCD.

        Closes all sockets and terminates OpenOCD subprocess.
        """
        # Stop apptrace if running
        if self._apptrace_running:
            try:
                self.stop_apptrace()
            except Exception:
                pass

        # Close TCP client socket
        if self._tcp_client_sock is not None:
            try:
                self._tcp_client_sock.close()
            except Exception:
                pass
            self._tcp_client_sock = None

        # Close TCP server socket
        if self._tcp_server_sock is not None:
            try:
                self._tcp_server_sock.close()
            except Exception:
                pass
            self._tcp_server_sock = None

        # Stop OpenOCD gracefully via telnet shutdown command
        if self._openocd_proc is not None and self._openocd_proc.poll() is None:
            try:
                # Try graceful shutdown via telnet first
                try:
                    self._send_telnet_cmd("shutdown", timeout=1.0)
                    self._openocd_proc.wait(timeout=2.0)
                    logger.info("OpenOCD shutdown gracefully")
                except Exception:
                    # If telnet shutdown fails, use SIGTERM
                    self._openocd_proc.terminate()
                    self._openocd_proc.wait(timeout=3.0)
                    logger.info("OpenOCD terminated")
            except subprocess.TimeoutExpired:
                # Last resort: SIGKILL
                self._openocd_proc.kill()
                self._openocd_proc.wait(timeout=2.0)
                logger.debug("OpenOCD killed (did not terminate gracefully)")
            except Exception as e:
                logger.warning("Error stopping OpenOCD: %s", e)
            finally:
                self._openocd_proc = None

    def _send_telnet_cmd(self, command: str, timeout: float = 2.0) -> str:
        """Send a single command to OpenOCD via telnet port.

        Args:
            command: Command to send.
            timeout: Command timeout in seconds.

        Returns:
            Response text from OpenOCD.

        Raises:
            RuntimeError: If telnet connection fails.
        """
        try:
            with socket.create_connection(("127.0.0.1", self._telnet_port), timeout=timeout) as sock:
                sock.settimeout(timeout)

                # Drain banner/prompt
                buf = b""
                start = time.time()
                while time.time() - start < timeout:
                    try:
                        chunk = sock.recv(4096)
                        if not chunk:
                            break
                        buf += chunk
                        if b"> " in buf:
                            break
                    except socket.timeout:
                        break

                # Send command
                sock.sendall(command.encode("utf-8") + b"\n")

                # Read response until prompt
                out = b""
                start = time.time()
                while time.time() - start < timeout:
                    try:
                        chunk = sock.recv(4096)
                        if not chunk:
                            break
                        out += chunk
                        if b"> " in out:
                            break
                    except socket.timeout:
                        break

                # Decode and strip prompt
                text = out.decode("utf-8", errors="replace")
                text = text.replace("\r", "")
                # Remove the prompt and command echo
                lines = text.split("\n")
                # Filter out command echo and prompt
                lines = [line for line in lines if line.strip() and not line.strip().startswith(">")]
                return "\n".join(lines).strip()

        except Exception as e:
            raise RuntimeError(f"Telnet command failed: {e}")

    def __enter__(self):
        return self

    def __exit__(self, exc_type, exc_val, exc_tb):
        try:
            self.disconnect()
        except Exception:
            pass
        return False
