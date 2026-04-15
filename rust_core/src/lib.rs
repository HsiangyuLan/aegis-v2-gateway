//! aegis_rust_core — Session pool + optional cascading dual ONNX paths.
//!
//! Python API:
//!   from aegis_rust_core import (
//!       EmbeddingEngine,
//!       CascadingEngine,
//!       compute_entropy_score,
//!       compute_cascade_entropy_score,
//!       compute_entropy_from_tokens,
//!   )

#![allow(clippy::useless_conversion)]

use pyo3::{buffer::PyBuffer, exceptions::PyBufferError, prelude::*};
use tracing::instrument;

mod cascade;
mod embedding;

pub use cascade::CascadingEngine;
pub use embedding::EmbeddingEngine;

/// Compute semantic entropy from raw UTF-8 bytes.
///
/// Uses the real HuggingFace WordPiece tokenizer internally if
/// ``EmbeddingEngine`` was constructed with a ``tokenizer_path``.
/// Falls back to the placeholder tokenizer otherwise.
///
/// The ``input_buf`` argument accepts any PEP 3118 buffer object:
/// ``bytes``, ``bytearray``, ``memoryview``, or ``numpy.ndarray[uint8]``.
/// PyO3's ``PyBuffer<u8>`` reads the CPython internal memory directly —
/// physically zero bytes are copied across the FFI boundary.
#[pyfunction]
#[instrument(skip(py, engine, input_buf))]
fn compute_entropy_score(
    py: Python<'_>,
    engine: &EmbeddingEngine,
    input_buf: PyBuffer<u8>,
) -> PyResult<f32> {
    let cell_slice = input_buf.as_slice(py).ok_or_else(|| {
        PyBufferError::new_err("Input must be C-contiguous buffer (bytes / bytearray / memoryview)")
    })?;
    let bytes: &[u8] =
        unsafe { std::slice::from_raw_parts(cell_slice.as_ptr() as *const u8, cell_slice.len()) };
    engine
        .compute(bytes)
        .map_err(|e| pyo3::exceptions::PyRuntimeError::new_err(e.to_string()))
}

/// Compute semantic entropy from pre-tokenized inputs (Python tokenizer path).
///
/// Use this when you want the HuggingFace ``AutoTokenizer`` on the Python side
/// for full control, passing the resulting token ID lists here.
#[pyfunction]
#[cfg(feature = "ort-backend")]
fn compute_entropy_from_tokens(
    engine: &EmbeddingEngine,
    input_ids: Vec<i64>,
    attention_mask: Vec<i64>,
) -> PyResult<f32> {
    engine
        .compute_from_tokens(&input_ids, &attention_mask)
        .map_err(|e| pyo3::exceptions::PyRuntimeError::new_err(e.to_string()))
}

#[pyfunction]
#[cfg(not(feature = "ort-backend"))]
fn compute_entropy_from_tokens(
    _engine: &EmbeddingEngine,
    input_ids: Vec<i64>,
    _attention_mask: Vec<i64>,
) -> PyResult<f32> {
    let n = input_ids.len() as f32;
    Ok((1.0 - (-n / 15.0_f32).exp()).clamp(0.0, 1.0))
}

#[pymodule]
fn aegis_rust_core(m: &Bound<'_, PyModule>) -> PyResult<()> {
    m.add_class::<EmbeddingEngine>()?;
    m.add_class::<CascadingEngine>()?;
    m.add_function(wrap_pyfunction!(compute_entropy_score, m)?)?;
    m.add_function(wrap_pyfunction!(cascade::compute_cascade_entropy_score, m)?)?;
    m.add_function(wrap_pyfunction!(compute_entropy_from_tokens, m)?)?;
    Ok(())
}
