//! Native probe-rs RTT transport for Embedded Agent Bridge (EAB).
//!
//! This Rust extension provides binary RTT (Real-Time Transfer) access via the probe-rs
//! library, enabling high-speed data streaming from embedded targets to Python with zero
//! text conversion overhead.
//!
//! # Architecture
//!
//! ```text
//! Python (EAB)
//!     ↓ import eab_probe_rs
//! PyO3 bindings (this crate)
//!     ↓ probe-rs API calls
//! probe-rs library
//!     ↓ USB/debug protocol
//! Debug probe (ST-Link, CMSIS-DAP, J-Link)
//!     ↓ SWD/JTAG
//! Target MCU (STM32, nRF, ESP32, etc.)
//! ```
//!
//! # Usage from Python
//!
//! ```python
//! from eab_probe_rs import ProbeRsSession
//!
//! # Connect to target
//! session = ProbeRsSession(chip="STM32L476RG")
//! session.attach()
//!
//! # Start RTT
//! num_channels = session.start_rtt()
//! print(f"Found {num_channels} RTT channels")
//!
//! # Read binary data from channel 0
//! data = session.rtt_read(channel=0)
//!
//! # Write to down channel
//! session.rtt_write(channel=0, data=b"command")
//!
//! # Cleanup
//! session.detach()
//! ```

use probe_rs::{
    probe::list::Lister,
    rtt::Rtt,
    Permissions, Session,
};
use pyo3::prelude::*;
use pyo3::types::PyBytes;
use std::sync::Mutex;

/// A probe-rs session with RTT support.
///
/// This class wraps a probe-rs `Session` and provides methods for:
/// - Attaching to a target chip via a debug probe
/// - Starting RTT (Real-Time Transfer) for high-speed data streaming
/// - Reading/writing raw bytes on RTT channels
/// - Resetting the target
///
/// # Thread Safety
///
/// The session is wrapped in a Mutex because probe-rs requires exclusive access
/// to the debug probe. Python's GIL ensures only one thread accesses this at a time,
/// but we use Mutex for Rust safety guarantees.
#[pyclass]
struct ProbeRsSession {
    /// The active probe-rs session (probe + core state).
    /// None if not connected.
    session: Mutex<Option<Session>>,

    /// RTT control block state.
    /// None until start_rtt() is called.
    rtt: Mutex<Option<Rtt>>,

    /// Target chip name (e.g., "STM32L476RG", "nRF52840_xxAA").
    chip: String,

    /// Optional probe selector (serial number or VID:PID).
    /// If None, uses the first available probe.
    probe_selector: Option<String>,
}

#[pymethods]
impl ProbeRsSession {
    /// Create a new probe-rs session for the specified chip.
    ///
    /// Args:
    ///     chip: Target chip name (e.g., "STM32L476RG", "nRF52840_xxAA")
    ///     probe_selector: Optional probe selector string (serial, VID:PID, or index)
    ///
    /// Returns:
    ///     ProbeRsSession instance (not yet connected — call attach() next)
    ///
    /// Example:
    ///     >>> session = ProbeRsSession(chip="STM32L476RG")
    ///     >>> session = ProbeRsSession(chip="nRF52840_xxAA", probe_selector="0483:374b")
    #[new]
    #[pyo3(signature = (chip, probe_selector=None))]
    fn new(chip: String, probe_selector: Option<String>) -> Self {
        Self {
            session: Mutex::new(None),
            rtt: Mutex::new(None),
            chip,
            probe_selector,
        }
    }

    /// Attach to the target chip via a debug probe.
    ///
    /// This:
    /// 1. Lists available debug probes
    /// 2. Opens the first probe (or the one matching probe_selector)
    /// 3. Attaches to the target chip via SWD
    /// 4. Halts the core briefly to establish connection, then resumes
    ///
    /// Raises:
    ///     RuntimeError: If no probe found, chip not recognized, or connection fails
    ///
    /// Example:
    ///     >>> session.attach()
    fn attach(&self) -> PyResult<()> {
        let lister = Lister::new();
        let probes = lister.list_all();

        if probes.is_empty() {
            return Err(pyo3::exceptions::PyRuntimeError::new_err(
                "No debug probes found. Check USB connection.",
            ));
        }

        // Select probe: if selector provided, filter; else take first
        let probe_info = if let Some(ref selector) = self.probe_selector {
            probes
                .iter()
                .find(|p| {
                    p.serial_number
                        .as_ref()
                        .map_or(false, |s| s.contains(selector))
                        || p.identifier.contains(selector)
                })
                .ok_or_else(|| {
                    pyo3::exceptions::PyRuntimeError::new_err(format!(
                        "No probe matching '{}' found",
                        selector
                    ))
                })?
        } else {
            &probes[0]
        };

        // Open the probe
        let probe = probe_info
            .open()
            .map_err(|e| pyo3::exceptions::PyRuntimeError::new_err(format!("Failed to open probe: {}", e)))?;

        // Attach to target with SWD
        let session = probe
            .attach(&self.chip, Permissions::default())
            .map_err(|e| {
                pyo3::exceptions::PyRuntimeError::new_err(format!(
                    "Failed to attach to chip '{}': {}. Check chip name and power.",
                    self.chip, e
                ))
            })?;

        // Store session
        *self.session.lock().unwrap() = Some(session);

        Ok(())
    }

