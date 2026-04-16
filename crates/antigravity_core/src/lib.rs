//! antigravity_core — PyO3 shell: zero-copy `Arc<[u8]>` + regex + optional ONNX NER + redaction.

use std::path::PathBuf;
use std::sync::{Arc, OnceLock};

use ag_pii_onnx::OnnxNerEngine;
use ag_pii_regex::PiiRegexDetector;
use ag_redact::merge_spans;
use ag_types::ScanResponse;
use pyo3::buffer::PyBuffer;
use pyo3::exceptions::{PyBufferError, PyRuntimeError, PyUnicodeDecodeError};
use pyo3::prelude::*;
use tokio::runtime::Runtime;

static TOKIO_RT: OnceLock<Runtime> = OnceLock::new();
static REGEX_DETECTOR: OnceLock<PiiRegexDetector> = OnceLock::new();
static ONNX_ENGINE: OnceLock<OnnxNerEngine> = OnceLock::new();

fn tokio_rt() -> &'static Runtime {
    TOKIO_RT.get_or_init(|| {
        Runtime::new().expect("antigravity_core: Tokio runtime init failed")
    })
}

fn regex_detector() -> &'static PiiRegexDetector {
    REGEX_DETECTOR.get_or_init(PiiRegexDetector::new)
}

fn onnx_engine() -> &'static OnnxNerEngine {
    ONNX_ENGINE.get_or_init(|| {
        let m = std::env::var("AG_PII_NER_ONNX").ok().map(PathBuf::from);
        let t = std::env::var("AG_PII_NER_TOKENIZER").ok().map(PathBuf::from);
        match (m, t) {
            (Some(mp), Some(tp)) => OnnxNerEngine::try_load(&mp, &tp),
            _ => OnnxNerEngine::disabled(),
        }
    })
}

async fn process_async(arc_data: Arc<[u8]>) -> Result<String, String> {
    let arc_task = Arc::clone(&arc_data);
    let inner: Result<String, String> = tokio::spawn(async move {
        let text = unsafe { ag_zero_copy::str_from_arc_unchecked(&arc_task) };
        let mut regex_m = regex_detector().detect(text);
        let onnx_m = onnx_engine()
            .detect(text)
            .map_err(|e| format!("ONNX NER: {e}"))?;
        regex_m.extend(onnx_m);
        let merged = merge_spans(regex_m);
        let redacted = ag_redact::redact_text(text, &merged);
        let resp = ScanResponse {
            status:        "success".to_string(),
            zero_copy:     true,
            async_engine:  true,
            pii_matches:   merged,
            degraded:      false,
            redacted_text: Some(redacted),
            circuit_state: None,
        };
        serde_json::to_string(&resp).map_err(|e| e.to_string())
    })
    .await
    .map_err(|e| format!("task join: {e}"))?;
    inner
}

#[pyfunction]
fn execute_command(py: Python<'_>, input_buf: PyBuffer<u8>) -> PyResult<String> {
    let cell_slice = input_buf.as_slice(py).ok_or_else(|| {
        PyBufferError::new_err(
            "Input must be C-contiguous buffer (bytes / bytearray / memoryview).",
        )
    })?;

    let bytes: &[u8] =
        unsafe { std::slice::from_raw_parts(cell_slice.as_ptr() as *const u8, cell_slice.len()) };

    std::str::from_utf8(bytes).map_err(|e| {
        PyUnicodeDecodeError::new_err(format!(
            "execute_command: invalid UTF-8 at {}: {e}",
            e.valid_up_to()
        ))
    })?;

    let arc_data = ag_zero_copy::arc_from_utf8_bytes(bytes)
        .map_err(|e| PyUnicodeDecodeError::new_err(e.to_string()))?;

    let json_result = py
        .allow_threads(move || tokio_rt().block_on(process_async(arc_data)))
        .map_err(PyRuntimeError::new_err)?;

    Ok(json_result)
}

#[pymodule]
fn antigravity_core(m: &Bound<'_, PyModule>) -> PyResult<()> {
    m.add_function(wrap_pyfunction!(execute_command, m)?)?;
    Ok(())
}
