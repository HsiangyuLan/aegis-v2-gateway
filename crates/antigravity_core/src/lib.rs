//! antigravity_core — Phase 3: Zero-Copy PII Detection Engine
//!
//! Python API (unchanged — backward compatible):
//!   ```python
//!   from antigravity_core import execute_command
//!   result = execute_command(b"contact alice@example.com re: card 4111-1111-1111-1111")
//!   # Returns JSON with pii_matches bounding boxes
//!   ```
//!
//! Phase 3 Upgrade: sleep mock → real PII detection
//! -------------------------------------------------
//! Phase 2 used `tokio::time::sleep(10ms)` as a placeholder inside the
//! spawned task.  Phase 3 replaces that with a real zero-copy PII scan:
//!
//!   1. `Arc<[u8]>` cloned into spawned Tokio task (O(1) refcount increment)
//!   2. `str::from_utf8_unchecked` — safe because UTF-8 validated at FFI boundary
//!   3. `pii::detector().detect(text)` — read-only regex scan, no allocation
//!   4. Serialise `Vec<PiiMatch>` offsets to JSON and return
//!
//! Zero-Copy Architecture (cumulative, all phases)
//! ------------------------------------------------
//!   Phase 1  1 copy  PyBuffer → Arc<[u8]>          (GIL release requires ownership)
//!   Phase 2  0 copies Arc::clone fan-out            (atomic refcount only)
//!   Phase 3  0 copies PII scan via &str borrow      (regex reads Arc bytes directly)
//!            N offset structs  Vec<PiiMatch>         (only metadata, not payload bytes)
//!
//! The input payload bytes are NEVER copied after the initial Arc allocation.

mod pii;

use std::sync::{Arc, OnceLock};

use pyo3::buffer::PyBuffer;
use pyo3::exceptions::{PyBufferError, PyRuntimeError, PyUnicodeDecodeError};
use pyo3::prelude::*;
use serde::Serialize;
use tokio::runtime::Runtime;

// ── Process-wide Tokio runtime ─────────────────────────────────────────────────

/// Process-wide Tokio multi-thread work-stealing runtime.
/// See Phase 2 documentation for design rationale.
static TOKIO_RT: OnceLock<Runtime> = OnceLock::new();

fn tokio_rt() -> &'static Runtime {
    TOKIO_RT.get_or_init(|| {
        Runtime::new().expect(
            "antigravity_core: failed to initialise Tokio multi-thread runtime",
        )
    })
}

// ── Response model ─────────────────────────────────────────────────────────────

/// JSON response returned to Python from `execute_command`.
///
/// Phase 3 additions:
///   `pii_matches` — list of PII bounding boxes detected in the payload.
///   Empty (`[]`) when the payload contains no recognised PII patterns.
///
/// Existing fields are preserved for backward compatibility.
#[derive(Serialize)]
struct CommandResponse {
    status:       &'static str,
    zero_copy:    bool,
    async_engine: bool,
    pii_matches:  Vec<pii::PiiMatch>,
}

// ── Async processing core ──────────────────────────────────────────────────────

/// Core async processing function — runs inside `tokio_rt().block_on(...)`.
///
/// # Phase 3 Changes vs Phase 2
///
/// The `tokio::time::sleep(10ms)` placeholder has been replaced with a real
/// PII detection scan via `pii::detector().detect(text)`.
///
/// # Zero-Copy Chain
///
/// ```text
/// Arc<[u8]>  ──► Arc::clone  ──►  tokio::spawn task
///                [O(1) atomic refcount — no byte copy]
///
/// Arc<[u8]>  ──► &str (from_utf8_unchecked)
///                [O(1) pointer cast — no alloc]
///
/// &str  ──► Regex::find_iter  ──►  Vec<PiiMatch>
///           [read-only scan — no byte copy]
///           [only offset metadata allocated]
/// ```
async fn process_async(arc_data: Arc<[u8]>) -> Result<String, String> {
    // ── Zero-copy fan-out ─────────────────────────────────────────────────────
    //
    // Arc::clone is O(1): only the reference count is incremented.
    // The heap bytes created at the FFI boundary are NOT copied here.
    let arc_task: Arc<[u8]> = Arc::clone(&arc_data);

    // ── Spawn Tokio task for PII scan ─────────────────────────────────────────
    //
    // The task now returns `Result<String, String>` (JSON or error message).
    // `JoinHandle<Result<String, String>>` requires double `?` propagation:
    //   .await → Result<Result<String,String>, JoinError>  (outer: task panic)
    //   ??     → unwrap both layers
    let json: String = tokio::spawn(async move {
        // SAFETY: UTF-8 validity was proven at the FFI boundary in
        // `execute_command` before `Arc::from(bytes)` was called.
        // `from_utf8_unchecked` is a zero-cost transmute — no allocation.
        let text = unsafe { std::str::from_utf8_unchecked(&arc_task) };

        // PII detection — reads `text` via borrowed &str, no byte allocation.
        // Returns only `Vec<PiiMatch>` containing offset metadata.
        let matches = pii::detector().detect(text);

        serde_json::to_string(&CommandResponse {
            status:       "success",
            zero_copy:    true,
            async_engine: true,
            pii_matches:  matches,
        })
        .map_err(|e| format!("JSON serialisation failed: {e}"))
    })
    .await
    // Outer error: Tokio JoinError (task panicked or was cancelled).
    .map_err(|e| format!("Tokio spawned task panicked: {e}"))?
    // Inner error: serde_json serialisation failure.
    ?;

    Ok(json)
}