    /// Start RTT on the target.
    ///
    /// This scans the target's RAM for the RTT control block (a struct placed by
    /// the firmware that describes RTT channel buffers). Once found, it initializes
    /// the RTT state for reading/writing channels.
    ///
    /// probe-rs automatically scans RAM for the RTT control block using the default
    /// search pattern (magic number "_SEGGER_RTT").
    ///
    /// Args:
    ///     block_address: Optional RTT control block address (e.g., 0x20001010).
    ///         If provided, skips scanning and uses this exact address.
    ///         Use this if auto-detection fails or for faster startup.
    ///
    /// Returns:
    ///     int: Number of up (target→host) channels found
    ///
    /// Raises:
    ///     RuntimeError: If not attached, or RTT control block not found
    ///
    /// Example:
    ///     >>> # Auto-detect (scans all RAM)
    ///     >>> num_channels = session.start_rtt()
    ///     >>> # Use explicit address (faster, always works if address is correct)
    ///     >>> num_channels = session.start_rtt(block_address=0x20001010)
    #[pyo3(signature = (block_address=None))]
    fn start_rtt(&self, block_address: Option<u64>) -> PyResult<usize> {
        let mut session_guard = self.session.lock().unwrap();
        let session = session_guard
            .as_mut()
            .ok_or_else(|| pyo3::exceptions::PyRuntimeError::new_err("Not attached. Call attach() first."))?;

        // Attach to core 0
        let mut core = session.core(0).map_err(|e| {
            pyo3::exceptions::PyRuntimeError::new_err(format!("Failed to attach to core: {}", e))
        })?;

        // Scan for RTT control block or use explicit address
        let mut rtt = if let Some(addr) = block_address {
            // Use explicit address (faster and more reliable when address is known)
            Rtt::attach_at(&mut core, addr).map_err(|e| {
                pyo3::exceptions::PyRuntimeError::new_err(format!(
                    "RTT control block not found at 0x{:08x}: {}",
                    addr, e
                ))
            })?
        } else {
            // Auto-scan RAM regions
            Rtt::attach(&mut core).map_err(|e| {
                pyo3::exceptions::PyRuntimeError::new_err(format!(
                    "RTT control block not found: {}. Ensure firmware has RTT enabled.\n\
                     Tip: If you know the control block address, use start_rtt(block_address=0xXXXXXXXX)",
                    e
                ))
            })?
        };

        let num_up = rtt.up_channels().len();

        // Store RTT state
        *self.rtt.lock().unwrap() = Some(rtt);

        Ok(num_up)
    }

    /// Read raw bytes from an RTT up (target→host) channel.
    ///
    /// Non-blocking: returns empty bytes if no data available.
    ///
    /// Args:
    ///     channel: RTT up channel index (0-based)
    ///
    /// Returns:
    ///     bytes: Raw data from the channel (may be empty)
    ///
    /// Raises:
    ///     RuntimeError: If RTT not started or channel doesn't exist
    ///
    /// Example:
    ///     >>> data = session.rtt_read(channel=0)
    ///     >>> if data:
    ///     ...     print(f"Received {len(data)} bytes")
    fn rtt_read(&self, channel: usize) -> PyResult<Py<PyBytes>> {
        let mut session_guard = self.session.lock().unwrap();
        let session = session_guard
            .as_mut()
            .ok_or_else(|| pyo3::exceptions::PyRuntimeError::new_err("Not attached"))?;

        let mut rtt_guard = self.rtt.lock().unwrap();
        let rtt = rtt_guard
            .as_mut()
            .ok_or_else(|| pyo3::exceptions::PyRuntimeError::new_err("RTT not started. Call start_rtt() first."))?;

        // Attach to core to perform read
        let mut core = session.core(0).map_err(|e| {
            pyo3::exceptions::PyRuntimeError::new_err(format!("Failed to access core: {}", e))
        })?;

        // Get the up channel (up_channels returns a mutable slice)
        let up_channel = rtt
            .up_channels()
            .get_mut(channel)
            .ok_or_else(|| pyo3::exceptions::PyValueError::new_err(format!("Channel {} not found", channel)))?;

        // Read up to 4KB at a time
        let mut buffer = vec![0u8; 4096];
        let count = up_channel.read(&mut core, &mut buffer).map_err(|e| {
            pyo3::exceptions::PyRuntimeError::new_err(format!("RTT read failed: {}", e))
        })?;

        // Return as Python bytes
        buffer.truncate(count);
        Python::with_gil(|py| Ok(PyBytes::new(py, &buffer).into()))
    }

    /// Write raw bytes to an RTT down (host→target) channel.
    ///
    /// Args:
    ///     channel: RTT down channel index (0-based)
    ///     data: Bytes to write
    ///
    /// Returns:
    ///     int: Number of bytes actually written (may be less than len(data) if buffer full)
    ///
    /// Raises:
    ///     RuntimeError: If RTT not started or channel doesn't exist
    ///
    /// Example:
    ///     >>> written = session.rtt_write(channel=0, data=b"command")
    ///     >>> print(f"Wrote {written} bytes")
    fn rtt_write(&self, channel: usize, data: &[u8]) -> PyResult<usize> {
        let mut session_guard = self.session.lock().unwrap();
        let session = session_guard
            .as_mut()
            .ok_or_else(|| pyo3::exceptions::PyRuntimeError::new_err("Not attached"))?;

        let mut rtt_guard = self.rtt.lock().unwrap();
        let rtt = rtt_guard
            .as_mut()
            .ok_or_else(|| pyo3::exceptions::PyRuntimeError::new_err("RTT not started"))?;

        let mut core = session.core(0).map_err(|e| {
            pyo3::exceptions::PyRuntimeError::new_err(format!("Failed to access core: {}", e))
        })?;

        let down_channel = rtt
            .down_channels()
            .get_mut(channel)
            .ok_or_else(|| pyo3::exceptions::PyValueError::new_err(format!("Channel {} not found", channel)))?;

        let written = down_channel.write(&mut core, data).map_err(|e| {
            pyo3::exceptions::PyRuntimeError::new_err(format!("RTT write failed: {}", e))
        })?;

        Ok(written)
    }

    /// Reset the target chip.
    ///
    /// Args:
    ///     halt: If True, halt the core after reset (for debugging)
    ///
    /// Raises:
    ///     RuntimeError: If not attached
    ///
    /// Example:
    ///     >>> session.reset(halt=False)
    #[pyo3(signature = (halt=false))]
    fn reset(&self, halt: bool) -> PyResult<()> {
        let mut session_guard = self.session.lock().unwrap();
        let session = session_guard
            .as_mut()
            .ok_or_else(|| pyo3::exceptions::PyRuntimeError::new_err("Not attached"))?;

        let mut core = session.core(0).map_err(|e| {
            pyo3::exceptions::PyRuntimeError::new_err(format!("Failed to access core: {}", e))
        })?;

        core.reset().map_err(|e| {
            pyo3::exceptions::PyRuntimeError::new_err(format!("Reset failed: {}", e))
        })?;

        if halt {
            core.halt(std::time::Duration::from_millis(100)).map_err(|e| {
                pyo3::exceptions::PyRuntimeError::new_err(format!("Halt failed: {}", e))
            })?;
        }

        Ok(())
    }

    /// Detach from the target and close the probe connection.
    ///
    /// Always call this when done to release the probe for other tools.
    ///
    /// Example:
    ///     >>> session.detach()
    fn detach(&self) -> PyResult<()> {
        *self.session.lock().unwrap() = None;
        *self.rtt.lock().unwrap() = None;
        Ok(())
    }

    /// Get the chip name this session is configured for.
    ///
    /// Returns:
    ///     str: Chip name
    #[getter]
    fn chip(&self) -> String {
        self.chip.clone()
    }

    /// Check if currently attached to a target.
    ///
    /// Returns:
    ///     bool: True if attached
    #[getter]
    fn is_attached(&self) -> bool {
        self.session.lock().unwrap().is_some()
    }

    /// Check if RTT is active.
    ///
    /// Returns:
    ///     bool: True if RTT started
    #[getter]
    fn is_rtt_active(&self) -> bool {
        self.rtt.lock().unwrap().is_some()
    }
}

/// Python module initialization.
///
/// This registers the `ProbeRsSession` class so Python can import it:
///     >>> from eab_probe_rs import ProbeRsSession
#[pymodule]
fn eab_probe_rs(m: &Bound<'_, PyModule>) -> PyResult<()> {
    m.add_class::<ProbeRsSession>()?;
    Ok(())
}