// ── Core FFI function ──────────────────────────────────────────────────────────

/// Execute an Agentic Commerce command transmitted as raw bytes from Python.
///
/// # Zero-Copy Memory Path (all three phases)
///
/// ```text
/// Python bytes  ──► PyBuffer<u8>.as_slice(py) ──► &[u8]
///                   [zero Python allocation — reads CPython buffer directly]
///
/// &[u8]  ──► Arc::<[u8]>::from(bytes)
///            [one Rust allocation — required for GIL release + Send]
///
/// Arc<[u8]>  ──► Arc::clone  ──► tokio::spawn task
///                [O(1) atomic refcount — no byte copy]
///
/// Arc<[u8]>  ──► &str  ──► Regex::find_iter  ──► Vec<PiiMatch>
///                [O(1) borrow — regex scans without allocating]
/// ```
///
/// # Arguments
///
/// * `py`        — GIL token
/// * `input_buf` — PEP 3118 buffer: `bytes`, `bytearray`, `memoryview`,
///                 or `numpy.ndarray[uint8]`
///
/// # Returns
///
/// JSON string:
/// ```json
/// {
///   "status": "success",
///   "zero_copy": true,
///   "async_engine": true,
///   "pii_matches": [
///     {"pii_type": "EMAIL",       "start": 14, "end": 31},
///     {"pii_type": "CREDIT_CARD", "start": 35, "end": 54}
///   ]
/// }
/// ```
///
/// # Errors
///
/// * `PyBufferError`        — buffer is not C-contiguous
/// * `PyUnicodeDecodeError` — bytes are not valid UTF-8
/// * `PyRuntimeError`       — Tokio task panic or JSON serialisation failure
#[pyfunction]
fn execute_command(py: Python<'_>, input_buf: PyBuffer<u8>) -> PyResult<String> {
    // ── Step 1: Zero-copy read from Python's buffer protocol ──────────────────
    let cell_slice = input_buf.as_slice(py).ok_or_else(|| {
        PyBufferError::new_err(
            "Input must be a C-contiguous buffer (bytes / bytearray / memoryview). \
             Fortran-order or non-contiguous arrays are not supported.",
        )
    })?;

    // Safety: Cell<u8> is repr(transparent) over u8; we only read.
    let bytes: &[u8] =
        unsafe { std::slice::from_raw_parts(cell_slice.as_ptr() as *const u8, cell_slice.len()) };

    // Validate UTF-8 under the GIL — establishes the invariant that lets
    // process_async use `from_utf8_unchecked` safely.
    std::str::from_utf8(bytes).map_err(|e| {
        PyUnicodeDecodeError::new_err(format!(
            "execute_command: input bytes are not valid UTF-8 at byte offset {}: {}",
            e.valid_up_to(),
            e,
        ))
    })?;

    // ── Step 2: Transfer ownership to Rust via Arc<[u8]> ──────────────────────
    //
    // One allocation.  All subsequent fan-out clones are O(1) atomic increments.
    let arc_data: Arc<[u8]> = Arc::from(bytes);

    // ── Step 3: Release GIL and dispatch to Tokio runtime ─────────────────────
    let json_result: String = py
        .allow_threads(move || tokio_rt().block_on(process_async(arc_data)))
        .map_err(PyRuntimeError::new_err)?;

    Ok(json_result)
}

// ── Module registration ────────────────────────────────────────────────────────

#[pymodule]
fn antigravity_core(m: &Bound<'_, PyModule>) -> PyResult<()> {
    m.add_function(wrap_pyfunction!(execute_command, m)?)?;
    Ok(())
}
